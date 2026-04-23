"""Smoke tests for the CLI wiring.

We call `cli.main` directly with argv lists and assert on exit codes and
filesystem side-effects. We also register a fake adapter so `run` works
without invoking any external process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openralph_py import cli
from openralph_py.adapters import registry
from openralph_py.adapters.base import (
    Adapter,
    AdapterCapabilities,
    ExecuteOptions,
    ExecuteResult,
)
from openralph_py.plan import load_tasks, save_tasks
from openralph_py.workspace import Workspace


class _FakeCLIAdapter(Adapter):
    name = "fake-cli"
    display_name = "Fake CLI"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="arg",
            supports_model_flag=False,
            supports_non_interactive=True,
        )

    def is_available(self) -> bool:
        return True

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        ws = Workspace(options.cwd)
        if ws.prd_path.exists():
            tasks = load_tasks(ws.prd_path)
            for t in tasks:
                if not t.passes:
                    t.passes = True
                    break
            save_tasks(ws.prd_path, tasks)
        return ExecuteResult(exit_code=0, stdout="", stderr="", duration_seconds=0.0)


@pytest.fixture
def fake_adapter():
    name = _FakeCLIAdapter.name
    if name in registry._registry:
        del registry._registry[name]
    adapter = _FakeCLIAdapter()
    registry.register_adapter(adapter)
    yield adapter
    if name in registry._registry:
        del registry._registry[name]


def _write_plan(path: Path) -> None:
    path.write_text(
        "# plan\n- [ ] alpha\n- [ ] beta\n- [x] already done\n",
        encoding="utf-8",
    )


def test_init_creates_workspace_files(tmp_path: Path):
    plan = tmp_path / "plan.md"
    _write_plan(plan)
    workspace = tmp_path / "ws"

    rc = cli.main(["init", "--from", str(plan), "--workspace", str(workspace)])
    assert rc == 0

    ws = Workspace(workspace)
    assert ws.prd_path.exists()
    assert ws.progress_path.exists()
    assert ws.prompt_path.exists()

    data = json.loads(ws.prd_path.read_text(encoding="utf-8"))
    assert data["metadata"]["generated"] is True
    assert len(data["items"]) == 3
    assert data["items"][0]["passes"] is False
    assert data["items"][2]["passes"] is True


def test_init_refuses_overwrite_without_force(tmp_path: Path):
    plan = tmp_path / "plan.md"
    _write_plan(plan)
    workspace = tmp_path / "ws"

    assert cli.main(["init", "--from", str(plan), "--workspace", str(workspace)]) == 0
    assert cli.main(["init", "--from", str(plan), "--workspace", str(workspace)]) == 1
    assert cli.main(["init", "--from", str(plan), "--workspace", str(workspace), "--force"]) == 0


def test_run_and_status_cycle(tmp_path: Path, fake_adapter, capsys):
    plan = tmp_path / "plan.md"
    _write_plan(plan)
    workspace = tmp_path / "ws"
    assert cli.main(["init", "--from", str(plan), "--workspace", str(workspace)]) == 0

    # First run completes "alpha".
    assert cli.main(["run", "--workspace", str(workspace), "--adapter", "fake-cli"]) == 0
    out = capsys.readouterr().out
    assert "iteration 1" in out

    # Second run completes "beta" and triggers the done marker.
    assert cli.main(["run", "--workspace", str(workspace), "--adapter", "fake-cli"]) == 0
    out = capsys.readouterr().out
    assert "all tasks complete" in out
    assert Workspace(workspace).has_done_marker()

    # Third run reports already complete (exit 2).
    assert cli.main(["run", "--workspace", str(workspace), "--adapter", "fake-cli"]) == 2

    # Status reflects truth.
    assert cli.main(["status", "--workspace", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "3/3 complete" in out
    assert "Done marker: present" in out
