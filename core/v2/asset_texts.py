from __future__ import annotations

from typing import Any, Mapping, Tuple


def _norm_text(v: Any) -> str:
    return str(v or "").strip()


def get_asset_transcript_info(meta: Mapping[str, Any] | None) -> Tuple[str, str]:
    """
    Resolve usable transcript text from asset metadata.

    Returns:
    - text: resolved transcript text
    - source: one of {"transcript_text", "prompt_text", ""}

    Note:
    - `prompt_text` is treated as legacy compatibility only.
    - `note` is intentionally excluded from synthesis semantics.
    """
    if not isinstance(meta, Mapping):
        return "", ""
    transcript_text = _norm_text(meta.get("transcript_text"))
    if transcript_text:
        return transcript_text, "transcript_text"
    legacy_prompt_text = _norm_text(meta.get("prompt_text"))
    if legacy_prompt_text:
        return legacy_prompt_text, "prompt_text"
    return "", ""


def get_asset_transcript_text(meta: Mapping[str, Any] | None) -> str:
    text, _ = get_asset_transcript_info(meta)
    return text


def resolve_prompt_text_voice_first(
    voice_prompt_text: str,
    asset_meta: Mapping[str, Any] | None,
) -> Tuple[str, str]:
    """
    Resolve synthesis prompt text with voice-first policy.

    Returns:
    - text: resolved prompt text
    - source: one of {"voice.prompt_text", "asset.transcript_text", "asset.prompt_text", ""}
    """
    vtxt = _norm_text(voice_prompt_text)
    if vtxt:
        return vtxt, "voice.prompt_text"
    atxt, asrc = get_asset_transcript_info(asset_meta)
    if asrc == "transcript_text":
        return atxt, "asset.transcript_text"
    if asrc == "prompt_text":
        return atxt, "asset.prompt_text"
    return "", ""
