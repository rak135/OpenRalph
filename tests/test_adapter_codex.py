"""Codex adapter tests.

We never touch the real Codex binary. Instead we exercise two surfaces
separately:

  1. ``build_command`` — a pure function over ``ExecuteOptions``.
  2. ``execute`` — with a fake ``Executor`` so we can assert the
     CommandSpec and the result normalization in isolation.

The split exists because Phase 2 adapters differ mostly in how they
*build* commands, not in how they run them.
"""

from __future__ import annotations

import os
from pathlib import Path

from openralph_py.adapters.base import (
    CommandSpec,
    ExecuteOptions,
    RawSubprocessResult,
)
from openralph_py.adapters.codex import CodexAdapter


def test_build_command_with_provider_prefixed_model(tmp_path: Path):
    spec = CodexAdapter().build_command(
        ExecuteOptions(
            prompt="do the thing",
            cwd=tmp_path,
            model="openai/gpt-5.4",
            timeout_seconds=300,
        )
    )
    assert spec.argv[:2] == ["codex", "exec"]
    assert "--model" in spec.argv
    assert spec.argv[spec.argv.index("--model") + 1] == "gpt-5.4"
    assert spec.argv[-1] == "do the thing"
    assert spec.cwd == tmp_path
    assert spec.timeout_seconds == 300


def test_build_command_without_slash_passes_model_through(tmp_path: Path):
    spec = CodexAdapter().build_command(
        ExecuteOptions(prompt="p", cwd=tmp_path, model="gpt-5.4")
    )
    assert spec.argv[spec.argv.index("--model") + 1] == "gpt-5.4"


def test_build_command_without_model_omits_flag(tmp_path: Path):
    spec = CodexAdapter().build_command(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert "--model" not in spec.argv
    assert spec.argv == ["codex", "exec", "p"]


def test_execute_uses_injected_executor_and_normalizes(tmp_path: Path):
    captured: dict = {}

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        captured["spec"] = spec
        return RawSubprocessResult(
            exit_code=7,
            stdout="out",
            stderr="err",
            duration_seconds=1.23,
            timed_out=True,
        )

    adapter = CodexAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="p", cwd=tmp_path))

    assert result.exit_code == 7
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.duration_seconds == 1.23
    assert result.timed_out is True
    assert result.adapter_name == "codex"
    assert result.raw is not None
    assert captured["spec"].argv[0] == "codex"


def test_capabilities_declare_non_interactive_and_stable(tmp_path: Path):
    caps = CodexAdapter().capabilities
    assert caps.supports_non_interactive is True
    assert caps.supports_model_flag is True
    assert caps.prompt_mode == "arg"
    assert caps.maturity == "stable"


def test_resolve_executable_prefers_env_override(monkeypatch):
    monkeypatch.setenv("OPENRALPH_CODEX_PATH", r"C:\tools\codex.cmd")

    def fake_which(candidate: str):
        if candidate == r"C:\tools\codex.cmd":
            return candidate
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    adapter = CodexAdapter()
    assert adapter.resolve_executable() == r"C:\tools\codex.cmd"


def test_resolve_executable_falls_back_to_windows_cmd(monkeypatch):
    monkeypatch.delenv("OPENRALPH_CODEX_PATH", raising=False)

    def fake_which(candidate: str):
        if candidate == "codex.cmd":
            return r"C:\Users\me\AppData\Roaming\npm\codex.cmd"
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    adapter = CodexAdapter()
    assert adapter.resolve_executable() == r"C:\Users\me\AppData\Roaming\npm\codex.cmd"
