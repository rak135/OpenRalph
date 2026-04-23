"""OpenCode adapter tests.

Exercise the non-interactive `opencode run --format json` path. The model
string is passed through literally — no provider prefix stripping.

Note: `--print` is not a valid opencode run flag (verified against
opencode 1.14.22). The correct structured-output flag is `--format json`.
"""

from __future__ import annotations

from pathlib import Path

from openralph_py.adapters.base import (
    CommandSpec,
    ExecuteOptions,
    RawSubprocessResult,
)
from openralph_py.adapters.opencode import OpenCodeAdapter


def test_build_command_uses_run_format_json_form(tmp_path: Path):
    spec = OpenCodeAdapter().build_command(
        ExecuteOptions(prompt="fix things", cwd=tmp_path)
    )
    assert spec.argv[:4] == ["opencode", "run", "--format", "json"]
    assert spec.argv[-1] == "fix things"
    assert "--model" not in spec.argv


def test_build_command_normalizes_multiline_prompt(tmp_path: Path):
    spec = OpenCodeAdapter().build_command(
        ExecuteOptions(prompt="line one\n\nline two\nline three", cwd=tmp_path)
    )
    assert spec.argv[-1] == "line one line two line three"


def test_build_command_supports_attached_file_and_prompt_override(tmp_path: Path):
    attached = tmp_path / "prompt.txt"
    spec = OpenCodeAdapter().build_command(
        ExecuteOptions(prompt="ignored", cwd=tmp_path),
        prompt_override="short message",
        attached_file=attached,
    )
    assert "--file" in spec.argv
    assert spec.argv[spec.argv.index("--file") + 1] == str(attached)
    assert spec.argv[-1] == "short message"


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


def test_execute_extracts_text_from_jsonl_events(tmp_path: Path):
    jsonl = "\n".join(
        [
            '{"type":"step_start","part":{}}',
            '{"type":"text","part":{"text":"alpha"}}',
            '{"type":"text","part":{"text":"beta"}}',
            '{"type":"step_finish","part":{}}',
        ]
    )

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        return RawSubprocessResult(
            exit_code=0,
            stdout=jsonl,
            stderr="",
            duration_seconds=0.2,
        )

    adapter = OpenCodeAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="p", cwd=tmp_path))
    assert result.stdout == "alpha\nbeta"


def test_execute_windows_uses_file_transport(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def fake_executor(spec: CommandSpec) -> RawSubprocessResult:
        captured["argv"] = spec.argv
        return RawSubprocessResult(
            exit_code=0,
            stdout='{"type":"text","part":{"text":"ok"}}',
            stderr="",
            duration_seconds=0.1,
        )

    monkeypatch.setattr("platform.system", lambda: "Windows")
    adapter = OpenCodeAdapter(executor=fake_executor)
    result = adapter.execute(ExecuteOptions(prompt="full\nprompt", cwd=tmp_path))

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--file" in argv
    assert result.stdout == "ok"


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
