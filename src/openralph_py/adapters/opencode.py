"""OpenCode adapter.

Runs ``opencode run --format json <prompt>`` — OpenCode's non-interactive
one-shot mode. ``--format json`` causes the session output to be emitted
as JSONL to stdout so the loop engine receives machine-readable events.

Phase 3.1 follow-up notes:
    - On Windows, multiline prompt arguments can be truncated to the first
        line when transported through argv. To keep behavior deterministic, we
        collapse prompts to one line for OpenCode's positional message arg.
    - OpenCode emits JSONL events. We deterministically extract textual
        assistant payloads from ``type=text`` events and pass that extracted
        text upstream as ``stdout`` so the bounded ``<ralph-result>`` parser
        sees the actual model text, not transport envelopes.

Note: ``--print`` is NOT a valid ``opencode run`` flag (verified against
opencode 1.14.22). The correct structured-output flag is ``--format json``.

Model passthrough is the tool's own string (e.g. ``anthropic/claude-...``
or ``openrouter/...``); OpenCode parses the provider prefix itself, so
we don't strip it.
"""

from __future__ import annotations

import json
import platform
import tempfile
from pathlib import Path

from openralph_py.adapters.base import (
    AdapterCapabilities,
    CommandSpec,
    ExecuteOptions,
    ExecuteResult,
    RawSubprocessResult,
    SubprocessAdapter,
)


class OpenCodeAdapter(SubprocessAdapter):
    name = "opencode"
    display_name = "OpenCode"
    executable = "opencode"
    executable_env_var = "OPENRALPH_OPENCODE_PATH"
    executable_fallbacks = ("opencode.cmd",)

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="arg",
            supports_model_flag=True,
            supports_non_interactive=True,
            requires_trusted_dir=False,
            honors_timeout=True,
            maturity="stable",
            notes=(
                "Uses `opencode run --format json <prompt>` for a one-shot, "
                "non-interactive invocation. `--print` is not a valid flag; "
                "structured output requires `--format json`. "
                "Prompt is normalized for argv transport; on Windows the full prompt is "
                "passed via `--file` to avoid .cmd argument parsing issues with tag text. "
                "Assistant text is extracted from JSONL text events so downstream "
                "bounded-contract parsing sees the model message content. "
                "Model string is passed through untouched so provider-prefixed "
                "ids (e.g. `anthropic/...`) work. "
                "Set OPENRALPH_OPENCODE_PATH to override executable discovery."
            ),
        )

    def build_command(
        self,
        options: ExecuteOptions,
        *,
        prompt_override: str | None = None,
        attached_file: Path | None = None,
    ) -> CommandSpec:
        prompt_arg = (
            prompt_override
            if prompt_override is not None
            else self._normalize_prompt_for_arg(options.prompt)
        )
        argv: list[str] = [self.executable, "run", "--format", "json"]
        if options.model:
            argv.extend(["--model", options.model])
        if attached_file is not None:
            argv.extend(["--file", str(attached_file), "--"])
        argv.append(prompt_arg)
        return CommandSpec(
            argv=argv,
            cwd=options.cwd,
            timeout_seconds=options.timeout_seconds,
        )

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        prompt_file: Path | None = None
        prompt_override: str | None = None

        # On Windows, passing the full prompt (which includes <...> tags) as a
        # positional arg through .cmd wrappers can break command parsing.
        # Use --file transport for the full prompt and keep the message arg simple.
        if platform.system() == "Windows":
            with tempfile.NamedTemporaryFile(
                suffix=".prompt.txt", delete=False, mode="w", encoding="utf-8"
            ) as tf:
                tf.write(options.prompt)
                prompt_file = Path(tf.name)
            prompt_override = (
                "Follow the attached prompt file exactly. "
                "Execute one task, update prd.json truthfully, and emit the required "
                "ralph-result block."
            )

        try:
            spec = self.build_command(
                options,
                prompt_override=prompt_override,
                attached_file=prompt_file,
            )
            if self._uses_real_executor:
                spec = CommandSpec(
                    argv=[self.require_executable(), *spec.argv[1:]],
                    cwd=spec.cwd,
                    env=spec.env,
                    timeout_seconds=spec.timeout_seconds,
                    stdin=spec.stdin,
                )
            raw: RawSubprocessResult = self._executor(spec)
            extracted = self._extract_text_from_jsonl(raw.stdout)
            effective_stdout = extracted if extracted.strip() else raw.stdout
            normalized = RawSubprocessResult(
                exit_code=raw.exit_code,
                stdout=effective_stdout,
                stderr=raw.stderr,
                duration_seconds=raw.duration_seconds,
                timed_out=raw.timed_out,
            )
            return ExecuteResult.from_raw(normalized, adapter_name=self.name)
        finally:
            if prompt_file is not None:
                try:
                    prompt_file.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _normalize_prompt_for_arg(prompt: str) -> str:
        """Collapse multiline prompts into a deterministic single-line message.

        This avoids multiline argv transport issues on Windows while
        preserving instruction content for OpenCode's positional message arg.
        """
        parts = [line.strip() for line in prompt.splitlines() if line.strip()]
        return " ".join(parts)

    @staticmethod
    def _extract_text_from_jsonl(stdout: str) -> str:
        """Extract assistant text payloads from OpenCode JSONL event output."""
        chunks: list[str] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "text":
                continue
            part = event.get("part")
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
        return "\n".join(chunks)
