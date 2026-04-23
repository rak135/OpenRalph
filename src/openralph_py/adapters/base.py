"""Phase 2 adapter boundary.

The adapter boundary is split into five concepts so vendor-specific
differences stay contained:

    ExecuteOptions       -- the request from the loop engine
    CommandSpec          -- how to launch the external process
    RawSubprocessResult  -- what the shared executor returned
    AdapterCapabilities  -- structured description of the adapter's
                            assumptions and caveats
    ExecuteResult        -- the normalized, loop-facing result

Most adapters inherit from ``SubprocessAdapter``, which turns a
``CommandSpec`` into an ``ExecuteResult`` through a single shared
executor. That keeps loop, command construction, subprocess execution,
and result normalization separable and independently testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable, Literal


class AdapterError(RuntimeError):
    """Raised when an adapter fails to execute."""


class AdapterNotAvailable(AdapterError):
    """Raised when the adapter's underlying CLI/service isn't installed or reachable."""


PromptMode = Literal["arg", "stdin", "flag"]
Maturity = Literal["stable", "experimental", "unverified"]


@dataclass
class ExecuteOptions:
    """The loop engine's request to run one iteration against an adapter."""

    prompt: str
    cwd: Path
    model: str | None = None
    timeout_seconds: float | None = None


@dataclass
class CommandSpec:
    """A fully-resolved, ready-to-launch subprocess description.

    Adapters produce one of these from an ``ExecuteOptions``. The shared
    executor consumes it. Nothing in here is adapter-specific.
    """

    argv: list[str]
    cwd: Path
    env: dict[str, str] | None = None
    timeout_seconds: float | None = None
    stdin: str | None = None


@dataclass
class RawSubprocessResult:
    """What the shared executor actually observed."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


@dataclass(frozen=True)
class AdapterCapabilities:
    """Structured description of an adapter's relevant execution assumptions.

    This exists so callers (and future features) can reason about adapter
    differences without reading adapter source. Keep fields stable and
    small; add new ones only when a real caller needs them.
    """

    prompt_mode: PromptMode
    supports_model_flag: bool
    supports_non_interactive: bool
    requires_trusted_dir: bool = False
    honors_timeout: bool = True
    maturity: Maturity = "stable"
    notes: str = ""


@dataclass
class ExecuteResult:
    """Normalized, loop-facing result of a single adapter invocation."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    adapter_name: str = ""
    raw: RawSubprocessResult | None = None

    @classmethod
    def from_raw(cls, raw: RawSubprocessResult, *, adapter_name: str) -> "ExecuteResult":
        return cls(
            exit_code=raw.exit_code,
            stdout=raw.stdout,
            stderr=raw.stderr,
            duration_seconds=raw.duration_seconds,
            timed_out=raw.timed_out,
            adapter_name=adapter_name,
            raw=raw,
        )


Executor = Callable[[CommandSpec], RawSubprocessResult]


class Adapter(ABC):
    """Minimal contract every adapter must satisfy.

    This stays intentionally small. Anything that needs subprocess
    plumbing should inherit from ``SubprocessAdapter`` (below) rather than
    re-implementing ``execute`` from scratch.
    """

    name: str
    display_name: str

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def execute(self, options: ExecuteOptions) -> ExecuteResult: ...


class SubprocessAdapter(Adapter):
    """Adapter whose ``execute`` delegates to a shared subprocess executor.

    Subclasses only have to:
      - declare ``name`` / ``display_name``
      - implement ``build_command(options) -> CommandSpec``
      - declare ``capabilities``

    Injecting a fake ``Executor`` is all that's needed for tests — no
    subclassing required, no monkeypatching of ``subprocess``.
    """

    executable: str = ""
    executable_env_var: str = ""
    executable_fallbacks: tuple[str, ...] = ()

    def __init__(self, *, executor: Executor | None = None) -> None:
        from openralph_py.adapters.execution import run_subprocess

        self._executor: Executor = executor or run_subprocess
        self._uses_real_executor: bool = executor is None

    @abstractmethod
    def build_command(self, options: ExecuteOptions) -> CommandSpec: ...

    def executable_candidates(self) -> tuple[str, ...]:
        candidates: list[str] = []
        if self.executable_env_var:
            override = os.environ.get(self.executable_env_var)
            if override:
                candidates.append(override)
        if self.executable:
            candidates.append(self.executable)
        candidates.extend(self.executable_fallbacks)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return tuple(deduped)

    def resolve_executable(self) -> str | None:
        import shutil

        for candidate in self.executable_candidates():
            resolved = shutil.which(candidate)
            if resolved is not None:
                return resolved
        return None

    def is_available(self) -> bool:
        return self.resolve_executable() is not None

    def require_executable(self) -> str:
        resolved = self.resolve_executable()
        if resolved is not None:
            return resolved
        candidates = ", ".join(repr(candidate) for candidate in self.executable_candidates())
        if self.executable_env_var:
            detail = f"{self.display_name}: executable not found. Checked {candidates} via PATH and {self.executable_env_var}."
        else:
            detail = f"{self.display_name}: executable not found. Checked {candidates} on PATH."
        raise AdapterNotAvailable(detail)

    def execute(self, options: ExecuteOptions) -> ExecuteResult:
        spec = self.build_command(options)
        if self._uses_real_executor:
            spec = CommandSpec(
                argv=[self.require_executable(), *spec.argv[1:]],
                cwd=spec.cwd,
                env=spec.env,
                timeout_seconds=spec.timeout_seconds,
                stdin=spec.stdin,
            )
        raw = self._executor(spec)
        return ExecuteResult.from_raw(raw, adapter_name=self.name)
