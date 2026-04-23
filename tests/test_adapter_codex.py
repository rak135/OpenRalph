"""Codex adapter tests.

We never touch the real Codex binary. Instead we exercise two surfaces
separately:

  1. ``build_command`` — a pure function over ``ExecuteOptions``.
  2. ``execute`` — with a fake ``Executor`` so we can assert the
     CommandSpec and the result normalization in isolation.

The split exists because Phase 2 adapters differ mostly in how they
*build* commands, not in how they run them.

``--skip-git-repo-check`` is present in every command because the adapter
adds it unconditionally to work from any workspace directory.
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
    assert "--skip-git-repo-check" in spec.argv
    # Prompt is passed via stdin ("-"), not as a positional arg.
    assert spec.argv[-1] == "-"
    assert spec.stdin == "do the thing"
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
    # Prompt delivered via stdin; "-" is the sentinel positional arg.
    assert spec.argv == ["codex", "exec", "--full-auto", "--skip-git-repo-check", "-"]
    assert spec.stdin == "p"


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


# ---------------------------------------------------------------------------
# Phase 3.1: full-auto + output-last-message
# ---------------------------------------------------------------------------


def test_build_command_includes_full_auto(tmp_path: Path):
    spec = CodexAdapter().build_command(ExecuteOptions(prompt="do it", cwd=tmp_path))
    assert "--full-auto" in spec.argv
    # --full-auto must come before --skip-git-repo-check and the "-" sentinel.
    fa_idx = spec.argv.index("--full-auto")
    skip_idx = spec.argv.index("--skip-git-repo-check")
    assert fa_idx < skip_idx
    # Prompt in stdin, not in argv.
    assert spec.stdin == "do it"
    assert spec.argv[-1] == "-"


def test_build_command_with_output_file_adds_flag(tmp_path: Path):
    out = tmp_path / "last.txt"
    spec = CodexAdapter().build_command(
        ExecuteOptions(prompt="do it", cwd=tmp_path),
        output_file=out,
    )
    assert "--output-last-message" in spec.argv
    idx = spec.argv.index("--output-last-message")
    assert spec.argv[idx + 1] == str(out)


def test_execute_uses_last_message_file_over_stdout(tmp_path: Path):
    """When --output-last-message file is non-empty, its content becomes stdout."""

    last_msg_content = (
        "<ralph-result>\n"
        "status: done\n"
        "summary: wrote hello.txt\n"
        "verification: confirmed file exists\n"
        "complete: true\n"
        "blocker: none\n"
        "</ralph-result>\n"
    )

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        # Find the --output-last-message path in argv and write to it.
        if "--output-last-message" in spec.argv:
            idx = spec.argv.index("--output-last-message")
            Path(spec.argv[idx + 1]).write_text(last_msg_content, encoding="utf-8")
        return RawSubprocessResult(
            exit_code=0,
            stdout="[codex progress events here]",
            stderr="",
            duration_seconds=1.0,
            timed_out=False,
        )

    adapter = CodexAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="do it", cwd=tmp_path))

    # stdout should be the last-message content, not the progress events.
    assert "ralph-result" in result.stdout
    assert "[codex progress events here]" not in result.stdout


def test_execute_falls_back_to_stdout_when_last_message_empty(tmp_path: Path):
    """If --output-last-message file is empty/absent, fall back to subprocess stdout."""

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        # Write nothing to the output file (simulate file not written by codex).
        return RawSubprocessResult(
            exit_code=0,
            stdout="fallback stdout content",
            stderr="",
            duration_seconds=0.5,
            timed_out=False,
        )

    adapter = CodexAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="do it", cwd=tmp_path))

    assert result.stdout == "fallback stdout content"


def test_execute_passes_full_auto_in_argv_to_executor(tmp_path: Path):
    captured: list[str] = []

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        captured.extend(spec.argv)
        return RawSubprocessResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    CodexAdapter(executor=fake_executor).execute(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert "--full-auto" in captured
