"""The real Phase 1/2/3 Ralph loop.

One call to `run_iteration` is exactly one iteration. It:

    1. Loads persistent state and the current PRD.
    2. Handles pre-existing `.ralph-done` (honoring it only if truly done).
    3. Picks one incomplete task deterministically.
    4. Builds the worker prompt.
    5. Invokes the adapter.
    6. Reloads PRD to observe any truthful updates made by the worker.
    7. Parses the bounded ``<ralph-result>`` block from worker stdout.
    8. Appends a progress entry, saves state, and writes the done marker
       if (and only if) all items now have passes=true.

Repeated invocations over persisted state form the multi-step Ralph loop.

Phase 3 adds `run_loop()` — a bounded multi-iteration wrapper that:
  - acquires a workspace lock (preventing concurrent invocations)
  - loops until max_iterations is reached, all tasks complete, or an error
  - returns a `LoopSummary` with a clear `StopReason`
  - uses the parsed result block (not vendor JSON) to enrich reporting

Design rule: prd.json is the source of truth for completion.  The
``<ralph-result>`` block provides an additional honesty signal from the
worker but does NOT override the plan.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import time

from openralph_py.adapters import Adapter, ExecuteOptions, ExecuteResult
from openralph_py.plan import Task, load_tasks
from openralph_py.progress import append_iteration_entry
from openralph_py.prompt import build_prompt
from openralph_py.result_contract import WorkerResult, parse_worker_result
from openralph_py.selector import all_complete, count_completed, select_next_task
from openralph_py.state import load_or_create_state, save_state
from openralph_py.workspace import PRD_FILE, Workspace


# ---------------------------------------------------------------------------
# Phase 3: stop reasons and loop summary
# ---------------------------------------------------------------------------


class StopReason(str, Enum):
    """Why `run_loop` stopped iterating."""

    ALL_COMPLETE = "all_complete"          # All plan tasks are done
    ALREADY_COMPLETE = "already_complete"  # Complete before first iteration
    MAX_ITERATIONS = "max_iterations"      # Hit the caller-supplied limit
    NO_TASKS = "no_tasks"                  # PRD has no tasks at all
    ADAPTER_ERROR = "adapter_error"        # Adapter raised an unrecoverable error
    LOCK_CONFLICT = "lock_conflict"        # Another process holds the workspace lock
    NO_PROGRESS = "no_progress"            # Same task repeated N times with no prd advancement


@dataclass
class LoopSummary:
    """Summary of a `run_loop()` run."""

    stop_reason: StopReason
    iterations_run: int
    total_tasks: int
    completed_tasks: int
    session_id: str
    no_progress_threshold: int
    outcomes: list["IterationOutcome"] = field(default_factory=list)

    @property
    def all_complete(self) -> bool:
        return self.stop_reason in (StopReason.ALL_COMPLETE, StopReason.ALREADY_COMPLETE)

    def format(self) -> str:
        lines = [
            f"Session:     {self.session_id}",
            f"Stop reason: {self.stop_reason.value}",
            f"Iterations:  {self.iterations_run}",
            f"Progress:    {self.completed_tasks}/{self.total_tasks} tasks complete",
            f"No-progress threshold: {self.no_progress_threshold}",
        ]
        if self.outcomes:
            lines.append("Iterations:")
            for o in self.outcomes:
                task_label = o.task.id if o.task else "(none)"
                confidence = o.completion_confidence
                # Show task-level and plan-level prd confirmation separately.
                prd_task = "prd-task:yes" if o.task_confirmed else "prd-task:no"
                prd_plan = "prd-plan:yes" if o.completed_now else "prd-plan:no"
                lines.append(
                    f"  #{o.iteration} task={task_label}"
                    f" exit={o.adapter_result.exit_code if o.adapter_result else 'n/a'}"
                    f" {prd_task} {prd_plan}"
                    f" confidence={confidence}"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core iteration type (extended in Phase 3 with parsed_result)
# ---------------------------------------------------------------------------


@dataclass
class IterationOutcome:
    status: str  # "ran" | "already_complete" | "no_tasks" | "error"
    iteration: int
    task: Task | None
    adapter_result: ExecuteResult | None
    tasks_before: list[Task]
    tasks_after: list[Task]
    task_confirmed: bool
    prd_advanced: bool
    completed_now: bool
    message: str = ""
    # Phase 3: result from the deterministic parser.  None means run_iteration
    # was not asked to parse (backward-compat), WorkerResult otherwise.
    parsed_result: WorkerResult | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ran", "already_complete")

    @property
    def completion_confidence(self) -> str:
        """Combined confidence level based on plan state and parsed result block.

        Levels (from strongest to weakest):
          promise-and-plan-confirmed  — worker promise + current task confirmed + plan complete
          promise-and-task-confirmed  — worker promise + current task confirmed (plan still partial)
          task-confirmed              — current task confirmed in plan, no trusted promise
          promise-only                — trusted promise claims complete, plan does not confirm
          unverified                  — plan incomplete, block absent/untrusted
        """
        task_done = self.task_confirmed
        plan_done = self.completed_now
        promise_ok = (
            self.parsed_result is not None
            and self.parsed_result.is_trusted
            and self.parsed_result.complete
        )
        if plan_done and task_done and promise_ok:
            return "promise-and-plan-confirmed"
        if task_done and promise_ok:
            return "promise-and-task-confirmed"
        if task_done:
            return "task-confirmed"
        # Block present but says done while plan disagrees → suspicious label.
        if promise_ok:
            return "promise-only"
        return "unverified"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _handle_preexisting_done(ws: Workspace, tasks: list[Task]) -> bool:
    """Return True if the `.ralph-done` marker is valid and should stop the loop.

    Matches the source repo's behavior: if the marker exists but tasks
    aren't actually all complete, the marker is treated as stale and removed.
    """
    if not ws.has_done_marker():
        return False
    if all_complete(tasks):
        return True
    ws.remove_done_marker()
    return False


# ---------------------------------------------------------------------------
# Single-iteration entry point
# ---------------------------------------------------------------------------


def run_iteration(
    workspace_root: Path,
    adapter: Adapter,
    *,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> IterationOutcome:
    ws = Workspace(workspace_root)
    ws.ensure()

    if not ws.prd_path.exists():
        return IterationOutcome(
            status="error",
            iteration=0,
            task=None,
            adapter_result=None,
            tasks_before=[],
            tasks_after=[],
            task_confirmed=False,
            prd_advanced=False,
            completed_now=False,
            message=f"{PRD_FILE} not found; run `init` first",
        )

    state = load_or_create_state(ws.state_path, plan_file=PRD_FILE)
    tasks_before = load_tasks(ws.prd_path)

    if _handle_preexisting_done(ws, tasks_before):
        return IterationOutcome(
            status="already_complete",
            iteration=state.iterations,
            task=None,
            adapter_result=None,
            tasks_before=tasks_before,
            tasks_after=tasks_before,
            task_confirmed=False,
            prd_advanced=False,
            completed_now=False,
            message=".ralph-done present and plan is complete",
        )

    if all_complete(tasks_before):
        if not ws.has_done_marker():
            ws.write_done_marker()
        return IterationOutcome(
            status="already_complete",
            iteration=state.iterations,
            task=None,
            adapter_result=None,
            tasks_before=tasks_before,
            tasks_after=tasks_before,
            task_confirmed=False,
            prd_advanced=False,
            completed_now=True,
            message="All tasks already complete; wrote .ralph-done",
        )

    next_task = select_next_task(tasks_before)
    if next_task is None:
        return IterationOutcome(
            status="no_tasks",
            iteration=state.iterations,
            task=None,
            adapter_result=None,
            tasks_before=tasks_before,
            tasks_after=tasks_before,
            task_confirmed=False,
            prd_advanced=False,
            completed_now=False,
            message="No tasks in plan",
        )

    prompt_text = build_prompt(ws, next_task)
    options = ExecuteOptions(
        prompt=prompt_text,
        cwd=ws.root,
        model=model,
        timeout_seconds=timeout_seconds,
    )

    iteration_no = state.iterations + 1
    started = time()
    result = adapter.execute(options)
    duration = time() - started

    tasks_after = load_tasks(ws.prd_path) if ws.prd_path.exists() else tasks_before

    # Phase 3: parse the bounded result block from worker stdout.
    parsed = parse_worker_result(result.stdout)

    # Task truth comes from prd.json: was the selected task actually marked passes=true?
    task_confirmed = any(t.id == next_task.id and t.passes for t in tasks_after)
    prd_advanced = count_completed(tasks_after) > count_completed(tasks_before)
    plan_complete = all_complete(tasks_after)
    if plan_complete and not ws.has_done_marker():
        ws.write_done_marker()

    state.iterations = iteration_no
    state.iteration_durations.append(result.duration_seconds or duration)
    state.last_run_at = time()
    state.last_task_id = next_task.id
    state.last_exit_code = result.exit_code
    save_state(ws.state_path, state)

    notes = None
    if result.timed_out:
        notes = f"adapter timed out after {options.timeout_seconds}s"

    outcome = IterationOutcome(
        status="ran",
        iteration=iteration_no,
        task=next_task,
        adapter_result=result,
        tasks_before=tasks_before,
        tasks_after=tasks_after,
        task_confirmed=task_confirmed,
        prd_advanced=prd_advanced,
        completed_now=plan_complete,
        parsed_result=parsed,
        message="iteration complete",
    )

    append_iteration_entry(
        ws.progress_path,
        iteration=iteration_no,
        task_id=next_task.id,
        task_description=next_task.description,
        exit_code=result.exit_code,
        duration_seconds=result.duration_seconds or duration,
        notes=notes,
        result_confidence=outcome.completion_confidence,
        result_summary=parsed.summary if parsed.is_trusted else None,
    )

    return outcome


# ---------------------------------------------------------------------------
# Phase 3: multi-iteration bounded loop
# ---------------------------------------------------------------------------


def run_loop(
    workspace_root: Path,
    adapter: Adapter,
    *,
    max_iterations: int | None = None,
    no_progress_threshold: int = 2,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> LoopSummary:
    """Run up to *max_iterations* iterations of the Ralph loop.

    Acquires the workspace lock before iterating.  Returns a ``LoopSummary``
    with a clear ``StopReason``.

    Stop conditions (checked in order each iteration):
      1. Lock cannot be acquired → LOCK_CONFLICT (immediately)
      2. All tasks complete → ALL_COMPLETE / ALREADY_COMPLETE
      3. No tasks in plan → NO_TASKS
      4. Adapter raised → ADAPTER_ERROR
        5. Same task repeated ``no_progress_threshold`` times with unverified confidence
         and no prd advancement → NO_PROGRESS
      6. max_iterations reached → MAX_ITERATIONS

    The plan (prd.json) is the source of truth for completion.  The parsed
    ``<ralph-result>`` block enriches reporting but does NOT stop the loop
    on its own.
    """
    if no_progress_threshold < 1:
        raise ValueError("no_progress_threshold must be >= 1")

    ws = Workspace(workspace_root)
    ws.ensure()

    session_id = str(uuid.uuid4())
    outcomes: list[IterationOutcome] = []

    lock = ws.acquire_lock()
    if lock is None:
        # Another process holds the lock; report immediately.
        tasks = load_tasks(ws.prd_path) if ws.prd_path.exists() else []
        return LoopSummary(
            stop_reason=StopReason.LOCK_CONFLICT,
            iterations_run=0,
            total_tasks=len(tasks),
            completed_tasks=count_completed(tasks),
            session_id=session_id,
            no_progress_threshold=no_progress_threshold,
        )

    with lock:
        # Persist session_id so external tooling can correlate state entries.
        state = load_or_create_state(ws.state_path, plan_file=PRD_FILE)
        state.session_id = session_id
        save_state(ws.state_path, state)

        stop_reason: StopReason | None = None
        iterations_run = 0

        # No-progress tracking: detect repeated unverified same-task attempts.
        _no_progress_task_id: str | None = None
        _no_progress_count: int = 0

        while True:
            # Check iteration cap before starting the next iteration.
            if max_iterations is not None and iterations_run >= max_iterations:
                stop_reason = StopReason.MAX_ITERATIONS
                break

            try:
                outcome = run_iteration(
                    workspace_root,
                    adapter,
                    model=model,
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                stop_reason = StopReason.ADAPTER_ERROR
                break

            outcomes.append(outcome)

            if outcome.status == "error":
                stop_reason = StopReason.ADAPTER_ERROR
                break

            if outcome.status == "no_tasks":
                stop_reason = StopReason.NO_TASKS
                break

            if outcome.status == "already_complete":
                stop_reason = StopReason.ALREADY_COMPLETE
                break

            # outcome.status == "ran"
            iterations_run += 1

            if outcome.completed_now:
                stop_reason = StopReason.ALL_COMPLETE
                break

            # No-progress detection: if the same task comes back with unverified
            # confidence and no prd advancement, increment the stall counter.
            current_task_id = outcome.task.id if outcome.task else None
            if (
                current_task_id is not None
                and outcome.completion_confidence == "unverified"
                and not outcome.prd_advanced
                and not outcome.completed_now
            ):
                if current_task_id == _no_progress_task_id:
                    _no_progress_count += 1
                else:
                    _no_progress_task_id = current_task_id
                    _no_progress_count = 1
                if _no_progress_count >= no_progress_threshold:
                    stop_reason = StopReason.NO_PROGRESS
                    break
            else:
                # Any real progress (prd advanced, different task, or trusted block)
                # resets the stall counter.
                _no_progress_task_id = current_task_id
                _no_progress_count = 0

        # Persist stop reason for status command.
        state = load_or_create_state(ws.state_path, plan_file=PRD_FILE)
        state.last_stop_reason = stop_reason.value if stop_reason else None
        save_state(ws.state_path, state)

    tasks_final = load_tasks(ws.prd_path) if ws.prd_path.exists() else []
    return LoopSummary(
        stop_reason=stop_reason or StopReason.ADAPTER_ERROR,
        iterations_run=iterations_run,
        total_tasks=len(tasks_final),
        completed_tasks=count_completed(tasks_final),
        session_id=session_id,
        no_progress_threshold=no_progress_threshold,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Status helper (unchanged from Phase 1/2)
# ---------------------------------------------------------------------------


@dataclass
class StatusReport:
    total: int
    completed: int
    next_task: Task | None
    done_marker: bool
    iterations: int
    last_task_id: str | None
    last_exit_code: int | None

    def format(self) -> str:
        lines = [
            f"Tasks:       {self.completed}/{self.total} complete",
        ]
        if self.next_task is not None:
            lines.append(f"Next:        {self.next_task.id}  {self.next_task.description}")
        else:
            lines.append("Next:        (none)")
        lines.append(f"Done marker: {'present' if self.done_marker else 'absent'}")
        lines.append(f"Iterations:  {self.iterations}")
        if self.last_task_id is not None:
            lines.append(
                f"Last run:    task={self.last_task_id} exit={self.last_exit_code}"
            )
        return "\n".join(lines)


def build_status(workspace_root: Path) -> StatusReport:
    ws = Workspace(workspace_root)
    tasks = load_tasks(ws.prd_path) if ws.prd_path.exists() else []
    state = load_or_create_state(ws.state_path, plan_file=PRD_FILE)
    return StatusReport(
        total=len(tasks),
        completed=count_completed(tasks),
        next_task=select_next_task(tasks),
        done_marker=ws.has_done_marker(),
        iterations=state.iterations,
        last_task_id=state.last_task_id,
        last_exit_code=state.last_exit_code,
    )
