from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import sys
from types import SimpleNamespace
from urllib.parse import quote

from flask import Flask

# Allow running as script from repo root or other working dirs.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.api_v2_routes import create_v2_blueprint
from core.storage import VoicesFileStore
from core.v2.errors import AppError, coerce_exception


def _json_resp(app: Flask, payload: dict, status: int = 200):
    return app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=int(status),
        mimetype="application/json",
    )


def _json_ok(app: Flask, payload: dict, *, status: int = 200):
    return _json_resp(app, payload, status=status)


def _json_error(app: Flask, e: Exception):
    err = coerce_exception(e)
    return _json_resp(app, err.to_dict(), status=int(err.status))


def _require_noop(fn):
    return fn


class _StoreCharacterConfig:
    def __init__(self, store: VoicesFileStore):
        self._store = store

    def load_characters(self):
        self._store.reload()

    def get_character(self, name: str):
        return self._store.get_voice(name)

    def list_characters(self):
        return [v.get("name", "") for v in self._store.list_voices()]

    def get_all_characters(self):
        return self._store.list_voices()

    def upsert_character(self, voice: dict):
        self._store.upsert_voice(voice or {})

    def delete_character(self, name: str) -> bool:
        return self._store.delete_voice(name)

    def save(self):
        self._store.save()


def _make_ctx(app: Flask, cc: _StoreCharacterConfig):
    lock = threading.Lock()
    return SimpleNamespace(
        require_v2_api_key=_require_noop,
        json_ok=lambda payload, status=200: _json_ok(app, payload, status=status),
        json_error=lambda e: _json_error(app, e if isinstance(e, Exception) else AppError(code="internal_error", message=str(e), status=500)),
        AppError=AppError,
        get_character_config=lambda: cc,
        v2_get_asset=lambda _aid: None,
        # Unused by this script but required by blueprint context shape.
        V2_LOCK=lock,
        V2_MODEL_LOCK=lock,
        V2_JOB_LOCK=lock,
        V2_ASSETS=None,
        V2_JOBS={},
        api_logger=None,
        log_event=lambda *a, **k: None,
        req_id=lambda: "m4_acceptance",
        v2_save_audio_bytes=lambda *a, **k: {},
        safe_int=lambda v, d=0: int(v) if str(v).isdigit() else int(d),
        get_cosyvoice=lambda: None,
        cv3_prefix_prompt=lambda s: s,
        v2_create_job=lambda payload: {},
        v2_enqueue_job=lambda *a, **k: None,
        v2_merge_files_to_wav=lambda *a, **k: "",
    )


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_single_source_crud_check(tmp_root: str):
    voices_path = os.path.join(tmp_root, "config", "voices_v2.json")
    store = VoicesFileStore(voices_path, allow_legacy_write=False)
    cc = _StoreCharacterConfig(store)

    app = Flask("m4_single_source_crud")
    app.register_blueprint(create_v2_blueprint(_make_ctx(app, cc)), url_prefix="/api/v2")
    client = app.test_client()

    r = client.post(
        "/api/v2/voices",
        json={
            "name": "Tom#default",
            "mode": "zero_shot",
            "prompt_text": "hello",
            "prompt_audio": "demo.wav",
            "ref_asset_ids": ["ref_a"],
        },
    )
    assert r.status_code == 201, r.data

    rows = _read_json(voices_path)
    assert isinstance(rows, list) and len(rows) == 1, rows
    assert rows[0]["name"] == "Tom#default", rows
    assert rows[0]["character"] == "Tom", rows
    assert rows[0]["emotion"] == "default", rows
    assert rows[0]["selection_policy"] == "random_per_text", rows

    old_id = quote("Tom#default", safe="")
    new_id = quote("Tom#calm", safe="")

    r = client.put(f"/api/v2/voices/{old_id}", json={"name": "Tom#calm", "ref_asset_ids": "bad"})
    assert r.status_code == 200, r.data

    r = client.get(f"/api/v2/voices/{old_id}")
    assert r.status_code == 404, r.data
    r = client.get(f"/api/v2/voices/{new_id}")
    assert r.status_code == 200, r.data

    rows = _read_json(voices_path)
    by_name = {x["name"]: x for x in rows}
    assert "Tom#calm" in by_name, rows
    assert by_name["Tom#calm"]["ref_asset_ids"] == [], rows

    # Simulate restart by constructing a new store/config wrapper.
    store2 = VoicesFileStore(voices_path, allow_legacy_write=False)
    cc2 = _StoreCharacterConfig(store2)
    assert cc2.get_character("Tom#calm") is not None

    r = client.post("/api/v2/voices/reload")
    assert r.status_code == 200, r.data
    assert int((r.get_json() or {}).get("count") or 0) == 1, r.data

    r = client.delete(f"/api/v2/voices/{new_id}")
    assert r.status_code == 200, r.data

    rows = _read_json(voices_path)
    assert rows == [], rows


def _run_legacy_write_protection_check(tmp_root: str):
    legacy_path = os.path.join(tmp_root, "config", "config.json")
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

    cc = _StoreCharacterConfig(VoicesFileStore(legacy_path, allow_legacy_write=False))
    app = Flask("m4_legacy_protection")
    app.register_blueprint(create_v2_blueprint(_make_ctx(app, cc)), url_prefix="/api/v2")
    client = app.test_client()

    r = client.post("/api/v2/voices", json={"name": "Blocked#default"})
    assert r.status_code == 500, r.data
    body = r.get_json() or {}
    err = body.get("error") or {}
    msg = str(err.get("message") or "")
    assert "legacy voices file is read-only" in msg, body


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="m4_acceptance_")
    try:
        _run_single_source_crud_check(tmp)
        _run_legacy_write_protection_check(tmp)
        print("M4 final acceptance test: OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
