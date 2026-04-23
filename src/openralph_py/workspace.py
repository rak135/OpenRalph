"""Workspace layout and filesystem conventions.

A workspace is any directory that holds the Ralph-style loop files. The
layout deliberately mirrors the source repo's semantics (PRD JSON, progress
log, state file, done marker, prompt template) without pulling in any
TUI/PTY concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PRD_FILE = "prd.json"
PROGRESS_FILE = "progress.txt"
PROMPT_FILE = ".ralph-prompt.md"
STATE_FILE = ".ralph-state.json"
DONE_FILE = ".ralph-done"

DEFAULT_PROMPT_TEMPLATE = """\
Ralph-style iterative loop. Work inside the workspace at {workspace}.

Full plan is in {plan} (PRD JSON). Each item has a `passes` boolean.
Progress log is in {progress}.

You have been given exactly ONE task to complete this iteration:

  id:          {task_id}
  description: {task_description}

Rules:
1. Do only this single task. Do not start other tasks.
2. When the task is complete, update {plan} so the item with id={task_id}
   has passes=true. Preserve all other fields of that item.
3. Append a short entry to {progress} describing what changed and why.
4. If ALL items in {plan} now have passes=true, create the file
   {done_marker} in the workspace root to signal completion.
5. You may run `git commit`, but you MUST NOT run `git push`.
6. End your final output with the marker <promise>TASK_DONE</promise>
   on its own line when the task is genuinely complete.
"""


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

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def has_done_marker(self) -> bool:
        return self.done_path.exists()

    def write_done_marker(self) -> None:
        self.done_path.write_text("complete\n", encoding="utf-8")

    def remove_done_marker(self) -> None:
        if self.done_path.exists():
            self.done_path.unlink()
