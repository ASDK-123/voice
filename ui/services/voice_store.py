import os
import json
import uuid
from typing import List, Optional

from core.config_manager import ConfigManager
from core.storage import VoicesFileStore


class VoiceStore:
    """
    UI-side helper for v2 voices single-source file.

    The source of truth is one JSON file pointed by app config key
    `v2_voices_config_path`.
    """

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def voices_path(self, path: Optional[str] = None) -> str:
        p = (path or "").strip()
        if not p:
            try:
                p = str(self.config_manager.get("v2_voices_config_path", "") or "").strip()
            except Exception:
                p = ""
        if not p:
            p = os.path.abspath("./config/voices_v2.json")
        return os.path.abspath(p)

    def list_voices(self, *, path: Optional[str] = None) -> List[dict]:
        target_path = self.voices_path(path)
        if not os.path.exists(target_path):
            return []
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if isinstance(data, dict):
            rows = [data]
        elif isinstance(data, list):
            rows = [x for x in data if isinstance(x, dict)]
        else:
            rows = []

        order: List[str] = []
        by_name = {}
        for row in rows:
            try:
                normalized = VoicesFileStore.normalize_voice(row)
            except Exception:
                continue
            name = str(normalized.get("name") or "").strip()
            if not name:
                continue
            if name not in by_name:
                order.append(name)
            by_name[name] = normalized
        return [dict(by_name[name]) for name in order if name in by_name]

    def get_voice(self, voice_id: str, *, path: Optional[str] = None) -> Optional[dict]:
        target = str(voice_id or "").strip()
        if not target:
            return None
        for row in self.list_voices(path=path):
            if str((row or {}).get("name") or "").strip() == target:
                return dict(row)
        return None

    def save_rows(self, rows: List[dict], *, path: Optional[str] = None) -> List[dict]:
        """
        Replace all rows in target voices file atomically, preserving incoming order.
        """
        target_path = self.voices_path(path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        incoming = [r for r in (rows or []) if isinstance(r, dict)]
        order: List[str] = []
        by_name = {}

        for row in incoming:
            try:
                saved = VoicesFileStore.normalize_voice(row)
            except Exception:
                continue
            name = str(saved.get("name") or "").strip()
            if not name:
                continue
            if name not in by_name:
                order.append(name)
            by_name[name] = saved

        payload = [dict(by_name[name]) for name in order if name in by_name]
        tmp = f"{target_path}.tmp_{uuid.uuid4().hex[:8]}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, target_path)

        return payload

    def upsert_voice(self, voice: dict, *, path: Optional[str] = None) -> dict:
        saved = VoicesFileStore.normalize_voice(voice or {})
        rows = self.list_voices(path=path)
        target = str(saved.get("name") or "").strip()
        found = False
        out: List[dict] = []
        for row in rows:
            name = str((row or {}).get("name") or "").strip()
            if name == target:
                out.append(dict(saved))
                found = True
            else:
                out.append(dict(row))
        if not found:
            out.append(dict(saved))
        self.save_rows(out, path=path)
        return dict(saved)

    def delete_voice(self, voice_id: str, *, path: Optional[str] = None) -> bool:
        target = str(voice_id or "").strip()
        if not target:
            return False
        rows = self.list_voices(path=path)
        out = [dict(r) for r in rows if str((r or {}).get("name") or "").strip() != target]
        if len(out) == len(rows):
            return False
        self.save_rows(out, path=path)
        return True
