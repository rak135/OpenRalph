"""OpenCode adapter tests.

Exercise the non-interactive `opencode run --print` path. The model
string is passed through literally — no provider prefix stripping.
"""

from __future__ import annotations

from pathlib import Path

from openralph_py.adapters.base import (
    CommandSpec,
    ExecuteOptions,
    RawSubprocessResult,
)
from openralph_py.adapters.opencode import OpenCodeAdapter


def test_build_command_uses_run_print_form(tmp_path: Path):
    spec = OpenCodeAdapter().build_command(
        ExecuteOptions(prompt="fix things", cwd=tmp_path)
    )
    assert spec.argv[:3] == ["opencode", "run", "--print"]
    assert spec.argv[-1] == "fix things"
    assert "--model" not in spec.argv


def test_build_command_passes_model_through_unchanged(tmp_path: Path):
    spec = OpenCodeAdapter().build_command(
        ExecuteOptions(prompt="p", cwd=tmp_path, model="anthropic/claude-sonnet-4-6"),
    )
    assert "--model" in spec.argv
    assert spec.argv[spec.argv.index("--model") + 1] == "anthropic/claude-sonnet-4-6"
    assert spec.argv[-1] == "p"


def test_execute_normalizes_successful_run(tmp_path: Path):
    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        return RawSubprocessResult(
            exit_code=0,
            stdout="done\n",
            stderr="",
            duration_seconds=0.2,
        )

    adapter = OpenCodeAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert result.exit_code == 0
    assert result.stdout == "done\n"
    assert result.adapter_name == "opencode"
    assert result.raw is not None


def test_capabilities_are_stable(tmp_path: Path):
    caps = OpenCodeAdapter().capabilities
    assert caps.maturity == "stable"
    assert caps.supports_non_interactive is True
    assert caps.prompt_mode == "arg"


def test_resolve_executable_prefers_env_override(monkeypatch):
    monkeypatch.setenv("OPENRALPH_OPENCODE_PATH", r"D:\tools\opencode.cmd")

    def fake_which(candidate: str):
        if candidate == r"D:\tools\opencode.cmd":
            return candidate
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    adapter = OpenCodeAdapter()
    assert adapter.resolve_executable() == r"D:\tools\opencode.cmd"
