"""Bounded text result contract for the worker output.

Phase 3 design mandate: the loop engine must not rely on vendor-native
JSON/JSONL as the source of truth for iteration outcomes. Instead, the
worker prompt instructs the agent to emit a deterministic, narrow text
block at the end of its output. This module owns the contract definition
and the local parser.

Block format — all five fields are required, order is flexible:

    <ralph-result>
    status: done|blocked|partial|error
    summary: one-line description of what changed
    verification: what was checked (tests run, files verified, etc.)
    complete: true|false
    blocker: none (or reason if the task is not complete)
    </ralph-result>

Parsing rules:
  - The block must appear exactly once in stdout.
  - All five fields must be present and non-empty (except blocker="none").
  - complete=true is only valid when status=done.
  - Any violation produces an UntrustedResult, not an exception.
  - Callers MUST NOT treat an UntrustedResult as successful completion.
  - The plan (prd.json) remains the ground-truth for completion; this block
    is an additional honesty signal from the worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BLOCK_RE = re.compile(r"<ralph-result>(.*?)</ralph-result>", re.DOTALL | re.IGNORECASE)
_REQUIRED_KEYS = frozenset({"status", "summary", "verification", "complete", "blocker"})
_VALID_STATUSES = frozenset({"done", "blocked", "partial", "error"})

# The literal block template injected into the worker prompt (see workspace.py).
RESULT_BLOCK_TEMPLATE = """\
<ralph-result>
status: done|blocked|partial|error
summary: one-line description of what you did
verification: what you checked (tests run, files verified, etc.)
complete: true|false
blocker: none (or reason if the task is not complete)
</ralph-result>"""


@dataclass(frozen=True)
class WorkerResultBlock:
    """Parsed, validated result from the worker's bounded output block.

    All fields come directly from the block.  ``is_trusted=True`` means the
    parser found a well-formed block; it does NOT guarantee the worker did
    correct work — that is confirmed by the plan file (prd.json).
    """

    status: str        # done | blocked | partial | error
    summary: str       # one-line description of what changed
    verification: str  # what was run or checked
    complete: bool     # True only when status=done AND complete=true
    blocker: str       # "none" or reason for incomplete

    @property
    def is_trusted(self) -> bool:
        return True

    @property
    def completion_confidence(self) -> str:
        """Promise-level confidence based on block content alone."""
        if self.complete and self.status == "done":
            return "promise-confirmed"
        return "promise-denied"


@dataclass(frozen=True)
class UntrustedResult:
    """Returned when the worker output does not match the bounded contract.

    Callers must treat this as "worker did not report cleanly" — not as
    failure, but also not as success.  Plan-based completion detection
    still applies.
    """

    raw_stdout: str
    reason: str

    @property
    def is_trusted(self) -> bool:
        return False

    @property
    def complete(self) -> bool:
        return False

    @property
    def status(self) -> str:
        return "untrusted"

    @property
    def summary(self) -> str:
        return ""

    @property
    def verification(self) -> str:
        return ""

    @property
    def blocker(self) -> str:
        return self.reason

    @property
    def completion_confidence(self) -> str:
        return "unverified"


# Union type used throughout the Phase 3 codebase.
WorkerResult = WorkerResultBlock | UntrustedResult


def parse_worker_result(stdout: str) -> WorkerResult:
    """Parse the bounded ``<ralph-result>`` block from worker stdout.

    Returns ``WorkerResultBlock`` on clean parse.
    Returns ``UntrustedResult`` on any violation.
    Never raises.
    """
    matches = _BLOCK_RE.findall(stdout)
    if not matches:
        return UntrustedResult(
            raw_stdout=stdout,
            reason="no <ralph-result> block found in worker output",
        )
    if len(matches) > 1:
        return UntrustedResult(
            raw_stdout=stdout,
            reason=(
                f"multiple <ralph-result> blocks found ({len(matches)}); "
                "expected exactly one"
            ),
        )

    body = matches[0]
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        # Only keep the first occurrence of each key (ignore duplicates).
        if key not in fields:
            fields[key] = val

    missing = _REQUIRED_KEYS - set(fields)
    if missing:
        return UntrustedResult(
            raw_stdout=stdout,
            reason=f"missing required fields in <ralph-result>: {sorted(missing)}",
        )

    status = fields["status"].lower()
    if status not in _VALID_STATUSES:
        return UntrustedResult(
            raw_stdout=stdout,
            reason=(
                f"invalid status {status!r}; "
                f"expected one of {sorted(_VALID_STATUSES)}"
            ),
        )

    complete_raw = fields["complete"].lower()
    if complete_raw not in ("true", "false"):
        return UntrustedResult(
            raw_stdout=stdout,
            reason=(
                f"invalid complete value {complete_raw!r}; "
                "expected 'true' or 'false'"
            ),
        )
    complete = complete_raw == "true"

    # Consistency: complete=true requires status=done.
    if complete and status != "done":
        return UntrustedResult(
            raw_stdout=stdout,
            reason=(
                f"complete=true but status={status!r}; "
                "complete=true requires status=done"
            ),
        )

    # summary and verification must not be empty.
    for key in ("summary", "verification"):
        if not fields[key]:
            return UntrustedResult(
                raw_stdout=stdout,
                reason=f"field '{key}' must not be empty",
            )

    return WorkerResultBlock(
        status=status,
        summary=fields["summary"],
        verification=fields["verification"],
        complete=complete,
        blocker=fields["blocker"],
    )
