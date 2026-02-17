from __future__ import annotations

from typing import Dict, Any

from core.cache_keys import (
    model_fingerprint,
    normalize_text,
    request_hash,
    voice_fingerprint,
)
from .normalize import (
    apply_instruction_override,
    normalize_prompt_and_instruct,
    normalize_request_text,
)


def build_request_hash(
    *,
    schema_version: str,
    model_dir: str,
    fp16: bool,
    load_trt: bool,
    load_vllm: bool,
    voice_id: str,
    mode: str,
    prompt_text_final: str,
    instruct_text_final: str,
    prompt_audio_hash: str,
    selected_ref_asset_id: str,
    variation_seed: int,
    text: str,
    speed: float,
    use_instruction: bool,
    instruction_text: str,
    part_index: int = 0,
) -> Dict[str, Any]:
    text_norm = normalize_text(text or "")
    mfp = model_fingerprint(
        model_dir=model_dir or "",
        fp16=bool(fp16),
        load_trt=bool(load_trt),
        load_vllm=bool(load_vllm),
    )
    vfp = voice_fingerprint(
        voice_id=(voice_id or "").strip(),
        mode=(mode or "").strip(),
        prompt_text_final=prompt_text_final or "",
        instruct_text_final=instruct_text_final or "",
        prompt_audio_hash=prompt_audio_hash or "",
        selected_ref_asset_id=(selected_ref_asset_id or "").strip(),
        variation_seed=int(variation_seed or 0),
    )
    req_hash = request_hash(
        schema_version=schema_version,
        model_fp=mfp,
        voice_fp=vfp,
        text_norm=text_norm,
        speed=float(speed),
        use_instruction=bool(use_instruction),
        instruction_text=instruction_text or "",
        part_index=int(part_index or 0),
    )
    return {
        "request_hash": req_hash,
        "text_norm": text_norm,
        "model_fp": mfp,
        "voice_fp": vfp,
    }


def build_cache_identity(
    *,
    schema_version: str,
    model_dir: str,
    fp16: bool,
    load_trt: bool,
    load_vllm: bool,
    voice_id: str,
    mode: str,
    prompt_text: str,
    instruct_text: str,
    prompt_audio_hash: str,
    selected_ref_asset_id: str,
    variation_seed: int,
    text: str,
    speed: float,
    use_instruction: bool,
    instruction: str,
    is_v3: bool,
    part_index: int = 0,
) -> Dict[str, Any]:
    """
    Single-entry identity builder shared by API/UI paths:
    - text normalization
    - instruction override normalization
    - CV3 prompt/instruct normalization
    - cache request hash assembly
    """
    text_norm = normalize_request_text(text or "")
    mode_final, instruct_text_overridden = apply_instruction_override(
        mode=mode,
        instruct_text=instruct_text,
        use_instruction=use_instruction,
        instruction=instruction,
    )
    prompt_text_final, instruct_text_final = normalize_prompt_and_instruct(
        mode=mode_final,
        prompt_text=prompt_text,
        instruct_text=instruct_text_overridden,
        is_v3=bool(is_v3),
    )
    id_info = build_request_hash(
        schema_version=schema_version,
        model_dir=model_dir,
        fp16=fp16,
        load_trt=load_trt,
        load_vllm=load_vllm,
        voice_id=voice_id,
        mode=mode_final,
        prompt_text_final=prompt_text_final,
        instruct_text_final=instruct_text_final,
        prompt_audio_hash=prompt_audio_hash,
        selected_ref_asset_id=selected_ref_asset_id,
        variation_seed=variation_seed,
        text=text_norm,
        speed=speed,
        use_instruction=bool(use_instruction),
        instruction_text=(instruct_text_final if use_instruction else ""),
        part_index=part_index,
    )
    id_info.update(
        {
            "mode": mode_final,
            "prompt_text_final": prompt_text_final,
            "instruct_text_final": instruct_text_final,
            "use_instruction": bool(use_instruction),
            "instruction_text": (instruct_text_final if use_instruction else ""),
        }
    )
    return id_info
