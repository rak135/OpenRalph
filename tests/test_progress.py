from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openralph_py.progress import append_iteration_entry


def test_appends_entry(tmp_path: Path):
    log = tmp_path / "progress.txt"
    log.write_text("", encoding="utf-8")
    append_iteration_entry(
        log,
        iteration=1,
        task_id="t-1",
        task_description="do a thing",
        exit_code=0,
        duration_seconds=2.5,
        now=datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc),
    )
    append_iteration_entry(
        log,
        iteration=2,
        task_id="t-2",
        task_description="do another",
        exit_code=1,
        duration_seconds=3.1,
        notes="timed out",
        now=datetime(2026, 4, 23, 12, 5, 0, tzinfo=timezone.utc),
    )
    text = log.read_text(encoding="utf-8")
    assert "## Iteration 1 - 2026-04-23T12:00:00Z" in text
    assert "- Task: t-1 do a thing" in text
    assert "- Exit: 0" in text
    assert "## Iteration 2 - 2026-04-23T12:05:00Z" in text
    assert "- Notes: timed out" in text
    # Two entries means two "## Iteration" headers.
    assert text.count("## Iteration") == 2
