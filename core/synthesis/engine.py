from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Dict, MutableMapping, Optional, Tuple


@dataclass(frozen=True)
class SynthesisResult:
    wav_bytes: bytes
    cache_hit: bool
    cache_key: str
    selected_ref_asset_id: str
    voice_id: str
    cache_path: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _inc_metric(metrics: Optional[MutableMapping[str, int]], metrics_lock: Optional[Lock], key: str) -> None:
    if metrics is None:
        return
    if metrics_lock is not None:
        with metrics_lock:
            metrics[key] = int(metrics.get(key, 0)) + 1
        return
    metrics[key] = int(metrics.get(key, 0)) + 1


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def run_synthesis(
    req: Dict[str, Any],
    *,
    prepare_char_config: Callable[[Dict[str, Any]], Dict[str, Any]],
    compute_cache_key: Callable[[Dict[str, Any], Dict[str, Any], int], Tuple[str, Dict[str, Any], str]],
    run_sync_synthesis: Callable[[Dict[str, Any], Dict[str, Any]], Tuple[bytes, Dict[str, Any]]],
    cache: Any,
    metrics: Optional[MutableMapping[str, int]] = None,
    metrics_lock: Optional[Lock] = None,
    part_index: int = 0,
    sync_wait_ms: int = 0,
    wait_inflight_on_conflict: bool = True,
) -> SynthesisResult:
    """
    Unified synthesis pipeline:
    - resolve request/config and compute cache key
    - cache hit/miss routing
    - in-flight de-dup wait
    - sync model inference + cache write-through
    """
    req_in = dict(req or {})
    cfg = prepare_char_config(req_in)
    req_hash, req_norm, selected_ref_asset_id = compute_cache_key(req_in, cfg, int(part_index or 0))

    cache_path = cache.get_path(req_hash)
    if cache_path:
        _inc_metric(metrics, metrics_lock, "cache_hit")
        return SynthesisResult(
            wav_bytes=_read_file_bytes(cache_path),
            cache_hit=True,
            cache_key=req_hash,
            selected_ref_asset_id=selected_ref_asset_id,
            voice_id=(cfg.get("name") or "").strip(),
            cache_path=cache_path,
            meta={"source": "cache"},
        )

    _inc_metric(metrics, metrics_lock, "cache_miss")

    inflight_owner = bool(cache.begin_inflight(req_hash))
    if not inflight_owner and wait_inflight_on_conflict:
        wait_ms = int(sync_wait_ms or 0)
        if wait_ms > 0 and cache.wait_inflight(req_hash, wait_ms):
            cache_path = cache.get_path(req_hash)
            if cache_path:
                _inc_metric(metrics, metrics_lock, "cache_hit")
                return SynthesisResult(
                    wav_bytes=_read_file_bytes(cache_path),
                    cache_hit=True,
                    cache_key=req_hash,
                    selected_ref_asset_id=selected_ref_asset_id,
                    voice_id=(cfg.get("name") or "").strip(),
                    cache_path=cache_path,
                    meta={"source": "cache_after_wait", "waited_inflight_ms": wait_ms},
                )

    try:
        wav_bytes, cfg2 = run_sync_synthesis(req_norm, cfg)
        cfg = cfg2 or cfg
        cache.put_bytes(
            req_hash,
            wav_bytes,
            meta={"voice_id": cfg.get("name", ""), "selected_ref_asset_id": selected_ref_asset_id},
        )
    finally:
        if inflight_owner:
            cache.end_inflight(req_hash)

    cache_path = cache.get_path(req_hash) or ""
    return SynthesisResult(
        wav_bytes=wav_bytes,
        cache_hit=False,
        cache_key=req_hash,
        selected_ref_asset_id=selected_ref_asset_id,
        voice_id=(cfg.get("name") or "").strip(),
        cache_path=cache_path,
        meta={"source": "inference"},
    )
