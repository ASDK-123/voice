from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, request, send_file


SOURCE_META = {
    "app": {
        "label": "应用日志",
        "filename": "app.log",
        "mimetype": "text/plain; charset=utf-8",
    },
    "access": {
        "label": "访问日志",
        "filename": "access.jsonl",
        "mimetype": "application/x-ndjson; charset=utf-8",
    },
    "crash": {
        "label": "崩溃日志",
        "filename": "crash.log",
        "mimetype": "text/plain; charset=utf-8",
    },
    "local_bridge": {
        "label": "本地桥接日志",
        "filename": "webui_local_bridge_api.log",
        "mimetype": "text/plain; charset=utf-8",
    },
}

TEXT_LEVEL_MAP = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
    "调试": "DEBUG",
    "信息": "INFO",
    "警告": "WARNING",
    "错误": "ERROR",
    "严重": "CRITICAL",
}

HUMAN_RE = re.compile(r"^\[(?P<level>[^\]]+)\](?:\[(?P<module>[^\]]+)\])?\s*(?P<message>.*)$")
KV_RE = re.compile(r"(?P<key>[A-Za-z0-9_\-]+)=(?P<value>[^,]+)")
ISO_TS_RE = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2}T[0-9:.+\-:]+)")


def create_v2_logs_blueprint(ctx) -> Blueprint:
    bp = Blueprint("api_v2_log_routes", __name__)
    require = ctx.require_v2_api_key
    json_ok = ctx.json_ok
    json_error = ctx.json_error
    AppError = ctx.AppError

    def _log_dir() -> Path:
        value = getattr(ctx, "log_dir", None)
        if value:
            return Path(str(value)).resolve()
        return Path("data/logs").resolve()

    def _export_bundle(output_zip: Path) -> Path:
        fn = getattr(ctx, "export_diagnostic_bundle", None)
        if callable(fn):
            return Path(fn(output_zip))
        from scripts.export_diagnostic_bundle import export_bundle

        return Path(export_bundle(output_zip))

    def _normalize_source(source: str) -> str:
        sid = str(source or "").strip().lower()
        if sid not in SOURCE_META:
            raise AppError(
                code="log_source_not_found",
                message="unknown log source",
                message_zh="未知日志源",
                status=400,
            )
        return sid

    def _source_path(source: str) -> Path:
        meta = SOURCE_META[_normalize_source(source)]
        return _log_dir() / str(meta["filename"])

    def _source_payload(source: str) -> dict[str, Any]:
        meta = SOURCE_META[source]
        path = _source_path(source)
        return {
            "id": source,
            "label": meta["label"],
            "available": path.exists() and path.is_file(),
        }

    def _normalize_level(level: str) -> str:
        raw = str(level or "").strip().upper()
        return TEXT_LEVEL_MAP.get(raw, raw)

    def _extract_timestamp(raw: str) -> str:
        match = ISO_TS_RE.search(str(raw or ""))
        return match.group("ts") if match else ""

    def _make_id(source: str, raw: str, line_no: int) -> str:
        digest = hashlib.sha1(f"{source}:{line_no}:{raw}".encode("utf-8", errors="ignore")).hexdigest()
        return f"log_{digest[:16]}"

    def _parse_access_line(raw: str, line_no: int) -> dict[str, Any]:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("access line is not dict")
        except Exception:
            return _parse_text_line("access", raw, line_no)
        msg = str(payload.get("msg_zh") or payload.get("msg_en") or payload.get("event") or text)
        return {
            "id": _make_id("access", text, line_no),
            "source": "access",
            "timestamp": str(payload.get("ts") or ""),
            "level": _normalize_level(str(payload.get("level") or "INFO")) or "INFO",
            "module": str(payload.get("module") or "access"),
            "event": str(payload.get("event") or ""),
            "message": msg,
            "request_id": str(payload.get("request_id") or ""),
            "fields": payload.get("fields") if isinstance(payload.get("fields"), dict) else {},
            "raw": text,
        }

    def _parse_text_line(source: str, raw: str, line_no: int) -> dict[str, Any]:
        text = str(raw or "").rstrip("\r\n")
        if not text:
            return {}
        level = "INFO"
        module = source
        message = text
        event = ""
        request_id = ""
        fields: dict[str, Any] = {}

        match = HUMAN_RE.match(text)
        if match:
            level = _normalize_level(match.group("level"))
            module = str(match.group("module") or source)
            message = str(match.group("message") or "").strip()
            if " | " in message:
                primary, suffix = message.split(" | ", 1)
                message = primary.strip()
                for field_match in KV_RE.finditer(suffix):
                    key = str(field_match.group("key") or "").strip()
                    value = str(field_match.group("value") or "").strip()
                    if key:
                        fields[key] = value
                request_id = str(fields.get("request_id") or "")
        else:
            request_match = re.search(r"(?:^|[|, ])request_id=(?P<rid>[A-Za-z0-9_:\-]+)", text)
            if request_match:
                request_id = str(request_match.group("rid") or "")

        return {
            "id": _make_id(source, text, line_no),
            "source": source,
            "timestamp": _extract_timestamp(text),
            "level": level or "INFO",
            "module": module or source,
            "event": event,
            "message": message or text,
            "request_id": request_id,
            "fields": fields,
            "raw": text,
        }

    def _parse_lines(source: str, raw_text: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        parser = _parse_access_line if source == "access" else _parse_text_line
        for idx, line in enumerate(raw_text.splitlines(), start=1):
            parsed = parser(line, idx) if source == "access" else parser(source, line, idx)
            if parsed:
                items.append(parsed)
        return items

    def _matches_filters(item: dict[str, Any], level: str, query_text: str) -> bool:
        if level and str(item.get("level") or "").upper() != level:
            return False
        if query_text:
            blob = " ".join(
                [
                    str(item.get("timestamp") or ""),
                    str(item.get("level") or ""),
                    str(item.get("module") or ""),
                    str(item.get("event") or ""),
                    str(item.get("message") or ""),
                    str(item.get("request_id") or ""),
                    json.dumps(item.get("fields") or {}, ensure_ascii=False, sort_keys=True),
                    str(item.get("raw") or ""),
                ]
            ).lower()
            if query_text not in blob:
                return False
        return True

    def _read_snapshot(path: Path, source: str, limit: int, level: str, query_text: str) -> list[dict[str, Any]]:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return []
        items = [item for item in _parse_lines(source, raw_text) if _matches_filters(item, level, query_text)]
        if limit > 0 and len(items) > limit:
            items = items[-limit:]
        return items

    def _read_delta(path: Path, source: str, cursor: int, level: str, query_text: str) -> list[dict[str, Any]]:
        with path.open("rb") as fh:
            fh.seek(cursor)
            raw_bytes = fh.read()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        return [item for item in _parse_lines(source, raw_text) if _matches_filters(item, level, query_text)]

    @bp.route("/api/v2/pro/logs/sources", methods=["GET"])
    @require
    def list_log_sources():
        try:
            items = [_source_payload(source) for source in SOURCE_META]
            return json_ok({"items": items}, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/pro/logs/tail", methods=["GET"])
    @require
    def tail_logs():
        try:
            source = _normalize_source(request.args.get("source", ""))
            path = _source_path(source)
            limit = max(1, min(int(ctx.safe_int(request.args.get("limit", 200), 200)), 500))
            cursor = max(0, int(ctx.safe_int(request.args.get("cursor", 0), 0)))
            level = _normalize_level(request.args.get("level", ""))
            query_text = str(request.args.get("q", "") or "").strip().lower()

            if not path.exists() or not path.is_file():
                return json_ok(
                    {
                        "items": [],
                        "next_cursor": "0",
                        "reset_required": False,
                        "source_available": False,
                    },
                    status=200,
                )

            size = path.stat().st_size
            reset_required = cursor > size
            if cursor > 0 and not reset_required:
                items = _read_delta(path, source, cursor, level, query_text)
            else:
                items = _read_snapshot(path, source, limit, level, query_text)

            return json_ok(
                {
                    "items": items,
                    "next_cursor": str(size),
                    "reset_required": reset_required,
                    "source_available": True,
                },
                status=200,
            )
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/pro/logs/file", methods=["GET"])
    @require
    def download_log_file():
        try:
            source = _normalize_source(request.args.get("source", ""))
            path = _source_path(source)
            if not path.exists() or not path.is_file():
                raise AppError(
                    code="invalid_request",
                    message="log file not found",
                    message_zh="日志文件不存在",
                    status=404,
                )
            meta = SOURCE_META[source]
            return send_file(
                path,
                mimetype=str(meta["mimetype"]),
                as_attachment=True,
                download_name=path.name,
            )
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/pro/logs/diagnostic-bundle", methods=["POST"])
    @require
    def download_diagnostic_bundle():
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            bundle_path = _log_dir() / f"diag_{ts}.zip"
            result = _export_bundle(bundle_path)
            return send_file(
                result,
                mimetype="application/zip",
                as_attachment=True,
                download_name=result.name,
            )
        except Exception as e:
            return json_error(e)

    return bp
