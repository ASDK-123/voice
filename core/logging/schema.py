from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import current_thread
from typing import Any


EVENT_PREFIXES = ("APP_", "UI_", "API_", "SYN_", "AUD_", "BRG_", "CRH_", "LEGACY_")


# Fixed event dictionary (v1): required keys for each event.
EVENT_FIELD_SPEC: dict[str, set[str]] = {
    "APP_START": {"version"},
    "APP_READY": {"window"},
    "APP_SHUTDOWN": set(),
    "UI_CLICK_SYNTH": {"voice_id", "text_len"},
    "UI_PLAY_START": {"file"},
    "UI_PLAY_FAIL": {"file", "reason"},
    "API_REQ_START": {"method", "path"},
    "API_REQ_END": {"method", "path", "status", "duration_ms"},
    "API_REQ_FAIL": {"method", "path", "status", "error_code"},
    "SYN_START": {"voice_id", "text_len"},
    "SYN_DONE": {"voice_id", "duration_ms"},
    "SYN_FAIL": {"voice_id", "reason"},
    "SYN_CACHE_HIT": {"cache_key"},
    "SYN_CACHE_MISS": {"cache_key"},
    "CRH_UNCAUGHT": {"error_type", "message"},
    "CRH_QT_FATAL": {"error_type", "message"},
    "CRH_THREAD_EXCEPTION": {"error_type", "message", "thread_name"},
}


def now_iso_ms() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _normalize_level(level: str) -> str:
    v = str(level or "INFO").upper()
    if v == "WARN":
        return "WARNING"
    if v in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return v
    return "INFO"


def _validate_event_code(event: str) -> str:
    code = str(event or "").strip().upper()
    if not code:
        raise ValueError("event code cannot be empty")
    if not code.startswith(EVENT_PREFIXES):
        raise ValueError(f"event code must start with one of {EVENT_PREFIXES}, got: {code}")
    return code


def validate_event_fields(event: str, fields: dict[str, Any]) -> None:
    req = EVENT_FIELD_SPEC.get(event)
    if req is None:
        return
    missing = [k for k in sorted(req) if k not in (fields or {})]
    if missing:
        raise ValueError(f"event {event} missing required fields: {', '.join(missing)}")


@dataclass
class LogEventV1:
    ts: str
    level: str
    module: str
    event: str
    request_id: str
    session_id: str
    thread: str
    msg_zh: str
    msg_en: str
    fields: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1"

    @classmethod
    def create(
        cls,
        *,
        level: str,
        module: str,
        event: str,
        request_id: str = "",
        session_id: str = "",
        msg_zh: str = "",
        msg_en: str = "",
        fields: dict[str, Any] | None = None,
        schema_version: str = "1",
    ) -> "LogEventV1":
        event_code = _validate_event_code(event)
        normalized_fields = dict(fields or {})
        validate_event_fields(event_code, normalized_fields)
        return cls(
            ts=now_iso_ms(),
            level=_normalize_level(level),
            module=str(module or "app"),
            event=event_code,
            request_id=str(request_id or ""),
            session_id=str(session_id or ""),
            thread=current_thread().name,
            msg_zh=str(msg_zh or ""),
            msg_en=str(msg_en or ""),
            fields=normalized_fields,
            schema_version=str(schema_version or "1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "level": self.level,
            "module": self.module,
            "event": self.event,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "thread": self.thread,
            "msg_zh": self.msg_zh,
            "msg_en": self.msg_en,
            "fields": self.fields,
            "schema_version": self.schema_version,
        }

