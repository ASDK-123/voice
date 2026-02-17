from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AppError(Exception):
    """
    Structured application error for API responses.
    """

    code: str
    message: str
    status: int = 400
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.details:
            d["error"]["details"] = self.details
        return d


def coerce_exception(e: Exception) -> AppError:
    """
    Convert common exception types into AppError.
    """
    if isinstance(e, AppError):
        return e
    if isinstance(e, ValueError):
        return AppError(code="invalid_request", message=str(e), status=400)
    if isinstance(e, FileNotFoundError):
        return AppError(code="asset_not_found", message=str(e), status=404)
    return AppError(code="internal_error", message=str(e) or "internal error", status=500)
