from __future__ import annotations

import json
import time
from typing import Any


def log_event(logger, *, request_id: str, event: str, **fields: Any) -> None:
    """
    Emit a single structured JSON log line.
    """
    payload = {
        "ts": int(time.time()),
        "request_id": request_id,
        "event": event,
        **fields,
    }
    try:
        logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:
        # Never fail request handling because logging failed.
        pass

