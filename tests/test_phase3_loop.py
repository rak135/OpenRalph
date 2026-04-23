"""Phase 3 loop tests: multi-iteration control, stop reasons, lock discipline,
completion confidence, and bounded result contract integration.

These tests complement the Phase 1/2 tests in test_loop.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openralph_py.adapters.base import (
    Adapter,
    AdapterCapabilities,
    ExecuteOptions,
    ExecuteResult,
)
from openralph_py.loop import IterationOutcome, LoopSummary, StopReason, run_loop, run_iteration
from openralph_py.plan import Task, load_tasks, save_tasks, write_prd_json
from openralph_py.result_contract import UntrustedResult, WorkerResultBlock
from openralph_py.workspace import LOCK_FILE, Workspace


# ---------------------------------------------------------------------------
# Test adapters
# ---------------------------------------------------------------------------


class FakeResultAdapter(Adapter):
    """Adapter that emits a proper <ralph-result> block and marks tasks done."""

    name = "fake-result"
    display_name = "Fake Result (test)"

    def __init__(
        self,
        *,
        mark_complete: bool = True,
        result_status: str = "done",
        result_complete: bool = True,
        exit_code: int = 0,
    ) -> None:
        self.mark_complete = mark_complete
        self.result_status = result_status
        self.result_complete = result_complete
        self.exit_code = exit_code
        self.calls: list[ExecuteOptions] = []

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="arg",
            supports_model_flag=False,
            supports_non_interactive=True,
        )

    def is_available(self) -> bool:
        return True

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        self.calls.append(options)
        ws = Workspace(options.cwd)
        if self.mark_complete and ws.prd_path.exists():
            tasks = load_tasks(ws.prd_path)
            for t in tasks:
                if not t.passes:
                    t.passes = True
                    break
            save_tasks(ws.prd_path, tasks)

        complete_str = "true" if self.result_complete else "false"
        stdout = (
            "Worker output line.\n"
            "<ralph-result>\n"
            f"status: {self.result_status}\n"
            "summary: completed the assigned task\n"
            "verification: manual review\n"
            f"complete: {complete_str}\n"
            "blocker: none\n"
            "</ralph-result>\n"
        )
        return ExecuteResult(
            exit_code=self.exit_code,
            stdout=stdout,
            stderr="",
            duration_seconds=0.01,
        )


class NoBlockAdapter(Adapter):
    """Adapter that does real work but omits the <ralph-result> block."""

    name = "no-block"
    display_name = "No Block (test)"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="arg",
            supports_model_flag=False,
            supports_non_interactive=True,
        )

    def is_available(self) -> bool:
        return True

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        ws = Workspace(options.cwd)
        if ws.prd_path.exists():
            tasks = load_tasks(ws.prd_path)
            for t in tasks:
                if not t.passes:
                    t.passes = True
                    break
            save_tasks(ws.prd_path, tasks)
        return ExecuteResult(
            exit_code=0,
            stdout="Did some work, no result block here.",
            stderr="",
            duration_seconds=0.01,
        )


def _seed(tmp_path: Path, tasks: list[Task]) -> Workspace:
    ws = Workspace(tmp_path)
    ws.ensure()
    write_prd_json(ws.prd_path, tasks)
    ws.progress_path.write_text("", encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# Parsed result attached to IterationOutcome
# ---------------------------------------------------------------------------


def test_run_iteration_attaches_parsed_result_block(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    adapter = FakeResultAdapter()

    outcome = run_iteration(ws.root, adapter)

    assert outcome.parsed_result is not None
    assert isinstance(outcome.parsed_result, WorkerResultBlock)
    assert outcome.parsed_result.is_trusted is True
    assert outcome.parsed_result.status == "done"
    assert outcome.parsed_result.complete is True


def test_run_iteration_attaches_untrusted_result_when_no_block(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    adapter = NoBlockAdapter()

    outcome = run_iteration(ws.root, adapter)

    assert outcome.parsed_result is not None
    assert isinstance(outcome.parsed_result, UntrustedResult)
    assert outcome.parsed_result.is_trusted is False
    # Plan-confirmed completion still works even with untrusted result.
    assert outcome.completed_now is True


# ---------------------------------------------------------------------------
# completion_confidence on IterationOutcome
# ---------------------------------------------------------------------------


def test_completion_confidence_promise_and_plan_confirmed(tmp_path: Path):
    """Both plan and block agree: highest confidence."""
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    outcome = run_iteration(ws.root, FakeResultAdapter())
    assert outcome.completion_confidence == "promise-and-plan-confirmed"


def test_completion_confidence_plan_confirmed_when_block_absent(tmp_path: Path):
    """Current task is confirmed in prd.json, but block is absent."""
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    outcome = run_iteration(ws.root, NoBlockAdapter())
    assert outcome.completion_confidence == "task-confirmed"


def test_completion_confidence_promise_and_task_confirmed_when_plan_partial(tmp_path: Path):
    """Current task can be confirmed even when full plan is still incomplete."""
    ws = _seed(tmp_path, [
        Task(id="a", description="alpha", passes=False),
        Task(id="b", description="beta", passes=False),
    ])
    outcome = run_iteration(ws.root, FakeResultAdapter())
    assert outcome.task is not None and outcome.task.id == "a"
    assert outcome.task_confirmed is True
    assert outcome.completed_now is False
    assert outcome.completion_confidence == "promise-and-task-confirmed"


def test_completion_confidence_unverified_when_plan_not_done_and_block_missing(tmp_path: Path):
    """Worker did nothing, no block: unverified."""
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    adapter = FakeResultAdapter(mark_complete=False, result_complete=False, result_status="blocked")
    outcome = run_iteration(ws.root, adapter)
    assert outcome.completion_confidence == "unverified"


def test_completion_confidence_promise_only_when_block_says_done_but_plan_disagrees(tmp_path: Path):
    """Block claims done but plan is unchanged: suspicious 'promise-only'."""
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    # Adapter claims done in block but doesn't update prd.json.
    adapter = FakeResultAdapter(mark_complete=False, result_status="done", result_complete=True)
    outcome = run_iteration(ws.root, adapter)
    assert outcome.completion_confidence == "promise-only"
    assert outcome.completed_now is False


# ---------------------------------------------------------------------------
# run_loop: multi-iteration stop behavior
# ---------------------------------------------------------------------------


def test_run_loop_stops_at_max_iterations(tmp_path: Path):
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
        Task(id="c", description="c", passes=False),
    ])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=2)

    assert summary.stop_reason == StopReason.MAX_ITERATIONS
    assert summary.iterations_run == 2
    assert summary.completed_tasks == 2
    assert summary.total_tasks == 3
    assert len(summary.outcomes) == 2
    assert not summary.all_complete


def test_run_loop_stops_all_complete_before_limit(tmp_path: Path):
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
    ])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=10)

    assert summary.stop_reason == StopReason.ALL_COMPLETE
    assert summary.iterations_run == 2
    assert summary.completed_tasks == 2
    assert summary.all_complete is True


def test_run_loop_already_complete_returns_immediately(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=True)])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=5)

    assert summary.stop_reason == StopReason.ALREADY_COMPLETE
    assert summary.iterations_run == 0
    assert summary.all_complete is True


def test_run_loop_no_tasks(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure()
    write_prd_json(ws.prd_path, [])
    ws.progress_path.write_text("", encoding="utf-8")
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=3)

    assert summary.stop_reason == StopReason.NO_TASKS
    assert summary.iterations_run == 0


def test_run_loop_unbounded_completes_all(tmp_path: Path):
    """max_iterations=None means run until complete."""
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
    ])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=None)

    assert summary.stop_reason == StopReason.ALL_COMPLETE
    assert summary.iterations_run == 2


def test_run_loop_summary_format_includes_stop_reason(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=1)

    text = summary.format()
    assert "max_iterations" in text or "all_complete" in text
    assert summary.session_id in text


def test_run_loop_persists_stop_reason_to_state(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    adapter = FakeResultAdapter()

    run_loop(ws.root, adapter, max_iterations=1)

    state = json.loads(ws.state_path.read_text(encoding="utf-8"))
    assert state["last_stop_reason"] in ("max_iterations", "all_complete")


def test_run_loop_persists_session_id_to_state(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    adapter = FakeResultAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=1)

    state = json.loads(ws.state_path.read_text(encoding="utf-8"))
    assert state["session_id"] == summary.session_id


# ---------------------------------------------------------------------------
# Lock discipline
# ---------------------------------------------------------------------------


def test_workspace_lock_acquires_and_releases(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure()

    lock = ws.acquire_lock()
    assert lock is not None
    assert ws.lock_path.exists()

    lock.release()
    assert not ws.lock_path.exists()


def test_workspace_lock_context_manager(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure()

    with ws.acquire_lock() as lock:
        assert lock is not None
        assert ws.lock_path.exists()

    assert not ws.lock_path.exists()


def test_workspace_lock_blocks_concurrent_acquire(tmp_path: Path):
    """Simulates a concurrent lock by writing a lock file with the current PID."""
    ws = Workspace(tmp_path)
    ws.ensure()

    # Write a lock with OUR OWN PID — simulates an alive concurrent process.
    ws.lock_path.write_text(json.dumps({"pid": os.getpid()}) + "\n", encoding="utf-8")

    second = ws.acquire_lock()
    assert second is None, "Should not acquire lock when current PID already holds it"

    # Clean up.
    ws.lock_path.unlink()


def test_workspace_lock_removes_stale_lock(tmp_path: Path):
    """A lock whose PID is not running is treated as stale."""
    ws = Workspace(tmp_path)
    ws.ensure()

    # PID 99999999 almost certainly does not exist on any machine.
    ws.lock_path.write_text(json.dumps({"pid": 99999999}) + "\n", encoding="utf-8")

    lock = ws.acquire_lock()
    assert lock is not None, "Stale lock should have been removed and new lock acquired"
    lock.release()


def test_run_loop_returns_lock_conflict_when_lock_held(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    # Simulate alive process holding the lock.
    ws.lock_path.write_text(json.dumps({"pid": os.getpid()}) + "\n", encoding="utf-8")

    adapter = FakeResultAdapter()
    summary = run_loop(ws.root, adapter, max_iterations=2)

    assert summary.stop_reason == StopReason.LOCK_CONFLICT
    assert summary.iterations_run == 0

    # Clean up our fake lock.
    ws.lock_path.unlink()


def test_run_loop_releases_lock_on_completion(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    adapter = FakeResultAdapter()

    run_loop(ws.root, adapter, max_iterations=1)

    assert not ws.lock_path.exists(), "Lock must be released after run_loop completes"


# ---------------------------------------------------------------------------
# Progress log enrichment
# ---------------------------------------------------------------------------


def test_progress_log_includes_confidence_and_summary(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])
    adapter = FakeResultAdapter()

    run_iteration(ws.root, adapter)

    log = ws.progress_path.read_text(encoding="utf-8")
    assert "Confidence:" in log
    assert "Worker summary:" in log


def test_progress_log_confidence_is_unverified_without_block(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="alpha", passes=False)])

    run_iteration(ws.root, NoBlockAdapter())

    log = ws.progress_path.read_text(encoding="utf-8")
    assert "Confidence: task-confirmed" in log
    # No worker summary when block is absent.
    assert "Worker summary:" not in log


# ---------------------------------------------------------------------------
# No fake success guarantee
# ---------------------------------------------------------------------------


def test_untrusted_result_does_not_stop_loop_prematurely(tmp_path: Path):
    """A worker that skips the result block must not cause premature completion."""
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
    ])
    # NoBlockAdapter marks tasks done in prd.json but omits the block.
    summary = run_loop(ws.root, NoBlockAdapter(), max_iterations=10)

    # Loop must still run until all tasks are plan-confirmed done.
    assert summary.stop_reason == StopReason.ALL_COMPLETE
    assert summary.iterations_run == 2


def test_block_claiming_done_without_plan_update_does_not_stop_loop(tmp_path: Path):
    """Worker claims complete in block but prd.json stays at passes=false.

    The loop must NOT treat the block claim as truth without plan confirmation.
    This case yields confidence=promise-only (not unverified), so no-progress
    protection does not trigger — the loop runs to max_iterations.
    """
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
    ])
    # Adapter says "done" in block but never touches prd.json.
    bad_adapter = FakeResultAdapter(
        mark_complete=False,
        result_status="done",
        result_complete=True,
        exit_code=0,
    )

    summary = run_loop(ws.root, bad_adapter, max_iterations=3)

    # Loop hits max_iterations: prd stays at 0 complete, block claim ignored,
    # but confidence=promise-only is NOT unverified so no-progress doesn't fire.
    assert summary.stop_reason == StopReason.MAX_ITERATIONS
    assert summary.completed_tasks == 0


# ---------------------------------------------------------------------------
# Phase 3.1: no-progress detection
# ---------------------------------------------------------------------------


class NoProgressAdapter(Adapter):
    """Adapter that does nothing — no prd update, no result block.

    Used to test the NO_PROGRESS stop condition.
    """

    name = "no-progress"
    display_name = "No Progress (test)"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="arg",
            supports_model_flag=False,
            supports_non_interactive=True,
        )

    def is_available(self) -> bool:
        return True

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        # Does nothing — prd.json untouched, no result block.
        return ExecuteResult(
            exit_code=0,
            stdout="I inspected the files but did nothing.",
            stderr="",
            duration_seconds=0.01,
        )


def test_no_progress_stops_loop_after_threshold(tmp_path: Path):
    """Loop stops with NO_PROGRESS after NO_PROGRESS_THRESHOLD consecutive
    unverified same-task iterations."""
    ws = _seed(tmp_path, [Task(id="a", description="do something", passes=False)])
    adapter = NoProgressAdapter()

    summary = run_loop(ws.root, adapter, max_iterations=10)

    assert summary.stop_reason == StopReason.NO_PROGRESS
    assert summary.iterations_run == 2  # default threshold
    # Must have stopped before hitting max_iterations.
    assert summary.iterations_run < 10
    assert summary.completed_tasks == 0


def test_no_progress_resets_counter_on_different_task(tmp_path: Path):
    """If the task changes (because one task was completed), the no-progress
    counter resets and the loop continues."""
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
    ])

    call_count = [0]

    class AlternatingAdapter(Adapter):
        name = "alternating"
        display_name = "Alternating"

        @property
        def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                prompt_mode="arg",
                supports_model_flag=False,
                supports_non_interactive=True,
            )

        def is_available(self) -> bool:
            return True

        def execute(self, options: ExecuteOptions) -> ExecuteResult:
            call_count[0] += 1
            # Complete task-a on iteration 1 (so task-b is next), then stall.
            if call_count[0] == 1:
                t = load_tasks(ws.prd_path)
                for task in t:
                    if task.id == "a":
                        task.passes = True
                        break
                save_tasks(ws.prd_path, t)
            return ExecuteResult(exit_code=0, stdout="", stderr="", duration_seconds=0.01)

    summary = run_loop(ws.root, AlternatingAdapter(), max_iterations=10)

    # After completing task-a on iteration 1, task-b becomes current.
    # Two unverified attempts on task-b trigger NO_PROGRESS.
    assert summary.stop_reason == StopReason.NO_PROGRESS
    assert summary.completed_tasks == 1  # task-a was completed


def test_no_progress_threshold_is_configurable(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="do something", passes=False)])
    adapter = NoProgressAdapter()

    summary = run_loop(
        ws.root,
        adapter,
        max_iterations=10,
        no_progress_threshold=3,
    )

    assert summary.stop_reason == StopReason.NO_PROGRESS
    assert summary.no_progress_threshold == 3
    assert summary.iterations_run == 3


def test_no_progress_threshold_rejects_invalid_value(tmp_path: Path):
    ws = _seed(tmp_path, [Task(id="a", description="do something", passes=False)])

    with pytest.raises(ValueError):
        run_loop(ws.root, NoProgressAdapter(), max_iterations=10, no_progress_threshold=0)


def test_no_progress_does_not_trigger_when_prd_advances(tmp_path: Path):
    """If prd.json advances each iteration (different task or completion),
    no-progress does not fire."""
    ws = _seed(tmp_path, [
        Task(id="a", description="a", passes=False),
        Task(id="b", description="b", passes=False),
        Task(id="c", description="c", passes=False),
    ])
    # FakeResultAdapter marks one task done per iteration.
    summary = run_loop(ws.root, FakeResultAdapter(), max_iterations=10)

    assert summary.stop_reason == StopReason.ALL_COMPLETE
    assert summary.completed_tasks == 3


def test_loop_summary_format_shows_prd_advancement(tmp_path: Path):
    """format() output must show task-level and plan-level prd confirmation."""
    ws = _seed(tmp_path, [Task(id="a", description="a", passes=False)])
    summary = run_loop(ws.root, FakeResultAdapter(), max_iterations=1)

    text = summary.format()
    assert "prd-task:" in text
    assert "prd-plan:" in text
    assert "No-progress threshold:" in text

