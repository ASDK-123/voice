"""Application runtime context for server assembly."""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType


@dataclass
class AppContext:
    """Server runtime context used by main/app assembly."""

    host: str
    port: int
    debug: bool
    config_file: str
    min_text_length: int
    runtime_module: ModuleType
    app: object


def build_context(
    *,
    host: str,
    port: int,
    debug: bool,
    config_file: str,
    min_text_length: int,
    runtime_module: ModuleType,
    app: object,
) -> AppContext:
    return AppContext(
        host=str(host),
        port=int(port),
        debug=bool(debug),
        config_file=str(config_file),
        min_text_length=int(min_text_length),
        runtime_module=runtime_module,
        app=app,
    )
