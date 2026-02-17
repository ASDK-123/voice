"""Server package scaffolding for phased API refactor (M0)."""

from .app import create_app
from .ctx import AppContext, build_context
from .main import main

__all__ = ["AppContext", "build_context", "create_app", "main"]
