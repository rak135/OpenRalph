from __future__ import annotations

from pathlib import Path

from openralph_py.state import PersistedState, load_or_create_state, load_state, save_state


def test_roundtrip(tmp_path: Path):
    path = tmp_path / ".ralph-state.json"
    s = PersistedState(plan_file="prd.json", iterations=3, iteration_durations=[1.1, 2.2, 3.3])
    save_state(path, s)
    loaded = load_state(path)
    assert loaded is not None
    assert loaded.iterations == 3
    assert loaded.iteration_durations == [1.1, 2.2, 3.3]


def test_load_or_create(tmp_path: Path):
    path = tmp_path / ".ralph-state.json"
    s1 = load_or_create_state(path, plan_file="prd.json")
    assert s1.iterations == 0
    s1.iterations = 5
    save_state(path, s1)

    s2 = load_or_create_state(path, plan_file="prd.json")
    assert s2.iterations == 5


def test_ignores_unknown_fields(tmp_path: Path):
    path = tmp_path / ".ralph-state.json"
    path.write_text('{"iterations": 2, "bogus_field": true}', encoding="utf-8")
    loaded = load_state(path)
    assert loaded is not None
    assert loaded.iterations == 2
