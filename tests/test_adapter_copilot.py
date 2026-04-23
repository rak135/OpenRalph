"""Copilot CLI adapter tests.

These tests cover command construction and result normalization without
requiring the real ``copilot`` binary. The adapter's capabilities also
declare that its support is unverified; we assert that honestly so
future readers don't mistake it for a tested integration.
"""

from __future__ import annotations

from pathlib import Path

from openralph_py.adapters.base import (
    CommandSpec,
    ExecuteOptions,
    RawSubprocessResult,
)
from openralph_py.adapters.copilot import CopilotAdapter


def test_build_command_sets_prompt_flag_and_trusted_dir(tmp_path: Path):
    spec = CopilotAdapter().build_command(
        ExecuteOptions(prompt="hello world", cwd=tmp_path, timeout_seconds=60)
    )
    assert spec.argv[0] == "copilot"
    assert "-p" in spec.argv
    assert spec.argv[spec.argv.index("-p") + 1] == "hello world"
    assert "--allow-all-tools" in spec.argv
    assert "--no-color" in spec.argv
    assert "--add-dir" in spec.argv
    assert spec.argv[spec.argv.index("--add-dir") + 1] == str(tmp_path)
    assert spec.cwd == tmp_path
    assert spec.timeout_seconds == 60


def test_build_command_adds_model_flag_when_set(tmp_path: Path):
    spec = CopilotAdapter().build_command(
        ExecuteOptions(prompt="p", cwd=tmp_path, model="gpt-4.1")
    )
    assert "--model" in spec.argv
    assert spec.argv[spec.argv.index("--model") + 1] == "gpt-4.1"


def test_build_command_without_model_omits_flag(tmp_path: Path):
    spec = CopilotAdapter().build_command(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert "--model" not in spec.argv


def test_execute_normalizes_non_zero_exit(tmp_path: Path):
    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        return RawSubprocessResult(
            exit_code=2,
            stdout="",
            stderr="auth error",
            duration_seconds=0.5,
        )

    adapter = CopilotAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert result.exit_code == 2
    assert result.stderr == "auth error"
    assert result.adapter_name == "copilot"


def test_capabilities_are_honest_about_maturity(tmp_path: Path):
    caps = CopilotAdapter().capabilities
    assert caps.maturity == "unverified"
    assert caps.requires_trusted_dir is True
    assert caps.prompt_mode == "flag"
    assert "Copilot" in caps.notes or "copilot" in caps.notes


def test_resolve_executable_uses_windows_cmd_fallback(monkeypatch):
    monkeypatch.delenv("OPENRALPH_COPILOT_PATH", raising=False)

    def fake_which(candidate: str):
        if candidate == "copilot.cmd":
            return r"C:\Users\me\AppData\Local\Programs\copilot.cmd"
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    adapter = CopilotAdapter()
    assert adapter.resolve_executable() == r"C:\Users\me\AppData\Local\Programs\copilot.cmd"
