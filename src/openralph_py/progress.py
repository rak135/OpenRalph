"""Append-only progress log.

Phase 1 uses a plain text log with dated iteration headers. The worker is
also encouraged (via the prompt) to append its own narrative entries; the
loop's contribution here is the bookkeeping line.

Phase 3 addition: iteration entries now include a ``result_confidence``
line that reports the completion confidence derived from the bounded text
result contract (result_contract.py).  This makes the progress log useful
for auditing whether the worker honored the result block contract.
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
    result_confidence: str | None = None,  # Phase 3: from IterationOutcome.completion_confidence
    result_summary: str | None = None,     # Phase 3: from parsed WorkerResultBlock.summary
    now: datetime | None = None,
) -> None:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"## Iteration {iteration} - {stamp}",
        f"- Task: {task_id} {task_description}",
        f"- Exit: {exit_code}",
        f"- Duration: {duration_seconds:.1f}s",
    ]
    if result_confidence is not None:
        lines.append(f"- Confidence: {result_confidence}")
    if result_summary:
        lines.append(f"- Worker summary: {result_summary}")
    if notes:
        lines.append(f"- Notes: {notes}")
    entry = "\n".join(lines) + "\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
