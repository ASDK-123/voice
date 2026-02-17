import hashlib
import json
import os
import re
from typing import Optional


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    t = str(text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.strip()
    # Collapse whitespace runs to a single space, but keep newlines.
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def stable_json_hash(obj) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _md5_hex(payload)


def model_fingerprint(model_dir: str, fp16: bool, load_trt: bool, load_vllm: bool) -> str:
    return stable_json_hash(
        {
            "model_dir": model_dir or "",
            "fp16": bool(fp16),
            "load_trt": bool(load_trt),
            "load_vllm": bool(load_vllm),
        }
    )


def cozyvoice3_prefix_prompt(prompt_text: str) -> str:
    # CosyVoice3 expects a system prompt and <|endofprompt|> separator.
    if "<|endofprompt|>" in prompt_text:
        return prompt_text
    return f"You are a helpful assistant.<|endofprompt|>{prompt_text}"


def cozyvoice3_normalize_instruct(instruct_text: str) -> str:
    t = instruct_text or ""
    if "<|endofprompt|>" not in t:
        t = f"{t}<|endofprompt|>"
    if "You are a helpful assistant." not in t:
        t = f"You are a helpful assistant. {t}"
    return t


def voice_fingerprint(
    *,
    voice_id: str,
    mode: str,
    prompt_text_final: str,
    instruct_text_final: str,
    prompt_audio_hash: str,
    selected_ref_asset_id: str = "",
    variation_seed: int = 0,
) -> str:
    return stable_json_hash(
        {
            "voice_id": (voice_id or "").strip(),
            "mode": (mode or "").strip(),
            "prompt_text": prompt_text_final or "",
            "instruct_text": instruct_text_final or "",
            "prompt_audio_hash": prompt_audio_hash or "",
            "selected_ref_asset_id": (selected_ref_asset_id or "").strip(),
            "variation_seed": int(variation_seed or 0),
        }
    )


def request_hash(
    *,
    schema_version: str,
    model_fp: str,
    voice_fp: str,
    text_norm: str,
    speed: float,
    use_instruction: bool,
    instruction_text: str,
    part_index: int = 0,
) -> str:
    return stable_json_hash(
        {
            "schema_version": schema_version,
            "model_fp": model_fp,
            "voice_fp": voice_fp,
            "text": text_norm or "",
            "speed": float(speed),
            "use_instruction": bool(use_instruction),
            "instruction": instruction_text or "",
            "part_index": int(part_index or 0),
        }
    )


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except Exception:
        return os.path.abspath(a) == os.path.abspath(b)


def safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def safe_float(x, default=1.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

