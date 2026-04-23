"""OpenCode adapter.

Runs ``opencode run --print <prompt>`` — OpenCode's non-interactive
one-shot mode. ``--print`` causes the session output to stream to
stdout and the process to exit on completion, which is what the loop
engine wants.

Model passthrough is the tool's own string (e.g. ``anthropic/claude-...``
or ``openrouter/...``); OpenCode parses the provider prefix itself, so
we don't strip it.
"""

from __future__ import annotations

from openralph_py.adapters.base import (
    AdapterCapabilities,
    CommandSpec,
    ExecuteOptions,
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
                "Uses `opencode run --print <prompt>` for a one-shot, "
                "non-interactive invocation. Model string is passed through "
                "untouched so provider-prefixed ids (e.g. `anthropic/...`) work. "
                "Set OPENRALPH_OPENCODE_PATH to override executable discovery."
            ),
        )

    def build_command(self, options: ExecuteOptions) -> CommandSpec:
        argv: list[str] = [self.executable, "run", "--print"]
        if options.model:
            argv.extend(["--model", options.model])
        argv.append(options.prompt)
        return CommandSpec(
            argv=argv,
            cwd=options.cwd,
            timeout_seconds=options.timeout_seconds,
        )
