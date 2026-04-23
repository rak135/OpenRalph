"""Shared subprocess executor.

One implementation, used by every adapter that shells out. Adapters
describe *what* to run via ``CommandSpec``; this module decides *how* to
run it (timeout, env merge, stdout/stderr capture, timing). Having a
single execution path means a bug in subprocess handling gets fixed once,
not three times.

Tests inject a fake ``Executor`` into the adapter instead of mocking
``subprocess``.
"""

from __future__ import annotations

import os
import subprocess
from time import monotonic

from openralph_py.adapters.base import (
    AdapterNotAvailable,
    CommandSpec,
    RawSubprocessResult,
)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return data


def run_subprocess(spec: CommandSpec) -> RawSubprocessResult:
    """Run a ``CommandSpec`` and return the raw subprocess result.

    Non-zero exit codes are not raised — they're part of the normal
    return shape. ``AdapterNotAvailable`` is raised only when the binary
    itself is missing; the caller distinguishes that from a tool run
    that exited non-zero.
    """

    if not spec.argv:
        raise ValueError("CommandSpec.argv must be non-empty")

    env = {**os.environ}
    if spec.env:
        env.update(spec.env)

    start = monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            list(spec.argv),
            cwd=str(spec.cwd),
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            check=False,
            env=env,
            input=spec.stdin,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
    except FileNotFoundError as exc:
        raise AdapterNotAvailable(
            f"executable not found: {spec.argv[0]!r}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr)
        exit_code = 124

    duration = monotonic() - start
    return RawSubprocessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        timed_out=timed_out,
    )
