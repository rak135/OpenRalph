from __future__ import annotations

from openralph_py.plan import Task
from openralph_py.selector import all_complete, count_completed, select_next_task


def _tasks(*pairs: tuple[str, bool]) -> list[Task]:
    return [Task(id=i, description=i, passes=p) for i, p in pairs]


def test_selects_first_incomplete_in_order():
    tasks = _tasks(("a", True), ("b", False), ("c", False))
    assert select_next_task(tasks).id == "b"


def test_none_when_all_complete():
    tasks = _tasks(("a", True), ("b", True))
    assert select_next_task(tasks) is None
    assert all_complete(tasks) is True


def test_all_complete_is_false_for_empty():
    assert all_complete([]) is False


def test_count_completed():
    tasks = _tasks(("a", True), ("b", False), ("c", True))
    assert count_completed(tasks) == 2


def test_deterministic():
    tasks = _tasks(("a", False), ("b", False))
    first = select_next_task(tasks).id
    for _ in range(10):
        assert select_next_task(tasks).id == first
