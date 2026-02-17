from __future__ import annotations

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
        return {
            "status": "ok" if cosyvoice is not None else "degraded",
            "api": "v2",
            "model_loaded": cosyvoice is not None,
            "voices": cc.list_characters() if cc else [],
            "voices_config_path": getattr(cc, "config_file", ""),
            "metrics": _metrics_snapshot(),
        }

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
            return json_error(e)

    return bp
