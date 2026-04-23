from __future__ import annotations

import json
from pathlib import Path

from openralph_py.plan import (
    Task,
    load_tasks,
    parse_markdown_plan,
    parse_prd_json,
    save_tasks,
    write_prd_json,
)


def test_parse_markdown_checkboxes():
    text = """\
# Plan

- [ ] write parser
- [x] scaffold repo
- [ ] [ui] add button
- [ ] plain task with - [ ] inside should not count (it's inline text)
"""
    tasks = parse_markdown_plan(text)
    # Note: line 5 still counts because the regex is line-anchored and the
    # leading "- [ ]" of that line is a valid checkbox.
    assert len(tasks) == 4
    assert tasks[0].description == "write parser"
    assert tasks[0].passes is False
    assert tasks[1].passes is True
    assert tasks[2].category == "ui"
    assert tasks[2].description == "add button"


def test_markdown_skips_fenced_code_blocks():
    text = """\
# Plan
- [ ] real task
```
- [ ] not a real task
```
- [x] another real task
"""
    tasks = parse_markdown_plan(text)
    assert [t.description for t in tasks] == ["real task", "another real task"]


def test_parse_prd_json_wrapped():
    data = {
        "metadata": {"generated": True, "generator": "test"},
        "items": [
            {"id": "1.1", "description": "first", "passes": False},
            {"description": "second", "passes": True},
        ],
    }
    tasks = parse_prd_json(json.dumps(data))
    assert tasks[0].id == "1.1"
    assert tasks[0].passes is False
    assert tasks[1].id == "task-2"
    assert tasks[1].passes is True


def test_parse_prd_json_plain_array():
    data = [{"description": "x", "passes": False}]
    tasks = parse_prd_json(json.dumps(data))
    assert len(tasks) == 1
    assert tasks[0].description == "x"


def test_load_tasks_detects_format(tmp_path: Path):
    md = tmp_path / "plan.md"
    md.write_text("- [ ] todo\n- [x] done\n", encoding="utf-8")
    assert [t.passes for t in load_tasks(md)] == [False, True]

    js = tmp_path / "prd.json"
    js.write_text(json.dumps([{"description": "a", "passes": False}]), encoding="utf-8")
    assert load_tasks(js)[0].description == "a"


def test_write_and_save_preserves_metadata(tmp_path: Path):
    path = tmp_path / "prd.json"
    write_prd_json(
        path,
        [Task(id="t1", description="first", passes=False)],
        source_file="plan.md",
        created_at="2026-04-23T00:00:00Z",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["metadata"]["generated"] is True
    assert data["metadata"]["sourceFile"] == "plan.md"
    assert data["items"][0]["passes"] is False

    save_tasks(path, [Task(id="t1", description="first", passes=True)])
    data2 = json.loads(path.read_text(encoding="utf-8"))
    # Metadata preserved, items updated truthfully.
    assert data2["metadata"]["sourceFile"] == "plan.md"
    assert data2["items"][0]["passes"] is True
