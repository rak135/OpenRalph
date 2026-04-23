"""Codex CLI adapter.

Runs ``codex exec --full-auto [--model NAME] --skip-git-repo-check <prompt>``
as a non-interactive subprocess via the shared executor. Model strings of the
form ``provider/name`` are split — Codex expects only the model name.

``--full-auto`` is required for non-interactive execution: without it Codex
may silently wait for approval of file writes, causing the subprocess to
hang or produce empty output.

``--skip-git-repo-check`` is required because the adapter must work from
any workspace directory, not only git-tracked ones.

``--output-last-message <file>`` is used to capture the model's final text
response as clean content. Codex's terminal renderer does not write model
text verbatim to stdout, so stdout from the subprocess is often empty or
contains only progress events. Reading the last-message file gives the
bounded ``<ralph-result>`` block a reliable channel.
"""

from __future__ import annotations

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
                "Uses `codex exec --full-auto --skip-git-repo-check` non-interactive subcommand. "
                "--full-auto enables automatic approval of workspace writes so the subprocess "
                "never hangs waiting for confirmation. "
                "--output-last-message captures the model's clean final text (avoids "
                "terminal-renderer output going to stdout instead of the response). "
                "Set OPENRALPH_CODEX_PATH to override executable discovery."
            ),
        )

    def build_command(self, options: ExecuteOptions, *, output_file: Path | None = None) -> CommandSpec:
        """Build the codex exec command.

        The prompt is delivered via **stdin** (using ``-`` as the prompt
        argument) rather than as a command-line argument.  On Windows,
        Python's ``subprocess.list2cmdline`` converts newlines in arguments to
        literal ``\\n`` sequences; codex then only sees the first line of a
        multiline prompt.  Stdin bypasses that limitation entirely.

        ``output_file`` (optional) adds ``--output-last-message <path>``
        so the model's final message is written to a file for reliable
        ``<ralph-result>`` extraction.  Callers that pass a ``output_file``
        are responsible for reading and cleaning up that file.
        """
        argv: list[str] = [self.executable, "exec", "--full-auto"]
        if options.model:
            model_name = (
                options.model.split("/", 1)[1] if "/" in options.model else options.model
            )
            argv.extend(["--model", model_name])
        argv.append("--skip-git-repo-check")
        if output_file is not None:
            argv.extend(["--output-last-message", str(output_file)])
        # Use "-" to tell codex to read the prompt from stdin.
        argv.append("-")
        return CommandSpec(
            argv=argv,
            cwd=options.cwd,
            timeout_seconds=options.timeout_seconds,
            stdin=options.prompt,  # delivered via subprocess stdin
        )

    # ------------------------------------------------------------------
    # Override execute to capture the model's last message via a temp file.
    # ------------------------------------------------------------------

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        """Execute codex and extract the model's last message from a temp file.

        The temp file gives us the model's raw text response, which is where
        the ``<ralph-result>`` block lives.  Without it, the codex terminal
        renderer writes progress events to stdout rather than the model text.
        """
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as tf:
            output_path = Path(tf.name)

        try:
            spec = self.build_command(options, output_file=output_path)
            if self._uses_real_executor:
                spec = CommandSpec(
                    argv=[self.require_executable(), *spec.argv[1:]],
                    cwd=spec.cwd,
                    env=spec.env,
                    timeout_seconds=spec.timeout_seconds,
                    stdin=spec.stdin,
                )
            raw: RawSubprocessResult = self._executor(spec)

            # Read the model's last message if the file was written.
            last_message = ""
            if output_path.exists():
                try:
                    last_message = output_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    last_message = ""

            # Prefer last_message (clean model text) over stdout (terminal events).
            # Fall back to stdout if the file is empty so tests using fake executors
            # still see their injected stdout.
            effective_stdout = last_message.strip() or raw.stdout

            augmented = RawSubprocessResult(
                exit_code=raw.exit_code,
                stdout=effective_stdout,
                stderr=raw.stderr,
                duration_seconds=raw.duration_seconds,
                timed_out=raw.timed_out,
            )
            return ExecuteResult.from_raw(augmented, adapter_name=self.name)
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
