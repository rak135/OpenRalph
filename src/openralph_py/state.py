"""Persistent loop state.

Mirrors the `PersistedState` shape from the source repo but trimmed to the
fields that are meaningful without a TUI. `iterations` counts completed
iterations; repeated `run` invocations bump this counter so the loop is
truly multi-step across process boundaries.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time


@dataclass
class PersistedState:
    plan_file: str = "prd.json"
    started_at: float = field(default_factory=time)
    iterations: int = 0
    iteration_durations: list[float] = field(default_factory=list)
    last_run_at: float | None = None
    last_task_id: str | None = None
    last_exit_code: int | None = None
    # Phase 3 additions
    last_stop_reason: str | None = None  # StopReason value from last run_loop call
    session_id: str | None = None        # Unique ID for each run_loop invocation

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PersistedState":
        allowed = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)


def load_state(path: Path) -> PersistedState | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return PersistedState.from_dict(data)


def save_state(path: Path, state: PersistedState) -> None:
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_or_create_state(path: Path, plan_file: str) -> PersistedState:
    existing = load_state(path)
    if existing is not None:
        return existing
    return PersistedState(plan_file=plan_file)
