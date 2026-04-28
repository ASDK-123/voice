"""
Compatibility wrapper for the API module.

M0 goal: keep runtime behavior unchanged while moving startup wiring into
`core/server/*` scaffolding. Existing imports like `from core import api` keep
working via re-exports from `core.api_legacy`.
"""

from __future__ import annotations

import os
import sys
from types import ModuleType
from typing import Dict


def _ensure_repo_root_on_path() -> None:
    # 移除被隐式加入的 core 目录，防止内置包 shadowing（如 core/logging 屏蔽了自带的 logging）
    current_dir = os.path.abspath(os.path.dirname(__file__))
    if current_dir in sys.path:
        sys.path.remove(current_dir)
        
    repo_root = os.path.abspath(os.path.join(current_dir, ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _load_legacy_module() -> ModuleType:
    _ensure_repo_root_on_path()
    from core import api_legacy as legacy  # type: ignore

    return legacy


def _reexport_legacy_symbols(legacy: ModuleType) -> None:
    exported: Dict[str, object] = {}
    for name in dir(legacy):
        if name.startswith("_"):
            continue
        exported[name] = getattr(legacy, name)
    globals().update(exported)
    globals()["__all__"] = sorted(exported.keys())


def main() -> int:
    _ensure_repo_root_on_path()
    from core.server.main import main as server_main  # type: ignore

    return int(server_main() or 0)


# Import and re-export legacy API surface only when used as a module.
if __name__ != "__main__":
    _reexport_legacy_symbols(_load_legacy_module())


if __name__ == "__main__":
    raise SystemExit(main())
