from openralph_py.adapters.base import (
    Adapter,
    AdapterCapabilities,
    AdapterError,
    AdapterNotAvailable,
    CommandSpec,
    ExecuteOptions,
    ExecuteResult,
    Executor,
    RawSubprocessResult,
    SubprocessAdapter,
)
from openralph_py.adapters.execution import run_subprocess
from openralph_py.adapters.registry import (
    get_adapter,
    list_adapters,
    register_adapter,
)

__all__ = [
    "Adapter",
    "AdapterCapabilities",
    "AdapterError",
    "AdapterNotAvailable",
    "CommandSpec",
    "ExecuteOptions",
    "ExecuteResult",
    "Executor",
    "RawSubprocessResult",
    "SubprocessAdapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
    "run_subprocess",
]
