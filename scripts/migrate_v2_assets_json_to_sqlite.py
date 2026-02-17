import os
import sys


def main() -> int:
    # Allow running from repo root: python scripts/migrate_v2_assets_json_to_sqlite.py
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo_root)

    from core.v2.assets_sqlite import AssetsSqliteStore

    data_root = os.path.join(repo_root, "data")
    json_path = os.path.join(data_root, "api_v2_assets.json")
    db_path = os.path.join(data_root, "api_v2_assets.sqlite3")

    store = AssetsSqliteStore(db_path)
    n = store.migrate_from_json_index(json_path)
    print(f"migrated_rows={n} json={json_path} sqlite={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

