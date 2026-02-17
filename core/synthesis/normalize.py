from __future__ import annotations

from typing import Tuple

from core.cache_keys import (
    cozyvoice3_normalize_instruct,
    cozyvoice3_prefix_prompt,
)
from core.emotion_selector import normalize_request_text as _normalize_request_text


def normalize_request_text(text: str) -> str:
    return _normalize_request_text(text or "")


def clean_text_for_inference(text: str) -> str:
    """
    Shared text cleaning entry used by API/worker before synthesis.

    Keep behavior aligned with request normalization for cross-surface cache parity.
    """
    return normalize_request_text(text)


def normalize_inference_mode(mode: str) -> str:
    """
    Normalize mode names from mixed aliases/localizations to canonical values.

    Canonical outputs:
    - zero_shot
    - reference_timbre
    - fine_grained
    - instruction
    """
    s = str(mode or "").strip()
    sl = s.lower()
    if not s:
        return "zero_shot"

    alias = {
        "zero-shot": "zero_shot",
        "zero_shot": "zero_shot",
        "reference-timbre": "reference_timbre",
        "reference_timbre": "reference_timbre",
        "fine-grained": "fine_grained",
        "fine_grained": "fine_grained",
        "instruction": "instruction",
    }
    if sl in alias:
        return alias[sl]

    # Legacy/localized aliases.
    if "instruction" in sl or "instruct" in sl or "指令" in s:
        return "instruction"
    if "fine" in sl or "精细" in s or "精細" in s:
        return "fine_grained"
    if "reference" in sl or "timbre" in sl or "参考" in s or "參考" in s:
        return "reference_timbre"
    if "zero" in sl or "零样" in s or "零樣" in s:
        return "zero_shot"

    return "zero_shot"


def apply_instruction_override(
    *,
    mode: str,
    instruct_text: str,
    use_instruction: bool,
    instruction: str,
) -> Tuple[str, str]:
    """
    Instruction override behavior shared by API/UI:
    when use_instruction=true and instruction non-empty, force instruction mode.
    """
    m = (mode or "").strip() or "零样本复制"
    ins = (instruct_text or "").strip()
    direct_ins = (instruction or "").strip()
    if use_instruction and direct_ins:
        return "指令控制", direct_ins
    return m, ins


def normalize_prompt_and_instruct(
    *,
    mode: str,
    prompt_text: str,
    instruct_text: str,
    is_v3: bool,
) -> Tuple[str, str]:
    """
    Keep a single normalization path for prompt/instruct formatting.
    """
    m = (mode or "").strip() or "零样本复制"
    p = (prompt_text or "").strip()
    i = (instruct_text or "").strip()

    if not is_v3:
        return p, i

    if m in {"零样本复制", "参考音色"} and p:
        p = cozyvoice3_prefix_prompt(p)
    if m == "指令控制" and i:
        i = cozyvoice3_normalize_instruct(i)
    return p, i
