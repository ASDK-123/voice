from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Optional

from flask import Flask

# Allow running as a script from repo root or other working dirs.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.api_v2_routes import create_v2_blueprint
from core.v2.assets_sqlite import AssetsSqliteStore
from core.v2.errors import AppError, coerce_exception


def _json_resp(app: Flask, payload: dict, status: int = 200):
    return app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=int(status),
        mimetype="application/json",
    )


def _json_ok(app: Flask, payload: dict, *, status: int = 200):
    return _json_resp(app, payload, status)


def _json_error(app: Flask, e: Exception):
    err = coerce_exception(e)
    payload = err.to_dict()
    return _json_resp(app, payload, int(err.status))


def _require_noop(fn):
    return fn


@dataclass
class _DummyCC:
    voices: list[dict[str, Any]]

    def get_all_characters(self) -> list:
        return list(self.voices or [])


def _make_asset_file(root: str, name: str, content: bytes) -> str:
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, name)
    with open(p, "wb") as f:
        f.write(content)
    return p


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="p2_backend_test_")
    try:
        data_root = os.path.join(tmp, "data")
        assets_dir = os.path.join(data_root, "assets", "audio")
        os.makedirs(assets_dir, exist_ok=True)
        db_path = os.path.join(data_root, "api_v2_assets.sqlite3")

        store = AssetsSqliteStore(db_path)

        # Assets: 1 used(ref), 1 unused(ref), 1 non-ref(output)
        used_path = _make_asset_file(assets_dir, "used1.wav", b"RIFF....WAVE")
        unused_path = _make_asset_file(assets_dir, "unused1.wav", b"RIFF....WAVE")
        out_path = _make_asset_file(assets_dir, "out1.wav", b"RIFF....WAVE")

        now = int(time.time())
        store.upsert(
            {
                "asset_id": "used1",
                "kind": "ref",
                "filename": "used1.wav",
                "path": used_path,
                "size": os.path.getsize(used_path),
                "created_at": now,
                "character": "Tom",
                "emotion": "default",
                "language": "zh",
                "note": "used",
                "linked": True,
            }
        )
        store.upsert(
            {
                "asset_id": "unused1",
                "kind": "ref",
                "filename": "unused1.wav",
                "path": unused_path,
                "size": os.path.getsize(unused_path),
                "created_at": now,
                "character": "Tom",
                "emotion": "happy",
                "language": "zh",
                "note": "unused",
                "linked": False,
            }
        )
        store.upsert(
            {
                "asset_id": "out1",
                "kind": "output",
                "filename": "out1.wav",
                "path": out_path,
                "size": os.path.getsize(out_path),
                "created_at": now,
                "character": "Tom",
                "emotion": "default",
                "language": "zh",
                "note": "output",
                "linked": False,
            }
        )

        # Voices: reference used1 by asset id and by prompt_audio path
        cc = _DummyCC(
            voices=[
                {"name": "Tom#default", "ref_asset_ids": ["used1"]},
                {"name": "Tom#alt", "prompt_audio": used_path},
            ]
        )

        app = Flask("p2_backend_test")
        lock = threading.Lock()

        ctx = SimpleNamespace(
            require_v2_api_key=_require_noop,
            json_ok=lambda payload, status=200: _json_ok(app, payload, status=status),
            json_error=lambda e: _json_error(app, e if isinstance(e, Exception) else AppError(code="internal_error", message=str(e), status=500)),
            AppError=AppError,
            api_logger=None,
            log_event=lambda *a, **k: None,
            req_id=lambda: "test_rid",
            V2_LOCK=lock,
            V2_MODEL_LOCK=lock,
            V2_JOB_LOCK=lock,
            V2_ASSETS=store,
            V2_JOBS=None,
            v2_get_asset=store.get,
            v2_save_audio_bytes=lambda *a, **k: {},
            safe_int=lambda v, d=0: int(v) if str(v).isdigit() else int(d),
            get_cosyvoice=lambda: None,
            get_character_config=lambda: cc,
            cv3_prefix_prompt=lambda s: s,
            v2_create_job=lambda payload: {},
            v2_enqueue_job=lambda *a, **k: None,
            v2_merge_files_to_wav=lambda *a, **k: "",
        )

        bp = create_v2_blueprint(ctx)
        app.register_blueprint(bp, url_prefix="/api/v2")

        client = app.test_client()

        # 1) unused should include only unused1 (ref), exclude used1 and out1
        r = client.get("/api/v2/assets/audio/unused")
        assert r.status_code == 200, r.data
        items = (r.get_json() or {}).get("items") or []
        got = sorted([x.get("asset_id") for x in items])
        assert got == ["unused1"], got

        # 1.1) list assets should compute linked/ref_count dynamically
        r = client.get("/api/v2/assets/audio?character=Tom")
        assert r.status_code == 200, r.data
        items = (r.get_json() or {}).get("items") or []
        by = {x.get("asset_id"): x for x in items}
        assert bool(by["used1"].get("linked")) is True, by["used1"]
        assert int(by["used1"].get("ref_count") or 0) == 2, by["used1"]
        assert bool(by["unused1"].get("linked")) is False, by["unused1"]
        assert int(by["unused1"].get("ref_count") or 0) == 0, by["unused1"]

        # 2) refs: used1 should be referenced by 2 voices; unused1 ref_count=0
        r = client.get("/api/v2/assets/audio/refs")
        assert r.status_code == 200, r.data
        items = (r.get_json() or {}).get("items") or []
        by = {x.get("asset_id"): x for x in items}
        assert int(by["used1"].get("ref_count") or 0) == 2, by["used1"]
        assert int(by["unused1"].get("ref_count") or 0) == 0, by["unused1"]

        # 2.1) update asset meta (note/transcript_text)
        r = client.put("/api/v2/assets/audio/unused1", json={"note": "unused_v2", "transcript_text": "prompt_for_unused"})
        assert r.status_code == 200, r.data
        meta = store.get("unused1") or {}
        assert meta.get("note") == "unused_v2", meta
        assert meta.get("transcript_text") == "prompt_for_unused", meta

        # 2.2) note update must not alter transcript_text semantics
        r = client.put("/api/v2/assets/audio/unused1", json={"note": "unused_v3"})
        assert r.status_code == 200, r.data
        meta = store.get("unused1") or {}
        assert meta.get("note") == "unused_v3", meta
        assert meta.get("transcript_text") == "prompt_for_unused", meta

        # 3) cleanup dry-run: unused1 deletable, used1 skipped
        r = client.post("/api/v2/assets/audio/cleanup", json={"asset_ids": ["unused1", "used1"], "dry_run": True})
        assert r.status_code == 200, r.data
        j = r.get_json() or {}
        assert j.get("dry_run") is True
        assert int(j.get("deleted") or 0) == 1, j
        skipped = j.get("skipped") or []
        assert any(x.get("asset_id") == "used1" and x.get("reason") == "still_referenced" for x in skipped), skipped

        # 4) cleanup real: unused1 removed from sqlite and file deleted
        r = client.post("/api/v2/assets/audio/cleanup", json={"asset_ids": ["unused1"], "dry_run": False})
        assert r.status_code == 200, r.data
        assert store.get("unused1") is None
        assert not os.path.exists(unused_path)

        # 5) unused now empty
        r = client.get("/api/v2/assets/audio/unused")
        assert r.status_code == 200, r.data
        items = (r.get_json() or {}).get("items") or []
        assert items == [], items

        print("P2 backend acceptance test: OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
