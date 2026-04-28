from __future__ import annotations

import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import Any

from .runtime import emit_event, get_logger, get_runtime


_INSTALLED = False
_CRASH_PATH = ""
_FAULT_FILE = None
_OLD_SYS_HOOK = None
_OLD_THREAD_HOOK = None
_OLD_QT_HOOK = None


def _append_crash_text(text: str) -> None:
    global _CRASH_PATH
    if not _CRASH_PATH:
        return
    line = f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} {text}\n"
    try:
        with open(_CRASH_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
    except Exception:
        pass


def _install_qt_handler(logger) -> None:
    global _OLD_QT_HOOK
    try:
        from PyQt5.QtCore import QtCriticalMsg, QtFatalMsg, qInstallMessageHandler
    except Exception:
        return

    def _qt_message_handler(mode: Any, context: Any, message: str):
        if mode not in (QtCriticalMsg, QtFatalMsg):
            if callable(_OLD_QT_HOOK):
                _OLD_QT_HOOK(mode, context, message)
            return

        mode_name = str(int(mode))
        level = "ERROR"
        event = "CRH_QT_FATAL" if mode == QtFatalMsg else "CRH_UNCAUGHT"
        payload_fields = {
            "qt_mode": mode_name,
            "file": getattr(context, "file", ""),
            "line": int(getattr(context, "line", 0) or 0),
            "function": getattr(context, "function", ""),
        }
        _append_crash_text(f"[QT] mode={mode_name} message={message}")
        try:
            emit_event(
                logger=logger,
                level=level,
                module="qt",
                event=event,
                msg_zh="Qt 致命消息" if mode == QtFatalMsg else "Qt 运行时消息",
                request_id="",
                fields={
                    "error_type": "QtMessage",
                    "message": str(message or ""),
                    **payload_fields,
                },
            )
        except Exception:
            pass
        if callable(_OLD_QT_HOOK):
            _OLD_QT_HOOK(mode, context, message)

    _OLD_QT_HOOK = qInstallMessageHandler(_qt_message_handler)


def install_crash_handlers(*, log_dir: str | None = None) -> str:
    global _INSTALLED, _CRASH_PATH, _FAULT_FILE, _OLD_SYS_HOOK, _OLD_THREAD_HOOK
    if _INSTALLED:
        return _CRASH_PATH

    rt = get_runtime()
    logger = get_logger("crash")
    base_dir = str(log_dir or rt.log_dir)
    os.makedirs(base_dir, exist_ok=True)
    _CRASH_PATH = os.path.join(base_dir, "crash.log")

    try:
        _FAULT_FILE = open(_CRASH_PATH, "a", encoding="utf-8")
        faulthandler.enable(_FAULT_FILE, all_threads=True)
    except Exception:
        _FAULT_FILE = None

    _OLD_SYS_HOOK = sys.excepthook
    _OLD_THREAD_HOOK = threading.excepthook

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _append_crash_text("[UNCAUGHT]\n" + text)
        try:
            emit_event(
                logger=logger,
                level="ERROR",
                module="app",
                event="CRH_UNCAUGHT",
                msg_zh="捕获到未处理异常",
                fields={
                    "error_type": getattr(exc_type, "__name__", "Exception"),
                    "message": str(exc_value or ""),
                },
            )
        except Exception:
            pass
        if callable(_OLD_SYS_HOOK):
            _OLD_SYS_HOOK(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args):
        text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _append_crash_text(f"[THREAD:{args.thread.name}]\n" + text)
        try:
            emit_event(
                logger=logger,
                level="ERROR",
                module="thread",
                event="CRH_THREAD_EXCEPTION",
                msg_zh="线程发生未处理异常",
                fields={
                    "error_type": getattr(args.exc_type, "__name__", "Exception"),
                    "message": str(args.exc_value or ""),
                    "thread_name": str(getattr(args.thread, "name", "") or ""),
                },
            )
        except Exception:
            pass
        if callable(_OLD_THREAD_HOOK):
            _OLD_THREAD_HOOK(args)

    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
    _install_qt_handler(logger)
    _INSTALLED = True
    return _CRASH_PATH
