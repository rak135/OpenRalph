"""Worker prompt construction.

The worker prompt is intentionally short, explicit, and action-oriented.
It pins the agent to a single task and tells it how to truthfully update
state.
"""

from __future__ import annotations

from pathlib import Path

from openralph_py.plan import Task
from openralph_py.workspace import (
    DEFAULT_PROMPT_TEMPLATE,
    DONE_FILE,
    PROGRESS_FILE,
    PRD_FILE,
    Workspace,
)


def load_template(ws: Workspace) -> str:
    if ws.prompt_path.exists():
        text = ws.prompt_path.read_text(encoding="utf-8")
        if text.strip():
            return text
    return DEFAULT_PROMPT_TEMPLATE


def build_prompt(ws: Workspace, task: Task, *, template: str | None = None) -> str:
    tpl = template if template is not None else load_template(ws)
    return tpl.format(
        workspace=str(ws.root),
        plan=PRD_FILE,
        progress=PROGRESS_FILE,
        done_marker=DONE_FILE,
        task_id=task.id,
        task_description=task.description,
    )


def write_default_prompt(path: Path) -> None:
    path.write_text(DEFAULT_PROMPT_TEMPLATE, encoding="utf-8")
