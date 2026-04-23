"""Codex CLI adapter.

Runs ``codex exec [--model NAME] <prompt>`` as a non-interactive
subprocess via the shared executor. Model strings of the form
``provider/name`` are split — Codex expects only the model name.
"""

from __future__ import annotations

from openralph_py.adapters.base import (
    AdapterCapabilities,
    CommandSpec,
    ExecuteOptions,
    SubprocessAdapter,
)


class CodexAdapter(SubprocessAdapter):
    name = "codex"
    display_name = "Codex CLI"
    executable = "codex"
    executable_env_var = "OPENRALPH_CODEX_PATH"
    executable_fallbacks = ("codex.cmd",)

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
                "Uses `codex exec` non-interactive subcommand. "
                "Set OPENRALPH_CODEX_PATH to override executable discovery."
            ),
        )

    def build_command(self, options: ExecuteOptions) -> CommandSpec:
        argv: list[str] = [self.executable, "exec"]
        if options.model:
            model_name = (
                options.model.split("/", 1)[1] if "/" in options.model else options.model
            )
            argv.extend(["--model", model_name])
        argv.append(options.prompt)
        return CommandSpec(
            argv=argv,
            cwd=options.cwd,
            timeout_seconds=options.timeout_seconds,
        )
