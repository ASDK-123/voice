import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests


def new_request_id() -> str:
    return f"rid_{uuid.uuid4().hex[:16]}"


@dataclass
class V2Config:
    host: str
    port: int
    api_key: str = ""
    timeout_s: float = 10.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class V2HttpError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str = "",
        details: Optional[dict] = None,
        raw_text: str = "",
    ):
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code or "")
        self.message = str(message or "")
        self.request_id = str(request_id or "")
        self.details = details or {}
        self.raw_text = str(raw_text or "")

    def short(self) -> str:
        parts = [f"HTTP {self.status_code}", f"code={self.code}" if self.code else ""]
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        if self.message:
            parts.append(f"msg={self.message}")
        return " ".join([p for p in parts if p]).strip()


def _pick_request_id(resp: requests.Response, payload: Any) -> str:
    rid = (resp.headers.get("X-Request-Id") or "").strip()
    if rid:
        return rid
    if isinstance(payload, dict):
        rid2 = (payload.get("request_id") or "").strip()
        if rid2:
            return rid2
    return ""


def _raise_for_status(resp: requests.Response) -> None:
    if 200 <= int(resp.status_code) < 400:
        return

    raw_text = ""
    try:
        raw_text = resp.text or ""
    except Exception:
        raw_text = ""

    payload: Any = None
    try:
        payload = resp.json()
    except Exception:
        payload = None

    code = ""
    message = ""
    details: Optional[dict] = None

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or "")
            message = str(err.get("message") or "")
            det = err.get("details")
            details = det if isinstance(det, dict) else None

    if not message:
        message = raw_text.strip() or f"HTTP {resp.status_code}"

    raise V2HttpError(
        status_code=int(resp.status_code),
        code=code,
        message=message,
        request_id=_pick_request_id(resp, payload),
        details=details,
        raw_text=raw_text,
    )


def _seg(s: str) -> str:
    """
    URL-encode a single path segment.

    Important: voice_id contains '#' (character#emotion). If not encoded, it becomes a URL fragment
    and won't reach the server.
    """
    return quote(str(s or ""), safe="")


class V2Client:
    """UI-side blocking HTTP client for v2 endpoints (call in worker threads)."""

    def __init__(self, cfg: V2Config):
        self.cfg = cfg
        self._session = requests.Session()

    def _headers(self, request_id: str = "") -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.cfg.api_key:
            h["X-API-Key"] = self.cfg.api_key
        if request_id:
            h["X-Request-Id"] = request_id
        return h

    def _get(self, path: str, *, params: Optional[dict] = None, request_id: str = "") -> requests.Response:
        url = self.cfg.base_url.rstrip("/") + path
        resp = self._session.get(url, params=params, headers=self._headers(request_id), timeout=float(self.cfg.timeout_s))
        _raise_for_status(resp)
        return resp

    def _post(self, path: str, *, json: Optional[dict] = None, params: Optional[dict] = None, request_id: str = "") -> requests.Response:
        url = self.cfg.base_url.rstrip("/") + path
        resp = self._session.post(url, json=json, params=params, headers=self._headers(request_id), timeout=float(self.cfg.timeout_s))
        _raise_for_status(resp)
        return resp

    def _put(self, path: str, *, json: Optional[dict] = None, request_id: str = "") -> requests.Response:
        url = self.cfg.base_url.rstrip("/") + path
        resp = self._session.put(url, json=json, headers=self._headers(request_id), timeout=float(self.cfg.timeout_s))
        _raise_for_status(resp)
        return resp

    def _delete(self, path: str, *, request_id: str = "") -> requests.Response:
        url = self.cfg.base_url.rstrip("/") + path
        resp = self._session.delete(url, headers=self._headers(request_id), timeout=float(self.cfg.timeout_s))
        _raise_for_status(resp)
        return resp

    def health(self) -> dict:
        return self._get("/api/v2/health").json()

    # -------- voices --------
    def list_voices(self) -> List[dict]:
        payload = self._get("/api/v2/voices").json() or {}
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def get_voice(self, voice_id: str) -> dict:
        return self._get(f"/api/v2/voices/{_seg(voice_id)}").json()

    def create_voice(self, voice: dict) -> dict:
        return self._post("/api/v2/voices", json=voice).json()

    def update_voice(self, voice_id: str, patch: dict) -> dict:
        return self._put(f"/api/v2/voices/{_seg(voice_id)}", json=patch).json()

    def delete_voice(self, voice_id: str) -> dict:
        return self._delete(f"/api/v2/voices/{_seg(voice_id)}").json()

    def reload_voices(self) -> dict:
        return self._post("/api/v2/voices/reload", json={}).json()

    def compile_voice(self, voice_id: str, compile_all: bool = False) -> dict:
        params = {"all": "1"} if compile_all else None
        url = self.cfg.base_url.rstrip("/") + f"/api/v2/voices/{_seg(voice_id)}/compile"
        resp = self._session.post(url, params=params, headers=self._headers(), timeout=max(float(self.cfg.timeout_s), 30.0))
        _raise_for_status(resp)
        return resp.json()

    # -------- assets --------
    def list_assets(self, *, character: str = "", emotion: str = "", language: str = "", kind: str = "ref") -> List[dict]:
        params: Dict[str, str] = {}
        if character:
            params["character"] = character
        if emotion:
            params["emotion"] = emotion
        if language:
            params["language"] = language
        if kind:
            params["kind"] = kind
        payload = self._get("/api/v2/assets/audio", params=params).json() or {}
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def upload_asset(self, *, file_path: str, character: str, emotion: str, language: str, note: str = "") -> dict:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f.read())}
        data = {"character": character, "emotion": emotion, "language": language, "note": note}
        url = self.cfg.base_url.rstrip("/") + "/api/v2/assets/audio"
        resp = self._session.post(url, files=files, data=data, headers=self._headers(), timeout=max(float(self.cfg.timeout_s), 60.0))
        _raise_for_status(resp)
        return resp.json()

    def delete_asset(self, asset_id: str) -> dict:
        return self._delete(f"/api/v2/assets/audio/{_seg(asset_id)}").json()

    def get_asset_meta(self, asset_id: str) -> dict:
        return self._get(f"/api/v2/assets/audio/{_seg(asset_id)}").json()

    def update_asset(self, asset_id: str, patch: dict) -> dict:
        return self._put(f"/api/v2/assets/audio/{_seg(asset_id)}", json=patch).json()

    def download_asset_content(self, asset_id: str) -> bytes:
        url = self.cfg.base_url.rstrip("/") + f"/api/v2/assets/audio/{_seg(asset_id)}/content"
        resp = self._session.get(url, headers=self._headers(), timeout=max(float(self.cfg.timeout_s), 30.0))
        _raise_for_status(resp)
        return resp.content

    def list_asset_refs(
        self,
        *,
        character: str = "",
        emotion: str = "",
        language: str = "",
        kind: str = "ref",
    ) -> List[dict]:
        params: Dict[str, str] = {}
        if character:
            params["character"] = character
        if emotion:
            params["emotion"] = emotion
        if language:
            params["language"] = language
        if kind:
            params["kind"] = kind
        payload = self._get("/api/v2/assets/audio/refs", params=params).json() or {}
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def list_unused_assets(
        self,
        *,
        character: str = "",
        emotion: str = "",
        language: str = "",
        kind: str = "ref",
    ) -> List[dict]:
        params: Dict[str, str] = {}
        if character:
            params["character"] = character
        if emotion:
            params["emotion"] = emotion
        if language:
            params["language"] = language
        if kind:
            params["kind"] = kind
        payload = self._get("/api/v2/assets/audio/unused", params=params).json() or {}
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def cleanup_assets(self, asset_ids: List[str], *, dry_run: bool = True) -> dict:
        payload = {"asset_ids": list(asset_ids or []), "dry_run": bool(dry_run)}
        return self._post("/api/v2/assets/audio/cleanup", json=payload).json()

    # -------- synthesize --------
    def synthesize_audio(self, req: dict) -> bytes:
        payload = dict(req or {})
        payload.setdefault("response_format", "audio")
        url = self.cfg.base_url.rstrip("/") + "/api/v2/synthesize"
        resp = self._session.post(url, json=payload, headers=self._headers(), timeout=max(float(self.cfg.timeout_s), 60.0))
        _raise_for_status(resp)
        return resp.content

    def synthesize_json(self, req: dict) -> dict:
        payload = dict(req or {})
        payload["response_format"] = "json"
        return self._post("/api/v2/synthesize", json=payload).json()
