from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from typing import Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.v2.assets_sqlite import AssetsSqliteStore


def _safe_str(v: Any) -> str:
    return str(v or "").strip()


def _load_voices(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _build_asset_prompt_index(voices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for v in voices:
        vid = _safe_str(v.get("name"))
        ptxt = _safe_str(v.get("prompt_text"))
        ref_ids = v.get("ref_asset_ids") if isinstance(v.get("ref_asset_ids"), list) else []
        for x in ref_ids:
            aid = _safe_str(x)
            if not aid:
                continue
            item = out.setdefault(aid, {"prompts": set(), "voices": set()})
            if ptxt:
                item["prompts"].add(ptxt)
            if vid:
                item["voices"].add(vid)
    return out


def _make_backup(db_path: str, backup_dir: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"api_v2_assets.sqlite3.backup_{ts}")
    shutil.copy2(db_path, dst)
    return os.path.abspath(dst)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate v2 assets: fill transcript_text from legacy prompt_text or bound voice prompt_text."
    )
    parser.add_argument("--db", default=os.path.abspath("./data/api_v2_assets.sqlite3"), help="Path to v2 assets sqlite db")
    parser.add_argument("--voices", default=os.path.abspath("./config/voices_v2.json"), help="Path to v2 voices json")
    parser.add_argument("--kind", default="ref", help="Asset kind filter, default=ref")
    parser.add_argument("--limit", type=int, default=200000, help="Max assets to scan")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--backup-dir", default=os.path.abspath("./tmp"), help="Backup dir when --apply")
    parser.add_argument("--report", default="", help="Optional report json path")
    parser.add_argument("--details-limit", type=int, default=2000, help="Max detail rows in report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = os.path.abspath(args.db)
    voices_path = os.path.abspath(args.voices)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"db not found: {db_path}")

    voices = _load_voices(voices_path)
    by_asset = _build_asset_prompt_index(voices)
    store = AssetsSqliteStore(db_path)
    assets = store.list(kind=str(args.kind or "").strip(), limit=max(1, int(args.limit or 1)))

    summary = {
        "timestamp": int(time.time()),
        "mode": "apply" if args.apply else "dry-run",
        "db_path": db_path,
        "voices_path": voices_path,
        "assets_scanned": 0,
        "voices_scanned": len(voices),
        "unchanged_has_transcript": 0,
        "filled_from_legacy_prompt_text": 0,
        "filled_from_voice_prompt_text": 0,
        "skipped_no_candidate": 0,
        "skipped_conflict": 0,
        "applied_updates": 0,
        "backup_path": "",
        "details": [],
    }

    if args.apply:
        summary["backup_path"] = _make_backup(db_path, os.path.abspath(args.backup_dir))

    details_limit = max(0, int(args.details_limit or 0))

    for meta in assets:
        if not isinstance(meta, dict):
            continue
        summary["assets_scanned"] += 1
        aid = _safe_str(meta.get("asset_id"))
        if not aid:
            continue

        transcript_now = _safe_str(meta.get("transcript_text"))
        if transcript_now:
            summary["unchanged_has_transcript"] += 1
            continue

        candidate = ""
        source = ""
        legacy_prompt = _safe_str(meta.get("prompt_text"))
        if legacy_prompt:
            candidate = legacy_prompt
            source = "legacy_prompt_text"
        else:
            mapped = by_asset.get(aid) or {}
            prompts = sorted([_safe_str(x) for x in list(mapped.get("prompts") or set()) if _safe_str(x)])
            voices_ref = sorted([_safe_str(x) for x in list(mapped.get("voices") or set()) if _safe_str(x)])
            if len(prompts) == 1:
                candidate = prompts[0]
                source = "voice_prompt_text"
            elif len(prompts) > 1:
                summary["skipped_conflict"] += 1
                if len(summary["details"]) < details_limit:
                    summary["details"].append(
                        {
                            "asset_id": aid,
                            "status": "conflict",
                            "voices": voices_ref,
                            "prompts": prompts,
                        }
                    )
                continue

        if not candidate:
            summary["skipped_no_candidate"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append({"asset_id": aid, "status": "no_candidate"})
            continue

        if source == "legacy_prompt_text":
            summary["filled_from_legacy_prompt_text"] += 1
        else:
            summary["filled_from_voice_prompt_text"] += 1

        if args.apply:
            updated = dict(meta)
            updated["transcript_text"] = candidate
            store.upsert(updated)
            summary["applied_updates"] += 1

        if len(summary["details"]) < details_limit:
            summary["details"].append(
                {
                    "asset_id": aid,
                    "status": "filled",
                    "source": source,
                    "transcript_text": candidate,
                }
            )

    report_path = _safe_str(args.report)
    if not report_path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        report_path = os.path.abspath(f"./tmp/transcript_migration_report_{ts}.json")
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, ensure_ascii=False, indent=2))
    print(f"report={os.path.abspath(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
