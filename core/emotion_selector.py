import hashlib
import os
from typing import Callable, Dict, Optional, Tuple

from .cache_keys import normalize_text, safe_int


def _stable_pick_index(key: str, n: int) -> int:
    if n <= 0:
        return 0
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % n


def resolve_voice_id(character: str, emotion: str) -> str:
    character = (character or "").strip()
    emotion = (emotion or "").strip() or "default"
    return f"{character}#{emotion}"


def pick_ref_asset_id(
    *,
    voice: dict,
    text_normalized: str,
    variation_seed: int,
    override_policy: str = "",
) -> str:
    """
    Pick one reference asset_id for an emotion voice.

    Policies:
    - random_per_text (default): deterministic by (character, emotion, text, variation_seed)
    - random_per_request: nondeterministic; should only be used with variation_seed to avoid cache surprises
    - fixed: first item
    """
    ids = (voice or {}).get("ref_asset_ids") or []
    ids = [str(x).strip() for x in ids if str(x).strip()]
    if not ids:
        return ""

    policy = (override_policy or (voice or {}).get("selection_policy") or "random_per_text").strip()
    if policy == "fixed":
        return ids[0]

    if policy == "random_per_request":
        import random

        return random.choice(ids)

    character = (voice or {}).get("character") or ""
    emotion = (voice or {}).get("emotion") or ""
    key = f"{character}|{emotion}|{text_normalized}|{safe_int(variation_seed)}"
    idx = _stable_pick_index(key, len(ids))
    return ids[idx]


def resolve_prompt_audio_path(
    *,
    voice: dict,
    selected_ref_asset_id: str,
    get_asset_meta: Callable[[str], Optional[dict]],
) -> Tuple[str, str]:
    """
    Return (prompt_audio_path, prompt_audio_hash_or_empty_if_unknown).

    - If selected_ref_asset_id is provided, it must exist in v2 asset index.
    - Else fall back to voice.prompt_audio path if present.
    """
    if selected_ref_asset_id:
        meta = get_asset_meta(selected_ref_asset_id)
        if not meta:
            raise ValueError(f"ref asset not found: {selected_ref_asset_id}")
        return meta.get("path", ""), meta.get("sha1", "")

    p = (voice or {}).get("prompt_audio", "") or ""
    if p:
        if not os.path.isabs(p):
            # Expect project-root relative paths in current code.
            # Caller should resolve relative paths before invoking if desired.
            p = os.path.abspath(p)
        return p, ""
    return "", ""


def resolve_voice_with_fallback(
    *,
    character_config_get: Callable[[str], Optional[dict]],
    character: str,
    emotion: str,
) -> Tuple[str, dict]:
    """
    Resolve requested (character, emotion) to a voice dict with fallback to default.
    Returns (voice_id, voice_dict).
    """
    vid = resolve_voice_id(character, emotion)
    voice = character_config_get(vid)
    if voice:
        return vid, voice
    default_vid = resolve_voice_id(character, "default")
    voice = character_config_get(default_vid)
    if voice:
        return default_vid, voice
    raise ValueError(f"voice not found: {vid} (fallback also missing: {default_vid})")


def normalize_request_text(text: str) -> str:
    return normalize_text(text or "")

