from __future__ import annotations

from core.emotion_selector import pick_ref_asset_id, normalize_request_text


def select_ref_asset_id(
    *,
    voice: dict,
    text: str,
    variation_seed: int,
    policy_override: str = "",
    selected_ref_asset_id: str = "",
) -> str:
    """
    Return selected ref asset id while preserving explicit request override.
    """
    explicit = (selected_ref_asset_id or "").strip()
    if explicit:
        return explicit
    text_norm = normalize_request_text(text or "")
    return pick_ref_asset_id(
        voice=voice or {},
        text_normalized=text_norm,
        variation_seed=int(variation_seed or 0),
        override_policy=(policy_override or "").strip(),
    )

