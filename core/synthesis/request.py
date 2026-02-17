from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class SynthesisRequest:
    """Raw request model used before normalization."""

    text: str
    voice_id: str = ""
    character: str = ""
    emotion: str = ""
    mode: str = ""
    speed: float = 1.0
    use_instruction: bool = False
    instruction: str = ""
    instruct_text: str = ""
    prompt_text: str = ""
    variation_seed: int = 0
    selection_policy: str = ""
    selected_ref_asset_id: str = ""

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "SynthesisRequest":
        d = data or {}
        return cls(
            text=str(d.get("text") or ""),
            voice_id=str(d.get("voice_id") or d.get("character_name") or ""),
            character=str(d.get("character") or ""),
            emotion=str(d.get("emotion") or ""),
            mode=str(d.get("mode") or ""),
            speed=float(d.get("speed") or 1.0),
            use_instruction=bool(d.get("use_instruction") or False),
            instruction=str(d.get("instruction") or ""),
            instruct_text=str(d.get("instruct_text") or ""),
            prompt_text=str(d.get("prompt_text") or ""),
            variation_seed=int(d.get("variation_seed") or 0),
            selection_policy=str(d.get("selection_policy") or ""),
            selected_ref_asset_id=str(d.get("selected_ref_asset_id") or ""),
        )


@dataclass(frozen=True)
class NormalizedRequest:
    """Normalized request model used by cache and synthesis paths."""

    text_norm: str
    mode: str
    speed: float
    use_instruction: bool
    instruction: str
    prompt_text_final: str
    instruct_text_final: str
    selected_ref_asset_id: str
    variation_seed: int
    voice_id: str
    character: str
    emotion: str

