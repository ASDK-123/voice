from __future__ import annotations

import json
import time
from typing import Any

from core.logging.runtime import emit_event, get_runtime


_EVENT_ZH = {
    "API_REQ_START": "请求开始",
    "API_REQ_END": "请求完成",
    "API_REQ_FAIL": "请求失败",
    "SYN_START": "开始语音合成",
    "SYN_DONE": "语音合成完成",
    "SYN_FAIL": "语音合成失败",
    "SYN_CACHE_HIT": "命中语音缓存",
    "SYN_CACHE_MISS": "未命中语音缓存",
}

def log_event(logger, *, request_id: str, event: str, **fields: Any) -> None:
    """
    Emit one event in the new schema while preserving legacy JSON output in smooth mode.
    """
    event_code = str(event or "").strip().upper()
    if not event_code.startswith(("APP_", "UI_", "API_", "SYN_", "AUD_", "BRG_", "CRH_", "LEGACY_")):
        event_code = "API_" + event_code

    level = "ERROR" if event_code.endswith("_FAIL") else "INFO"
    msg_zh = _EVENT_ZH.get(event_code, f"事件 {event_code}")
    payload = None

    try:
        payload = emit_event(
            logger=logger,
            level=level,
            module="api.v2",
            event=event_code,
            request_id=request_id,
            msg_zh=msg_zh,
            fields=fields,
        )
    except Exception:
        pass

    # Smooth compatibility: keep legacy JSON format for existing grep/scripts.
    try:
        compat_mode = get_runtime().settings.log_compat_mode.lower()
    except Exception:
        compat_mode = "smooth"
    if compat_mode in {"smooth", "legacy"}:
        try:
            legacy = {
                "ts": int(time.time()),
                "request_id": request_id,
                "event": str(event or ""),
                **dict(fields or {}),
            }
            logger.info(json.dumps(legacy, ensure_ascii=False, sort_keys=True))
        except Exception:
            pass

    # Keep function total side-effect visibility for callers that inspect adapter behavior in tests.
    return payload
