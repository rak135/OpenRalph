"""Adapter registry.

The loop engine never imports a concrete adapter — it looks them up by
name. Each adapter type registers itself once at module load time; extra
adapters (e.g. test fakes) can be registered at runtime via
``register_adapter``.
"""

from __future__ import annotations

from openralph_py.adapters.base import Adapter

_registry: dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    if adapter.name in _registry:
        raise ValueError(f"Adapter {adapter.name!r} already registered")
    _registry[adapter.name] = adapter


def get_adapter(name: str) -> Adapter:
    try:
        return _registry[name]
    except KeyError as exc:
        raise KeyError(f"Unknown adapter: {name!r}") from exc


def list_adapters() -> list[Adapter]:
    return list(_registry.values())


def _load_default_adapters() -> None:
    if _registry:
        return
    from openralph_py.adapters.codex import CodexAdapter
    from openralph_py.adapters.copilot import CopilotAdapter
    from openralph_py.adapters.opencode import OpenCodeAdapter

    register_adapter(CodexAdapter())
    register_adapter(CopilotAdapter())
    register_adapter(OpenCodeAdapter())


_load_default_adapters()
