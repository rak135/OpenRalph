"""End-to-end loop semantics using a fake adapter.

These tests demonstrate that repeated `run_iteration` invocations over the
same workspace truly form the multi-step Ralph loop: each call advances
state, each call completes exactly one task, and the completion marker
appears only when all tasks are done.
"""

from __future__ import annotations

import json
from pathlib import Path

from openralph_py.adapters.base import (
    Adapter,
    AdapterCapabilities,
    ExecuteOptions,
    ExecuteResult,
)
from openralph_py.loop import build_status, run_iteration
from openralph_py.plan import Task, load_tasks, save_tasks, write_prd_json
from openralph_py.workspace import Workspace


class FakeAdapter(Adapter):
    """Adapter that simulates a worker marking the selected task complete."""

    name = "fake"
    display_name = "Fake (test)"

    def __init__(self, *, mark_complete: bool = True, exit_code: int = 0) -> None:
        self.mark_complete = mark_complete
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
        return ExecuteResult(
            exit_code=self.exit_code,
            stdout="<promise>TASK_DONE</promise>\n",
            stderr="",
            duration_seconds=0.01,
        )


def _seed_workspace(tmp_path: Path, tasks: list[Task]) -> Workspace:
    ws = Workspace(tmp_path)
    ws.ensure()
    write_prd_json(ws.prd_path, tasks)
    ws.progress_path.write_text("", encoding="utf-8")
    return ws


def test_single_iteration_completes_one_task(tmp_path: Path):
    ws = _seed_workspace(tmp_path, [
        Task(id="a", description="first", passes=False),
        Task(id="b", description="second", passes=False),
    ])
    adapter = FakeAdapter()

    outcome = run_iteration(ws.root, adapter)

    assert outcome.status == "ran"
    assert outcome.iteration == 1
    assert outcome.task is not None and outcome.task.id == "a"
    tasks_after = load_tasks(ws.prd_path)
    assert [t.passes for t in tasks_after] == [True, False]
    assert ws.state_path.exists()
    state_data = json.loads(ws.state_path.read_text(encoding="utf-8"))
    assert state_data["iterations"] == 1
    assert state_data["last_task_id"] == "a"
    assert ws.progress_path.read_text(encoding="utf-8").count("## Iteration") == 1
    assert not ws.has_done_marker()


def test_repeated_runs_form_the_loop(tmp_path: Path):
    ws = _seed_workspace(tmp_path, [
        Task(id="a", description="first", passes=False),
        Task(id="b", description="second", passes=False),
        Task(id="c", description="third", passes=False),
    ])
    adapter = FakeAdapter()

    outcomes = [run_iteration(ws.root, adapter) for _ in range(3)]

    assert [o.status for o in outcomes] == ["ran", "ran", "ran"]
    assert [o.task.id for o in outcomes] == ["a", "b", "c"]
    tasks_after = load_tasks(ws.prd_path)
    assert all(t.passes for t in tasks_after)
    assert ws.has_done_marker(), "done marker should be written only after all tasks complete"
    state = json.loads(ws.state_path.read_text(encoding="utf-8"))
    assert state["iterations"] == 3
    assert len(state["iteration_durations"]) == 3
    # One more run should report already_complete, not advance iterations.
    extra = run_iteration(ws.root, adapter)
    assert extra.status == "already_complete"
    state = json.loads(ws.state_path.read_text(encoding="utf-8"))
    assert state["iterations"] == 3


def test_adapter_failure_preserves_incomplete_state(tmp_path: Path):
    ws = _seed_workspace(tmp_path, [
        Task(id="a", description="first", passes=False),
    ])
    adapter = FakeAdapter(mark_complete=False, exit_code=1)

    outcome = run_iteration(ws.root, adapter)

    assert outcome.status == "ran"
    tasks_after = load_tasks(ws.prd_path)
    assert tasks_after[0].passes is False, "failed run must not fake completion"
    assert not ws.has_done_marker()
    log = ws.progress_path.read_text(encoding="utf-8")
    assert "Exit: 1" in log


def test_stale_done_marker_is_removed(tmp_path: Path):
    ws = _seed_workspace(tmp_path, [
        Task(id="a", description="first", passes=False),
    ])
    ws.write_done_marker()
    adapter = FakeAdapter()

    outcome = run_iteration(ws.root, adapter)

    assert outcome.status == "ran"
    assert ws.has_done_marker(), "marker re-written because final task was completed"
    tasks_after = load_tasks(ws.prd_path)
    assert tasks_after[0].passes is True


def test_run_without_prd_errors(tmp_path: Path):
    adapter = FakeAdapter()
    outcome = run_iteration(tmp_path, adapter)
    assert outcome.status == "error"
    assert "prd.json" in outcome.message


def test_status_report(tmp_path: Path):
    ws = _seed_workspace(tmp_path, [
        Task(id="a", description="first", passes=False),
        Task(id="b", description="second", passes=False),
    ])
    adapter = FakeAdapter()
    run_iteration(ws.root, adapter)

    report = build_status(ws.root)
    assert report.total == 2
    assert report.completed == 1
    assert report.next_task is not None and report.next_task.id == "b"
    assert report.iterations == 1
    assert report.last_task_id == "a"
    assert report.done_marker is False
    text = report.format()
    assert "1/2 complete" in text
