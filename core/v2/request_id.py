from __future__ import annotations

import uuid
from typing import Optional


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]


def pick_request_id(header_value: Optional[str]) -> str:
    v = (header_value or "").strip()
    if not v:
        return new_request_id()
    # Keep it short/safe; don't allow unbounded header content.
    return v[:64]

