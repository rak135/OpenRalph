"""Deterministic selection of the single task to execute this iteration.

The source repository biases selection toward highest-risk/highest-impact
items. Phase 1 uses the simplest deterministic rule that preserves the
loop's correctness: the first item with `passes=false`, in original plan
order. This is easy to reason about and stable across runs.
"""

from __future__ import annotations

from openralph_py.plan import Task


def select_next_task(tasks: list[Task]) -> Task | None:
    for task in tasks:
        if not task.passes:
            return task
    return None


def count_completed(tasks: list[Task]) -> int:
    return sum(1 for t in tasks if t.passes)


def all_complete(tasks: list[Task]) -> bool:
    return len(tasks) > 0 and all(t.passes for t in tasks)
