from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Iterable, Optional


SCHEMA_VERSION = 1


class AssetsSqliteStore:
    """
    Simple SQLite-backed store for v2 assets metadata.

    - One row per asset_id.
    - File content still lives on disk (data/assets/audio/*).
    """

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                  asset_id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  filename TEXT,
                  path TEXT NOT NULL,
                  size INTEGER NOT NULL,
                  sha1 TEXT,
                  created_at INTEGER NOT NULL,
                  character TEXT,
                  emotion TEXT,
                  language TEXT,
                  note TEXT,
                  linked INTEGER,
                  meta_json TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                  k TEXT PRIMARY KEY,
                  v TEXT NOT NULL
                )
                """
            )
            con.execute(
                "INSERT OR IGNORE INTO meta(k, v) VALUES(?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def upsert(self, meta: dict[str, Any]) -> None:
        now = int(time.time())
        row = dict(meta or {})
        asset_id = (row.get("asset_id") or "").strip()
        if not asset_id:
            raise ValueError("asset_id is required")
        kind = (row.get("kind") or "").strip() or "ref"
        path = (row.get("path") or "").strip()
        if not path:
            raise ValueError("path is required")
        size = int(row.get("size") or 0)
        created_at = int(row.get("created_at") or now)

        # Keep extra fields in meta_json for forward compatibility.
        known = {
            "asset_id",
            "kind",
            "filename",
            "path",
            "size",
            "sha1",
            "created_at",
            "character",
            "emotion",
            "language",
            "note",
            "linked",
        }
        extra = {k: v for k, v in row.items() if k not in known}

        with self._connect() as con:
            con.execute(
                """
                INSERT INTO assets(
                  asset_id, kind, filename, path, size, sha1, created_at,
                  character, emotion, language, note, linked, meta_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                  kind=excluded.kind,
                  filename=excluded.filename,
                  path=excluded.path,
                  size=excluded.size,
                  sha1=excluded.sha1,
                  created_at=excluded.created_at,
                  character=excluded.character,
                  emotion=excluded.emotion,
                  language=excluded.language,
                  note=excluded.note,
                  linked=excluded.linked,
                  meta_json=excluded.meta_json
                """,
                (
                    asset_id,
                    kind,
                    row.get("filename"),
                    path,
                    size,
                    row.get("sha1"),
                    created_at,
                    row.get("character"),
                    row.get("emotion"),
                    row.get("language"),
                    row.get("note"),
                    1 if row.get("linked") else 0,
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                ),
            )

    def get(self, asset_id: str) -> Optional[dict[str, Any]]:
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return None
        with self._connect() as con:
            cur = con.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,))
            r = cur.fetchone()
        if not r:
            return None
        d = dict(r)
        extra = {}
        try:
            if d.get("meta_json"):
                extra = json.loads(d["meta_json"])
        except Exception:
            extra = {}
        d.pop("meta_json", None)
        d["linked"] = bool(d.get("linked"))
        d.update(extra or {})
        return d

    def delete(self, asset_id: str) -> bool:
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return False
        with self._connect() as con:
            cur = con.execute("DELETE FROM assets WHERE asset_id=?", (asset_id,))
            return cur.rowcount > 0

    def list(
        self,
        *,
        character: str = "",
        emotion: str = "",
        language: str = "",
        kind: str = "",
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        wh = []
        args: list[Any] = []
        if character:
            wh.append("character=?")
            args.append(character)
        if emotion:
            wh.append("emotion=?")
            args.append(emotion)
        if language:
            wh.append("language=?")
            args.append(language)
        if kind:
            wh.append("kind=?")
            args.append(kind)
        where = (" WHERE " + " AND ".join(wh)) if wh else ""
        sql = f"SELECT * FROM assets{where} ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as con:
            rows = con.execute(sql, args).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            extra = {}
            try:
                if d.get("meta_json"):
                    extra = json.loads(d["meta_json"])
            except Exception:
                extra = {}
            d.pop("meta_json", None)
            d["linked"] = bool(d.get("linked"))
            d.update(extra or {})
            out.append(d)
        return out

    def migrate_from_json_index(self, json_path: str) -> int:
        """
        Migrate legacy JSON index (data/api_v2_assets.json) into SQLite.
        Returns number of rows upserted.
        """
        if not json_path or not os.path.exists(json_path):
            return 0
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
        n = 0
        for _aid, meta in data.items():
            if not isinstance(meta, dict):
                continue
            try:
                self.upsert(meta)
                n += 1
            except Exception:
                continue
        return n

