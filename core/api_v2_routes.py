from __future__ import annotations

import os
import time
import uuid
import shutil
import threading
import mimetypes
import tempfile
from typing import Any

from flask import Blueprint, Response, request, send_from_directory
from core.v2.asset_texts import resolve_prompt_text_voice_first


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

    def _first_nonempty(items: object) -> str:
        if not isinstance(items, list):
            return ""
        for x in items:
            s = str(x or "").strip()
            if s:
                return s
        return ""

    def _primary_asset_id_for_voice(voice: dict[str, Any]) -> str:
        if not isinstance(voice, dict):
            return ""
        aid = _first_nonempty(voice.get("ref_asset_ids"))
        if aid:
            return aid
        return str(voice.get("prompt_audio_asset_id") or "").strip()

    def _sync_primary_asset_transcript(voice: dict[str, Any]) -> dict[str, Any]:
        """
        Mirror voice.prompt_text to primary asset transcript with shared-asset protection.
        """
        aid = _primary_asset_id_for_voice(voice)
        if not aid:
            return {"status": "skipped_no_asset", "asset_id": ""}

        prompt_text = str((voice or {}).get("prompt_text") or "").strip()
        if not prompt_text:
            return {"status": "skipped_empty_prompt", "asset_id": aid}

        try:
            voices = _iter_voices()
            by_aid, _ = _build_asset_refs(voices)
            ref_count = len(set(by_aid.get(aid) or set()))
            if ref_count > 1:
                return {"status": "skipped_shared", "asset_id": aid, "ref_count": ref_count}

            with ctx.V2_LOCK:
                meta = ctx.V2_ASSETS.get(aid)
                if not meta:
                    return {"status": "skipped_no_asset", "asset_id": aid}
                updated = dict(meta)
                updated["transcript_text"] = prompt_text
                # Keep legacy compatibility field in sync.
                updated["prompt_text"] = prompt_text
                ctx.V2_ASSETS.upsert(updated)
            return {"status": "applied", "asset_id": aid, "ref_count": ref_count}
        except Exception as e:
            return {"status": "skipped_error", "asset_id": aid, "reason": str(e)}

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
            transcript_text = (request.form.get("transcript_text") or "").strip()

            meta = ctx.v2_save_audio_bytes(data, source_name=file_obj.filename or "upload.wav", kind="ref")
            if character:
                meta["character"] = character
            if emotion:
                meta["emotion"] = emotion
            if language:
                meta["language"] = language
            if note:
                meta["note"] = note
            if transcript_text:
                meta["transcript_text"] = transcript_text
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

        Supported fields: note, transcript_text, prompt_text(legacy), character, emotion, language, linked.
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
                if "transcript_text" in data:
                    updated["transcript_text"] = str(data.get("transcript_text") or "").strip()
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

    @bp.route("/voices/import-legacy", methods=["POST"])
    @require
    def import_legacy_voices():
        temp_dir = tempfile.mkdtemp(prefix="voices_import_legacy_")
        temp_path = ""
        try:
            cc = ctx.get_character_config()
            voices_path = str(getattr(ctx, "v2_voices_config_path", "") or getattr(cc, "config_file", "")).strip()
            assets_db_path = str(getattr(ctx, "v2_assets_db_path", "") or getattr(getattr(ctx, "V2_ASSETS", None), "db_path", "")).strip()
            assets_dir = str(getattr(ctx, "v2_assets_dir", "") or "").strip()
            if not voices_path or not assets_db_path or not assets_dir:
                return json_error(AppError(code="internal_error", message="v2 import paths not configured", status=500))

            file_obj = request.files.get("file")
            if not file_obj:
                return json_error(AppError(code="invalid_request", message="file is required", status=400))
            if not file_obj.filename:
                return json_error(AppError(code="invalid_request", message="invalid file upload", status=400))

            temp_path = os.path.join(temp_dir, os.path.basename(file_obj.filename) or "legacy_voices.json")
            file_obj.save(temp_path)
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) <= 0:
                return json_error(AppError(code="invalid_request", message="empty file", status=400))

            dry_run = (request.form.get("dry_run") or "").strip().lower() in {"1", "true", "yes", "on"}
            default_language = (request.form.get("default_language") or "").strip() or "zh"
            create_emotion = (request.form.get("create_emotion") or "").strip() or "default"
            selection_policy = (request.form.get("selection_policy") or "").strip() or "random_per_text"

            from core.v2.legacy_import import import_legacy_voice_config_to_v2

            result = import_legacy_voice_config_to_v2(
                legacy_config_path=temp_path,
                v2_voices_config_path=voices_path,
                v2_assets_db_path=assets_db_path,
                v2_assets_dir=assets_dir,
                default_language=default_language,
                create_emotion=create_emotion,
                selection_policy=selection_policy,
                dry_run=dry_run,
            )

            if not dry_run and cc and hasattr(cc, "load_characters"):
                cc.load_characters()

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="voice_import_legacy",
                dry_run=dry_run,
                imported_voices=result.get("imported_voices"),
                imported_assets=result.get("imported_assets"),
                skipped_assets=result.get("skipped_assets"),
                errors=len(result.get("errors") or []),
            )
            return json_ok(
                {
                    "imported_voices": int(result.get("imported_voices") or 0),
                    "imported_assets": int(result.get("imported_assets") or 0),
                    "skipped_assets": int(result.get("skipped_assets") or 0),
                    "errors": list(result.get("errors") or []),
                    "dry_run": bool(result.get("dry_run")),
                },
                status=200,
            )
        except Exception as e:
            return json_error(e)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
            saved_voice = cc.get_character(name) if cc else None
            if not isinstance(saved_voice, dict):
                saved_voice = dict(voice)
            asset_sync = _sync_primary_asset_transcript(saved_voice)
            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="voice_create",
                voice_id=name,
                character=saved_voice.get("character"),
                emotion=saved_voice.get("emotion"),
                asset_sync_status=asset_sync.get("status"),
                asset_sync_asset_id=asset_sync.get("asset_id"),
            )
            payload = dict(saved_voice)
            payload["asset_transcript_sync"] = asset_sync
            return json_ok(payload, status=201)
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
            saved_voice = cc.get_character(new_name) if cc else None
            if not isinstance(saved_voice, dict):
                saved_voice = dict(updated)
            asset_sync = _sync_primary_asset_transcript(saved_voice)
            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="voice_update",
                voice_id=saved_voice.get("name"),
                asset_sync_status=asset_sync.get("status"),
                asset_sync_asset_id=asset_sync.get("asset_id"),
            )
            payload = dict(saved_voice)
            payload["asset_transcript_sync"] = asset_sync
            return json_ok(payload, status=200)
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
                resolved, src = resolve_prompt_text_voice_first(prompt_text, meta)
                if src == "asset.prompt_text":
                    try:
                        ctx.api_logger.warning(f"[v2] compile using legacy asset.prompt_text: voice={voice_id} asset={aid}")
                    except Exception:
                        pass
                pt = resolved or prompt_text
                if pt and is_v3 and "<|endofprompt|>" not in pt:
                    pt = ctx.cv3_prefix_prompt(pt)
                return pt

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

    # ==================== Pro 模式：批量合成 API ====================

    # 内存级批次状态管理器（进程内共享）
    _PRO_BATCHES: dict[str, dict[str, Any]] = {}
    _PRO_BATCHES_LOCK = threading.Lock()

    def _pro_batch_worker(batch_id: str, items: list[dict], output_dir: str) -> None:
        """后台线程：逐条串行合成，更新批次状态。"""
        for item in items:
            # 检查是否已取消
            with _PRO_BATCHES_LOCK:
                batch = _PRO_BATCHES.get(batch_id)
                if not batch or batch.get("cancel_flag"):
                    break

            row_id = item.get("row_id", "")
            text = item.get("text", "")
            voice_id = item.get("voice_id", "")
            speed = float(item.get("speed", 1.0))
            mode = str(item.get("mode", "zero_shot") or "zero_shot")
            instruct_text = str(item.get("instruct_text", "") or "")
            variation_seed = int(item.get("variation_seed", item.get("seed", 42)) or 42)

            # 标记当前条目为处理中
            with _PRO_BATCHES_LOCK:
                batch = _PRO_BATCHES.get(batch_id)
                if batch and row_id in batch["items"]:
                    batch["items"][row_id]["status"] = "processing"

            try:
                # 构建合成请求（复用现有合成引擎）
                req = {
                    "text": str(text or ""),
                    "voice_id": str(voice_id or ""),
                    "speed": speed,
                    "mode": mode,
                    "instruct_text": instruct_text,
                    "variation_seed": variation_seed,
                    "response_format": "audio",
                }

                # 调用合成引擎（串行调用，线程安全）
                result = ctx.v2_run_engine(
                    req,
                    part_index=0,
                    sync_wait_ms=120_000,
                    wait_inflight_on_conflict=True,
                )

                # 保存 wav 文件
                wav_path = os.path.join(output_dir, f"{row_id}.wav")
                with open(wav_path, "wb") as f:
                    f.write(result.wav_bytes)

                # 计算音频时长（毫秒）
                duration_ms = 0
                try:
                    wav_size = len(result.wav_bytes)
                    # WAV 头部 44 字节，22050Hz, 16bit, mono → 每毫秒 44.1 字节
                    if wav_size > 44:
                        duration_ms = int((wav_size - 44) / 44.1)
                except Exception:
                    pass

                # 更新条目状态
                with _PRO_BATCHES_LOCK:
                    batch = _PRO_BATCHES.get(batch_id)
                    if batch and row_id in batch["items"]:
                        batch["items"][row_id].update({
                            "status": "done",
                            "audio_path": wav_path,
                            "duration_ms": duration_ms,
                            "error": None,
                        })
                        batch["completed"] = batch.get("completed", 0) + 1

            except Exception as e:
                with _PRO_BATCHES_LOCK:
                    batch = _PRO_BATCHES.get(batch_id)
                    if batch and row_id in batch["items"]:
                        batch["items"][row_id].update({
                            "status": "failed",
                            "audio_path": None,
                            "duration_ms": None,
                            "error": str(e)[:200],
                        })
                        batch["failed"] = batch.get("failed", 0) + 1

        # 批次完成，更新总体状态
        with _PRO_BATCHES_LOCK:
            batch = _PRO_BATCHES.get(batch_id)
            if batch:
                if batch.get("cancel_flag"):
                    batch["status"] = "cancelled"
                else:
                    batch["status"] = "done"

    @bp.route("/pro/batch", methods=["POST"])
    @require
    def pro_batch_create():
        """提交批量合成任务，立即返回 batch_id（HTTP 202）。"""
        try:
            payload: dict[str, Any] = request.get_json() or {}
            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                return json_error(AppError(
                    code="invalid_request",
                    message="items 数组不能为空",
                    status=400,
                ))

            # 生成批次 ID 和输出目录
            batch_id = "batch_" + uuid.uuid4().hex[:12]
            output_dir = os.path.join(
                os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                "output", "pro_batch", batch_id,
            )
            os.makedirs(output_dir, exist_ok=True)

            # 初始化批次状态
            batch_items: dict[str, dict] = {}
            for item in items:
                row_id = str(item.get("row_id", "")).strip()
                if not row_id:
                    row_id = "row_" + uuid.uuid4().hex[:8]
                batch_items[row_id] = {
                    "status": "pending",
                    "audio_path": None,
                    "duration_ms": None,
                    "error": None,
                }

            with _PRO_BATCHES_LOCK:
                _PRO_BATCHES[batch_id] = {
                    "batch_id": batch_id,
                    "total": len(items),
                    "completed": 0,
                    "failed": 0,
                    "status": "processing",
                    "items": batch_items,
                    "output_dir": output_dir,
                    "cancel_flag": False,
                }

            # 规范化 items 列表（确保 row_id 对齐）
            normalized_items = []
            for item, row_id in zip(items, batch_items.keys()):
                ni = dict(item)
                ni["row_id"] = row_id
                normalized_items.append(ni)

            # 启动后台线程
            t = threading.Thread(
                target=_pro_batch_worker,
                args=(batch_id, normalized_items, output_dir),
                daemon=True,
                name=f"pro_batch_{batch_id}",
            )
            t.start()

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="pro_batch_create",
                batch_id=batch_id,
                total=len(items),
            )

            return json_ok(
                {"batch_id": batch_id, "total": len(items), "status": "processing"},
                status=202,
            )
        except Exception as e:
            return json_error(e)

    @bp.route("/pro/batch/<batch_id>", methods=["GET"])
    @require
    def pro_batch_status(batch_id: str):
        """查询批量合成任务状态。"""
        try:
            with _PRO_BATCHES_LOCK:
                batch = _PRO_BATCHES.get(batch_id)
            if not batch:
                return json_error(AppError(
                    code="batch_not_found",
                    message="批次不存在",
                    status=404,
                ))

            # 构建前端需要的 items 数组
            items_list = []
            for row_id, info in batch["items"].items():
                audio_url = None
                if info.get("status") == "done":
                    audio_url = f"/api/v2/pro/batch/{batch_id}/audio/{row_id}"
                items_list.append({
                    "row_id": row_id,
                    "status": info.get("status", "pending"),
                    "audio_url": audio_url,
                    "duration_ms": info.get("duration_ms"),
                    "error": info.get("error"),
                })

            return json_ok({
                "batch_id": batch_id,
                "total": batch.get("total", 0),
                "completed": batch.get("completed", 0),
                "failed": batch.get("failed", 0),
                "status": batch.get("status", "unknown"),
                "items": items_list,
            }, status=200)
        except Exception as e:
            return json_error(e)

    @bp.route("/pro/batch/<batch_id>/audio/<row_id>", methods=["GET"])
    @require
    def pro_batch_audio(batch_id: str, row_id: str):
        """获取批量合成中单条的音频二进制流。"""
        try:
            with _PRO_BATCHES_LOCK:
                batch = _PRO_BATCHES.get(batch_id)
            if not batch:
                return json_error(AppError(
                    code="batch_not_found",
                    message="批次不存在",
                    status=404,
                ))

            item = batch["items"].get(row_id)
            if not item:
                return json_error(AppError(
                    code="row_not_found",
                    message="该行条目不存在",
                    status=404,
                ))

            if item.get("status") != "done" or not item.get("audio_path"):
                return json_error(AppError(
                    code="audio_not_ready",
                    message="音频尚未生成完成",
                    status=425,
                ))

            audio_path = item["audio_path"]
            if not os.path.exists(audio_path):
                return json_error(AppError(
                    code="audio_file_missing",
                    message="音频文件丢失",
                    status=500,
                ))

            return send_from_directory(
                os.path.dirname(audio_path),
                os.path.basename(audio_path),
                mimetype="audio/wav",
            )
        except Exception as e:
            return json_error(e)

    @bp.route("/pro/batch/<batch_id>", methods=["DELETE"])
    @require
    def pro_batch_cancel(batch_id: str):
        """取消批量合成任务并清理临时文件。"""
        try:
            with _PRO_BATCHES_LOCK:
                batch = _PRO_BATCHES.get(batch_id)
                if not batch:
                    return json_error(AppError(
                        code="batch_not_found",
                        message="批次不存在",
                        status=404,
                    ))
                batch["cancel_flag"] = True
                batch["status"] = "cancelling"
                output_dir = batch.get("output_dir", "")

            # 清理输出目录
            if output_dir and os.path.isdir(output_dir):
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                except Exception:
                    pass

            # 从内存中移除批次记录
            with _PRO_BATCHES_LOCK:
                _PRO_BATCHES.pop(batch_id, None)

            ctx.log_event(
                ctx.api_logger,
                request_id=ctx.req_id(),
                event="pro_batch_cancel",
                batch_id=batch_id,
            )

            return json_ok(
                {"status": "cancelled", "batch_id": batch_id},
                status=200,
            )
        except Exception as e:
            return json_error(e)

    return bp
