from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, List, Tuple

from core.v2.assets_sqlite import AssetsSqliteStore


def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: str, payload) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp_{uuid.uuid4().hex[:8]}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_voices_file(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    data = _read_json(path)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _upsert_voice(voices: Dict[str, dict], voice: dict) -> None:
    name = str((voice or {}).get("name") or "").strip()
    if not name:
        raise ValueError("voice.name is required")
    voices[name] = dict(voice)


def _import_audio_to_assets(
    *,
    assets: AssetsSqliteStore,
    assets_dir: str,
    file_path: str,
    character: str,
    emotion: str,
    language: str,
    note: str = "",
) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)
    with open(file_path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(f"empty audio file: {file_path}")

    sha1 = _sha1_bytes(data)
    ext = os.path.splitext(file_path)[1].lower().strip(".")
    if not ext:
        ext = "wav"

    asset_id = f"ref_{uuid.uuid4().hex[:12]}"
    filename = os.path.basename(file_path)
    out_path = os.path.abspath(os.path.join(assets_dir, f"{asset_id}.{ext}"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    meta = {
        "asset_id": asset_id,
        "kind": "ref",
        "filename": filename,
        "path": out_path,
        "size": int(len(data)),
        "sha1": sha1,
        "created_at": int(time.time()),
        "character": character,
        "emotion": emotion,
        "language": language,
        "note": note or "",
        "linked": 1,
    }
    assets.upsert(meta)
    return meta


def import_legacy_voice_config_to_v2(
    *,
    legacy_config_path: str,
    v2_voices_config_path: str,
    v2_assets_db_path: str,
    v2_assets_dir: str,
    default_language: str = "zh",
    create_emotion: str = "default",
    selection_policy: str = "random_per_text",
    dry_run: bool = False,
) -> dict:
    """
    Import legacy GUI voice configs into v2 stores.

    Legacy format: a list of dicts, each with keys:
    - name, mode, prompt_text, prompt_audio, instruct_text, color

    v2 result:
    - voice_id becomes: "{name}#{emotion}" (emotion defaults to "default")
    - prompt_audio is imported into v2 assets (SQLite + data/assets/audio/*)
    - voice.ref_asset_ids is set to include the imported asset_id

    Notes:
    - This is one-way import. It does not delete existing v2 voices/assets.
    - We deliberately keep v2 voices config separate from legacy config files.
    """
    legacy_config_path = os.path.abspath(legacy_config_path)
    v2_voices_config_path = os.path.abspath(v2_voices_config_path)
    v2_assets_db_path = os.path.abspath(v2_assets_db_path)
    v2_assets_dir = os.path.abspath(v2_assets_dir)

    if not os.path.exists(legacy_config_path):
        raise FileNotFoundError(legacy_config_path)

    legacy = _read_json(legacy_config_path)
    if not isinstance(legacy, list):
        raise ValueError("legacy config must be a JSON list")

    existing_list = _load_voices_file(v2_voices_config_path)
    voices: Dict[str, dict] = {}
    for v in existing_list:
        name = str(v.get("name") or "").strip()
        if name:
            voices[name] = dict(v)

    assets = AssetsSqliteStore(v2_assets_db_path)

    imported_voices = 0
    imported_assets = 0
    skipped_assets = 0
    errors: List[str] = []

    for row in legacy:
        if not isinstance(row, dict):
            continue
        character = str((row.get("name") or "")).strip()
        if not character:
            continue

        emotion = (create_emotion or "default").strip() or "default"
        voice_id = f"{character}#{emotion}"

        # Merge with existing if present
        base = dict(voices.get(voice_id) or {})
        base.update(
            {
                "name": voice_id,
                "character": character,
                "emotion": emotion,
                "mode": row.get("mode", base.get("mode", "")),
                "prompt_text": row.get("prompt_text", base.get("prompt_text", "")),
                "instruct_text": row.get("instruct_text", base.get("instruct_text", "")),
                "color": row.get("color", base.get("color", "#FF6B6B")),
                "selection_policy": base.get("selection_policy") or selection_policy,
            }
        )

        ref_ids = base.get("ref_asset_ids") if isinstance(base.get("ref_asset_ids"), list) else []
        ref_ids = [str(x).strip() for x in (ref_ids or []) if str(x).strip()]

        prompt_audio = str(row.get("prompt_audio") or "").strip()
        if prompt_audio:
            # The legacy file is usually project-relative or absolute.
            if not os.path.isabs(prompt_audio):
                prompt_audio_abs = os.path.abspath(os.path.join(os.path.dirname(legacy_config_path), prompt_audio))
            else:
                prompt_audio_abs = prompt_audio
            if os.path.exists(prompt_audio_abs):
                if not dry_run:
                    try:
                        meta = _import_audio_to_assets(
                            assets=assets,
                            assets_dir=v2_assets_dir,
                            file_path=prompt_audio_abs,
                            character=character,
                            emotion=emotion,
                            language=default_language,
                            note=os.path.basename(prompt_audio_abs),
                        )
                        imported_assets += 1
                        aid = str(meta.get("asset_id") or "").strip()
                        if aid and aid not in ref_ids:
                            ref_ids.append(aid)
                        # Also set prompt_audio path to imported asset path for compatibility.
                        base["prompt_audio"] = meta.get("path", prompt_audio_abs)
                    except Exception as e:
                        errors.append(f"{voice_id}: import prompt_audio failed: {e}")
                        skipped_assets += 1
                else:
                    imported_assets += 1
            else:
                skipped_assets += 1

        if ref_ids:
            base["ref_asset_ids"] = ref_ids

        if not dry_run:
            _upsert_voice(voices, base)
        imported_voices += 1

    out_list = list(voices.values())
    out_list.sort(key=lambda x: str(x.get("name") or ""))

    if not dry_run:
        _write_json_atomic(v2_voices_config_path, out_list)

    return {
        "legacy_config_path": legacy_config_path,
        "v2_voices_config_path": v2_voices_config_path,
        "v2_assets_db_path": v2_assets_db_path,
        "v2_assets_dir": v2_assets_dir,
        "imported_voices": imported_voices,
        "imported_assets": imported_assets,
        "skipped_assets": skipped_assets,
        "errors": errors,
        "dry_run": dry_run,
    }

