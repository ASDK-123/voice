import time
import io
import os
import sys
import json
import uuid
import argparse
import subprocess
import tempfile
import logging
import warnings
import threading
import hashlib
import queue
from pathlib import Path
from functools import wraps
from types import SimpleNamespace

# 绂佺敤 tqdm
os.environ["TQDM_DISABLE"] = "1"
# Ignore all warnings in runtime logs.
warnings.filterwarnings("ignore")

import torch
print(f"CUDA Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: Running on CPU! This will be very slow.")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, '..'))
sys.path.insert(0, os.path.join(ROOT_DIR, '../third_party/AcademiCodec'))
sys.path.insert(0, os.path.join(ROOT_DIR, '../third_party/Matcha-TTS'))

import numpy as np
from flask import Flask, request, Response, stream_with_context, g
import torch
import torchaudio

from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.utils.file_utils import load_wav
from flask_cors import CORS

try:
    from core.cache_manager import CacheManager
    from core.cache_keys import (
        sha1_file as _sha1_file,
        cozyvoice3_prefix_prompt as _cv3_prefix_prompt,
        cozyvoice3_normalize_instruct as _cv3_norm_instruct,
        safe_float as _safe_float,
        safe_int as _safe_int,
    )
    from core.synthesis.resolve_voice import resolve_voice_or_fallback as _syn_resolve_voice_or_fallback
    from core.synthesis.select_ref import select_ref_asset_id as _syn_select_ref_asset_id
    from core.synthesis.cache_key import build_cache_identity as _syn_build_cache_identity
    from core.synthesis.engine import run_synthesis as _syn_run_synthesis
    from core.synthesis.normalize import (
        clean_text_for_inference as _syn_clean_text_for_inference,
        normalize_inference_mode as _syn_normalize_inference_mode,
    )
    from core.storage import VoicesFileStore
except Exception:
    # Allows running this file in alternative import contexts.
    from .cache_manager import CacheManager  # type: ignore
    from .cache_keys import (  # type: ignore
        sha1_file as _sha1_file,
        cozyvoice3_prefix_prompt as _cv3_prefix_prompt,
        cozyvoice3_normalize_instruct as _cv3_norm_instruct,
        safe_float as _safe_float,
        safe_int as _safe_int,
    )
    from .synthesis.resolve_voice import resolve_voice_or_fallback as _syn_resolve_voice_or_fallback  # type: ignore
    from .synthesis.select_ref import select_ref_asset_id as _syn_select_ref_asset_id  # type: ignore
    from .synthesis.cache_key import build_cache_identity as _syn_build_cache_identity  # type: ignore
    from .synthesis.engine import run_synthesis as _syn_run_synthesis  # type: ignore
    from .synthesis.normalize import (  # type: ignore
        clean_text_for_inference as _syn_clean_text_for_inference,
        normalize_inference_mode as _syn_normalize_inference_mode,
    )
    from .storage import VoicesFileStore  # type: ignore

# v2 helpers (request_id, errors, sqlite assets store)
from core.v2.assets_sqlite import AssetsSqliteStore
from core.v2.errors import AppError, coerce_exception
from core.v2.http import install_middleware as _v2_install_http, json_ok as _v2_http_ok, json_error as _v2_http_error
from core.v2.logging import log_event as _v2_log_event
from core.v2.request_id import pick_request_id as _v2_pick_request_id
from core.api_v2_routes import create_v2_blueprint as _create_v2_blueprint
from core.server.routes_v2_misc import create_v2_misc_blueprint as _create_v2_misc_blueprint

# ==================== Logging ====================

# Dedicated API logger.
api_logger = logging.getLogger('cosyvoice_api')
api_logger.setLevel(logging.INFO)
api_logger.propagate = False  # Avoid duplicate logs through root logger.

# Silence noisy third-party logs.
logging.getLogger('cosyvoice').setLevel(logging.ERROR)
logging.getLogger('Matcha-TTS').setLevel(logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('torch').setLevel(logging.ERROR)
logging.getLogger('lightning').setLevel(logging.ERROR)

# In-process callback fanout for UI log streaming.
log_callbacks = []

class CallbackHandler(logging.Handler):
    """Emit formatted log lines to registered callbacks."""
    def emit(self, record):
        msg = self.format(record)
        for callback in log_callbacks:
            try:
                callback(msg)
            except:
                pass

# Callback handler.
callback_handler = CallbackHandler()
callback_handler.setFormatter(logging.Formatter('%(message)s'))
api_logger.addHandler(callback_handler)

# Console handler.
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[%(name)s] %(message)s'))
api_logger.addHandler(console_handler)

def set_log_callback(callback):
    """Register a log callback used by desktop UI."""
    log_callbacks.append(callback)

# ==================== 閰嶇疆鍔犺浇 ====================

def _resolve_default_voices_config_path() -> str:
    """
    Resolve runtime voices config path with M4 single-source priority.

    Priority:
    1) app_config.json:v2_voices_config_path
    2) config/super_agent.json
    3) config/voices_v2.json
    """
    repo_root = os.path.abspath(os.path.join(ROOT_DIR, '..'))
    app_config_path = os.path.join(repo_root, 'app_config.json')
    candidates = []

    if os.path.exists(app_config_path):
        try:
            with open(app_config_path, 'r', encoding='utf-8') as f:
                app_cfg = json.load(f) or {}
            v2_path = str((app_cfg.get('v2_voices_config_path') or '')).strip()
            if v2_path:
                if not os.path.isabs(v2_path):
                    v2_path = os.path.abspath(os.path.join(repo_root, v2_path))
                candidates.append(v2_path)
        except Exception:
            pass

    candidates.append(os.path.abspath(os.path.join(repo_root, 'config', 'super_agent.json')))
    candidates.append(os.path.abspath(os.path.join(repo_root, 'config', 'voices_v2.json')))

    dedup = []
    seen = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        dedup.append(p)

    for p in dedup:
        if p.lower().endswith('.json') and os.path.exists(p):
            return p
    return dedup[0] if dedup else os.path.abspath(os.path.join(repo_root, 'config', 'super_agent.json'))


class CharacterConfig:
    """Role config manager backed by v2 single-source voices store."""

    def __init__(self, config_file: str):
        cfg = (config_file or '').strip()
        if not cfg:
            cfg = _resolve_default_voices_config_path()
        if not os.path.isabs(cfg):
            cfg = os.path.abspath(os.path.join(ROOT_DIR, '..', cfg))
        self.config_file = cfg
        self.characters = {}
        self._legacy_hint_logged = False
        self._store = VoicesFileStore(self.config_file, allow_legacy_write=False)
        self.load_characters()

    def load_characters(self):
        """Reload voices from single-source file."""
        try:
            self._store.reload()
            rows = self._store.list_voices()
            new_chars = {}
            for row in rows:
                name = str((row or {}).get('name') or '').strip()
                if name:
                    new_chars[name] = dict(row)
            self.characters = new_chars

            if os.path.exists(self.config_file):
                api_logger.info(f"[M4] Loaded {len(self.characters)} voices from {os.path.basename(self.config_file)}")
            else:
                api_logger.warning(f"[M4] Voices config not found yet: {self.config_file} (will be created on first save)")

            self._warn_legacy_import_hint_if_needed()
        except Exception as e:
            api_logger.error(f"[M4] Failed to load {self.config_file}: {e}")

    def _warn_legacy_import_hint_if_needed(self):
        if self._legacy_hint_logged:
            return
        if self.characters:
            return
        if VoicesFileStore.is_legacy_voice_path(self.config_file):
            return

        repo_root = os.path.abspath(os.path.join(ROOT_DIR, '..'))
        legacy_candidates = [
            os.path.join(repo_root, 'config', 'config.json'),
            os.path.join(repo_root, 'config', 'voice_config.json'),
        ]
        existing_legacy = []
        for p in legacy_candidates:
            if not os.path.exists(p):
                continue
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    existing_legacy.append(p)
                elif isinstance(data, dict) and data:
                    existing_legacy.append(p)
            except Exception:
                continue

        if existing_legacy:
            api_logger.warning(
                "[M4] v2 voices config is empty; legacy voice configs detected. "
                "Please import with scripts/import_legacy_voice_config_to_v2.py"
            )
            for p in existing_legacy:
                api_logger.warning(f"[M4] legacy voice source detected: {p}")
            self._legacy_hint_logged = True

    def get_character(self, char_name: str) -> dict:
        voice = self.characters.get(char_name)
        return dict(voice) if isinstance(voice, dict) else None

    def list_characters(self) -> list:
        return sorted(self.characters.keys())

    def get_all_characters(self) -> list:
        return [dict(self.characters[name]) for name in self.list_characters()]

    def upsert_character(self, voice: dict):
        saved = self._store.upsert_voice(voice or {})
        self.characters[saved['name']] = dict(saved)

    def delete_character(self, name: str) -> bool:
        deleted = self._store.delete_voice(name)
        if deleted:
            self.characters.pop(name, None)
        return bool(deleted)

    def save(self):
        self._store.save()
        self.load_characters()

def clean_text(text: str) -> str:
    """Compatibility wrapper: use shared synthesis text cleaner."""
    return _syn_clean_text_for_inference(text)


# ==================== FFmpeg Helpers ====================

def run_ffmpeg(input_file: str, output_file: str, args: list = None):
    """
    Run FFmpeg command using system executable.
    
    Args:
        input_file: input audio file path
        output_file: output audio file path
        args: extra ffmpeg args
    """
    if args is None:
        args = []
    
    cmd = ['ffmpeg', '-i', input_file, '-y'] + args + [output_file]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: FFmpeg error: {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("ERROR: FFmpeg not found in system PATH. Please install FFmpeg.")
        return False


def speed_change_ffmpeg(input_audio_path: str, speed: float, output_path: str) -> bool:
    """
    Apply speed transform via FFmpeg atempo filter.
    
    Args:
        input_audio_path: input audio file path
        speed: speed multiplier (0.5-2.0)
        output_path: output audio file path
    
    Returns:
        True if succeeded, False otherwise.
    """
    if speed < 0.5 or speed > 2.0:
        print("WARNING: Speed out of range [0.5-2.0], clamping to valid range")
        speed = max(0.5, min(2.0, speed))
    
    # FFmpeg atempo is used for speed transform.
    filter_args = ['-filter:a', f'atempo={speed}']
    return run_ffmpeg(input_audio_path, output_path, filter_args)


# ==================== CosyVoice3 Init ====================

def load_cosyvoice_model():
    """Load local CosyVoice model via shared utils."""
    try:
        # Relative import when used as package.
        from .utils import load_cosyvoice_model as _load_model
    except ImportError:
        # Absolute import when executed as script.
        from core.utils import load_cosyvoice_model as _load_model
    return _load_model()

# Global model handle.
cosyvoice = None

# ==================== Dependency Injection ====================

def set_globals(model, config_manager):
    """
    Set runtime globals, primarily used by desktop embedded server.
    
    Args:
        model: CosyVoice model instance
        config_manager: role config manager (get_character/list_characters)
    """
    global cosyvoice, character_config
    cosyvoice = model
    character_config = config_manager
    print("INFO: API globals set from external source")

# ==================== Flask App ====================

app = Flask(__name__)
# CORS support.
CORS(app)

# Upload safety: Flask will reject larger payloads with 413.
# Override default with `MAX_UPLOAD_MB`.
try:
    _max_upload_mb = _safe_int(os.getenv("MAX_UPLOAD_MB", "50"), 50)
    app.config["MAX_CONTENT_LENGTH"] = int(_max_upload_mb) * 1024 * 1024
except Exception:
    pass

# Request id middleware (applies to all endpoints).
_v2_install_http(app, logger=api_logger, pick_request_id=_v2_pick_request_id)

# Global role config, initialized during startup.
character_config = None

# Minimum text length gate.
min_text_length = 0  # default 0 = no minimum


# Stream output switch.
STREAM_MODE = False

# Speaker cache switch.
SPK_CACHE_MODE = False

def set_min_text_length(length: int):
    """Set minimum text length."""
    global min_text_length
    min_text_length = length
    api_logger.debug(f"[api] min_text_length set to {length}")

def set_stream_mode(enabled: bool):
    """Enable or disable stream output mode."""
    global STREAM_MODE
    STREAM_MODE = enabled
    api_logger.info(f"[api] stream mode set to {enabled}")

def set_spk_cache_mode(enabled: bool):
    """Enable/disable speaker cache mode."""
    global SPK_CACHE_MODE
    SPK_CACHE_MODE = enabled
    api_logger.info(f"[api] speaker cache mode set to {enabled}")


# ==================== API v2 State ====================

PROJECT_ROOT = os.path.abspath(os.path.join(ROOT_DIR, '..'))
DATA_ROOT = os.path.join(PROJECT_ROOT, 'data')
V2_AUDIO_DIR = os.path.join(DATA_ROOT, 'assets', 'audio')
V2_OUTPUT_DIR = os.path.join(DATA_ROOT, 'outputs')
V2_INDEX_PATH = os.path.join(DATA_ROOT, 'api_v2_assets.json')
V2_CACHE_ROOT = os.path.join(DATA_ROOT, 'cache')
V2_DB_PATH = os.path.join(DATA_ROOT, 'api_v2_assets.sqlite3')

os.makedirs(V2_AUDIO_DIR, exist_ok=True)
os.makedirs(V2_OUTPUT_DIR, exist_ok=True)
os.makedirs(V2_CACHE_ROOT, exist_ok=True)

V2_LOCK = threading.Lock()
V2_JOB_LOCK = threading.Lock()
V2_MODEL_LOCK = threading.Lock()
V2_JOBS = {}
V2_ASSETS = AssetsSqliteStore(V2_DB_PATH)

V2_CACHE_MAX_MB = _safe_int(os.getenv("CACHE_MAX_MB", "500"), 500)
V2_CACHE = CacheManager(V2_CACHE_ROOT, max_bytes=V2_CACHE_MAX_MB * 1024 * 1024)
V2_CACHE_SCHEMA_VERSION = "cv_cache_v2"
V2_METRICS_LOCK = threading.Lock()
V2_METRICS = {
    "cache_hit": 0,
    "cache_miss": 0,
    "jobs_enqueued": 0,
    "jobs_completed": 0,
    "jobs_failed": 0,
}

V2_JOB_QUEUE: "queue.PriorityQueue[tuple]" = queue.PriorityQueue()
V2_JOB_WORKER_STARTED = False


def _v2_maybe_migrate_assets_json():
    """
    Backward compatibility: if legacy JSON index exists, import it into SQLite.
    """
    try:
        if os.path.exists(V2_INDEX_PATH):
            n = V2_ASSETS.migrate_from_json_index(V2_INDEX_PATH)
            api_logger.info(f"[v2] migrated legacy assets index to sqlite: {n} rows")
    except Exception as e:
        api_logger.warning(f"[v2] migrate legacy assets index failed: {e}")


def _v2_get_api_key():
    return os.getenv('V2_API_KEY', '').strip() or os.getenv('API_KEY', '').strip()


def require_v2_api_key(fn):
    @wraps(fn)
    def _wrapper(*args, **kwargs):
        required = _v2_get_api_key()
        if not required:
            return fn(*args, **kwargs)
        provided = request.headers.get('X-API-Key', '').strip()
        if not provided:
            auth = request.headers.get('Authorization', '').strip()
            if auth.lower().startswith('bearer '):
                provided = auth[7:].strip()
        if provided != required:
            return _v2_json_error(AppError(code="unauthorized", message="unauthorized", status=401))
        return fn(*args, **kwargs)
    return _wrapper


def _v2_hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _v2_req_id() -> str:
    return getattr(g, "request_id", "") or ""


def _v2_json_ok(payload: dict, status: int = 200):
    return _v2_http_ok(app, payload, status=int(status))


def _v2_json_error(e: Exception):
    return _v2_http_error(app, api_logger, e)


def _v2_new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _v2_get_asset(asset_id: str):
    with V2_LOCK:
        return V2_ASSETS.get(asset_id)


def _v2_save_audio_bytes(audio_bytes: bytes, source_name: str = 'upload.wav', kind: str = 'ref') -> dict:
    ext = os.path.splitext(source_name)[1].lower() or '.wav'
    if ext not in {'.wav', '.mp3', '.flac', '.m4a', '.ogg'}:
        ext = '.wav'
    asset_id = _v2_new_id(kind)
    filename = f"{asset_id}{ext}"
    file_path = os.path.join(V2_AUDIO_DIR, filename)
    with open(file_path, 'wb') as f:
        f.write(audio_bytes)

    now = int(time.time())
    meta = {
        'asset_id': asset_id,
        'filename': filename,
        'path': file_path,
        'size': len(audio_bytes),
        'sha1': _v2_hash_bytes(audio_bytes),
        'created_at': now,
        'kind': kind
    }
    with V2_LOCK:
        V2_ASSETS.upsert(meta)
    return meta


def _v2_register_file_as_asset(file_path: str, source_name: str, kind: str, extra_meta: dict = None) -> dict:
    """
    Register an existing audio file into v2 asset index.
    Prefer hardlink; fall back to copy.
    """
    extra_meta = extra_meta or {}
    ext = os.path.splitext(source_name)[1].lower() or os.path.splitext(file_path)[1].lower() or '.wav'
    if ext not in {'.wav', '.mp3', '.flac', '.m4a', '.ogg'}:
        ext = '.wav'
    asset_id = _v2_new_id(kind)
    filename = f"{asset_id}{ext}"
    target_path = os.path.join(V2_AUDIO_DIR, filename)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        if os.path.exists(target_path):
            os.remove(target_path)
    except Exception:
        pass
    linked = False
    try:
        os.link(file_path, target_path)
        linked = True
    except Exception:
        linked = False

    if not linked:
        import shutil

        shutil.copy2(file_path, target_path)

    now = int(time.time())
    size_bytes = int(os.path.getsize(target_path))
    try:
        sha1 = _sha1_file(target_path)
    except Exception:
        sha1 = ''

    meta = {
        'asset_id': asset_id,
        'filename': filename,
        'path': target_path,
        'size': size_bytes,
        'sha1': sha1,
        'created_at': now,
        'kind': kind,
        'linked': linked,
    }
    meta.update(extra_meta)
    with V2_LOCK:
        V2_ASSETS.upsert(meta)
    return meta


def _v2_maybe_start_job_worker():
    global V2_JOB_WORKER_STARTED
    if V2_JOB_WORKER_STARTED:
        return
    V2_JOB_WORKER_STARTED = True

    def _worker_loop():
        while True:
            try:
                prio, job_id = V2_JOB_QUEUE.get()
                try:
                    _v2_run_job(job_id)
                finally:
                    V2_JOB_QUEUE.task_done()
            except Exception:
                # Keep worker alive on unexpected exceptions.
                time.sleep(0.1)

    t = threading.Thread(target=_worker_loop, daemon=True, name="v2_job_worker")
    t.start()


def _v2_enqueue_job(job_id: str, priority: int = 100):
    _v2_maybe_start_job_worker()
    V2_JOB_QUEUE.put((int(priority), job_id))
    with V2_METRICS_LOCK:
        V2_METRICS["jobs_enqueued"] += 1


def _v2_resolve_prompt_audio_path(req: dict) -> str:
    asset_id = (req or {}).get('prompt_audio_asset_id', '').strip()
    if asset_id:
        meta = _v2_get_asset(asset_id)
        if not meta:
            raise ValueError(f'prompt_audio_asset_id not found: {asset_id}')
        return meta['path']
    direct_path = (req or {}).get('prompt_audio', '').strip()
    if direct_path:
        if not os.path.isabs(direct_path):
            direct_path = os.path.abspath(os.path.join(PROJECT_ROOT, direct_path))
        if not os.path.exists(direct_path):
            raise ValueError(f'prompt_audio not found: {direct_path}')
        return direct_path
    b64 = (req or {}).get('prompt_audio_base64', '').strip()
    if b64:
        data = __import__('base64').b64decode(b64)
        return _v2_save_audio_bytes(data, source_name='prompt.wav', kind='temp')['path']
    return ''


def _v2_prepare_char_config(req: dict) -> dict:
    req = req or {}
    voice_id = (req.get('voice_id', '') or '').strip() or (req.get('character_name', '') or '').strip()
    character = (req.get('character', '') or '').strip()
    emotion = (req.get('emotion', '') or '').strip()
    variation_seed = _safe_int(req.get('variation_seed', 0), 0)
    policy_override = (req.get('selection_policy', '') or '').strip()
    selected_ref_asset_id = (req.get('selected_ref_asset_id', '') or '').strip()

    resolved_voice_id, voice = _syn_resolve_voice_or_fallback(
        voice_id=voice_id,
        character=character,
        emotion=emotion or "default",
        character_config_get=character_config.get_character,
    )
    # Keep old behavior: explicit missing voice_id should return 4xx via ValueError.
    if voice_id and not voice:
        raise ValueError(f'voice not found: {voice_id}')

    if voice:
        cfg = dict(voice)
        cfg.setdefault('name', resolved_voice_id or voice_id)
        prompt_audio_path = (cfg.get('prompt_audio') or '').strip()
        if prompt_audio_path and not os.path.isabs(prompt_audio_path):
            cfg['prompt_audio'] = os.path.abspath(os.path.join(PROJECT_ROOT, prompt_audio_path))

        ref_ids = cfg.get('ref_asset_ids') or []
        if isinstance(ref_ids, list) and ref_ids:
            selected_ref_asset_id = _syn_select_ref_asset_id(
                voice=cfg,
                text=req.get('text', ''),
                variation_seed=variation_seed,
                policy_override=policy_override,
                selected_ref_asset_id=selected_ref_asset_id,
            )
            if selected_ref_asset_id:
                meta = _v2_get_asset(selected_ref_asset_id)
                if not meta:
                    raise ValueError(f"ref asset not found: {selected_ref_asset_id}")
                cfg['prompt_audio'] = meta.get('path', cfg.get('prompt_audio', ''))
                cfg['prompt_audio_asset_id'] = selected_ref_asset_id
                cfg['prompt_audio_sha1'] = meta.get('sha1', '')
                asset_prompt_text = (meta.get('prompt_text') or meta.get('note') or '')
                asset_prompt_text = (asset_prompt_text or '').strip()
                if asset_prompt_text:
                    cfg['prompt_text'] = asset_prompt_text

        cfg['selected_ref_asset_id'] = selected_ref_asset_id
        return cfg

    prompt_text = (req or {}).get('prompt_text', '').strip()
    prompt_audio = _v2_resolve_prompt_audio_path(req)
    instruct_text = (req or {}).get('instruct_text', '').strip()
    mode = str((req or {}).get('mode') or '').strip() or 'zero_shot'
    if not prompt_audio:
        raise ValueError('prompt audio is required for direct synthesis')
    cfg = {
        'name': (req or {}).get('name', 'api_v2_temp'),
        'mode': mode,
        'prompt_text': prompt_text,
        'prompt_audio': prompt_audio,
        'instruct_text': instruct_text,
        'color': (req or {}).get('color', '#FF6B6B')
    }
    return cfg


def _v2_run_sync_synthesis(req: dict, char_cfg: dict | None = None):
    text = (req or {}).get('text', '').strip()
    if not text:
        raise ValueError('text is required')
    speed = float((req or {}).get('speed', 1.0))
    mode = str((req or {}).get('mode') or '').strip() or 'zero_shot'
    use_instruction = bool((req or {}).get('use_instruction', False))
    instruction = ((req or {}).get('instruction') or '').strip()
    char_cfg = dict(char_cfg or _v2_prepare_char_config(req))

    if use_instruction and instruction:
        # Treat as instruction-enhanced generation; reuse prompt_audio as reference.
        char_cfg['instruct_text'] = instruction
        mode = 'instruction'
    with V2_MODEL_LOCK:
        audio_buffer = _inference(text=text, char_config=char_cfg, mode=mode, speed=speed, stream_response=False)
    if audio_buffer is None:
        raise RuntimeError('inference failed')
    audio_buffer.seek(0)
    return audio_buffer.read(), char_cfg


def _v2_compute_cache_key(req: dict, cfg: dict, part_index: int = 0) -> tuple[str, dict, str]:
    """
    Compute request hash for disk cache.
    Returns: (request_hash, normalized_req, selected_ref_asset_id)
    """
    req = dict(req or {})
    text_raw = req.get('text', '')
    speed = _safe_float(req.get('speed', 1.0), 1.0)
    req['speed'] = speed

    selected_ref_asset_id = (cfg.get('selected_ref_asset_id') or cfg.get('prompt_audio_asset_id') or '').strip()
    prompt_audio_path = (cfg.get('prompt_audio') or '').strip()
    prompt_audio_sha1 = (cfg.get('prompt_audio_sha1') or '').strip()
    if prompt_audio_path and not os.path.isabs(prompt_audio_path):
        prompt_audio_path = os.path.abspath(os.path.join(PROJECT_ROOT, prompt_audio_path))
        cfg['prompt_audio'] = prompt_audio_path
    if not prompt_audio_path or not os.path.exists(prompt_audio_path):
        raise ValueError('prompt_audio not found')

    is_v3 = cosyvoice is not None and 'CosyVoice3' in getattr(cosyvoice, 'model_dir', '')
    mode = str(req.get('mode') or cfg.get('mode') or 'zero_shot').strip()
    variation_seed = _safe_int(req.get('variation_seed', 0), 0)
    use_instruction = bool(req.get('use_instruction', False))
    instruction = (req.get('instruction') or '').strip()
    instruct_text = (req.get('instruct_text') or cfg.get('instruct_text') or '').strip()
    prompt_text = (req.get('prompt_text') or cfg.get('prompt_text') or '').strip()

    prompt_audio_hash = prompt_audio_sha1 or ''
    if not prompt_audio_hash:
        try:
            prompt_audio_hash = _sha1_file(prompt_audio_path)
        except Exception:
            prompt_audio_hash = ''

    try:
        from core.config_manager import ConfigManager
        fp16 = bool(ConfigManager().get('fp16', False))
    except Exception:
        fp16 = False
    model_dir = getattr(cosyvoice, 'model_dir', '') if cosyvoice is not None else ''
    load_trt = True
    load_vllm = os.getenv('ENABLE_VLLM', 'false').lower() == 'true'
    id_info = _syn_build_cache_identity(
        schema_version=V2_CACHE_SCHEMA_VERSION,
        model_dir=model_dir,
        fp16=fp16,
        load_trt=load_trt,
        load_vllm=load_vllm,
        voice_id=(cfg.get('name') or '').strip(),
        mode=mode,
        prompt_text=prompt_text,
        instruct_text=instruct_text,
        prompt_audio_hash=prompt_audio_hash,
        selected_ref_asset_id=selected_ref_asset_id,
        variation_seed=variation_seed,
        text=text_raw,
        speed=speed,
        use_instruction=use_instruction,
        instruction=instruction,
        is_v3=is_v3,
        part_index=int(part_index or 0),
    )
    req['text'] = id_info['text_norm']
    return id_info['request_hash'], req, selected_ref_asset_id


def _v2_run_engine(
    req: dict,
    *,
    part_index: int = 0,
    sync_wait_ms: int = 0,
    wait_inflight_on_conflict: bool = True,
):
    return _syn_run_synthesis(
        req=dict(req or {}),
        prepare_char_config=_v2_prepare_char_config,
        compute_cache_key=_v2_compute_cache_key,
        run_sync_synthesis=lambda req_norm, cfg: _v2_run_sync_synthesis(req_norm, cfg),
        cache=V2_CACHE,
        metrics=V2_METRICS,
        metrics_lock=V2_METRICS_LOCK,
        part_index=int(part_index or 0),
        sync_wait_ms=int(sync_wait_ms or 0),
        wait_inflight_on_conflict=bool(wait_inflight_on_conflict),
    )


def _v2_segment_to_asset(seg_req: dict, segment_index: int) -> tuple[dict, str]:
    """
    Run one segment for v2 jobs with disk cache.
    Returns: (asset_meta, selected_ref_asset_id)
    """
    seg_req = dict(seg_req or {})
    result = _v2_run_engine(
        seg_req,
        part_index=0,
        sync_wait_ms=60_000,
        wait_inflight_on_conflict=True,
    )

    cache_path = result.cache_path
    if cache_path:
        meta = _v2_register_file_as_asset(
            cache_path,
            source_name=f"segment_{segment_index}.wav",
            kind='output',
            extra_meta={
                'cache_key': result.cache_key,
                'cache_hit': bool(result.cache_hit),
                'selected_ref_asset_id': result.selected_ref_asset_id,
            },
        )
        return meta, result.selected_ref_asset_id

    meta = _v2_save_audio_bytes(result.wav_bytes, source_name=f"segment_{segment_index}.wav", kind='output')
    meta['cache_key'] = result.cache_key
    meta['cache_hit'] = bool(result.cache_hit)
    meta['selected_ref_asset_id'] = result.selected_ref_asset_id
    return meta, result.selected_ref_asset_id


def _v2_merge_files_to_wav(file_paths: list, output_name: str = None) -> str:
    if not file_paths:
        raise ValueError('file_paths is empty')
    if not output_name:
        output_name = f"merged_{uuid.uuid4().hex[:8]}.wav"
    output_path = os.path.join(V2_OUTPUT_DIR, output_name)
    list_path = os.path.join(V2_OUTPUT_DIR, f"merge_{uuid.uuid4().hex[:8]}.txt")
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in file_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_path, '-c', 'copy', '-y', output_path]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    finally:
        try:
            os.remove(list_path)
        except Exception:
            pass
    return output_path


def _v2_create_job(payload: dict) -> dict:
    job_id = _v2_new_id('job')
    job = {
        'job_id': job_id,
        'status': 'queued',
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
        'payload': payload,
        'results': [],
        'error': None,
        'cancel_requested': False
    }
    with V2_JOB_LOCK:
        V2_JOBS[job_id] = job
    return job


def _v2_run_job(job_id: str):
    with V2_JOB_LOCK:
        job = V2_JOBS.get(job_id)
        if not job:
            return
        job['status'] = 'running'
        job['updated_at'] = int(time.time())
    payload = job.get('payload', {})
    segments = payload.get('segments', [])
    merge_output = bool(payload.get('merge', False))
    merged_asset = None
    try:
        segment_paths = []
        for idx, seg in enumerate(segments, start=1):
            with V2_JOB_LOCK:
                if V2_JOBS[job_id].get('cancel_requested'):
                    V2_JOBS[job_id]['status'] = 'cancelled'
                    V2_JOBS[job_id]['updated_at'] = int(time.time())
                    return
            meta, selected_ref_asset_id = _v2_segment_to_asset(seg, idx)
            segment_paths.append(meta['path'])
            with V2_JOB_LOCK:
                V2_JOBS[job_id]['results'].append({
                    'segment_index': idx,
                    'voice_name': (seg or {}).get('voice_id') or (seg or {}).get('character') or '',
                    'asset_id': meta['asset_id'],
                    'cache': {'hit': bool(meta.get('cache_hit')), 'key': meta.get('cache_key', '')},
                    'selected_ref_asset_id': selected_ref_asset_id,
                })
                V2_JOBS[job_id]['updated_at'] = int(time.time())

        if merge_output and segment_paths:
            merged_path = _v2_merge_files_to_wav(segment_paths)
            with open(merged_path, 'rb') as f:
                merged_meta = _v2_save_audio_bytes(f.read(), source_name=os.path.basename(merged_path), kind='merged')
            merged_asset = merged_meta['asset_id']

        with V2_JOB_LOCK:
            V2_JOBS[job_id]['status'] = 'completed'
            V2_JOBS[job_id]['merged_asset_id'] = merged_asset
            V2_JOBS[job_id]['updated_at'] = int(time.time())
        with V2_METRICS_LOCK:
            V2_METRICS["jobs_completed"] += 1
    except Exception as e:
        with V2_JOB_LOCK:
            V2_JOBS[job_id]['status'] = 'failed'
            V2_JOBS[job_id]['error'] = str(e)
            V2_JOBS[job_id]['updated_at'] = int(time.time())
        with V2_METRICS_LOCK:
            V2_METRICS["jobs_failed"] += 1


_v2_maybe_migrate_assets_json()


# ==================== Tavern-Compatible API ====================

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def tts_tavern():
    """
    Tavern-compatible TTS endpoint.
    Supports GET/POST and OPTIONS (CORS preflight).
    
    Request body:
    {
        "text": "text to synthesize",
        "speaker": "voice_id",
        "speed": 1.0
    }
    """
    # Handle CORS preflight.
    if request.method == 'OPTIONS':
        response = app.response_class(
            response='',
            status=200,
            mimetype='text/plain'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    try:
        if cosyvoice is None:
            response = app.response_class(
                response=json.dumps({'error': 'model not loaded'}),
                status=500,
                mimetype='application/json'
            )
            return response
        
        # Support both GET and POST.
        if request.method == 'GET':
            data = request.args
            text = data.get('text', '').strip()
            character_name = data.get('speaker', '').strip()
            speed = float(data.get('speed', 1.0))
            instruct_text = data.get('instruct', '').strip()
        else:
            # POST request
            data = request.get_json() if request.is_json else {}
            text = data.get('text', '').strip()
            character_name = data.get('speaker', '').strip()  # Tavern uses "speaker".
            speed = float(data.get('speed', 1.0))
            instruct_text = data.get('instruct', '').strip()  # Optional instruction override.

        api_logger.info(
            f"[api] {request.method} / request: speaker={character_name}, "
            f"speed={speed}, text_len={len(text)}, instruct={'Yes' if instruct_text else 'No'}"
        )
        
        if not text:
            response = app.response_class(
                response=json.dumps({'error': 'text cannot be empty'}),
                status=400,
                mimetype='application/json'
            )
            return response
        
        if not character_name:
            response = app.response_class(
                response=json.dumps({'error': 'speaker is required'}),
                status=400,
                mimetype='application/json'
            )
            return response
        
        # Resolve voice config.
        char_config_origin = character_config.get_character(character_name)
        if not char_config_origin:
            response = app.response_class(
                response=json.dumps({'error': f'voice not found: {character_name}'}),
                status=404,
                mimetype='application/json'
            )
            return response
        
        # Apply one-off instruction override from request.
        if instruct_text:
            # Shallow copy to avoid mutating shared config.
            char_config = char_config_origin.copy()
            char_config['mode'] = '指令控制'
            char_config['instruct_text'] = instruct_text
            api_logger.info(f"[api] apply instruction override: {instruct_text}")
        else:
            char_config = char_config_origin
        
        # Normalize text before synthesis.
        original_text = text
        text = clean_text(text)
        if len(text) != len(original_text):
            api_logger.warning(f'Text cleaned: {len(original_text)} -> {len(text)} chars')
        
        # Enforce minimum text length.
        if len(text) < min_text_length:
            error_msg = f'text too short: {len(text)} < min_text_length={min_text_length}'
            api_logger.warning(error_msg)
            response = app.response_class(
                response=json.dumps({'error': error_msg}),
                status=400,
                mimetype='application/json'
            )
            return response
        
        api_logger.info(
            f"[api] synthesis start: mode={char_config.get('mode')}, "
            f"speed={speed}, text_len={len(text)}"
        )
        
        # Keep v1 behavior while ensuring execution path goes through unified engine.
        engine_req = {
            'text': text,
            'voice_id': character_name,
            'mode': char_config.get('mode', ''),
            'speed': speed,
            'instruct_text': instruct_text or char_config.get('instruct_text', ''),
            'use_instruction': bool(instruct_text.strip()),
            'instruction': instruct_text,
        }
        result = _v2_run_engine(
            engine_req,
            part_index=0,
            sync_wait_ms=0,
            wait_inflight_on_conflict=True,
        )
        do_stream = STREAM_MODE
        if do_stream:
            def generate():
                yield result.wav_bytes

            return Response(stream_with_context(generate()), mimetype='audio/wav')
        return Response(result.wav_bytes, mimetype='audio/wav')
    
    except Exception as e:
        print(f"ERROR: Error in POST /: {e}")
        import traceback
        traceback.print_exc()
        error_msg = f'request exception: {str(e)[:100]}'
        response = app.response_class(
            response=json.dumps({'error': error_msg}),
            status=500,
            mimetype='application/json'
        )
        return response

@app.route('/api/tts', methods=['POST', 'OPTIONS'])
def tts_api():
    """
    Standard TTS endpoint.
    
    Request body:
    {
        "text": "text to synthesize",
        "character_name": "voice_id",
        "mode": "零样本复制|精细控制|指令控制",
        "speed": 1.0
    }
    """
    # Handle CORS preflight.
    if request.method == 'OPTIONS':
        response = app.response_class(
            response='',
            status=200,
            mimetype='text/plain'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    try:
        if cosyvoice is None:
            response = app.response_class(
                response=json.dumps({'error': 'model not loaded'}),
                status=500,
                mimetype='application/json'
            )
            return response
        
        data = request.get_json()
        
        text = data.get('text', '').strip()
        character_name = data.get('character_name', '').strip()
        mode = data.get('mode', None)
        speed = float(data.get('speed', 1.0))
        
        api_logger.info(
            f"[api] POST /api/tts: character={character_name}, mode={mode}, "
            f"speed={speed}, text_len={len(text)}"
        )
        
        if not text:
            response = app.response_class(
                response=json.dumps({'error': 'text cannot be empty'}),
                status=400,
                mimetype='application/json'
            )
            return response
        
        if not character_name:
            response = app.response_class(
                response=json.dumps({'error': 'speaker is required'}),
                status=400,
                mimetype='application/json'
            )
            return response
        
        # Resolve voice config.
        char_config = character_config.get_character(character_name)
        if not char_config:
            response = app.response_class(
                response=json.dumps({'error': f'voice not found: {character_name}'}),
                status=404,
                mimetype='application/json'
            )
            return response
        
        # Normalize text before synthesis.
        original_text = text
        text = clean_text(text)
        if len(text) != len(original_text):
            api_logger.warning(f'Text cleaned: {len(original_text)} -> {len(text)} chars')
        
        # Enforce minimum text length.
        if len(text) < min_text_length or not text.strip():
            error_msg = f'text too short: {len(text)} < min_text_length={min_text_length}'
            api_logger.warning(error_msg)
            
            # 鐢熸垚 0.5s 闈欓煶鏁版嵁 (22050Hz, 16bit, Mono)
            # 22050 * 0.5 = 11025 samples
            # byte len = 11025 * 2 = 22050 bytes
            import io
            import struct
            
            silence_duration = 0.5
            sample_rate = 22050
            num_samples = int(sample_rate * silence_duration)
            # data size
            data_size = num_samples * 2 
            
            # Total size = 36 + data_size
            file_size = 36 + data_size
            
            header = io.BytesIO()
            header.write(b'RIFF')
            header.write(struct.pack('<I', file_size))
            header.write(b'WAVE')
            header.write(b'fmt ')
            header.write(struct.pack('<I', 16)) # Chunk size
            header.write(struct.pack('<H', 1))  # PCM
            header.write(struct.pack('<H', 1))  # Mono
            header.write(struct.pack('<I', sample_rate)) 
            header.write(struct.pack('<I', sample_rate * 2)) 
            header.write(struct.pack('<H', 2)) 
            header.write(struct.pack('<H', 16)) 
            header.write(b'data')
            header.write(struct.pack('<I', data_size))
            
            # Silence data (zeros)
            silence_data = b'\x00' * data_size
            
            complete_wav = header.getvalue() + silence_data
            
            # Return silence wav directly for short-text requests.
            return Response(complete_wav, mimetype='audio/wav')
        
        api_logger.info(
            f"[api] synthesis start: mode={mode or char_config.get('mode')}, "
            f"speed={speed}, text_len={len(text)}"
        )
        
        engine_req = {
            'text': text,
            'voice_id': character_name,
            'mode': mode or char_config.get('mode', ''),
            'speed': speed,
            'instruct_text': char_config.get('instruct_text', ''),
            'use_instruction': False,
            'instruction': '',
        }
        result = _v2_run_engine(
            engine_req,
            part_index=0,
            sync_wait_ms=0,
            wait_inflight_on_conflict=True,
        )
        return Response(result.wav_bytes, mimetype='audio/wav')
    
    except Exception as e:
        print(f"ERROR: Error in /api/tts: {e}")
        import traceback
        traceback.print_exc()
        error_msg = f'request exception: {str(e)[:100]}'
        response = app.response_class(
            response=json.dumps({'error': error_msg}),
            status=500,
            mimetype='application/json'
        )
        return response

@app.route('/api/characters', methods=['GET'])
def list_characters():
    """
    Return all available voices (minimal fields only).
    """
    try:
        characters = []
        for char_name in character_config.list_characters():
            # Keep response minimal for compatibility.
            characters.append({
                'name': char_name,
                'voice_id': char_name
            })
        
        response = app.response_class(
            response=json.dumps(characters),
            status=200,
            mimetype='application/json'
        )
        return response
    except Exception as e:
        print(f"ERROR: Error in /api/characters: {e}")
        response = app.response_class(
            response=json.dumps({'error': str(e)}),
            status=500,
            mimetype='application/json'
        )
        return response

@app.route('/speakers', methods=['GET', 'OPTIONS'])
def get_speakers():
    """
    Tavern-compatible speakers endpoint.
    Returns: [{name, voice_id}, ...]
    """
    # Handle CORS preflight.
    if request.method == 'OPTIONS':
        response = app.response_class(
            response='',
            status=200,
            mimetype='text/plain'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    try:
        speakers = []
        for char_name in character_config.list_characters():
            # Keep response minimal for compatibility.
            speakers.append({
                'name': char_name,
                'voice_id': char_name
            })
        
        # Use app.response_class to return raw JSON array.
        response = app.response_class(
            response=json.dumps(speakers),
            status=200,
            mimetype='application/json'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        print(f"ERROR: Error in /speakers: {e}")
        response = app.response_class(
            response=json.dumps({'error': str(e)}),
            status=500,
            mimetype='application/json'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        response = app.response_class(
            response=json.dumps({
                'status': 'ok',
                'model': 'CosyVoice3-0.5B',
                'characters': character_config.list_characters()
            }),
            status=200,
            mimetype='application/json'
        )
        return response
    except Exception as e:
        response = app.response_class(
            response=json.dumps({'status': 'error', 'error': str(e)}),
            status=500,
            mimetype='application/json'
        )
        return response

@app.route('/api/toggle_stream', methods=['POST'])
def toggle_stream():
    """Toggle stream output mode."""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        set_stream_mode(enabled)
        
        response = app.response_class(
            response=json.dumps({'status': 'ok', 'stream_mode': STREAM_MODE}),
            status=200,
            mimetype='application/json'
        )
        return response
    except Exception as e:
        response = app.response_class(
            response=json.dumps({'error': str(e)}),
            status=500,
            mimetype='application/json'
        )
        return response

@app.route('/api/toggle_spk_cache', methods=['POST'])
def toggle_spk_cache():
    """Toggle speaker cache mode."""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        set_spk_cache_mode(enabled)
        
        response = app.response_class(
            response=json.dumps({'status': 'ok', 'spk_cache_mode': SPK_CACHE_MODE}),
            status=200,
            mimetype='application/json'
        )
        return response
    except Exception as e:
        response = app.response_class(
            response=json.dumps({'error': str(e)}),
            status=500,
            mimetype='application/json'
        )
        return response


# ==================== Direct TTS Endpoint ====================

@app.route('/api/tts_direct', methods=['POST', 'OPTIONS'])
def tts_direct():
    """
    Direct TTS endpoint without role config dependency.
    Supports uploading reference audio for zero-shot synthesis.
    
    Request format (multipart/form-data):
    - text: target text
    - prompt_text: transcript of reference audio
    - prompt_audio: reference audio file (WAV/MP3)
    - speed: optional, default 1.0
    
    Or JSON format (with base64 encoded audio):
    {
        "text": "target text",
        "prompt_text": "reference transcript",
        "prompt_audio_base64": "base64 encoded audio",
        "speed": 1.0
    }
    """
    # Handle CORS preflight.
    if request.method == 'OPTIONS':
        response = app.response_class(
            response='',
            status=200,
            mimetype='text/plain'
        )
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    try:
        if cosyvoice is None:
            return app.response_class(
                response=json.dumps({'error': 'model not loaded'}),
                status=500,
                mimetype='application/json'
            )
        
        import tempfile
        import base64
        
        # Detect request type.
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Multipart form upload.
            text = request.form.get('text', '').strip()
            prompt_text = request.form.get('prompt_text', '').strip()
            speed = float(request.form.get('speed', 1.0))
            
            if 'prompt_audio' not in request.files:
                return app.response_class(
                    response=json.dumps({'error': 'missing prompt audio file'}),
                    status=400,
                    mimetype='application/json'
                )
            
            audio_file = request.files['prompt_audio']
            
            # Save uploaded audio to temporary file.
            temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            audio_file.save(temp_audio.name)
            prompt_audio_path = temp_audio.name
            
        else:
            # JSON request.
            data = request.get_json()
            text = data.get('text', '').strip()
            prompt_text = data.get('prompt_text', '').strip()
            speed = float(data.get('speed', 1.0))
            
            audio_base64 = data.get('prompt_audio_base64', '')
            if not audio_base64:
                return app.response_class(
                    response=json.dumps({'error': 'missing prompt_audio_base64'}),
                    status=400,
                    mimetype='application/json'
                )
            
            # Decode base64 and save to temporary file.
            audio_bytes = base64.b64decode(audio_base64)
            temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio.write(audio_bytes)
            temp_audio.close()
            prompt_audio_path = temp_audio.name
        
        api_logger.info(
            f"[api] POST /api/tts_direct: prompt_text_len={len(prompt_text)}, "
            f"text_len={len(text)}, speed={speed}"
        )
        
        if not text:
            return app.response_class(
                response=json.dumps({'error': 'text cannot be empty'}),
                status=400,
                mimetype='application/json'
            )
        
        if not prompt_text:
            return app.response_class(
                response=json.dumps({'error': 'prompt_text cannot be empty'}),
                status=400,
                mimetype='application/json'
            )
        
        # Normalize text before synthesis.
        text = clean_text(text)
        
        # Run zero-shot inference.
        try:
            import torchaudio
            
            for result in cosyvoice.inference_zero_shot(
                text,
                prompt_text,
                prompt_audio_path,
                stream=False,
                speed=speed
            ):
                # Read generated audio tensor.
                audio_tensor = result['tts_speech']
                
                # Save via temp wav to avoid BytesIO compatibility issues.
                import tempfile
                temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                temp_wav_path = temp_wav.name
                temp_wav.close()
                
                torchaudio.save(temp_wav_path, audio_tensor, cosyvoice.sample_rate)
                
                # Read WAV bytes.
                with open(temp_wav_path, 'rb') as f:
                    wav_bytes = f.read()
                
                # Cleanup temporary files.
                import os
                try:
                    os.unlink(temp_wav_path)
                    os.unlink(prompt_audio_path)
                except:
                    pass
                
                response = app.response_class(
                    response=wav_bytes,
                    status=200,
                    mimetype='audio/wav'
                )
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response
        
        except Exception as e:
            api_logger.error(f"inference failed: {e}")
            return app.response_class(
                response=json.dumps({'error': f'inference failed: {str(e)}'}),
                status=500,
                mimetype='application/json'
            )
    
    except Exception as e:
        api_logger.error(f"request handling failed: {e}")
        return app.response_class(
            response=json.dumps({'error': str(e)}),
            status=500,
            mimetype='application/json'
        )


# ==================== API v2 Endpoints ====================

def _v2_metrics_snapshot() -> dict:
    with V2_METRICS_LOCK:
        m = dict(V2_METRICS)
    denom = int(m.get("cache_hit", 0)) + int(m.get("cache_miss", 0))
    hit_rate = (float(m.get("cache_hit", 0)) / float(denom)) if denom > 0 else 0.0
    m["cache_hit_rate"] = hit_rate
    try:
        m["queue_depth"] = int(V2_JOB_QUEUE.qsize())
    except Exception:
        m["queue_depth"] = 0
    try:
        m["cache"] = V2_CACHE.stats()
        m["cache"]["max_mb"] = V2_CACHE_MAX_MB
    except Exception:
        m["cache"] = {}
    return m


# v2 routes split: assets/voices/jobs/merge are registered via Blueprint to keep api.py slimmer.
_v2_routes_ctx = SimpleNamespace(
    require_v2_api_key=require_v2_api_key,
    json_ok=_v2_json_ok,
    json_error=_v2_json_error,
    AppError=AppError,
    api_logger=api_logger,
    log_event=_v2_log_event,
    req_id=_v2_req_id,
    V2_LOCK=V2_LOCK,
    V2_MODEL_LOCK=V2_MODEL_LOCK,
    V2_JOB_LOCK=V2_JOB_LOCK,
    V2_ASSETS=V2_ASSETS,
    V2_JOBS=V2_JOBS,
    v2_get_asset=_v2_get_asset,
    v2_save_audio_bytes=_v2_save_audio_bytes,
    safe_int=_safe_int,
    get_cosyvoice=lambda: cosyvoice,
    get_character_config=lambda: character_config,
    cv3_prefix_prompt=_cv3_prefix_prompt,
    v2_create_job=_v2_create_job,
    v2_enqueue_job=_v2_enqueue_job,
    v2_merge_files_to_wav=_v2_merge_files_to_wav,
    v2_metrics_snapshot=_v2_metrics_snapshot,
    v2_prepare_char_config=_v2_prepare_char_config,
    v2_compute_cache_key=_v2_compute_cache_key,
    v2_run_engine=_v2_run_engine,
    v2_register_file_as_asset=_v2_register_file_as_asset,
)
app.register_blueprint(_create_v2_blueprint(_v2_routes_ctx), url_prefix="/api/v2")
# Register misc v2 routes (health / metrics / synth) via server blueprint.
app.register_blueprint(_create_v2_misc_blueprint(_v2_routes_ctx))


# ==================== 鎺ㄧ悊鏍稿績閫昏緫 ====================

def _make_stream_generator(iterator, speed=1.0):
    """Build wav stream response generator."""
    import struct
    
    # 1. Yield WAV Header (44 bytes) for streaming (unknown length)
    header = io.BytesIO()
    header.write(b'RIFF')
    header.write(struct.pack('<I', 0)) # Placeholder size: 0 (streaming)
    header.write(b'WAVE')
    header.write(b'fmt ')
    header.write(struct.pack('<I', 16)) # Chunk size
    header.write(struct.pack('<H', 1))  # PCM
    header.write(struct.pack('<H', 1))  # Mono
    # sample rate access might need global cosyvoice or passed in
    sample_rate = 22050
    if cosyvoice is not None and hasattr(cosyvoice, 'sample_rate'):
        sample_rate = cosyvoice.sample_rate

    header.write(struct.pack('<I', sample_rate)) 
    header.write(struct.pack('<I', sample_rate * 2)) 
    header.write(struct.pack('<H', 2)) 
    header.write(struct.pack('<H', 16)) 
    header.write(b'data')
    header.write(struct.pack('<I', 0)) # Data size: 0 (streaming)    
    yield header.getvalue()

    # 2. Yield chunks
    for output in iterator:
        if 'tts_speech' not in output: continue
        speech_tensor = output['tts_speech']
        speech_numpy = speech_tensor.cpu().numpy()
        audio_int16 = (speech_numpy * 32767).astype(np.int16)
        yield audio_int16.tobytes()

def _normalize_inference_mode(mode: str) -> str:
    """Compatibility wrapper: use shared synthesis mode normalizer."""
    return _syn_normalize_inference_mode(mode)


def _inference(text: str, char_config: dict, mode: str = None, speed: float = 1.0, stream_response: bool = False):
    """Core inference entry with mode normalization and optional streaming."""
    try:
        if cosyvoice is None:
            api_logger.error('Model not loaded')
            return None

        text = str(text or '').strip()
        if not text:
            api_logger.error('Empty text for inference')
            return None

        cfg = dict(char_config or {})
        mode_norm = _normalize_inference_mode(mode or cfg.get('mode', ''))

        prompt_audio_path = str(cfg.get('prompt_audio') or '').strip()
        prompt_text = str(cfg.get('prompt_text') or '').strip()
        instruct_text = str(cfg.get('instruct_text') or '').strip()

        if not prompt_audio_path or not os.path.exists(prompt_audio_path):
            api_logger.error(f'Prompt audio not found: {prompt_audio_path}')
            return None

        is_v3 = 'CosyVoice3' in getattr(cosyvoice, 'model_dir', '')
        stream_flag = bool(stream_response or STREAM_MODE)

        if mode_norm in {'zero_shot', 'reference_timbre'}:
            if not prompt_text:
                api_logger.error('Prompt text not found in config')
                return None
            if is_v3 and '<|endofprompt|>' not in prompt_text:
                prompt_text = f'You are a helpful assistant.<|endofprompt|>{prompt_text}'

            use_cache_id = ''
            if mode_norm == 'reference_timbre' or SPK_CACHE_MODE:
                char_name = str(cfg.get('name') or '').strip()
                if char_name:
                    available_spks = cosyvoice.list_available_spks()
                    if char_name not in available_spks:
                        cosyvoice.add_zero_shot_spk(prompt_text, prompt_audio_path, char_name)
                    use_cache_id = char_name

            iterator = cosyvoice.inference_zero_shot(
                text,
                prompt_text,
                prompt_audio_path,
                stream=stream_flag,
                zero_shot_spk_id=use_cache_id,
            )

        elif mode_norm == 'instruction':
            if not instruct_text:
                api_logger.error('Instruction text not found in config')
                return None
            if is_v3:
                if '<|endofprompt|>' not in instruct_text:
                    instruct_text = f'{instruct_text}<|endofprompt|>'
                if 'You are a helpful assistant.' not in instruct_text:
                    instruct_text = f'You are a helpful assistant. {instruct_text}'

            iterator = cosyvoice.inference_instruct2(
                text,
                instruct_text,
                prompt_audio_path,
                stream=stream_flag,
            )

        elif mode_norm == 'fine_grained':
            tts_text = text
            if is_v3 and '<|endofprompt|>' not in tts_text:
                tts_text = f'You are a helpful assistant.<|endofprompt|>{tts_text}'
            iterator = cosyvoice.inference_cross_lingual(
                tts_text,
                prompt_audio_path,
                stream=stream_flag,
            )

        else:
            api_logger.error(f'Unknown mode: {mode_norm}')
            return None

        if stream_response:
            if speed != 1.0:
                api_logger.warning('Streaming mode does not support speed change. Speed ignored.')
            return _make_stream_generator(iterator, speed)

        tts_speeches = []
        for output in iterator:
            if isinstance(output, dict) and output.get('tts_speech') is not None:
                tts_speeches.append(output['tts_speech'])

        if not tts_speeches:
            return None

        audio_data = torch.concat(tts_speeches, dim=1)

        if speed != 1.0:
            sample_rate = getattr(cosyvoice, 'sample_rate', 22050)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_input:
                torchaudio.save(tmp_input.name, audio_data, sample_rate, format='wav')
                temp_input_path = tmp_input.name

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_output:
                temp_output_path = tmp_output.name

            if speed_change_ffmpeg(temp_input_path, speed, temp_output_path):
                audio_data, _ = torchaudio.load(temp_output_path)
            else:
                api_logger.warning('Speed change failed, returning original audio')

            try:
                os.unlink(temp_input_path)
            except Exception:
                pass
            try:
                os.unlink(temp_output_path)
            except Exception:
                pass

        buffer = io.BytesIO()
        sample_rate = getattr(cosyvoice, 'sample_rate', 22050)
        torchaudio.save(buffer, audio_data, sample_rate, format='wav')
        buffer.seek(0)
        return buffer

    except Exception as e:
        api_logger.error(f'[inference] {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CosyVoice3 API Server")
    parser.add_argument(
        "--config",
        type=str,
        default=_resolve_default_voices_config_path(),
        help="voices config json path (default: app_config.v2_voices_config_path / config/super_agent.json)",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="server host")
    parser.add_argument("--port", type=int, default=9880, help="server port")
    parser.add_argument("--debug", action="store_true", help="enable debug mode")
    parser.add_argument("--min_text_length", type=int, default=0, help="minimum text length")
    return parser


def resolve_config_file(config_file: str) -> str:
    cfg = (config_file or "").strip() or _resolve_default_voices_config_path()
    if not os.path.isabs(cfg):
        cfg = os.path.join(ROOT_DIR, "..", cfg)
    cfg = os.path.abspath(cfg)
    if not cfg.endswith(".json"):
        raise ValueError(f"--config must point to a .json file, got: {cfg}")
    return cfg


def _warmup_model_once() -> None:
    global cosyvoice, character_config
    print("🔥 Warming up model (reducing first-request latency)...")
    try:
        if character_config is None or cosyvoice is None:
            return
        chars = character_config.list_characters()
        if not chars:
            return
        warmup_char = chars[0]
        char_cfg = character_config.get_character(warmup_char) or {}
        prompt_text = str(char_cfg.get("prompt_text") or "")
        prompt_audio = str(char_cfg.get("prompt_audio") or "")
        if not prompt_audio or not os.path.exists(prompt_audio):
            return
        if "CosyVoice3" in getattr(cosyvoice, "model_dir", ""):
            if "<|endofprompt|>" not in prompt_text:
                prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_text}"
        cosyvoice.inference_zero_shot("你好", prompt_text, prompt_audio, stream=False)
        print("✅ Warmup completed!")
    except Exception as e:
        print(f"⚠️ Warmup failed (non-fatal): {e}")


def initialize_runtime(*, config_file: str, min_text_length: int = 0, warmup: bool = True):
    global character_config, cosyvoice
    character_config = CharacterConfig(config_file)
    set_min_text_length(int(min_text_length or 0))
    api_logger.info("📦 Loading CosyVoice model...")
    cosyvoice = load_cosyvoice_model()
    api_logger.info("✅ Model loaded successfully")
    if warmup:
        _warmup_model_once()
    return cosyvoice, character_config


def run_server(*, app, host: str, port: int, debug: bool) -> None:
    print("\n🚀 Starting CosyVoice3 API Server...")
    print(f"🔗 Host: {host}:{port}")
    print(f"🔎 Health check: http://{host}:{port}/api/health")
    cli = sys.modules.get("flask.cli")
    if cli is not None:
        cli.show_server_banner = lambda *x: None
    app.run(host=host, port=int(port), debug=bool(debug), threaded=True)


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        cfg = resolve_config_file(args.config)
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    try:
        initialize_runtime(config_file=cfg, min_text_length=int(args.min_text_length), warmup=True)
    except Exception as e:
        api_logger.error(f"❌ Failed to initialize runtime: {e}")
        import traceback

        traceback.print_exc()
        return 1
    run_server(app=app, host=args.host, port=int(args.port), debug=bool(args.debug))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


