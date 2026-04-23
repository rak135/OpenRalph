"""GitHub Copilot CLI adapter.

Targets the current standalone ``copilot`` CLI (the new preview CLI),
not the retired ``gh copilot`` extension. Uses the non-interactive
prompt-mode flag and bypasses the interactive approval prompt so the
loop can run unattended.

Honesty note: the Copilot CLI is evolving and flag surface has shifted
between previews. Where we rely on a flag whose behavior may change,
the adapter exposes that in ``capabilities.notes`` rather than
pretending certainty.
"""

from __future__ import annotations

from openralph_py.adapters.base import (
    AdapterCapabilities,
    CommandSpec,
    ExecuteOptions,
    SubprocessAdapter,
)


class CopilotAdapter(SubprocessAdapter):
    name = "copilot"
    display_name = "GitHub Copilot CLI"
    executable = "copilot"
    executable_env_var = "OPENRALPH_COPILOT_PATH"
    executable_fallbacks = ("copilot.cmd",)

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            prompt_mode="flag",
            supports_model_flag=True,
            supports_non_interactive=True,
            requires_trusted_dir=True,
            honors_timeout=True,
            maturity="unverified",
            notes=(
                "Uses `copilot -p <prompt> --allow-all-tools --no-color`. "
                "Requires the current standalone Copilot CLI (not the `gh copilot` "
                "extension). --allow-all-tools bypasses interactive tool approval; "
                "remove it if you want manual approval. The CLI may refuse to run "
                "outside a trusted directory and may require `gh auth` / Copilot "
                "subscription — neither is verified by this adapter. "
                "Set OPENRALPH_COPILOT_PATH to override executable discovery."
            ),
        )

    def build_command(self, options: ExecuteOptions) -> CommandSpec:
        argv: list[str] = [
            self.executable,
            "-p",
            options.prompt,
            "--allow-all-tools",
            "--no-color",
        ]
        if options.model:
            argv.extend(["--model", options.model])
        argv.extend(["--add-dir", str(options.cwd)])
        return CommandSpec(
            argv=argv,
            cwd=options.cwd,
            timeout_seconds=options.timeout_seconds,
        )
