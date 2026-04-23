"""The real Phase 1 Ralph loop.

One call to `run_iteration` is exactly one iteration. It:

    1. Loads persistent state and the current PRD.
    2. Handles pre-existing `.ralph-done` (honoring it only if truly done).
    3. Picks one incomplete task deterministically.
    4. Builds the worker prompt.
    5. Invokes the adapter.
    6. Reloads PRD to observe any truthful updates made by the worker.
    7. Appends a progress entry, saves state, and writes the done marker
       if (and only if) all items now have passes=true.

Repeated invocations over persisted state form the multi-step Ralph loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time

from openralph_py.adapters import Adapter, ExecuteOptions, ExecuteResult
from openralph_py.plan import Task, load_tasks
from openralph_py.progress import append_iteration_entry
from openralph_py.prompt import build_prompt
from openralph_py.selector import all_complete, count_completed, select_next_task
from openralph_py.state import PersistedState, load_or_create_state, save_state
from openralph_py.workspace import PRD_FILE, Workspace


@dataclass
class IterationOutcome:
    status: str  # "ran" | "already_complete" | "no_tasks" | "error"
    iteration: int
    task: Task | None
    adapter_result: ExecuteResult | None
    tasks_before: list[Task]
    tasks_after: list[Task]
    completed_now: bool
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("ran", "already_complete")


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

    newly_complete = all_complete(tasks_after)
    if newly_complete and not ws.has_done_marker():
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

    append_iteration_entry(
        ws.progress_path,
        iteration=iteration_no,
        task_id=next_task.id,
        task_description=next_task.description,
        exit_code=result.exit_code,
        duration_seconds=result.duration_seconds or duration,
        notes=notes,
    )

    return IterationOutcome(
        status="ran",
        iteration=iteration_no,
        task=next_task,
        adapter_result=result,
        tasks_before=tasks_before,
        tasks_after=tasks_after,
        completed_now=newly_complete,
        message="iteration complete",
    )


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
    if not ws.prd_path.exists():
        return StatusReport(
            total=0,
            completed=0,
            next_task=None,
            done_marker=ws.has_done_marker(),
            iterations=0,
            last_task_id=None,
            last_exit_code=None,
        )
    tasks = load_tasks(ws.prd_path)
    state = load_or_create_state(ws.state_path, plan_file=PRD_FILE) if ws.state_path.exists() else PersistedState(plan_file=PRD_FILE)
    return StatusReport(
        total=len(tasks),
        completed=count_completed(tasks),
        next_task=select_next_task(tasks),
        done_marker=ws.has_done_marker(),
        iterations=state.iterations,
        last_task_id=state.last_task_id,
        last_exit_code=state.last_exit_code,
    )
