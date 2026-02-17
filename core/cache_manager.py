from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class CacheRecord:
    request_hash: str
    path: str
    size_bytes: int
    created_at: int
    last_access: int
    meta: dict


class CacheManager:
    """
    Disk-backed LRU cache for generated WAVs.

    - Stores audio at: {root}/audio/{request_hash}.wav
    - Stores index at: {root}/index.json
    - Enforces size cap with LRU (by last_access).
    - Supports in-flight de-dup to prevent duplicate generation.
    """

    def __init__(self, root_dir: str, max_bytes: int, index_backend: Optional[str] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.audio_dir = os.path.join(self.root_dir, "audio")
        self.index_path = os.path.join(self.root_dir, "index.json")
        self.db_path = os.path.join(self.root_dir, "index.sqlite3")
        self.max_bytes = int(max_bytes)

        os.makedirs(self.audio_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._index: Dict[str, dict] = {}
        self._total_bytes = 0
        self._inflight: Dict[str, threading.Event] = {}

        backend = (index_backend or os.getenv("CACHE_INDEX_BACKEND", "sqlite") or "sqlite").strip().lower()
        self._backend = backend if backend in {"json", "sqlite"} else "sqlite"
        self._db: Optional[sqlite3.Connection] = None
        self._dirty: set[str] = set()
        self._deleted: set[str] = set()

        self._load_index()

    def _ensure_sqlite_locked(self) -> None:
        if self._backend != "sqlite":
            return
        if self._db is not None:
            return
        os.makedirs(self.root_dir, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("PRAGMA temp_store=MEMORY;")
            con.execute("PRAGMA foreign_keys=ON;")
            con.execute("PRAGMA busy_timeout=30000;")
        except Exception:
            pass
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                request_hash TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_access INTEGER NOT NULL,
                meta_json TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_cache_last_access ON cache_entries(last_access)")
        self._db = con

    def _sqlite_count_locked(self) -> int:
        if self._db is None:
            return 0
        try:
            row = self._db.execute("SELECT COUNT(1) AS c FROM cache_entries").fetchone()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    def _sqlite_import_json_once_locked(self) -> None:
        """
        Best-effort import from legacy index.json if sqlite is empty.

        - Keeps index.json in place (non-destructive).
        - Skips missing files.
        """
        if self._backend != "sqlite":
            return
        if not os.path.exists(self.index_path):
            return
        if self._db is None:
            return
        if self._sqlite_count_locked() > 0:
            return

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return

        now = int(time.time())
        try:
            cur = self._db.cursor()
            cur.execute("BEGIN")
            for k, rec in data.items():
                if not isinstance(rec, dict):
                    continue
                request_hash = str(rec.get("request_hash") or k or "").strip()
                if not request_hash:
                    continue
                p = str(rec.get("path") or "").strip()
                if not p or not os.path.exists(p):
                    continue
                try:
                    sz = int(os.path.getsize(p))
                except Exception:
                    continue
                created_at = int(rec.get("created_at") or now)
                last_access = int(rec.get("last_access") or created_at or now)
                meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
                meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
                cur.execute(
                    """
                    INSERT OR REPLACE INTO cache_entries
                    (request_hash, path, size_bytes, created_at, last_access, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (request_hash, p, sz, created_at, last_access, meta_json),
                )
            cur.execute("COMMIT")
        except Exception:
            try:
                self._db.execute("ROLLBACK")
            except Exception:
                pass

    def _load_index(self):
        with self._lock:
            self._index = {}
            self._total_bytes = 0

            if self._backend == "sqlite":
                try:
                    self._ensure_sqlite_locked()
                except Exception:
                    # Fail open to json for maximum compatibility.
                    self._backend = "json"
                    self._db = None

            if self._backend == "sqlite" and self._db is not None:
                self._sqlite_import_json_once_locked()
                total = 0
                stale: list[str] = []
                try:
                    rows = self._db.execute(
                        "SELECT request_hash, path, size_bytes, created_at, last_access, meta_json FROM cache_entries"
                    ).fetchall()
                except Exception:
                    rows = []
                for row in rows:
                    request_hash = str(row["request_hash"])
                    p = str(row["path"] or "")
                    if not p or not os.path.exists(p):
                        stale.append(request_hash)
                        continue
                    try:
                        sz = int(os.path.getsize(p))
                    except Exception:
                        stale.append(request_hash)
                        continue
                    meta_json = str(row["meta_json"] or "{}")
                    try:
                        meta = json.loads(meta_json) if meta_json else {}
                    except Exception:
                        meta = {}
                    rec = {
                        "request_hash": request_hash,
                        "path": p,
                        "size_bytes": sz,
                        "created_at": int(row["created_at"] or 0),
                        "last_access": int(row["last_access"] or 0),
                        "meta": meta if isinstance(meta, dict) else {},
                    }
                    self._index[request_hash] = rec
                    total += sz
                self._total_bytes = total
                if stale:
                    try:
                        cur = self._db.cursor()
                        cur.execute("BEGIN")
                        for k in stale:
                            cur.execute("DELETE FROM cache_entries WHERE request_hash = ?", (k,))
                        cur.execute("COMMIT")
                    except Exception:
                        try:
                            self._db.execute("ROLLBACK")
                        except Exception:
                            pass
                return

            # json backend
            if not os.path.exists(self.index_path):
                return
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._index = data
                # Recompute total based on existing files (index may be stale).
                total = 0
                for k, rec in list(self._index.items()):
                    p = rec.get("path", "")
                    if not p or not os.path.exists(p):
                        self._index.pop(k, None)
                        continue
                    try:
                        sz = int(os.path.getsize(p))
                    except Exception:
                        self._index.pop(k, None)
                        continue
                    rec["size_bytes"] = sz
                    total += sz
                self._total_bytes = total
            except Exception:
                # Corrupt index: treat as empty (best-effort).
                self._index = {}
                self._total_bytes = 0

    def _save_index_locked(self):
        os.makedirs(self.root_dir, exist_ok=True)
        if self._backend == "sqlite":
            self._ensure_sqlite_locked()
            if self._db is None:
                return
            if not self._dirty and not self._deleted:
                return
            dirty = list(self._dirty)
            deleted = list(self._deleted)
            self._dirty.clear()
            self._deleted.clear()
            try:
                cur = self._db.cursor()
                cur.execute("BEGIN")
                for k in deleted:
                    cur.execute("DELETE FROM cache_entries WHERE request_hash = ?", (k,))
                for k in dirty:
                    rec = self._index.get(k)
                    if not rec:
                        continue
                    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
                    meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO cache_entries
                        (request_hash, path, size_bytes, created_at, last_access, meta_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rec.get("request_hash", k),
                            rec.get("path", ""),
                            int(rec.get("size_bytes", 0)),
                            int(rec.get("created_at", 0)),
                            int(rec.get("last_access", 0)),
                            meta_json,
                        ),
                    )
                cur.execute("COMMIT")
            except Exception:
                try:
                    self._db.execute("ROLLBACK")
                except Exception:
                    pass
            return

        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self.index_path)

    def stats(self) -> dict:
        with self._lock:
            return {
                "items": len(self._index),
                "total_bytes": self._total_bytes,
                "max_bytes": self.max_bytes,
                "inflight": len(self._inflight),
                "index_backend": self._backend,
                "index_path": self.db_path if self._backend == "sqlite" else self.index_path,
            }

    def _record_path(self, request_hash: str) -> str:
        return os.path.join(self.audio_dir, f"{request_hash}.wav")

    def get_path(self, request_hash: str) -> Optional[str]:
        now = int(time.time())
        with self._lock:
            rec = self._index.get(request_hash)
            if not rec:
                return None
            p = rec.get("path", "")
            if not p or not os.path.exists(p):
                self._index.pop(request_hash, None)
                if self._backend == "sqlite":
                    self._deleted.add(request_hash)
                self._save_index_locked()
                return None
            rec["last_access"] = now
            if self._backend == "sqlite":
                self._dirty.add(request_hash)
            # Persist lazily: still cheap enough to save here to keep LRU correct.
            self._save_index_locked()
            return p

    def put_bytes(self, request_hash: str, wav_bytes: bytes, meta: Optional[dict] = None) -> str:
        if not isinstance(wav_bytes, (bytes, bytearray)):
            raise TypeError("wav_bytes must be bytes")
        meta = meta or {}
        final_path = self._record_path(request_hash)
        tmp_path = final_path + ".tmp"
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(wav_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, final_path)

        now = int(time.time())
        size_bytes = int(os.path.getsize(final_path))
        with self._lock:
            old = self._index.get(request_hash)
            if old:
                self._total_bytes -= int(old.get("size_bytes", 0))
            self._index[request_hash] = {
                "request_hash": request_hash,
                "path": final_path,
                "size_bytes": size_bytes,
                "created_at": int(old.get("created_at", now)) if old else now,
                "last_access": now,
                "meta": meta,
            }
            self._total_bytes += size_bytes
            self._prune_locked()
            if self._backend == "sqlite":
                self._dirty.add(request_hash)
            self._save_index_locked()
        return final_path

    def link_or_copy_to(self, cache_path: str, target_path: str) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        try:
            if os.path.exists(target_path):
                os.remove(target_path)
        except Exception:
            pass
        try:
            os.link(cache_path, target_path)  # hardlink if same volume
            return
        except Exception:
            pass
        # Fallback: copy
        import shutil

        shutil.copy2(cache_path, target_path)

    def begin_inflight(self, request_hash: str) -> bool:
        """
        Register an in-flight generation. Returns True if caller owns generation.
        """
        with self._lock:
            if request_hash in self._inflight:
                return False
            self._inflight[request_hash] = threading.Event()
            return True

    def wait_inflight(self, request_hash: str, timeout_ms: int) -> bool:
        with self._lock:
            ev = self._inflight.get(request_hash)
        if not ev:
            return True
        return bool(ev.wait(timeout=max(0.0, timeout_ms / 1000.0)))

    def end_inflight(self, request_hash: str) -> None:
        with self._lock:
            ev = self._inflight.get(request_hash)
            if ev:
                ev.set()
                self._inflight.pop(request_hash, None)

    def _prune_locked(self):
        if self.max_bytes <= 0:
            return
        if self._total_bytes <= self.max_bytes:
            return
        # Sort by last_access ascending (oldest first).
        items = sorted(self._index.items(), key=lambda kv: int(kv[1].get("last_access", 0)))
        for k, rec in items:
            if self._total_bytes <= self.max_bytes:
                break
            p = rec.get("path", "")
            try:
                sz = int(rec.get("size_bytes", 0))
            except Exception:
                sz = 0
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                # If can't delete, skip; prevents infinite loop by removing record anyway.
                pass
            self._index.pop(k, None)
            if self._backend == "sqlite":
                self._deleted.add(k)
            self._total_bytes = max(0, self._total_bytes - sz)
