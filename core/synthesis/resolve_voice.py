from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from core.emotion_selector import resolve_voice_with_fallback


def parse_voice_id(voice_id: str) -> Tuple[str, str]:
    vid = (voice_id or "").strip()
    if not vid:
        return "", "default"
    if "#" in vid:
        c, e = vid.split("#", 1)
        return (c or "").strip(), ((e or "").strip() or "default")
    return vid, "default"


def resolve_voice_or_fallback(
    *,
    voice_id: str,
    character: str,
    emotion: str,
    character_config_get: Callable[[str], Optional[Dict]],
) -> Tuple[str, Optional[Dict]]:
    """
    Resolve voice by explicit voice_id first, then character+emotion fallback.
    """
    vid = (voice_id or "").strip()
    ch = (character or "").strip()
    emo = (emotion or "").strip() or "default"

    if vid:
        voice = character_config_get(vid)
        return vid, voice
    if ch:
        return resolve_voice_with_fallback(
            character_config_get=character_config_get,
            character=ch,
            emotion=emo,
        )
    return "", None

