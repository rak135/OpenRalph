"""Adapter registry + shared executor tests.

The registry is the only place the loop engine learns which adapters
exist; these tests lock in that the three Phase 2 adapters are
discoverable and that the shared subprocess executor behaves correctly
at its own boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openralph_py.adapters import (
    AdapterNotAvailable,
    CommandSpec,
    get_adapter,
    list_adapters,
    registry,
    run_subprocess,
)
from openralph_py.adapters.base import Adapter, AdapterCapabilities, ExecuteOptions, ExecuteResult


def test_default_adapters_are_registered():
    names = {a.name for a in list_adapters()}
    assert {"codex", "copilot", "opencode"} <= names


def test_get_adapter_returns_correct_type():
    assert get_adapter("codex").name == "codex"
    assert get_adapter("copilot").name == "copilot"
    assert get_adapter("opencode").name == "opencode"


def test_unknown_adapter_raises():
    with pytest.raises(KeyError):
        get_adapter("does-not-exist")


def test_runtime_registration_roundtrips():
    class _Dummy(Adapter):
        name = "dummy-registry"
        display_name = "Dummy"

        @property
        def capabilities(self) -> AdapterCapabilities:
            return AdapterCapabilities(
                prompt_mode="arg",
                supports_model_flag=False,
                supports_non_interactive=True,
            )

        def is_available(self) -> bool:
            return True

        def execute(self, options: ExecuteOptions) -> ExecuteResult:
            return ExecuteResult(exit_code=0, stdout="", stderr="", duration_seconds=0.0)

    dummy = _Dummy()
    registry.register_adapter(dummy)
    try:
        assert get_adapter("dummy-registry") is dummy
        with pytest.raises(ValueError):
            registry.register_adapter(dummy)  # duplicate
    finally:
        del registry._registry[dummy.name]


def test_run_subprocess_captures_stdout_and_exit_code(tmp_path: Path):
    # Use the current Python interpreter as a portable subprocess target.
    spec = CommandSpec(
        argv=[sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"],
        cwd=tmp_path,
    )
    result = run_subprocess(spec)
    assert result.exit_code == 3
    assert result.stdout.strip() == "hi"
    assert result.timed_out is False


def test_run_subprocess_raises_adapter_not_available_when_missing(tmp_path: Path):
    spec = CommandSpec(
        argv=["this-binary-does-not-exist-xyz-12345"],
        cwd=tmp_path,
    )
    with pytest.raises(AdapterNotAvailable):
        run_subprocess(spec)


def test_run_subprocess_marks_timeout(tmp_path: Path):
    spec = CommandSpec(
        argv=[sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout_seconds=0.1,
    )
    result = run_subprocess(spec)
    assert result.timed_out is True
    assert result.exit_code == 124
