"""CLI entrypoint for server runtime assembly (C1)."""

from __future__ import annotations

import os
import sys
from typing import Sequence

from .app import create_app
from .ctx import build_context


def _ensure_repo_root_on_path() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Start API server through explicit runtime wiring.

    C1 contract:
    - no runpy indirection
    - no ctx-side legacy module loader
    """
    _ensure_repo_root_on_path()
    from core import api_legacy as legacy  # type: ignore

    parser = legacy.build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config_file = legacy.resolve_config_file(args.config)
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    try:
        legacy.initialize_runtime(
            config_file=config_file,
            min_text_length=int(args.min_text_length),
            warmup=True,
        )
    except Exception as e:
        legacy.api_logger.error(f"❌ Failed to initialize runtime: {e}")
        import traceback

        traceback.print_exc()
        return 1

    ctx = build_context(
        host=args.host,
        port=int(args.port),
        debug=bool(args.debug),
        config_file=config_file,
        min_text_length=int(args.min_text_length),
        runtime_module=legacy,
        app=legacy.app,
    )
    app = create_app(ctx)
    legacy.run_server(app=app, host=ctx.host, port=ctx.port, debug=ctx.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
