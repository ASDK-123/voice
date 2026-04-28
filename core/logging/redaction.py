from __future__ import annotations

import hashlib
import os
from typing import Any


DEFAULT_HEADER_ALLOWLIST = {
    "x-request-id",
    "content-type",
    "accept",
    "user-agent",
    "authorization",
}


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()


def redact_text(value: str, *, max_preview: int = 120) -> dict[str, Any]:
    text = str(value or "")
    if len(text) <= max_preview:
        return {"text_preview": text, "text_sha1": _sha1_text(text), "text_len": len(text)}
    preview = text[:max_preview]
    return {"text_preview": preview + "...", "text_sha1": _sha1_text(text), "text_len": len(text)}


def redact_path(path: str, *, keep_basename: bool = True) -> str:
    raw = str(path or "")
    if not raw:
        return raw
    norm = raw.replace("\\", "/").strip()
    if not keep_basename:
        return norm
    base = os.path.basename(norm)
    parent = os.path.basename(os.path.dirname(norm))
    if parent:
        return f".../{parent}/{base}"
    return f".../{base}"


def redact_token(value: str, *, visible_prefix: int = 4, visible_suffix: int = 2) -> str:
    s = str(value or "")
    if len(s) <= visible_prefix + visible_suffix:
        return "*" * len(s)
    return s[:visible_prefix] + "*" * (len(s) - visible_prefix - visible_suffix) + s[-visible_suffix:]


def redact_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    if not headers:
        return {}
    out: dict[str, Any] = {}
    for k, v in headers.items():
        key = str(k or "").strip()
        low = key.lower()
        if low not in DEFAULT_HEADER_ALLOWLIST:
            out[key] = "***"
            continue
        if low == "authorization":
            out[key] = redact_token(str(v or ""), visible_prefix=6, visible_suffix=2)
            continue
        out[key] = str(v or "")
    return out


def redact_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    if not fields:
        return {}
    out: dict[str, Any] = {}
    for k, v in fields.items():
        key = str(k or "")
        low = key.lower()
        if v is None:
            out[key] = None
            continue

        if "header" in low and isinstance(v, dict):
            out[key] = redact_headers(v)
            continue

        if low in {"text", "input", "prompt_text", "instruct_text"}:
            out[key] = redact_text(str(v))
            continue

        if "path" in low or "file" in low:
            out[key] = redact_path(str(v))
            continue

        if "token" in low or "api_key" in low or "password" in low:
            out[key] = redact_token(str(v))
            continue

        if isinstance(v, dict):
            out[key] = redact_fields(v)
            continue

        out[key] = v
    return out

