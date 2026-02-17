from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
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
    return con


def _load_index_json(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def migrate(json_path: str, db_path: str, dry_run: bool = False) -> dict:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"index json not found: {json_path}")

    index = _load_index_json(json_path)
    now = int(time.time())
    inserted = 0
    skipped_missing = 0
    skipped_bad = 0

    con = _connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("BEGIN")
        for k, rec in index.items():
            if not isinstance(rec, dict):
                skipped_bad += 1
                continue
            request_hash = str(rec.get("request_hash") or k or "").strip()
            if not request_hash:
                skipped_bad += 1
                continue
            path = str(rec.get("path") or "").strip()
            if not path or not os.path.exists(path):
                skipped_missing += 1
                continue
            try:
                size_bytes = int(os.path.getsize(path))
            except Exception:
                skipped_missing += 1
                continue

            created_at = int(rec.get("created_at") or now)
            last_access = int(rec.get("last_access") or created_at or now)
            meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
            meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))

            if not dry_run:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO cache_entries
                    (request_hash, path, size_bytes, created_at, last_access, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (request_hash, path, size_bytes, created_at, last_access, meta_json),
                )
            inserted += 1
        if dry_run:
            cur.execute("ROLLBACK")
        else:
            cur.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()

    return {
        "inserted": inserted,
        "skipped_missing": skipped_missing,
        "skipped_bad": skipped_bad,
        "json_path": os.path.abspath(json_path),
        "db_path": os.path.abspath(db_path),
        "dry_run": bool(dry_run),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate CacheManager index.json to sqlite index.sqlite3")
    ap.add_argument("--json", dest="json_path", default=os.path.join("data", "cache", "index.json"))
    ap.add_argument("--db", dest="db_path", default=os.path.join("data", "cache", "index.sqlite3"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary = migrate(args.json_path, args.db_path, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

