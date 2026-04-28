from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid
import atexit
from dataclasses import dataclass
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Any

from .compat import event_to_legacy_text, legacy_line_to_event
from .redaction import redact_fields
from .schema import LogEventV1


_DEFAULTS: dict[str, Any] = {
    "log_language": "zh-CN",
    "log_console_format": "human",
    "log_file_format": "jsonl",
    "log_level": "INFO",
    "log_dir": "data/logs",
    "log_third_party_mode": "quiet",
    "log_compat_mode": "smooth",
    "log_schema_version": "1",
    "log_queue_max": 10000,
    "log_drop_policy": "drop_debug_first",
}

_LEVEL_ZH = {
    "DEBUG": "调试",
    "INFO": "信息",
    "WARNING": "警告",
    "ERROR": "错误",
    "CRITICAL": "严重",
}


@dataclass
class LogSettings:
    log_language: str = "zh-CN"
    log_console_format: str = "human"
    log_file_format: str = "jsonl"
    log_level: str = "INFO"
    log_dir: str = "data/logs"
    log_third_party_mode: str = "quiet"
    log_compat_mode: str = "smooth"
    log_schema_version: str = "1"
    log_queue_max: int = 10000
    log_drop_policy: str = "drop_debug_first"

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "LogSettings":
        d = dict(_DEFAULTS)
        d.update(dict(cfg or {}))
        return cls(
            log_language=str(d.get("log_language", "zh-CN")),
            log_console_format=str(d.get("log_console_format", "human")),
            log_file_format=str(d.get("log_file_format", "jsonl")),
            log_level=str(d.get("log_level", "INFO")).upper(),
            log_dir=str(d.get("log_dir", "data/logs")),
            log_third_party_mode=str(d.get("log_third_party_mode", "quiet")),
            log_compat_mode=str(d.get("log_compat_mode", "smooth")),
            log_schema_version=str(d.get("log_schema_version", "1")),
            log_queue_max=max(100, int(d.get("log_queue_max", 10000) or 10000)),
            log_drop_policy=str(d.get("log_drop_policy", "drop_debug_first")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "log_language": self.log_language,
            "log_console_format": self.log_console_format,
            "log_file_format": self.log_file_format,
            "log_level": self.log_level,
            "log_dir": self.log_dir,
            "log_third_party_mode": self.log_third_party_mode,
            "log_compat_mode": self.log_compat_mode,
            "log_schema_version": self.log_schema_version,
            "log_queue_max": self.log_queue_max,
            "log_drop_policy": self.log_drop_policy,
        }


class _DropOnFullQueueHandler(QueueHandler):
    def __init__(self, q: queue.Queue, *, drop_policy: str):
        super().__init__(q)
        self.drop_policy = str(drop_policy or "drop_debug_first")
        self._dropped = 0
        self._cv_runtime = True

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
            return
        except queue.Full:
            pass

        if self.drop_policy == "drop_debug_first" and int(record.levelno) <= int(logging.DEBUG):
            self._dropped += 1
            return

        # Best effort: drop one item then retry.
        try:
            self.queue.get_nowait()
            self.queue.put_nowait(record)
        except Exception:
            self._dropped += 1


class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_obj = getattr(record, "event_obj", None)
        if isinstance(event_obj, dict):
            level = str(event_obj.get("level", record.levelname)).upper()
            level_zh = _LEVEL_ZH.get(level, "信息")
            module = str(event_obj.get("module", record.name))
            msg = str(event_obj.get("msg_zh") or event_obj.get("msg_en") or record.getMessage())
            fields = event_obj.get("fields") or {}
            suffix_parts: list[str] = []
            rid = str(event_obj.get("request_id") or "")
            if rid:
                suffix_parts.append(f"request_id={rid}")
            for key in ("status", "duration_ms", "voice_id", "path", "method"):
                if key in fields:
                    suffix_parts.append(f"{key}={fields.get(key)}")
            suffix = ""
            if suffix_parts:
                suffix = " | " + ", ".join(suffix_parts)
            return f"[{level_zh}][{module}] {msg}{suffix}"
        return record.getMessage()


class _JsonlFormatter(logging.Formatter):
    def __init__(self, session_id: str, schema_version: str):
        super().__init__()
        self.session_id = session_id
        self.schema_version = schema_version

    def format(self, record: logging.LogRecord) -> str:
        event_obj = getattr(record, "event_obj", None)
        if isinstance(event_obj, dict):
            payload = dict(event_obj)
            payload.setdefault("session_id", self.session_id)
            payload.setdefault("schema_version", self.schema_version)
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)

        fallback = legacy_line_to_event(
            record.getMessage(),
            module=record.name,
            session_id=self.session_id,
            schema_version=self.schema_version,
        )
        return json.dumps(fallback.to_dict(), ensure_ascii=False, sort_keys=True)


class _AccessEventFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        event_obj = getattr(record, "event_obj", None)
        if isinstance(event_obj, dict):
            evt = str(event_obj.get("event", "")).upper()
            return evt.startswith("API_")
        msg = record.getMessage()
        return '"event": "http_access"' in msg or '"event":"http_access"' in msg


class LoggingRuntime:
    def __init__(self, settings: LogSettings):
        self.settings = settings
        self.session_id = "sess_" + uuid.uuid4().hex[:16]
        self.log_dir = Path(settings.log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.queue: queue.Queue = queue.Queue(maxsize=int(settings.log_queue_max))
        self.queue_handler = _DropOnFullQueueHandler(
            self.queue,
            drop_policy=settings.log_drop_policy,
        )
        self.listener: QueueListener | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self.listener is not None:
                return

            handlers: list[logging.Handler] = []

            console_handler = logging.StreamHandler()
            if self.settings.log_console_format.lower() == "json":
                console_handler.setFormatter(_JsonlFormatter(self.session_id, self.settings.log_schema_version))
            else:
                console_handler.setFormatter(_HumanFormatter())
            handlers.append(console_handler)

            app_file = RotatingFileHandler(
                str(self.log_dir / "app.log"),
                maxBytes=10 * 1024 * 1024,
                backupCount=10,
                encoding="utf-8",
            )
            app_file.setFormatter(_HumanFormatter())
            handlers.append(app_file)

            access_file = RotatingFileHandler(
                str(self.log_dir / "access.jsonl"),
                maxBytes=20 * 1024 * 1024,
                backupCount=14,
                encoding="utf-8",
            )
            access_file.setFormatter(_JsonlFormatter(self.session_id, self.settings.log_schema_version))
            access_file.addFilter(_AccessEventFilter())
            handlers.append(access_file)

            self.listener = QueueListener(self.queue, *handlers, respect_handler_level=True)
            self.listener.start()

            root = logging.getLogger()
            root.setLevel(getattr(logging, self.settings.log_level, logging.INFO))
            for h in list(root.handlers):
                if h is self.queue_handler:
                    continue
                if getattr(h, "_cv_runtime", False):
                    continue
                root.removeHandler(h)
            if self.queue_handler not in root.handlers:
                root.addHandler(self.queue_handler)

            self._apply_third_party_mode()

    def _apply_third_party_mode(self) -> None:
        mode = self.settings.log_third_party_mode.lower().strip()
        if mode == "verbose":
            return
        level = logging.WARNING if mode == "normal" else logging.ERROR
        noisy = [
            "httpx",
            "urllib3",
            "werkzeug",
            "torch",
            "lightning",
            "cosyvoice",
            "Matcha-TTS",
            "matplotlib",
        ]
        for name in noisy:
            logging.getLogger(name).setLevel(level)

    def bind_logger(self, logger: logging.Logger) -> logging.Logger:
        if logger.propagate:
            logger.setLevel(getattr(logging, self.settings.log_level, logging.INFO))
            return logger
        if self.queue_handler not in logger.handlers:
            logger.addHandler(self.queue_handler)
        logger.setLevel(getattr(logging, self.settings.log_level, logging.INFO))
        return logger

    def emit_event(
        self,
        *,
        logger: logging.Logger,
        level: str,
        module: str,
        event: str,
        msg_zh: str,
        msg_en: str = "",
        request_id: str = "",
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_fields = redact_fields(fields or {})
        evt = LogEventV1.create(
            level=level,
            module=module,
            event=event,
            request_id=request_id,
            session_id=self.session_id,
            msg_zh=msg_zh,
            msg_en=msg_en,
            fields=safe_fields,
            schema_version=self.settings.log_schema_version,
        )
        payload = evt.to_dict()
        text = event_to_legacy_text(payload) if self.settings.log_compat_mode in {"smooth", "legacy"} else (
            msg_zh or msg_en or event
        )
        logger.log(
            getattr(logging, evt.level, logging.INFO),
            text,
            extra={"event_obj": payload},
        )
        return payload

    def shutdown(self) -> None:
        with self._lock:
            if self.listener is not None:
                self.listener.stop()
                self.listener = None


_RUNTIME: LoggingRuntime | None = None


def _load_config_dict(config_path: str) -> dict[str, Any]:
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def init_logging(*, config_path: str = "app_config.json", config: dict[str, Any] | None = None) -> LoggingRuntime:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    cfg = dict(_load_config_dict(config_path))
    if config:
        cfg.update(config)
    settings = LogSettings.from_config(cfg)
    rt = LoggingRuntime(settings)
    rt.start()
    _RUNTIME = rt
    atexit.register(shutdown_logging)
    return rt


def get_runtime() -> LoggingRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = init_logging()
    return _RUNTIME


def get_logger(name: str) -> logging.Logger:
    rt = get_runtime()
    lg = logging.getLogger(str(name or "cosyvoice"))
    return rt.bind_logger(lg)


def emit_event(
    *,
    logger: logging.Logger | None,
    level: str,
    module: str,
    event: str,
    msg_zh: str,
    msg_en: str = "",
    request_id: str = "",
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rt = get_runtime()
    lg = logger or get_logger(module)
    return rt.emit_event(
        logger=lg,
        level=level,
        module=module,
        event=event,
        msg_zh=msg_zh,
        msg_en=msg_en,
        request_id=request_id,
        fields=fields,
    )


def shutdown_logging() -> None:
    global _RUNTIME
    if _RUNTIME is not None:
        _RUNTIME.shutdown()
        _RUNTIME = None
