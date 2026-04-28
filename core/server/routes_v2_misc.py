from __future__ import annotations

import os
import time

from flask import Blueprint, Response, request


def create_v2_misc_blueprint(ctx) -> Blueprint:
    """
    v2 misc routes:
    - /health
    - /api/v2/health
    - /metrics
    - /api/v2/metrics
    - /api/v2/synthesize
    """

    bp = Blueprint("api_v2_misc_routes", __name__)
    require = ctx.require_v2_api_key
    json_ok = ctx.json_ok
    json_error = ctx.json_error
    AppError = ctx.AppError

    def _metrics_snapshot() -> dict:
        fn = getattr(ctx, "v2_metrics_snapshot", None)
        if callable(fn):
            try:
                return fn() or {}
            except Exception:
                return {}
        return {}

    def _health_payload() -> dict:
        cosyvoice = ctx.get_cosyvoice()
        cc = ctx.get_character_config()

        # 基础字段
        payload = {
            "status": "ok" if cosyvoice is not None else "degraded",
            "api": "v2",
            "model_loaded": cosyvoice is not None,
            "voices": cc.list_characters() if cc else [],
            "voices_config_path": getattr(cc, "config_file", ""),
            "metrics": _metrics_snapshot(),
        }

        # GPU/显存信息（安全降级，无 GPU 时返回 null）
        try:
            import torch
            if torch.cuda.is_available():
                payload["gpu_name"] = torch.cuda.get_device_name(0)
                payload["vram_used_mb"] = int(torch.cuda.memory_allocated(0) / 1024 / 1024)
                payload["vram_total_mb"] = int(torch.cuda.get_device_properties(0).total_mem / 1024 / 1024)
            else:
                payload["gpu_name"] = None
                payload["vram_used_mb"] = None
                payload["vram_total_mb"] = None
        except Exception:
            payload["gpu_name"] = None
            payload["vram_used_mb"] = None
            payload["vram_total_mb"] = None

        return payload

    @bp.route("/health", methods=["GET"])
    def health_root():
        try:
            return json_ok(_health_payload(), status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/health", methods=["GET"])
    def v2_health():
        try:
            return json_ok(_health_payload(), status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/metrics", methods=["GET"])
    def metrics_root():
        try:
            return json_ok(_metrics_snapshot(), status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/metrics", methods=["GET"])
    def v2_metrics():
        try:
            return json_ok(_metrics_snapshot(), status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/synthesize", methods=["POST"])
    @require
    def v2_synthesize():
        try:
            # Support multipart direct cloning in one call.
            if request.content_type and "multipart/form-data" in request.content_type:
                req = {
                    "text": request.form.get("text", "").strip(),
                    "character": request.form.get("character", "").strip(),
                    "emotion": request.form.get("emotion", "").strip(),
                    "voice_id": request.form.get("voice_id", "").strip(),
                    "prompt_text": request.form.get("prompt_text", "").strip(),
                    "mode": request.form.get("mode", "zero_shot").strip(),
                    "speed": float(request.form.get("speed", 1.0)),
                    "instruct_text": request.form.get("instruct_text", "").strip(),
                    "use_instruction": request.form.get("use_instruction", "false").lower() == "true",
                    "instruction": request.form.get("instruction", "").strip(),
                    "variation_seed": ctx.safe_int(request.form.get("variation_seed", 0), 0),
                    "selection_policy": request.form.get("selection_policy", "").strip(),
                    "prefer_async": request.form.get("prefer_async", "false").lower() == "true",
                    "sync_wait_ms": ctx.safe_int(request.form.get("sync_wait_ms", 0), 0),
                    "name": request.form.get("name", "api_v2_temp").strip(),
                    "response_format": request.form.get("response_format", "audio").strip(),
                    "save_output": request.form.get("save_output", "false").lower() == "true",
                }
                if "prompt_audio" in request.files:
                    file_obj = request.files["prompt_audio"]
                    meta = ctx.v2_save_audio_bytes(
                        file_obj.read(),
                        source_name=file_obj.filename or "prompt.wav",
                        kind="ref",
                    )
                    req["prompt_audio_asset_id"] = meta["asset_id"]
            else:
                req = request.get_json() or {}

            if ctx.get_cosyvoice() is None:
                return json_error(AppError(code="model_not_loaded", message="model not loaded", status=503))

            response_format = (req.get("response_format", "audio") or "audio").strip().lower()
            save_output = bool(req.get("save_output", False))
            prefer_async = bool(req.get("prefer_async", False))
            sync_wait_ms = ctx.safe_int(req.get("sync_wait_ms", 0), 0)
            text_val = str(req.get("text", "") or "")
            voice_id_val = str(req.get("voice_id", "") or req.get("voice_name", "") or "unknown")
            t0 = time.perf_counter()

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="SYN_START",
                voice_id=voice_id_val,
                text_len=len(text_val),
            )

            if prefer_async:
                cfg = ctx.v2_prepare_char_config(req)
                req_hash, req_norm, _ = ctx.v2_compute_cache_key(req, cfg, part_index=0)
                payload = dict(req)
                payload["text"] = req_norm.get("text", "")
                job = ctx.v2_create_job({"segments": [payload], "merge": False, "priority": 10})
                ctx.v2_enqueue_job(job["job_id"], priority=10)
                ctx.log_event(
                    ctx.api_logger,
                    request_id=ctx.req_id(),
                    event="job_create",
                    job_id=job["job_id"],
                    priority=10,
                    segments=1,
                    via="prefer_async",
                )
                return json_ok({"job_id": job["job_id"], "status": "queued", "cache_key": req_hash}, status=202)

            result = ctx.v2_run_engine(
                req,
                part_index=0,
                sync_wait_ms=sync_wait_ms,
                wait_inflight_on_conflict=True,
            )
            req_hash = result.cache_key
            wav_bytes = result.wav_bytes
            selected_ref_asset_id = result.selected_ref_asset_id
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            resolved_voice = str(result.voice_id or voice_id_val or "unknown")
            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="SYN_DONE",
                voice_id=resolved_voice,
                duration_ms=elapsed_ms,
                bytes=len(wav_bytes),
            )
            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="SYN_CACHE_HIT" if result.cache_hit else "SYN_CACHE_MISS",
                cache_key=req_hash,
                voice_id=resolved_voice,
            )

            if save_output:
                cache_path = result.cache_path
                if cache_path:
                    out_meta = ctx.v2_register_file_as_asset(cache_path, source_name="output.wav", kind="output")
                else:
                    out_meta = ctx.v2_save_audio_bytes(wav_bytes, source_name="output.wav", kind="output")
            else:
                out_meta = None

            if response_format == "json":
                payload = {
                    "status": "ok",
                    "voice_name": result.voice_id,
                    "bytes": len(wav_bytes),
                    "asset_id": out_meta["asset_id"] if out_meta else None,
                    "cache": {"hit": bool(result.cache_hit), "key": req_hash},
                    "selected_ref_asset_id": selected_ref_asset_id,
                }
                resp = json_ok(payload, status=200)
                resp.headers["X-Cache"] = "HIT" if result.cache_hit else "MISS"
                resp.headers["X-Cache-Key"] = req_hash
                if out_meta:
                    resp.headers["X-Asset-Id"] = out_meta["asset_id"]
                return resp

            resp = Response(wav_bytes, mimetype="audio/wav")
            resp.headers["X-Cache"] = "HIT" if result.cache_hit else "MISS"
            resp.headers["X-Cache-Key"] = req_hash
            if out_meta:
                resp.headers["X-Asset-Id"] = out_meta["asset_id"]
            return resp
        except Exception as e:
            try:
                ctx.log_event(
                    ctx.api_logger,
                    request_id=ctx.req_id(),
                    event="SYN_FAIL",
                    voice_id=str(locals().get("voice_id_val") or "unknown"),
                    reason=str(e),
                    error_type=type(e).__name__,
                )
            except Exception:
                pass
            return json_error(e)

    # ==================== Pro 模式：系统控制 API ====================

    @bp.route("/api/v2/pro/system/unload", methods=["POST"])
    @require
    def pro_system_unload():
        """释放 GPU 显存：销毁模型实例并清理 CUDA 缓存。"""
        try:
            cosyvoice = ctx.get_cosyvoice()
            if cosyvoice is None:
                return json_ok({"status": "already_unloaded", "vram_freed_mb": 0}, status=200)

            vram_before = 0
            try:
                import torch
                if torch.cuda.is_available():
                    vram_before = int(torch.cuda.memory_allocated(0) / 1024 / 1024)
            except Exception:
                pass

            # 通过 api_legacy 中的全局引用销毁模型
            try:
                from core.utils import unload_cosyvoice_model
                unload_cosyvoice_model(cosyvoice)
            except ImportError:
                pass

            # 清理全局引用（通过 api_legacy 的 set_model_and_config）
            try:
                from core import api_legacy
                api_legacy.cosyvoice = None
            except Exception:
                pass

            # 清理 GPU 显存
            vram_freed = 0
            try:
                import torch
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    vram_after = int(torch.cuda.memory_allocated(0) / 1024 / 1024)
                    vram_freed = max(0, vram_before - vram_after)
            except Exception:
                pass

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="pro_system_unload",
                vram_freed_mb=vram_freed,
            )

            return json_ok({"status": "unloaded", "vram_freed_mb": vram_freed}, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/api/v2/pro/system/reload", methods=["POST"])
    @require
    def pro_system_reload():
        """重新加载模型到 GPU 显存。"""
        try:
            # 检查是否已加载
            if ctx.get_cosyvoice() is not None:
                model_dir = getattr(ctx.get_cosyvoice(), "model_dir", "")
                model_name = os.path.basename(model_dir) if model_dir else "unknown"
                return json_ok({
                    "status": "already_loaded",
                    "model_name": model_name,
                }, status=200)

            # 重新加载模型
            from core.utils import load_cosyvoice_model
            new_model = load_cosyvoice_model()

            # 更新全局引用
            try:
                from core import api_legacy
                api_legacy.cosyvoice = new_model
            except Exception:
                pass

            model_dir = getattr(new_model, "model_dir", "")
            model_name = os.path.basename(model_dir) if model_dir else "unknown"

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="pro_system_reload",
                model_name=model_name,
            )

            return json_ok({
                "status": "loaded",
                "model_name": model_name,
            }, status=200)
        except Exception as e:
            return json_error(e)

    return bp
