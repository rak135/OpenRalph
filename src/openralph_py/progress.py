"""Append-only progress log.

Phase 1 uses a plain text log with dated iteration headers. The worker is
also encouraged (via the prompt) to append its own narrative entries; the
loop's contribution here is the bookkeeping line.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def append_iteration_entry(
    path: Path,
    *,
    iteration: int,
    task_id: str,
    task_description: str,
    exit_code: int,
    duration_seconds: float,
    notes: str | None = None,
    now: datetime | None = None,
) -> None:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"## Iteration {iteration} - {stamp}",
        f"- Task: {task_id} {task_description}",
        f"- Exit: {exit_code}",
        f"- Duration: {duration_seconds:.1f}s",
    ]
    if notes:
        lines.append(f"- Notes: {notes}")
    entry = "\n".join(lines) + "\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
