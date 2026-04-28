from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from flask import g, request

from .errors import AppError, coerce_exception
from .logging import log_event


def get_request_id() -> str:
    return getattr(g, "request_id", "") or ""


def json_ok(app, payload: dict[str, Any], *, status: int = 200) :
    """
    JSON response with `X-Request-Id` header and `request_id` field.
    """
    rid = get_request_id()
    body = dict(payload or {})
    if rid and "request_id" not in body:
        body["request_id"] = rid
    resp = app.response_class(
        response=json.dumps(body, ensure_ascii=False),
        status=int(status),
        mimetype="application/json",
    )
    if rid:
        resp.headers["X-Request-Id"] = rid
    return resp


def json_error(app, logger, e: Exception):
    """
    Structured error response:
    {"error":{"code":"...","message":"...","details":{...}},"request_id":"..."}
    """
    err = coerce_exception(e)
    rid = get_request_id()
    try:
        log_event(
            logger,
            request_id=rid,
            event="API_REQ_FAIL",
            method=request.method,
            path=request.path,
            status=err.status,
            error_code=err.code,
            message=err.message,
            message_zh=err.message_zh or "",
        )
    except Exception:
        pass
    payload = err.to_dict()
    payload["request_id"] = rid
    resp = app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=int(err.status),
        mimetype="application/json",
    )
    if rid:
        resp.headers["X-Request-Id"] = rid
    return resp


def install_middleware(
    app,
    *,
    logger,
    pick_request_id: Callable[[Optional[str]], str],
) -> None:
    """
    Install request-id middleware + access log + 413 handler.

    - before_request: set `g.request_id` and `g._t0`
    - after_request: attach `X-Request-Id`, emit `http_access` log
    - errorhandler(413): return v2-style error JSON
    """

    @app.before_request
    def _set_request_id():
        g._t0 = time.perf_counter()
        g.request_id = pick_request_id(request.headers.get("X-Request-Id"))
        try:
            log_event(
                logger,
                request_id=get_request_id(),
                event="API_REQ_START",
                method=request.method,
                path=request.path,
                content_length=int(request.content_length or 0),
            )
        except Exception:
            pass

    @app.after_request
    def _attach_request_id(resp):
        try:
            rid = get_request_id()
            if rid:
                resp.headers["X-Request-Id"] = rid
        except Exception:
            pass

        try:
            rid = get_request_id()
            t0 = getattr(g, "_t0", None)
            dt_ms = int((time.perf_counter() - float(t0)) * 1000) if t0 else None
            log_event(
                logger,
                request_id=rid,
                event="API_REQ_END",
                method=request.method,
                path=request.path,
                status=int(getattr(resp, "status_code", 0) or 0),
                duration_ms=dt_ms,
                content_length=int(request.content_length or 0),
            )
        except Exception:
            pass
        return resp

    @app.errorhandler(413)
    def _payload_too_large(_e):
        return json_error(app, logger, AppError(code="payload_too_large", message="payload too large", status=413))
