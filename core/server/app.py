"""Flask app assembly for runtime context."""

from __future__ import annotations

from .ctx import AppContext


def create_app(ctx: AppContext):
    """Return Flask app from runtime context."""

    if ctx is None:
        raise ValueError("ctx is required")
    if ctx.app is None:
        raise ValueError("ctx.app is not initialized")
    return ctx.app
