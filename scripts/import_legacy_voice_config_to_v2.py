import argparse
import os
import sys

# Allow running from repo root without installing as a package.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.v2.legacy_import import import_legacy_voice_config_to_v2


def main():
    ap = argparse.ArgumentParser(description="Import legacy GUI voice configs into v2 voices + v2 assets store")
    ap.add_argument("--legacy", default=os.path.abspath("./config/config.json"), help="legacy voices json (list)")
    ap.add_argument("--v2-voices", default="", help="v2 voices config json path")
    ap.add_argument("--db", default=os.path.abspath("./data/api_v2_assets.sqlite3"), help="v2 assets sqlite db path")
    ap.add_argument("--assets-dir", default=os.path.abspath("./data/assets/audio"), help="v2 assets audio dir")
    ap.add_argument("--lang", default="zh", help="default language meta for imported assets")
    ap.add_argument("--dry-run", action="store_true", help="do not write anything")
    args = ap.parse_args()

    v2_voices = args.v2_voices.strip()
    if not v2_voices:
        # best-effort: reuse app_config.json key if present
        try:
            from core.config_manager import ConfigManager

            v2_voices = (ConfigManager().get("v2_voices_config_path", "") or "").strip()
        except Exception:
            v2_voices = ""
    if not v2_voices:
        v2_voices = os.path.abspath("./config/voices_v2.json")

    res = import_legacy_voice_config_to_v2(
        legacy_config_path=args.legacy,
        v2_voices_config_path=v2_voices,
        v2_assets_db_path=args.db,
        v2_assets_dir=args.assets_dir,
        default_language=args.lang,
        dry_run=bool(args.dry_run),
    )
    print(res)


if __name__ == "__main__":
    main()
