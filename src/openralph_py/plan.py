"""PRD / markdown plan parsing and persistence.

A Task carries the stable identity that is used across iterations. Two
input formats are supported, mirroring the source repository:

    1. PRD JSON: either a plain array of items, or a wrapped object with
       `metadata` + `items`. Each item must have `description` and `passes`.
    2. Markdown checkbox lists: `- [ ] text` or `- [x] text`.

Phase 1 persists tasks as wrapped PRD JSON. The markdown path is the
ingestion format for `init --from plan.md`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.+?)\s*$")
CATEGORY_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\]\s*(.+)$")


@dataclass
class Task:
    id: str
    description: str
    passes: bool = False
    category: str | None = None
    steps: list[str] = field(default_factory=list)

    def to_prd_item(self) -> dict:
        item: dict = {
            "id": self.id,
            "description": self.description,
            "passes": self.passes,
        }
        if self.category:
            item["category"] = self.category
        if self.steps:
            item["steps"] = list(self.steps)
        return item

    @classmethod
    def from_prd_item(cls, item: dict, index: int) -> "Task":
        if not isinstance(item, dict):
            raise ValueError(f"PRD item at index {index} is not an object")
        description = item.get("description") or item.get("title")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"PRD item at index {index} missing 'description'")
        passes = item.get("passes", False)
        if not isinstance(passes, bool):
            raise ValueError(f"PRD item at index {index} has non-boolean 'passes'")
        raw_id = item.get("id")
        task_id = raw_id if isinstance(raw_id, str) and raw_id else f"task-{index + 1}"
        category = item.get("category") if isinstance(item.get("category"), str) else None
        raw_steps = item.get("steps", [])
        steps: list[str] = []
        if isinstance(raw_steps, list):
            for s in raw_steps:
                if isinstance(s, str):
                    steps.append(s)
        return cls(
            id=task_id,
            description=description.strip(),
            passes=passes,
            category=category,
            steps=steps,
        )


def parse_markdown_plan(text: str) -> list[Task]:
    """Extract tasks from a markdown plan.

    Ignores checkboxes inside fenced code blocks. A leading `[tag]` in the
    task text is lifted into `category`.
    """
    tasks: list[Task] = []
    in_code_block = False
    next_index = 1
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        match = CHECKBOX_RE.match(line)
        if not match:
            continue
        _, mark, body = match.groups()
        body = body.strip()
        category: str | None = None
        cat_match = CATEGORY_RE.match(body)
        if cat_match:
            category = cat_match.group(1)
            body = cat_match.group(2).strip()
        tasks.append(
            Task(
                id=f"task-{next_index}",
                description=body,
                passes=mark.lower() == "x",
                category=category,
            )
        )
        next_index += 1
    return tasks


def _extract_items(data: object) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    raise ValueError("PRD JSON must be an array or an object with 'items'")


def parse_prd_json(text: str) -> list[Task]:
    data = json.loads(text)
    raw_items = _extract_items(data)
    return [Task.from_prd_item(item, i) for i, item in enumerate(raw_items)]


def load_tasks(path: Path) -> list[Task]:
    text = path.read_text(encoding="utf-8")
    trimmed = text.lstrip()
    if trimmed.startswith("{") or trimmed.startswith("["):
        return parse_prd_json(text)
    return parse_markdown_plan(text)


def write_prd_json(
    path: Path,
    tasks: Iterable[Task],
    *,
    source_file: str | None = None,
    generator: str = "openralph-py-init",
    created_at: str | None = None,
) -> None:
    metadata: dict = {
        "generated": True,
        "generator": generator,
    }
    if created_at:
        metadata["createdAt"] = created_at
    if source_file:
        metadata["sourceFile"] = source_file
    payload = {
        "metadata": metadata,
        "items": [t.to_prd_item() for t in tasks],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def save_tasks(path: Path, tasks: Iterable[Task]) -> None:
    """Update an existing PRD JSON file, preserving its metadata wrapper if any."""
    tasks = list(tasks)
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    wrapper: dict
    if existing_text.strip():
        data = json.loads(existing_text)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            wrapper = dict(data)
        else:
            wrapper = {"items": []}
    else:
        wrapper = {"items": []}
    wrapper["items"] = [t.to_prd_item() for t in tasks]
    path.write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")


def task_to_dict(task: Task) -> dict:
    return asdict(task)
