from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional


LEGACY_VOICE_BASENAMES = {"config.json", "voice_config.json"}


class VoicesFileStore:
    """
    Thread-safe JSON-backed voices store with atomic persistence.

    Runtime single source of truth:
    - one v2 voices json file
    - legacy files are read-only import sources
    """

    def __init__(self, file_path: str, *, allow_legacy_write: bool = False):
        self.file_path = os.path.abspath(file_path or "")
        self.allow_legacy_write = bool(allow_legacy_write)
        self._lock = threading.RLock()
        self._voices: Dict[str, dict] = {}
        self.reload()

    @staticmethod
    def is_legacy_voice_path(path: str) -> bool:
        p = os.path.normcase(os.path.abspath(path or ""))
        base = os.path.basename(p).lower()
        if base not in LEGACY_VOICE_BASENAMES:
            return False
        return f"{os.sep}config{os.sep}" in p

    def _assert_writable_target(self) -> None:
        if self.allow_legacy_write:
            return
        if self.is_legacy_voice_path(self.file_path):
            raise RuntimeError(
                f"legacy voices file is read-only at runtime: {self.file_path}; "
                "use v2_voices_config_path and legacy import tools instead"
            )

    @staticmethod
    def _safe_str(v: Any) -> str:
        return str(v or "").strip()

    @classmethod
    def normalize_voice(cls, voice: dict) -> dict:
        if not isinstance(voice, dict):
            raise ValueError("voice must be a dict")

        out = dict(voice)
        name = cls._safe_str(out.get("name") or out.get("voice_id"))
        character = cls._safe_str(out.get("character"))
        emotion = cls._safe_str(out.get("emotion")) or "default"

        if not name:
            if character:
                name = f"{character}#{emotion}"
            else:
                raise ValueError("voice.name is required")

        if "#" in name:
            ch, emo = name.split("#", 1)
            character = cls._safe_str(ch) or character
            emotion = cls._safe_str(emo) or emotion or "default"
            name = f"{character}#{emotion}" if character else name
        else:
            character = character or name
            emotion = emotion or "default"
            name = f"{character}#{emotion}"

        out["name"] = name
        out["character"] = character
        out["emotion"] = emotion

        if not cls._safe_str(out.get("selection_policy")):
            out["selection_policy"] = "random_per_text"

        ref_ids = out.get("ref_asset_ids")
        if not isinstance(ref_ids, list):
            out["ref_asset_ids"] = []
        else:
            out["ref_asset_ids"] = [cls._safe_str(x) for x in ref_ids if cls._safe_str(x)]

        out.setdefault("mode", "")
        out.setdefault("prompt_text", "")
        out.setdefault("prompt_audio", "")
        out.setdefault("instruct_text", "")
        out.setdefault("color", "#FF6B6B")
        return out

    def _load_raw(self) -> List[dict]:
        if not self.file_path:
            return []
        if not os.path.exists(self.file_path):
            return []
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    def reload(self) -> None:
        with self._lock:
            loaded: Dict[str, dict] = {}
            rows = self._load_raw()
            for row in rows:
                try:
                    voice = self.normalize_voice(row)
                except Exception:
                    continue
                loaded[voice["name"]] = voice
            self._voices = loaded

    def list_voices(self) -> List[dict]:
        with self._lock:
            items = [dict(v) for v in self._voices.values()]
        items.sort(key=lambda x: self._safe_str(x.get("name")))
        return items

    def get_voice(self, voice_id: str) -> Optional[dict]:
        key = self._safe_str(voice_id)
        with self._lock:
            v = self._voices.get(key)
            return dict(v) if isinstance(v, dict) else None

    def upsert_voice(self, voice: dict) -> dict:
        self._assert_writable_target()
        normalized = self.normalize_voice(voice)
        with self._lock:
            self._voices[normalized["name"]] = dict(normalized)
        return dict(normalized)

    def delete_voice(self, voice_id: str) -> bool:
        self._assert_writable_target()
        key = self._safe_str(voice_id)
        with self._lock:
            if key in self._voices:
                del self._voices[key]
                return True
            return False

    def _write_json_atomic(self, payload: list) -> None:
        os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
        tmp = f"{self.file_path}.tmp_{uuid.uuid4().hex[:8]}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.file_path)

    def save(self) -> None:
        self._assert_writable_target()
        with self._lock:
            payload = [dict(v) for v in self._voices.values()]
        payload.sort(key=lambda x: self._safe_str(x.get("name")))
        self._write_json_atomic(payload)
