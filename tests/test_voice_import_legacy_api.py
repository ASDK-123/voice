from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace

from flask import Flask, request

from core.api_v2_routes import create_v2_blueprint
from core.v2.assets_sqlite import AssetsSqliteStore
from core.v2.errors import AppError, coerce_exception


class _FileBackedCC:
    def __init__(self, config_file: str):
        self.config_file = os.path.abspath(config_file)
        self.characters: dict[str, dict] = {}
        self.load_characters()

    def load_characters(self):
        self.characters = {}
        if not os.path.exists(self.config_file):
            return
        with open(self.config_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("voices config must be a JSON list")
        for row in data:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                self.characters[name] = dict(row)

    def get_all_characters(self) -> list[dict]:
        return [dict(v) for v in self.characters.values()]

    def get_character(self, name: str):
        row = self.characters.get(str(name or "").strip())
        return dict(row) if isinstance(row, dict) else None

    def list_characters(self):
        return sorted(self.characters.keys())

    def upsert_character(self, voice: dict):
        name = str((voice or {}).get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        self.characters[name] = dict(voice)
        return True

    def delete_character(self, name: str):
        return self.characters.pop(str(name or "").strip(), None) is not None

    def save(self):
        rows = list(self.characters.values())
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)


class TestVoiceImportLegacyApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_voice_import_legacy_")
        self.assets_dir = os.path.join(self.tmp, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)
        self.db_path = os.path.join(self.tmp, "assets.sqlite3")
        self.voices_path = os.path.join(self.tmp, "voices_v2.json")
        self.required_api_key = ""
        self.store = AssetsSqliteStore(self.db_path)
        self.cc = _FileBackedCC(self.voices_path)
        app = Flask("test_voice_import_legacy")
        lock = threading.Lock()

        def _json_ok(payload: dict, status: int = 200):
            return app.response_class(
                response=json.dumps(payload, ensure_ascii=False),
                status=int(status),
                mimetype="application/json",
            )

        def _json_error(e: Exception):
            err = coerce_exception(e)
            return app.response_class(
                response=json.dumps(err.to_dict(), ensure_ascii=False),
                status=int(err.status),
                mimetype="application/json",
            )

        def _require(fn):
            def _wrapped(*args, **kwargs):
                if not self.required_api_key:
                    return fn(*args, **kwargs)
                provided = request.headers.get("X-API-Key", "").strip()
                if provided != self.required_api_key:
                    return _json_error(AppError(code="unauthorized", message="unauthorized", status=401))
                return fn(*args, **kwargs)

            _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
            return _wrapped

        self.ctx = SimpleNamespace(
            require_v2_api_key=_require,
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
            v2_voices_config_path=self.voices_path,
            v2_assets_db_path=self.db_path,
            v2_assets_dir=self.assets_dir,
        )
        app.register_blueprint(create_v2_blueprint(self.ctx), url_prefix="/api/v2")
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post_import(self, payload: list[dict], *, dry_run: bool, filename: str = "legacy.json", headers: dict | None = None):
        body = {
            "file": (io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), filename),
            "dry_run": "1" if dry_run else "0",
            "default_language": "zh",
            "create_emotion": "default",
            "selection_policy": "random_per_text",
        }
        return self.client.post(
            "/api/v2/voices/import-legacy",
            data=body,
            content_type="multipart/form-data",
            headers=headers or {},
        )

    def test_dry_run_returns_summary_without_writing_v2_data(self):
        audio_path = os.path.join(self.tmp, "legacy_ref.wav")
        with open(audio_path, "wb") as fh:
            fh.write(b"RIFF....WAVE")
        resp = self._post_import(
            [
                {
                    "name": "Alice",
                    "mode": "zero_shot",
                    "prompt_text": "你好",
                    "prompt_audio": audio_path,
                }
            ],
            dry_run=True,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        self.assertTrue(body.get("dry_run"))
        self.assertEqual(body.get("imported_voices"), 1)
        self.assertEqual(body.get("imported_assets"), 1)
        self.assertFalse(os.path.exists(self.voices_path))
        self.assertEqual(self.cc.list_characters(), [])
        self.assertEqual(self.store.list(), [])

    def test_execute_import_updates_voices_and_assets(self):
        audio_path = os.path.join(self.tmp, "legacy_ref.wav")
        with open(audio_path, "wb") as fh:
            fh.write(b"RIFF....WAVE")
        resp = self._post_import(
            [
                {
                    "name": "Alice",
                    "mode": "zero_shot",
                    "prompt_text": "你好",
                    "prompt_audio": audio_path,
                    "color": "#FF6600",
                }
            ],
            dry_run=False,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        self.assertFalse(body.get("dry_run"))
        self.assertEqual(body.get("imported_voices"), 1)
        self.assertEqual(body.get("imported_assets"), 1)
        self.cc.load_characters()
        self.assertIn("Alice#default", self.cc.list_characters())
        self.assertTrue(os.path.exists(self.voices_path))
        with open(self.voices_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual(rows[0]["name"], "Alice#default")
        self.assertEqual(len(self.store.list()), 1)
        asset = self.store.list()[0]
        self.assertTrue(os.path.exists(asset["path"]))

    def test_missing_prompt_audio_counts_as_skipped_asset(self):
        resp = self._post_import(
            [
                {
                    "name": "Bob",
                    "mode": "zero_shot",
                    "prompt_text": "你好",
                    "prompt_audio": os.path.join(self.tmp, "missing.wav"),
                }
            ],
            dry_run=False,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        self.assertEqual(body.get("imported_voices"), 1)
        self.assertEqual(body.get("imported_assets"), 0)
        self.assertEqual(body.get("skipped_assets"), 1)

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            "/api/v2/voices/import-legacy",
            data={
                "file": (io.BytesIO(b"{not json"), "legacy.json"),
                "dry_run": "1",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_non_list_json_returns_400(self):
        resp = self.client.post(
            "/api/v2/voices/import-legacy",
            data={
                "file": (io.BytesIO(json.dumps({"name": "bad"}).encode("utf-8")), "legacy.json"),
                "dry_run": "1",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_api_key_protects_import_endpoint(self):
        self.required_api_key = "secret"
        resp = self._post_import([], dry_run=True)
        self.assertEqual(resp.status_code, 401, resp.data)
        ok = self._post_import([], dry_run=True, headers={"X-API-Key": "secret"})
        self.assertEqual(ok.status_code, 200, ok.data)


if __name__ == "__main__":
    unittest.main()
