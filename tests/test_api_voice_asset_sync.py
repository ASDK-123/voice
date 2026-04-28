from __future__ import annotations

import os
import json
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.parse import quote

from flask import Flask

from core.api_v2_routes import create_v2_blueprint
from core.v2.assets_sqlite import AssetsSqliteStore
from core.v2.errors import AppError, coerce_exception


class _DummyCC:
    def __init__(self, voices: list[dict] | None = None):
        self._voices: dict[str, dict] = {}
        for v in voices or []:
            name = str(v.get("name") or "").strip()
            if name:
                self._voices[name] = dict(v)

    def get_all_characters(self) -> list[dict]:
        return [dict(v) for v in self._voices.values()]

    def get_character(self, name: str):
        v = self._voices.get(str(name or "").strip())
        return dict(v) if isinstance(v, dict) else None

    def upsert_character(self, voice: dict):
        name = str((voice or {}).get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        self._voices[name] = dict(voice)
        return True

    def delete_character(self, name: str):
        return self._voices.pop(str(name or "").strip(), None) is not None

    def save(self):
        return None

    def load_characters(self):
        return None

    def list_characters(self):
        return sorted(self._voices.keys())


class TestApiVoiceAssetSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_api_voice_asset_sync_")
        self.assets_dir = os.path.join(self.tmp, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)
        self.db_path = os.path.join(self.tmp, "assets.sqlite3")
        self.store = AssetsSqliteStore(self.db_path)
        self.cc = _DummyCC([])

        app = Flask("test_api_voice_asset_sync")
        lock = threading.Lock()

        def _json_ok(payload: dict, status: int = 200):
            return app.response_class(response=json.dumps(payload, ensure_ascii=False), status=int(status), mimetype="application/json")

        def _json_error(e: Exception):
            err = coerce_exception(e)
            return app.response_class(response=json.dumps(err.to_dict(), ensure_ascii=False), status=int(err.status), mimetype="application/json")

        self.ctx = SimpleNamespace(
            require_v2_api_key=lambda fn: fn,
            json_ok=_json_ok,
            json_error=lambda e: _json_error(e if isinstance(e, Exception) else AppError(code="internal_error", message=str(e), status=500)),
            AppError=AppError,
            api_logger=None,
            log_event=lambda *a, **k: None,
            req_id=lambda: "rid_test",
            V2_LOCK=lock,
            V2_MODEL_LOCK=lock,
            V2_JOB_LOCK=lock,
            V2_ASSETS=self.store,
            V2_JOBS=None,
            v2_get_asset=self.store.get,
            v2_save_audio_bytes=lambda *a, **k: {},
            safe_int=lambda v, d=0: int(v) if str(v).isdigit() else int(d),
            get_cosyvoice=lambda: None,
            get_character_config=lambda: self.cc,
            cv3_prefix_prompt=lambda s: s,
            v2_create_job=lambda payload: {},
            v2_enqueue_job=lambda *a, **k: None,
            v2_merge_files_to_wav=lambda *a, **k: "",
        )
        app.register_blueprint(create_v2_blueprint(self.ctx), url_prefix="/api/v2")
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _upsert_asset(self, asset_id: str, transcript_text: str = "", prompt_text: str = ""):
        now = int(time.time())
        path = os.path.join(self.assets_dir, f"{asset_id}.wav")
        with open(path, "wb") as f:
            f.write(b"RIFF....WAVE")
        self.store.upsert(
            {
                "asset_id": asset_id,
                "kind": "ref",
                "filename": f"{asset_id}.wav",
                "path": path,
                "size": os.path.getsize(path),
                "created_at": now,
                "character": "Tom",
                "emotion": "default",
                "language": "zh",
                "transcript_text": transcript_text,
                "prompt_text": prompt_text,
                "linked": False,
            }
        )

    def test_create_voice_applies_asset_mirror_when_not_shared(self):
        self._upsert_asset("a1", transcript_text="", prompt_text="")

        payload = {
            "name": "Tom#default",
            "character": "Tom",
            "emotion": "default",
            "mode": "参考音色",
            "prompt_text": "hello_from_voice",
            "prompt_audio_asset_id": "a1",
            "ref_asset_ids": ["a1"],
        }
        r = self.client.post("/api/v2/voices", json=payload)
        self.assertEqual(r.status_code, 201, r.data)
        body = r.get_json() or {}
        sync = body.get("asset_transcript_sync") or {}
        self.assertEqual(sync.get("status"), "applied", sync)
        self.assertEqual(sync.get("asset_id"), "a1", sync)

        meta = self.store.get("a1") or {}
        self.assertEqual(meta.get("transcript_text"), "hello_from_voice", meta)
        self.assertEqual(meta.get("prompt_text"), "hello_from_voice", meta)

    def test_update_voice_skips_shared_asset_sync(self):
        self._upsert_asset("shared1", transcript_text="keep_me", prompt_text="keep_me")
        self.cc = _DummyCC(
            [
                {
                    "name": "Tom#default",
                    "character": "Tom",
                    "emotion": "default",
                    "prompt_text": "old_prompt",
                    "prompt_audio_asset_id": "shared1",
                    "ref_asset_ids": ["shared1"],
                },
                {
                    "name": "Tom#happy",
                    "character": "Tom",
                    "emotion": "happy",
                    "prompt_text": "another_prompt",
                    "prompt_audio_asset_id": "shared1",
                    "ref_asset_ids": ["shared1"],
                },
            ]
        )

        voice_id = quote("Tom#default", safe="")
        r = self.client.put(f"/api/v2/voices/{voice_id}", json={"prompt_text": "new_prompt"})
        self.assertEqual(r.status_code, 200, r.data)
        body = r.get_json() or {}
        sync = body.get("asset_transcript_sync") or {}
        self.assertEqual(sync.get("status"), "skipped_shared", sync)
        self.assertEqual(sync.get("asset_id"), "shared1", sync)

        meta = self.store.get("shared1") or {}
        self.assertEqual(meta.get("transcript_text"), "keep_me", meta)
        self.assertEqual(meta.get("prompt_text"), "keep_me", meta)


if __name__ == "__main__":
    unittest.main()
