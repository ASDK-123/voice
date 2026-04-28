from __future__ import annotations

from typing import Any

from .schema import LogEventV1


_LEVEL_PREFIX = (
    ("[ERROR]", "ERROR"),
    ("[WARN]", "WARNING"),
    ("[WARNING]", "WARNING"),
    ("[OK]", "INFO"),
    ("[INFO]", "INFO"),
    ("[DEBUG]", "DEBUG"),
)


def parse_legacy_level(message: str) -> str:
    text = str(message or "").strip().upper()
    for prefix, level in _LEVEL_PREFIX:
        if text.startswith(prefix):
            return level
    return "INFO"


def strip_legacy_prefix(message: str) -> str:
    text = str(message or "").strip()
    upper = text.upper()
    for prefix, _level in _LEVEL_PREFIX:
        if upper.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def legacy_line_to_event(
    message: str,
    *,
    module: str = "legacy",
    session_id: str = "",
    request_id: str = "",
    schema_version: str = "1",
) -> LogEventV1:
    level = parse_legacy_level(message)
    msg = strip_legacy_prefix(message)
    return LogEventV1.create(
        level=level,
        module=module,
        event="LEGACY_LOG",
        request_id=request_id,
        session_id=session_id,
        msg_zh=msg,
        msg_en="",
        fields={},
        schema_version=schema_version,
    )


def event_to_legacy_text(event_obj: dict[str, Any]) -> str:
    level = str(event_obj.get("level", "INFO")).upper()
    module = str(event_obj.get("module", "app"))
    msg = str(event_obj.get("msg_zh") or event_obj.get("msg_en") or "")
    return f"[{level}][{module}] {msg}"

