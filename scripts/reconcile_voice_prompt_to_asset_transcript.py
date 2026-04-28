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
        raise FileNotFoundError(f"voices config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    raise ValueError(f"invalid voices json root type: {type(data).__name__}")


def _first_nonempty_list(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    for x in items:
        s = _safe_str(x)
        if s:
            return s
    return ""


def _voice_id(v: dict[str, Any]) -> str:
    return _safe_str(v.get("name") or v.get("voice_id"))


def _primary_asset_id(v: dict[str, Any]) -> str:
    aid = _first_nonempty_list(v.get("ref_asset_ids"))
    if aid:
        return aid
    return _safe_str(v.get("prompt_audio_asset_id"))


def _build_asset_refs(voices: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for v in voices or []:
        vid = _voice_id(v)
        if not vid:
            continue
        aid = _safe_str(v.get("prompt_audio_asset_id"))
        if aid:
            out.setdefault(aid, set()).add(vid)
        ref_ids = v.get("ref_asset_ids") if isinstance(v.get("ref_asset_ids"), list) else []
        for x in ref_ids:
            rid = _safe_str(x)
            if rid:
                out.setdefault(rid, set()).add(vid)
    return out


def _make_backup(db_path: str, backup_dir: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"api_v2_assets.sqlite3.reconcile_backup_{ts}")
    shutil.copy2(db_path, dst)
    return os.path.abspath(dst)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Reconcile primary asset transcript_text/prompt_text from voice.prompt_text "
            "(voice is source of truth; shared assets are protected)."
        )
    )
    p.add_argument("--voices", default=os.path.abspath("./config/super_agent.json"), help="Path to voices json")
    p.add_argument("--db", default=os.path.abspath("./data/api_v2_assets.sqlite3"), help="Path to assets sqlite db")
    p.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    p.add_argument("--backup-dir", default=os.path.abspath("./tmp"), help="SQLite backup dir for --apply")
    p.add_argument("--report", default="", help="Optional report json path")
    p.add_argument("--details-limit", type=int, default=5000, help="Maximum detail rows written in report")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    voices_path = os.path.abspath(args.voices)
    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"assets db not found: {db_path}")

    voices = _load_voices(voices_path)
    refs_by_asset = _build_asset_refs(voices)
    store = AssetsSqliteStore(db_path)

    summary: dict[str, Any] = {
        "timestamp": int(time.time()),
        "mode": "apply" if bool(args.apply) else "dry-run",
        "voices_path": voices_path,
        "db_path": db_path,
        "voices_scanned": len(voices),
        "updated": 0,
        "already_aligned": 0,
        "skipped_no_asset": 0,
        "skipped_missing_asset": 0,
        "skipped_empty_prompt": 0,
        "skipped_shared": 0,
        "conflict": 0,
        "backup_path": "",
        "details": [],
    }

    details_limit = max(0, int(args.details_limit or 0))

    if args.apply:
        summary["backup_path"] = _make_backup(db_path, os.path.abspath(args.backup_dir))

    for v in voices:
        vid = _voice_id(v)
        if not vid:
            continue
        aid = _primary_asset_id(v)
        if not aid:
            summary["skipped_no_asset"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append({"voice_id": vid, "status": "skipped_no_asset"})
            continue

        voice_prompt = _safe_str(v.get("prompt_text"))
        if not voice_prompt:
            summary["skipped_empty_prompt"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append({"voice_id": vid, "asset_id": aid, "status": "skipped_empty_prompt"})
            continue

        meta = store.get(aid)
        if not isinstance(meta, dict):
            summary["skipped_missing_asset"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append({"voice_id": vid, "asset_id": aid, "status": "skipped_missing_asset"})
            continue

        refs = sorted(refs_by_asset.get(aid) or [])
        ref_count = len(refs)
        transcript_now = _safe_str(meta.get("transcript_text"))
        legacy_prompt_now = _safe_str(meta.get("prompt_text"))
        aligned = transcript_now == voice_prompt and legacy_prompt_now == voice_prompt

        if ref_count > 1:
            summary["skipped_shared"] += 1
            if not aligned:
                summary["conflict"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append(
                    {
                        "voice_id": vid,
                        "asset_id": aid,
                        "status": "skipped_shared",
                        "ref_count": ref_count,
                        "ref_voices": refs,
                        "voice_prompt_text": voice_prompt,
                        "asset_transcript_text": transcript_now,
                        "asset_prompt_text": legacy_prompt_now,
                        "conflict": not aligned,
                    }
                )
            continue

        if aligned:
            summary["already_aligned"] += 1
            if len(summary["details"]) < details_limit:
                summary["details"].append({"voice_id": vid, "asset_id": aid, "status": "already_aligned"})
            continue

        if args.apply:
            updated = dict(meta)
            updated["transcript_text"] = voice_prompt
            # Legacy compatibility mirror, not source-of-truth.
            updated["prompt_text"] = voice_prompt
            store.upsert(updated)

        summary["updated"] += 1
        if len(summary["details"]) < details_limit:
            summary["details"].append(
                {
                    "voice_id": vid,
                    "asset_id": aid,
                    "status": "updated",
                    "old_transcript_text": transcript_now,
                    "old_prompt_text": legacy_prompt_now,
                    "new_transcript_text": voice_prompt,
                    "new_prompt_text": voice_prompt,
                }
            )

    report_path = _safe_str(args.report)
    if not report_path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        report_path = os.path.abspath(f"./tmp/reconcile_voice_prompt_to_asset_transcript_report_{ts}.json")
    report_path = os.path.abspath(report_path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in summary.items() if k != "details"}, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
