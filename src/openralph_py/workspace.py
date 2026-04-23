"""Workspace layout and filesystem conventions.

A workspace is any directory that holds the Ralph-style loop files. The
layout deliberately mirrors the source repo's semantics (PRD JSON, progress
log, state file, done marker, prompt template) without pulling in any
TUI/PTY concerns.

Phase 3 additions:
  - LOCK_FILE (.ralph-lock) — per-workspace PID-based lock used by run_loop()
    to prevent concurrent invocations.
  - Lock / acquire_lock() — acquire/release helpers on Workspace.
  - DEFAULT_PROMPT_TEMPLATE updated to require the <ralph-result> block so
    the deterministic parser (result_contract.py) has something to parse.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

PRD_FILE = "prd.json"
PROGRESS_FILE = "progress.txt"
PROMPT_FILE = ".ralph-prompt.md"
STATE_FILE = ".ralph-state.json"
DONE_FILE = ".ralph-done"
LOCK_FILE = ".ralph-lock"

DEFAULT_PROMPT_TEMPLATE = """\
You are a software agent executing one task in an automated loop. Follow every step.

WORKSPACE: {workspace}
PLAN FILE: {plan}  (JSON — each item has "id", "description", "passes" boolean)
PROGRESS:  {progress}

TASK ID:   {task_id}
TASK:      {task_description}

STEPS (all mandatory):
1. Read {plan}. Confirm "{task_id}" exists with "passes": false.
2. Implement the task. Do real work (write files, run commands). Do not just inspect.
3. Verify: check the result is correct (read the file back, run the test, etc.).
4. Update {plan}: set "passes": true for the item whose "id" is "{task_id}". Keep all other items unchanged.
5. Append to {progress}: "task {task_id}: <one sentence of what you did>"
6. If every item in {plan} now has "passes": true, create the file {done_marker}.
7. End your response with the block below. Fill in the summary and verification fields.

<ralph-result>
status: done
summary: <what you implemented>
verification: <how you verified it>
complete: true
blocker: none
</ralph-result>

If you could not complete the task, use status: blocked, complete: false, and describe the blocker field.
Do NOT skip step 4 (plan update) or step 7 (result block). Do NOT run git push.
"""


def _is_process_running(pid: int) -> bool:
    """Return True if a process with *pid* is currently running on this host.

    On Windows ``os.kill(pid, 0)`` sends CTRL_C_EVENT (signal 0) rather than
    the POSIX "null signal" probe, which would interrupt the current process.
    We use the Windows kernel API instead.
    """
    if platform.system() == "Windows":
        import ctypes  # available on all CPython/Windows builds
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    # POSIX: null-signal probe.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it.
        return True


@dataclass
class Lock:
    """Represents an acquired workspace lock.  Release via `.release()` or
    use as a context manager."""

    path: Path

    def release(self) -> None:
        """Remove the lock file.  Safe to call multiple times."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "Lock":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


@dataclass
class Workspace:
    root: Path

    @property
    def prd_path(self) -> Path:
        return self.root / PRD_FILE

    @property
    def progress_path(self) -> Path:
        return self.root / PROGRESS_FILE

    @property
    def prompt_path(self) -> Path:
        return self.root / PROMPT_FILE

    @property
    def state_path(self) -> Path:
        return self.root / STATE_FILE

    @property
    def done_path(self) -> Path:
        return self.root / DONE_FILE

    @property
    def lock_path(self) -> Path:
        return self.root / LOCK_FILE

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def has_done_marker(self) -> bool:
        return self.done_path.exists()

    def write_done_marker(self) -> None:
        self.done_path.write_text("complete\n", encoding="utf-8")

    def remove_done_marker(self) -> None:
        if self.done_path.exists():
            self.done_path.unlink()

    # ------------------------------------------------------------------
    # Phase 3: lock support
    # ------------------------------------------------------------------

    def acquire_lock(self) -> Lock | None:
        """Try to acquire the workspace execution lock.

        Returns a ``Lock`` on success.
        Returns ``None`` if a live process already holds the lock.

        Stale locks (PID no longer running) are removed automatically.
        """
        lock_path = self.lock_path
        if lock_path.exists():
            try:
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                pid = int(data.get("pid", 0))
            except (json.JSONDecodeError, ValueError, OSError):
                pid = 0

            if pid and _is_process_running(pid):
                return None  # Live lock held by another process.
            # Stale lock — clean it up.
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

        lock_data = {"pid": os.getpid()}
        lock_path.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")
        return Lock(lock_path)
