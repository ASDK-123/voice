import sys
import os
import io
import torch
import random
import torchaudio
from typing import List, Optional
from types import SimpleNamespace

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from .models import TaskSegment
from .cache_manager import CacheManager
from .cache_keys import (
    sha1_file as _sha1_file,
    cozyvoice3_prefix_prompt as _cv3_prefix_prompt,
    cozyvoice3_normalize_instruct as _cv3_norm_instruct,
    safe_int as _safe_int,
)
from .synthesis.cache_key import build_cache_identity as _syn_build_cache_identity
from .synthesis.engine import run_synthesis as _syn_run_synthesis
from .synthesis.normalize import normalize_inference_mode as _syn_normalize_inference_mode

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_ROOT = os.path.join(PROJECT_ROOT, "data")
CACHE_ROOT = os.path.join(DATA_ROOT, "cache")
CACHE_SCHEMA_VERSION = "cv_cache_v2"


def _is_instruction_mode(mode: str) -> bool:
    mode_v = str(mode or "").strip()
    return _syn_normalize_inference_mode(mode_v) == "instruction"


def _build_segment_cache_identity(
    *,
    schema_version: str,
    model_dir: str,
    fp16: bool,
    load_trt: bool,
    load_vllm: bool,
    is_v3: bool,
    voice_id: str,
    mode: str,
    prompt_text: str,
    instruct_text: str,
    prompt_audio_hash: str,
    selected_ref_asset_id: str,
    variation_seed: int,
    text: str,
    speed: float,
    part_index: int,
    use_instruction: Optional[bool] = None,
    instruction: str = "",
) -> dict:
    mode_v = str(mode or "").strip()
    instruct_text_v = str(instruct_text or "").strip()
    if use_instruction is None:
        use_instruction = _is_instruction_mode(mode_v)
    use_instruction_v = bool(use_instruction)
    instruction_v = str(instruction or "").strip()
    if use_instruction_v and not instruction_v:
        instruction_v = instruct_text_v
    return _syn_build_cache_identity(
        schema_version=schema_version,
        model_dir=model_dir,
        fp16=bool(fp16),
        load_trt=bool(load_trt),
        load_vllm=bool(load_vllm),
        voice_id=str(voice_id or "").strip(),
        mode=mode_v,
        prompt_text=str(prompt_text or ""),
        instruct_text=instruct_text_v,
        prompt_audio_hash=str(prompt_audio_hash or ""),
        selected_ref_asset_id=str(selected_ref_asset_id or "").strip(),
        variation_seed=int(variation_seed or 0),
        text=str(text or ""),
        speed=float(speed),
        use_instruction=use_instruction_v,
        instruction=instruction_v,
        is_v3=bool(is_v3),
        part_index=int(part_index or 0),
    )

class ModelLoaderThread(QThread):
    """Background loader for CosyVoice model."""
    success = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def run(self):
        try:
            from .utils import load_cosyvoice_model
            model = load_cosyvoice_model()
            self.success.emit(model)
        except Exception as e:
            self.error.emit(str(e))

class ModelUnloaderThread(QThread):
    """Background unloader for CosyVoice model."""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, model):
        super().__init__()
        self.model = model
    
    def run(self):
        try:
            from .utils import unload_cosyvoice_model
            unload_cosyvoice_model(self.model)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class AudioGenerationWorker(QThread):
    """Generate audio segments in worker thread."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    segment_finished = pyqtSignal(int, list)
    
    def __init__(self, segments: List[TaskSegment], output_dir: str, 
                 project_name: str, cosyvoice_model=None):
        super().__init__()
        self.segments = segments
        self.output_dir = output_dir
        self.project_name = project_name
        self.cosyvoice = cosyvoice_model
        self.is_running = True
    
    def stop(self):
        self.is_running = False

    @staticmethod
    def _env_flag(name: str, default: bool) -> bool:
        raw = str(os.getenv(name, "true" if default else "false")).strip().lower()
        return raw not in {"0", "false", "no", "off", ""}

    def _use_engine_path(self) -> bool:
        # C4: worker local path defaults to unified synthesis engine with fallback.
        return self._env_flag("WORKER_USE_SYNTHESIS_ENGINE", True)

    def run(self):
        try:
            if self.cosyvoice is None:
                self.progress.emit("Loading CosyVoice model...")
                self.cosyvoice = self.load_model()
                self.progress.emit("Model loaded")

            cache_max_mb = _safe_int(os.getenv("CACHE_MAX_MB", "500"), 500)
            cache = CacheManager(CACHE_ROOT, max_bytes=int(cache_max_mb) * 1024 * 1024)

            try:
                from .config_manager import ConfigManager
                fp16 = bool(ConfigManager().get("fp16", False))
            except Exception:
                fp16 = False
            model_dir = getattr(self.cosyvoice, "model_dir", "") or ""
            load_trt = True
            load_vllm = os.getenv("ENABLE_VLLM", "false").lower() == "true"
            is_v3 = "CosyVoice3" in model_dir

            use_engine = self._use_engine_path()
            self.progress.emit(f"[worker] synthesis engine path: {'on' if use_engine else 'off'}")

            project_output_dir = os.path.join(self.output_dir, self.project_name)
            os.makedirs(project_output_dir, exist_ok=True)

            all_generated_files = []

            for segment in self.segments:
                if not self.is_running:
                    break

                torch.manual_seed(segment.seed)
                random.seed(segment.seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed(segment.seed)
                    torch.cuda.manual_seed_all(segment.seed)

                self.progress.emit(f"Generating segment {segment.index}...")
                self.progress.emit(f"   Text: {segment.text}")
                self.progress.emit(f"   Voice: {segment.voice_config.name} ({segment.mode})")
                self.progress.emit(f"   Seed: {segment.seed}")

                if not segment.voice_config.prompt_audio or not os.path.exists(segment.voice_config.prompt_audio):
                    self.progress.emit(f"Warning: prompt audio missing, skip segment: {segment.voice_config.prompt_audio}")
                    continue

                segment_files = []
                try:
                    if use_engine:
                        segment_files = self._run_segment_with_engine(
                            segment=segment,
                            cache=cache,
                            project_output_dir=project_output_dir,
                            fp16=fp16,
                            model_dir=model_dir,
                            load_trt=load_trt,
                            load_vllm=load_vllm,
                            is_v3=is_v3,
                        )
                    else:
                        segment_files = self._run_segment_legacy(
                            segment=segment,
                            cache=cache,
                            project_output_dir=project_output_dir,
                            fp16=fp16,
                            model_dir=model_dir,
                            load_trt=load_trt,
                            load_vllm=load_vllm,
                            is_v3=is_v3,
                        )
                except Exception as e:
                    if use_engine:
                        self.progress.emit(f"[worker] engine path failed, fallback legacy: {e}")
                        segment_files = self._run_segment_legacy(
                            segment=segment,
                            cache=cache,
                            project_output_dir=project_output_dir,
                            fp16=fp16,
                            model_dir=model_dir,
                            load_trt=load_trt,
                            load_vllm=load_vllm,
                            is_v3=is_v3,
                        )
                    else:
                        raise

                if segment_files:
                    segment.add_version(segment_files)
                    all_generated_files.extend(segment_files)

                self.segment_finished.emit(segment.index, segment_files)

            if self.is_running:
                self.finished.emit(all_generated_files)

        except Exception as e:
            self.error.emit(f"Generation failed: {str(e)}")

    def _run_segment_with_engine(
        self,
        *,
        segment: TaskSegment,
        cache: CacheManager,
        project_output_dir: str,
        fp16: bool,
        model_dir: str,
        load_trt: bool,
        load_vllm: bool,
        is_v3: bool,
    ) -> List[str]:
        prompt_audio_path = segment.voice_config.prompt_audio
        version = int(segment.run_count or 0) + 1
        mode = segment.mode or segment.voice_config.mode
        prompt_text = segment.voice_config.prompt_text or ""
        instruct_text = segment.instruct_text or ""

        try:
            prompt_audio_hash = _sha1_file(prompt_audio_path)
        except Exception:
            prompt_audio_hash = ""

        req = {
            "text": segment.text,
            "voice_id": segment.voice_config.name,
            "mode": mode,
            "prompt_text": prompt_text,
            "prompt_audio": prompt_audio_path,
            "instruct_text": instruct_text,
            "speed": 1.0,
            "variation_seed": version,
            "selected_ref_asset_id": "",
            "schema_version": CACHE_SCHEMA_VERSION,
            "model_dir": model_dir,
            "fp16": bool(fp16),
            "load_trt": bool(load_trt),
            "load_vllm": bool(load_vllm),
            "is_v3": bool(is_v3),
            "prompt_audio_hash": prompt_audio_hash,
        }

        def _prepare_char_config(req_in: dict) -> dict:
            return {
                "name": req_in.get("voice_id", ""),
                "mode": req_in.get("mode", ""),
                "prompt_text": req_in.get("prompt_text", ""),
                "prompt_audio": req_in.get("prompt_audio", ""),
                "instruct_text": req_in.get("instruct_text", ""),
            }

        def _compute_cache_key(req_in: dict, cfg: dict, part_index: int):
            id_info = _build_segment_cache_identity(
                schema_version=req_in.get("schema_version", CACHE_SCHEMA_VERSION),
                model_dir=req_in.get("model_dir", ""),
                fp16=bool(req_in.get("fp16", False)),
                load_trt=bool(req_in.get("load_trt", True)),
                load_vllm=bool(req_in.get("load_vllm", False)),
                is_v3=bool(req_in.get("is_v3", False)),
                voice_id=cfg.get("name", ""),
                mode=cfg.get("mode", ""),
                prompt_text=cfg.get("prompt_text", ""),
                instruct_text=cfg.get("instruct_text", ""),
                prompt_audio_hash=req_in.get("prompt_audio_hash", ""),
                selected_ref_asset_id=req_in.get("selected_ref_asset_id", ""),
                variation_seed=_safe_int(req_in.get("variation_seed", 0), 0),
                text=req_in.get("text", ""),
                speed=float(req_in.get("speed", 1.0)),
                part_index=int(part_index or 0),
            )
            req_norm = dict(req_in)
            req_norm["text"] = id_info.get("text_norm", req_norm.get("text", ""))
            return id_info["request_hash"], req_norm, str(req_in.get("selected_ref_asset_id", "")).strip()

        def _run_sync_synthesis(req_norm: dict, cfg: dict):
            seg_proxy = SimpleNamespace(
                text=str(req_norm.get("text", "") or ""),
                voice_config=segment.voice_config,
                instruct_text=str(req_norm.get("instruct_text", "") or ""),
                mode=cfg.get("mode", ""),
            )
            inference_func = self.get_inference_function(segment)
            outputs = list(inference_func(seg_proxy, cfg.get("prompt_audio", "")))
            wav_bytes = self._tts_outputs_to_wav_bytes(outputs)
            return wav_bytes, cfg

        result = _syn_run_synthesis(
            req=req,
            prepare_char_config=_prepare_char_config,
            compute_cache_key=_compute_cache_key,
            run_sync_synthesis=_run_sync_synthesis,
            cache=cache,
            part_index=0,
            sync_wait_ms=60_000,
            wait_inflight_on_conflict=True,
        )

        self.progress.emit(f"{'Cache hit' if result.cache_hit else 'Cache miss'}: {result.cache_key}")
        filename = self.generate_filename(segment, 0, version)
        filepath = os.path.join(project_output_dir, filename)
        if result.cache_path and os.path.exists(result.cache_path):
            cache.link_or_copy_to(result.cache_path, filepath)
        else:
            with open(filepath, "wb") as f:
                f.write(result.wav_bytes)
        self.progress.emit(f"Saved: {filename}")
        return [filepath]

    def _run_segment_legacy(
        self,
        *,
        segment: TaskSegment,
        cache: CacheManager,
        project_output_dir: str,
        fp16: bool,
        model_dir: str,
        load_trt: bool,
        load_vllm: bool,
        is_v3: bool,
    ) -> List[str]:
        prompt_audio_path = segment.voice_config.prompt_audio
        version = segment.run_count + 1
        mode = segment.mode or segment.voice_config.mode
        prompt_text = segment.voice_config.prompt_text or ""
        instruct_text = segment.instruct_text or ""
        try:
            prompt_audio_hash = _sha1_file(prompt_audio_path)
        except Exception:
            prompt_audio_hash = ""

        cache_identity_common = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "model_dir": model_dir,
            "fp16": fp16,
            "load_trt": load_trt,
            "load_vllm": load_vllm,
            "is_v3": is_v3,
            "voice_id": segment.voice_config.name,
            "mode": mode,
            "prompt_text": prompt_text,
            "instruct_text": instruct_text,
            "prompt_audio_hash": prompt_audio_hash,
            "selected_ref_asset_id": "",
            "variation_seed": version,
            "text": segment.text,
            "speed": 1.0,
        }

        cache_path0 = None
        req_hash0 = ""
        try:
            id0 = _build_segment_cache_identity(part_index=0, **cache_identity_common)
            req_hash0 = id0["request_hash"]
            cache_path0 = cache.get_path(req_hash0)
        except Exception:
            cache_identity_common = None

        if cache_path0:
            self.progress.emit(f"Cache hit: {req_hash0}")
            filename = self.generate_filename(segment, 0, version)
            filepath = os.path.join(project_output_dir, filename)
            cache.link_or_copy_to(cache_path0, filepath)
            self.progress.emit(f"Saved: {filename}")
            return [filepath]

        segment_files = []
        inference_func = self.get_inference_function(segment)

        for sub_idx, result in enumerate(inference_func(segment, prompt_audio_path)):
            if not self.is_running:
                break

            filename = self.generate_filename(segment, sub_idx, segment.run_count + 1)
            filepath = os.path.join(project_output_dir, filename)
            torchaudio.save(filepath, result["tts_speech"], self.cosyvoice.sample_rate)
            segment_files.append(filepath)

            try:
                with open(filepath, "rb") as f:
                    wav_bytes = f.read()
                if cache_identity_common is not None:
                    id_part = _build_segment_cache_identity(part_index=int(sub_idx), **cache_identity_common)
                    req_hash = id_part["request_hash"]
                    cache.put_bytes(req_hash, wav_bytes, meta={"voice_id": segment.voice_config.name, "gui": True})
                    self.progress.emit(f"   Cache PUT: {req_hash}")
            except Exception:
                pass

            self.progress.emit(f"Saved: {filename}")

        return segment_files

    def _tts_outputs_to_wav_bytes(self, outputs: list) -> bytes:
        tts_speeches = []
        for item in outputs:
            speech = None
            if isinstance(item, dict):
                speech = item.get("tts_speech")
            elif torch.is_tensor(item):
                speech = item
            if speech is None or not torch.is_tensor(speech):
                continue
            if speech.dim() == 1:
                speech = speech.unsqueeze(0)
            if speech.dim() > 2:
                speech = speech.squeeze()
                if speech.dim() == 1:
                    speech = speech.unsqueeze(0)
            tts_speeches.append(speech.detach().cpu())

        if not tts_speeches:
            raise RuntimeError("model returned empty audio")

        audio_data = tts_speeches[0] if len(tts_speeches) == 1 else torch.concat(tts_speeches, dim=1)
        sample_rate = int(getattr(self.cosyvoice, "sample_rate", 22050) or 22050)
        buffer = io.BytesIO()
        torchaudio.save(buffer, audio_data, sample_rate, format="wav")
        return buffer.getvalue()

    def load_model(self):
        """Load CosyVoice model."""
        from .utils import load_cosyvoice_model
        return load_cosyvoice_model()
    
    def get_inference_function(self, segment: TaskSegment):
        # Pick inference behavior by keywords to avoid hard dependency on UI language.
        mode_raw = str(getattr(segment, "mode", "") or getattr(segment.voice_config, "mode", "") or "").strip()
        mode = _syn_normalize_inference_mode(mode_raw)
        is_v3 = "CosyVoice3" in str(getattr(self.cosyvoice, "model_dir", "") or "")

        if mode == "instruction":
            def inference(seg, prompt_audio):
                instruct_text = str(getattr(seg, "instruct_text", "") or "")
                if is_v3 and instruct_text:
                    instruct_text = _cv3_norm_instruct(instruct_text)
                return self.cosyvoice.inference_instruct2(
                    seg.text, instruct_text,
                    prompt_audio, stream=False
                )
            return inference

        if mode == "fine_grained":
            def inference(seg, prompt_audio):
                text = str(getattr(seg, "text", "") or "")
                if is_v3 and "<|endofprompt|>" not in text:
                    text = f"You are a helpful assistant.<|endofprompt|>{text}"
                return self.cosyvoice.inference_cross_lingual(text, prompt_audio, stream=False)
            return inference

        if mode == "reference_timbre":
            def inference(seg, prompt_audio):
                prompt_text = str(getattr(seg.voice_config, "prompt_text", "") or "")
                char_name = str(getattr(seg.voice_config, "name", "") or "")
                if is_v3 and "<|endofprompt|>" not in prompt_text and prompt_text:
                    prompt_text = _cv3_prefix_prompt(prompt_text)
                try:
                    available_spks = self.cosyvoice.list_available_spks()
                except Exception:
                    available_spks = []
                if char_name and (char_name not in available_spks):
                    self.progress.emit(f"[RefMode] Register speaker: {char_name}")
                    self.cosyvoice.add_zero_shot_spk(prompt_text, prompt_audio, char_name)
                else:
                    self.progress.emit(f"[RefMode] Speaker cache hit: {char_name}")
                return self.cosyvoice.inference_zero_shot(
                    seg.text, prompt_text,
                    prompt_audio, stream=False,
                    zero_shot_spk_id=char_name
                )
            return inference

        # Default: zero-shot
        def inference(seg, prompt_audio):
            prompt_text = str(getattr(seg.voice_config, "prompt_text", "") or "")
            if is_v3 and "<|endofprompt|>" not in prompt_text and prompt_text:
                prompt_text = _cv3_prefix_prompt(prompt_text)
            return self.cosyvoice.inference_zero_shot(seg.text, prompt_text, prompt_audio, stream=False)

        return inference
    
    def generate_filename(self, segment: TaskSegment, sub_index: int, version: int) -> str:
        """Build output filename for one generated part."""
        # Use the first 10 chars as filename preview.
        text_preview = self.sanitize_filename(segment.text[:10])
        
        # Pattern: segmentIndex_version_textPreview_partIndex.wav
        return f"{segment.index}_{version}_{text_preview}_{sub_index+1}.wav"
    
    def sanitize_filename(self, text: str) -> str:
        """Sanitize filename for Windows compatibility."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            text = text.replace(char, '')
        text = ''.join(char for char in text if ord(char) >= 32)
        text = text.replace(' ', '_').replace('\n', '_').replace('\t', '_')
        while '__' in text:
            text = text.replace('__', '_')
        text = text.strip('_')
        return text or 'audio'


class V2AudioGenerationWorker(QThread):
    """
    Generate audio by calling v2 HTTP API (preferred path for cache/jobs/emotion voices).

    This worker writes WAV bytes returned by /api/v2/synthesize to the same output folder layout
    as AudioGenerationWorker so TaskPlan UI keeps working.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    segment_finished = pyqtSignal(int, list)

    def __init__(
        self,
        segments: List[TaskSegment],
        output_dir: str,
        project_name: str,
        *,
        base_url: str,
        api_key: str = "",
        timeout_s: float = 60.0,
    ):
        super().__init__()
        self.segments = segments
        self.output_dir = output_dir
        self.project_name = project_name
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout_s = float(timeout_s)
        self.is_running = True

    def stop(self):
        self.is_running = False

    def _headers(self) -> dict:
        h = {}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def sanitize_filename(self, text: str) -> str:
        invalid_chars = '<>:"/\\\\|?*'
        for char in invalid_chars:
            text = text.replace(char, "")
        text = "".join(char for char in text if ord(char) >= 32)
        text = text.replace(" ", "_").replace("\n", "_").replace("\t", "_")
        while "__" in text:
            text = text.replace("__", "_")
        text = text.strip("_")
        return text or "audio"

    def generate_filename(self, segment: TaskSegment, sub_index: int, version: int) -> str:
        text_preview = self.sanitize_filename((segment.text or "")[:10])
        return f"{segment.index}_{version}_{text_preview}_{sub_index+1}.wav"

    def run(self):
        try:
            if not self.base_url:
                raise RuntimeError("v2 base_url is empty")

            project_output_dir = os.path.join(self.output_dir, self.project_name)
            os.makedirs(project_output_dir, exist_ok=True)

            all_generated_files = []

            for segment in self.segments:
                if not self.is_running:
                    break

                version = int(getattr(segment, "run_count", 0) or 0) + 1
                mode = segment.mode or segment.voice_config.mode
                instruct_text = segment.instruct_text or segment.voice_config.instruct_text or ""
                mode_norm = _syn_normalize_inference_mode(mode)
                use_instruction = (mode_norm == "instruction") and bool(instruct_text.strip())

                self.progress.emit(f"[v2] synth segment {segment.index} / voice={segment.voice_config.name}")

                payload = {
                    "text": segment.text,
                    "voice_id": segment.voice_config.name,
                    "mode": mode,
                    "speed": 1.0,
                    "instruct_text": instruct_text,
                    "use_instruction": bool(use_instruction),
                    "instruction": instruct_text if use_instruction else "",
                    "variation_seed": version,
                    "response_format": "audio",
                }

                url = f"{self.base_url}/api/v2/synthesize"
                r = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout_s)
                if r.status_code >= 400:
                    # Try to parse structured error.
                    try:
                        j = r.json()
                        raise RuntimeError(f"v2 error {r.status_code}: {j}")
                    except Exception:
                        raise RuntimeError(f"v2 error {r.status_code}: {r.text[:200]}")

                wav_bytes = r.content or b""
                if not wav_bytes:
                    raise RuntimeError("v2 returned empty audio")

                filename = self.generate_filename(segment, 0, version)
                filepath = os.path.join(project_output_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(wav_bytes)

                segment_files = [filepath]
                all_generated_files.append(filepath)
                segment.add_version(segment_files)
                self.segment_finished.emit(segment.index, segment_files)
                self.progress.emit(f"[v2] output: {filename}")

            if self.is_running:
                self.finished.emit(all_generated_files)

        except Exception as e:
            self.error.emit(f"v2 synthesis failed: {str(e)}")
