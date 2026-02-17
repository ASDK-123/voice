from __future__ import annotations

import os
import time
import mimetypes
from typing import Any

from flask import Blueprint, Response, request


def create_v2_blueprint(ctx) -> Blueprint:
    """
    v2 routes split from core/api.py.

    ctx is a SimpleNamespace-like object that provides:
    - require_v2_api_key (decorator)
    - json_ok / json_error
    - AppError
    - api_logger / log_event / req_id
    - V2_LOCK / V2_MODEL_LOCK / V2_JOB_LOCK
    - V2_ASSETS / V2_JOBS
    - v2_get_asset / v2_save_audio_bytes
    - safe_int
    - get_cosyvoice() / get_character_config()
    - cv3_prefix_prompt()
    - v2_create_job() / v2_enqueue_job()
    - v2_merge_files_to_wav()
    """

    bp = Blueprint("api_v2_routes", __name__)

    require = ctx.require_v2_api_key
    json_ok = ctx.json_ok
    json_error = ctx.json_error
    AppError = ctx.AppError

    def _norm_path(p: str) -> str:
        s = (p or "").strip()
        if not s:
            return ""
        try:
            return os.path.normcase(os.path.abspath(s))
        except Exception:
            return s

    def _voice_id(v: dict) -> str:
        if not isinstance(v, dict):
            return ""
        return str(v.get("name") or v.get("voice_id") or "").strip()

    def _iter_voices() -> list[dict[str, Any]]:
        cc = ctx.get_character_config()
        items = cc.get_all_characters() if cc else []
        return items if isinstance(items, list) else []

    def _build_asset_refs(voices: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """
        Return (refs_by_asset_id, refs_by_path).

        refs_by_path is a compatibility layer for voices that store only prompt_audio path
        (no asset_id), to avoid accidentally deleting still-used assets.
        """
        by_aid: dict[str, set[str]] = {}
        by_path: dict[str, set[str]] = {}

        for v in voices or []:
            vid = _voice_id(v)
            if not vid:
                continue

            aid = str(v.get("prompt_audio_asset_id") or "").strip()
            if aid:
                by_aid.setdefault(aid, set()).add(vid)

            ref_ids = v.get("ref_asset_ids") or []
            if isinstance(ref_ids, list):
                for x in ref_ids:
                    x = str(x or "").strip()
                    if x:
                        by_aid.setdefault(x, set()).add(vid)

            p = str(v.get("prompt_audio") or "").strip()
            np = _norm_path(p)
            if np:
                by_path.setdefault(np, set()).add(vid)

        return by_aid, by_path

    @bp.route("/assets/audio", methods=["GET"])
    @require
    def list_audio_assets():
        character = (request.args.get("character") or "").strip()
        emotion = (request.args.get("emotion") or "").strip()
        language = (request.args.get("language") or "").strip()
        kind = (request.args.get("kind") or "").strip()
        with ctx.V2_LOCK:
            items = ctx.V2_ASSETS.list(character=character, emotion=emotion, language=language, kind=kind)
        # Compute linked/ref_count dynamically from current voices, so UI reflects bind/unbind immediately.
        try:
            voices = _iter_voices()
            by_aid, by_path = _build_asset_refs(voices)
            out: list[dict[str, Any]] = []
            for a in items or []:
                if not isinstance(a, dict):
                    continue
                d = dict(a)
                aid = str(d.get("asset_id") or "").strip()
                ap = _norm_path(str(d.get("path") or ""))
                vset = set()
                if aid:
                    vset |= set(by_aid.get(aid) or set())
                if ap:
                    vset |= set(by_path.get(ap) or set())
                d["linked"] = bool(vset)
                d["ref_count"] = len(vset)
                out.append(d)
            items = out
        except Exception:
            # Best-effort: keep raw items if voice scan fails.
            pass

        return json_ok({"items": items, "count": len(items)}, status=200)

    @bp.route("/assets/audio", methods=["POST"])
    @require
    def upload_audio_asset():
        try:
            if "file" not in request.files and "audio" not in request.files:
                return json_error(AppError(code="invalid_request", message="file or audio is required", status=400))
            file_obj = request.files.get("file") or request.files.get("audio")
            if not file_obj:
                return json_error(AppError(code="invalid_request", message="invalid file upload", status=400))
            data = file_obj.read()
            if not data:
                return json_error(AppError(code="invalid_request", message="empty file", status=400))

            character = (request.form.get("character") or "").strip()
            emotion = (request.form.get("emotion") or "").strip() or "default"
            language = (request.form.get("language") or "").strip() or "zh"
            note = (request.form.get("note") or "").strip()

            meta = ctx.v2_save_audio_bytes(data, source_name=file_obj.filename or "upload.wav", kind="ref")
            if character:
                meta["character"] = character
            if emotion:
                meta["emotion"] = emotion
            if language:
                meta["language"] = language
            if note:
                meta["note"] = note
            with ctx.V2_LOCK:
                ctx.V2_ASSETS.upsert(meta)
            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="asset_upload",
                asset_id=meta.get("asset_id"),
                kind=meta.get("kind"),
                character=character,
                emotion=emotion,
                language=language,
            )
            return json_ok(meta, status=201)
        except Exception as e:
            return json_error(e)

    @bp.route("/assets/audio/<asset_id>", methods=["GET"])
    @require
    def get_audio_asset(asset_id: str):
        meta = ctx.v2_get_asset(asset_id)
        if not meta:
            return json_error(AppError(code="asset_not_found", message="asset not found", status=404))
        return json_ok(meta, status=200)

    @bp.route("/assets/audio/<asset_id>", methods=["PUT"])
    @require
    def update_audio_asset(asset_id: str):
        """
        Update v2 audio asset metadata (not content).

        Supported fields: note, prompt_text, character, emotion, language, linked.
        Extra keys are preserved in meta_json for forward compatibility.
        """
        try:
            data: dict[str, Any] = request.get_json() or {}
            with ctx.V2_LOCK:
                meta = ctx.V2_ASSETS.get(asset_id)
                if not meta:
                    return json_error(AppError(code="asset_not_found", message="asset not found", status=404))

                updated = dict(meta)
                if "note" in data:
                    updated["note"] = str(data.get("note") or "").strip()
                if "prompt_text" in data:
                    updated["prompt_text"] = str(data.get("prompt_text") or "").strip()
                if "character" in data:
                    updated["character"] = str(data.get("character") or "").strip()
                if "emotion" in data:
                    updated["emotion"] = str(data.get("emotion") or "").strip() or "default"
                if "language" in data:
                    updated["language"] = str(data.get("language") or "").strip() or "zh"
                if "linked" in data:
                    updated["linked"] = bool(data.get("linked"))

                ctx.V2_ASSETS.upsert(updated)

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="asset_update",
                asset_id=asset_id,
            )
            return json_ok(updated, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/assets/audio/<asset_id>/content", methods=["GET"])
    @require
    def get_audio_content(asset_id: str):
        meta = ctx.v2_get_asset(asset_id)
        if not meta:
            return json_error(AppError(code="asset_not_found", message="asset not found", status=404))
        try:
            path = str(meta.get("path") or "")
            with open(path, "rb") as f:
                content = f.read()
            mimetype, _ = mimetypes.guess_type(path)
            return Response(content, mimetype=mimetype or "application/octet-stream")
        except Exception as e:
            return json_error(e)

    @bp.route("/assets/audio/<asset_id>", methods=["DELETE"])
    @require
    def delete_audio_asset(asset_id: str):
        with ctx.V2_LOCK:
            meta = ctx.V2_ASSETS.get(asset_id)
            deleted = ctx.V2_ASSETS.delete(asset_id)
        if not meta:
            return json_error(AppError(code="asset_not_found", message="asset not found", status=404))
        if not deleted:
            return json_error(AppError(code="internal_error", message="asset delete failed", status=500))
        try:
            if os.path.exists(meta["path"]):
                os.remove(meta["path"])
        except Exception:
            pass
        ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="asset_delete", asset_id=asset_id)
        return json_ok({"status": "deleted", "asset_id": asset_id}, status=200)

    @bp.route("/assets/audio/refs", methods=["GET"])
    @require
    def list_audio_asset_refs():
        """
        Reverse reference view: which voices reference which ref assets.
        """
        character = (request.args.get("character") or "").strip()
        emotion = (request.args.get("emotion") or "").strip()
        language = (request.args.get("language") or "").strip()
        kind = (request.args.get("kind") or "ref").strip()
        if kind.lower() in {"all", "*"}:
            kind = ""

        with ctx.V2_LOCK:
            assets = ctx.V2_ASSETS.list(character=character, emotion=emotion, language=language, kind=kind)

        voices = _iter_voices()
        by_aid, by_path = _build_asset_refs(voices)

        items: list[dict[str, Any]] = []
        for a in assets or []:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("asset_id") or "").strip()
            ap = _norm_path(str(a.get("path") or ""))
            vset = set()
            if aid:
                vset |= set(by_aid.get(aid) or set())
            if ap:
                vset |= set(by_path.get(ap) or set())
            voices_list = sorted(vset)
            row = dict(a)
            row["ref_count"] = len(voices_list)
            row["voices"] = voices_list
            items.append(row)

        return json_ok({"items": items, "count": len(items)}, status=200)

    @bp.route("/assets/audio/unused", methods=["GET"])
    @require
    def list_unused_audio_assets():
        """
        List unused ref assets: assets(kind=ref) that are not referenced by any voice.
        """
        character = (request.args.get("character") or "").strip()
        emotion = (request.args.get("emotion") or "").strip()
        language = (request.args.get("language") or "").strip()
        kind = (request.args.get("kind") or "ref").strip()
        if kind.lower() in {"all", "*"}:
            kind = ""

        with ctx.V2_LOCK:
            assets = ctx.V2_ASSETS.list(character=character, emotion=emotion, language=language, kind=kind)

        voices = _iter_voices()
        by_aid, by_path = _build_asset_refs(voices)

        items: list[dict[str, Any]] = []
        for a in assets or []:
            if not isinstance(a, dict):
                continue
            # By default, we are cleaning refs only.
            if kind.strip().lower() in {"ref", ""}:
                if str(a.get("kind") or "").strip().lower() not in {"ref", ""}:
                    continue

            aid = str(a.get("asset_id") or "").strip()
            ap = _norm_path(str(a.get("path") or ""))
            vset = set()
            if aid:
                vset |= set(by_aid.get(aid) or set())
            if ap:
                vset |= set(by_path.get(ap) or set())
            if vset:
                continue
            row = dict(a)
            row["reason"] = "not_referenced"
            items.append(row)

        return json_ok({"items": items, "count": len(items)}, status=200)

    @bp.route("/assets/audio/cleanup", methods=["POST"])
    @require
    def cleanup_audio_assets():
        """
        Bulk cleanup ref assets by asset_id list (supports dry-run).
        """
        try:
            payload: dict[str, Any] = request.get_json() or {}
            asset_ids = payload.get("asset_ids") or []
            if not isinstance(asset_ids, list) or not asset_ids:
                return json_error(AppError(code="invalid_request", message="asset_ids is required", status=400))
            dry_run = bool(payload.get("dry_run", False))

            # Build refs snapshot at cleanup time (server-side, safety-first).
            voices = _iter_voices()
            by_aid, by_path = _build_asset_refs(voices)

            requested = 0
            deleted = 0
            bytes_reclaimed = 0
            skipped: list[dict[str, Any]] = []
            deleted_ids: list[str] = []

            for raw in asset_ids:
                aid = str(raw or "").strip()
                if not aid:
                    continue
                requested += 1
                with ctx.V2_LOCK:
                    meta = ctx.V2_ASSETS.get(aid)
                if not meta:
                    skipped.append({"asset_id": aid, "reason": "asset_not_found"})
                    continue
                if str(meta.get("kind") or "").strip().lower() != "ref":
                    skipped.append({"asset_id": aid, "reason": "kind_not_ref", "kind": meta.get("kind")})
                    continue

                ap = _norm_path(str(meta.get("path") or ""))
                vset = set(by_aid.get(aid) or set())
                if ap:
                    vset |= set(by_path.get(ap) or set())
                if vset:
                    skipped.append({"asset_id": aid, "reason": "still_referenced", "voices": sorted(vset)})
                    continue

                try:
                    sz = int(meta.get("size") or 0)
                except Exception:
                    sz = 0
                if not sz and ap and os.path.exists(ap):
                    try:
                        sz = int(os.path.getsize(ap))
                    except Exception:
                        sz = 0

                if not dry_run:
                    with ctx.V2_LOCK:
                        ok = ctx.V2_ASSETS.delete(aid)
                    if not ok:
                        skipped.append({"asset_id": aid, "reason": "delete_failed"})
                        continue
                    try:
                        if ap and os.path.exists(ap):
                            os.remove(ap)
                    except Exception:
                        # Best-effort: metadata is removed, file may remain; still count as deleted.
                        pass

                deleted += 1
                bytes_reclaimed += int(sz or 0)
                deleted_ids.append(aid)

            try:
                ctx.log_event(
                    ctx.api_logger,
                    request_id=ctx.req_id(),
                    event="asset_cleanup",
                    dry_run=dry_run,
                    requested=requested,
                    deleted=deleted,
                    skipped=len(skipped),
                    bytes_reclaimed=bytes_reclaimed,
                )
            except Exception:
                pass

            return json_ok(
                {
                    "status": "ok",
                    "dry_run": dry_run,
                    "requested": requested,
                    "deleted": deleted,
                    "deleted_ids": deleted_ids,
                    "skipped": skipped,
                    "bytes_reclaimed": bytes_reclaimed,
                },
                status=200,
            )
        except Exception as e:
            return json_error(e)

    @bp.route("/voices", methods=["GET"])
    @require
    def list_voices():
        cc = ctx.get_character_config()
        items = cc.get_all_characters() if cc else []
        return json_ok({"items": items, "count": len(items)}, status=200)

    @bp.route("/voices/reload", methods=["POST"])
    @require
    def reload_voices():
        """
        Reload voices from disk for the embedded CharacterConfig.

        This is primarily used by the desktop UI when it updates the v2 voices JSON directly
        (without going through /voices CRUD).
        """
        cc = ctx.get_character_config()
        if not cc:
            return json_error(AppError(code="internal_error", message="character_config not set", status=500))
        try:
            cc.load_characters()
            return json_ok({"status": "reloaded", "count": len(cc.list_characters())}, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/voices", methods=["POST"])
    @require
    def create_voice():
        try:
            cc = ctx.get_character_config()
            if not cc:
                return json_error(AppError(code="internal_error", message="character_config not set", status=500))

            data: dict[str, Any] = request.get_json() or {}
            name = (data.get("name") or "").strip()
            if not name:
                return json_error(AppError(code="invalid_request", message="name is required", status=400))
            if cc.get_character(name):
                return json_error(AppError(code="conflict", message="voice already exists", status=409))

            prompt_audio = data.get("prompt_audio", "")
            prompt_audio_asset_id = (data.get("prompt_audio_asset_id") or "").strip()
            if prompt_audio_asset_id:
                meta = ctx.v2_get_asset(prompt_audio_asset_id)
                if not meta:
                    return json_error(AppError(code="asset_not_found", message="prompt_audio_asset_id not found", status=404))
                prompt_audio = meta["path"]

            voice = dict(data)
            voice.update(
                {
                    "name": name,
                    "mode": data.get("mode", "zero_shot"),
                    "prompt_text": data.get("prompt_text", ""),
                    "prompt_audio": prompt_audio,
                    "instruct_text": data.get("instruct_text", ""),
                    "color": data.get("color", "#FF6B6B"),
                }
            )
            if "#" in name:
                ch, emo = name.split("#", 1)
                if ch and "character" not in voice:
                    voice["character"] = ch
                if emo and "emotion" not in voice:
                    voice["emotion"] = emo or "default"
            if "ref_asset_ids" in voice and not isinstance(voice.get("ref_asset_ids"), list):
                voice["ref_asset_ids"] = []

            cc.upsert_character(voice)
            cc.save()
            ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="voice_create", voice_id=name, character=voice.get("character"), emotion=voice.get("emotion"))
            return json_ok(voice, status=201)
        except Exception as e:
            return json_error(e)

    @bp.route("/voices/<voice_id>", methods=["GET"])
    @require
    def get_voice(voice_id: str):
        cc = ctx.get_character_config()
        voice = cc.get_character(voice_id) if cc else None
        if not voice:
            return json_error(AppError(code="voice_not_found", message="voice not found", status=404))
        return json_ok(voice, status=200)

    @bp.route("/voices/<voice_id>", methods=["PUT"])
    @require
    def update_voice(voice_id: str):
        try:
            cc = ctx.get_character_config()
            if not cc:
                return json_error(AppError(code="internal_error", message="character_config not set", status=500))

            old_voice = cc.get_character(voice_id)
            if not old_voice:
                return json_error(AppError(code="voice_not_found", message="voice not found", status=404))

            data: dict[str, Any] = request.get_json() or {}
            new_name = (data.get("name") or voice_id).strip()
            updated = dict(old_voice)
            updated.update(data)
            updated["name"] = new_name
            if "#" in new_name:
                ch, emo = new_name.split("#", 1)
                if ch:
                    updated.setdefault("character", ch)
                if emo:
                    updated.setdefault("emotion", emo or "default")

            if "prompt_audio_asset_id" in data:
                aid = (data.get("prompt_audio_asset_id") or "").strip()
                if aid:
                    meta = ctx.v2_get_asset(aid)
                    if not meta:
                        return json_error(AppError(code="asset_not_found", message="prompt_audio_asset_id not found", status=404))
                    updated["prompt_audio"] = meta["path"]

            if new_name != voice_id:
                cc.delete_character(voice_id)
            if "ref_asset_ids" in updated and not isinstance(updated.get("ref_asset_ids"), list):
                updated["ref_asset_ids"] = []

            cc.upsert_character(updated)
            cc.save()
            ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="voice_update", voice_id=updated.get("name"))
            return json_ok(updated, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/voices/<voice_id>", methods=["DELETE"])
    @require
    def delete_voice(voice_id: str):
        cc = ctx.get_character_config()
        if not cc or not cc.delete_character(voice_id):
            return json_error(AppError(code="voice_not_found", message="voice not found", status=404))
        cc.save()
        ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="voice_delete", voice_id=voice_id)
        return json_ok({"status": "deleted", "voice_id": voice_id}, status=200)

    @bp.route("/voices/<voice_id>/compile", methods=["POST"])
    @require
    def compile_voice(voice_id: str):
        try:
            cosyvoice = ctx.get_cosyvoice()
            if cosyvoice is None:
                return json_error(AppError(code="model_not_loaded", message="model not loaded", status=503))
            cc = ctx.get_character_config()
            voice = cc.get_character(voice_id) if cc else None
            if not voice:
                return json_error(AppError(code="voice_not_found", message="voice not found", status=404))

            prompt_text = (voice.get("prompt_text", "") or "").strip()
            prompt_audio = (voice.get("prompt_audio", "") or "").strip()
            ref_asset_ids = voice.get("ref_asset_ids") or []
            compile_all = (request.args.get("all") or "").strip().lower() in {"1", "true", "yes"}

            is_v3 = "CosyVoice3" in getattr(cosyvoice, "model_dir", "")
            if is_v3:
                prompt_text = ctx.cv3_prefix_prompt(prompt_text)

            compiled: list[str] = []

            def _pick_prompt_text_for_asset(aid: str) -> str:
                if not aid:
                    return prompt_text
                meta = ctx.v2_get_asset(aid)
                if not meta:
                    return prompt_text
                pt = (meta.get("prompt_text") or meta.get("note") or "").strip()
                return pt or prompt_text

            def _compile_one(spk_id: str, audio_path: str, use_prompt_text: str):
                if not audio_path or not os.path.exists(audio_path):
                    raise ValueError(f"prompt_audio not found: {audio_path}")
                if not (use_prompt_text or "").strip():
                    raise ValueError("prompt_text is required")
                cosyvoice.add_zero_shot_spk(use_prompt_text, audio_path, spk_id)
                compiled.append(spk_id)

            with ctx.V2_MODEL_LOCK:
                if isinstance(ref_asset_ids, list) and ref_asset_ids and compile_all:
                    for aid in ref_asset_ids:
                        aid = (aid or "").strip()
                        if not aid:
                            continue
                        meta = ctx.v2_get_asset(aid)
                        if not meta:
                            continue
                        spk_id = f"{voice_id}@{aid}"
                        _compile_one(spk_id, meta.get("path", ""), _pick_prompt_text_for_asset(aid))
                else:
                    if isinstance(ref_asset_ids, list) and ref_asset_ids:
                        aid = (ref_asset_ids[0] or "").strip()
                        meta = ctx.v2_get_asset(aid) if aid else None
                        if meta:
                            prompt_audio = meta.get("path", prompt_audio)
                            pt = _pick_prompt_text_for_asset(aid)
                        else:
                            pt = prompt_text
                    else:
                        pt = prompt_text
                    _compile_one(voice_id, prompt_audio, pt)

                if hasattr(cosyvoice, "save_spkinfo"):
                    cosyvoice.save_spkinfo()

            ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="voice_compile", voice_id=voice_id, compiled=len(compiled), compile_all=compile_all)
            return json_ok({"status": "ok", "voice_id": voice_id, "compiled": compiled}, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/jobs", methods=["POST"])
    @require
    def create_job():
        try:
            payload: dict[str, Any] = request.get_json() or {}
            segments = payload.get("segments", [])
            if not isinstance(segments, list) or not segments:
                return json_error(AppError(code="invalid_request", message="segments is required", status=400))
            job = ctx.v2_create_job(payload)
            priority = ctx.safe_int(payload.get("priority", 100), 100)
            ctx.v2_enqueue_job(job["job_id"], priority=priority)
            ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="job_create", job_id=job["job_id"], priority=priority, segments=len(segments))
            return json_ok({"job_id": job["job_id"], "status": "queued"}, status=202)
        except Exception as e:
            return json_error(e)

    @bp.route("/jobs/<job_id>", methods=["GET"])
    @require
    def get_job(job_id: str):
        with ctx.V2_JOB_LOCK:
            job = ctx.V2_JOBS.get(job_id)
        if not job:
            return json_error(AppError(code="job_not_found", message="job not found", status=404))
        return json_ok(job, status=200)

    @bp.route("/jobs/<job_id>/cancel", methods=["POST"])
    @require
    def cancel_job(job_id: str):
        with ctx.V2_JOB_LOCK:
            job = ctx.V2_JOBS.get(job_id)
            if not job:
                return json_error(AppError(code="job_not_found", message="job not found", status=404))
            job["cancel_requested"] = True
            job["updated_at"] = int(time.time())
        ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="job_cancel", job_id=job_id)
        return json_ok({"status": "cancel_requested", "job_id": job_id}, status=202)

    @bp.route("/jobs/<job_id>/retry", methods=["POST"])
    @require
    def retry_job(job_id: str):
        with ctx.V2_JOB_LOCK:
            old_job = ctx.V2_JOBS.get(job_id)
        if not old_job:
            return json_error(AppError(code="job_not_found", message="job not found", status=404))
        new_job = ctx.v2_create_job(old_job.get("payload", {}))
        payload = new_job.get("payload", {}) or {}
        priority = ctx.safe_int(payload.get("priority", 100), 100)
        ctx.v2_enqueue_job(new_job["job_id"], priority=priority)
        ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="job_retry", old_job_id=job_id, job_id=new_job["job_id"], priority=priority)
        return json_ok({"job_id": new_job["job_id"], "status": "queued"}, status=202)

    @bp.route("/merge", methods=["POST"])
    @require
    def merge():
        try:
            data: dict[str, Any] = request.get_json() or {}
            asset_ids = data.get("asset_ids", [])
            file_paths = []
            for asset_id in asset_ids:
                meta = ctx.v2_get_asset(asset_id)
                if not meta:
                    return json_error(AppError(code="asset_not_found", message=f"asset not found: {asset_id}", status=404))
                file_paths.append(meta["path"])
            if not file_paths:
                return json_error(AppError(code="invalid_request", message="asset_ids is required", status=400))
            merged_path = ctx.v2_merge_files_to_wav(file_paths, data.get("output_name"))
            with open(merged_path, "rb") as f:
                merged_meta = ctx.v2_save_audio_bytes(f.read(), source_name=os.path.basename(merged_path), kind="merged")
            ctx.log_event(ctx.api_logger, request_id=ctx.req_id(), event="merge", merged_asset_id=merged_meta.get("asset_id"), count=len(file_paths))
            return json_ok({"status": "ok", "asset_id": merged_meta["asset_id"], "path": merged_meta["path"]}, status=200)
        except Exception as e:
            return json_error(e)

    return bp
