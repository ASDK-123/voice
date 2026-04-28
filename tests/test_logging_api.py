from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from flask import Flask, request

from core.server.routes_v2_logs import create_v2_logs_blueprint
from core.v2.errors import AppError, coerce_exception


class TestLoggingApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_logging_api_")
        self.log_dir = os.path.join(self.tmp, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.required_api_key = ""

        app = Flask("test_logging_api")

        def _json_ok(payload: dict, status: int = 200):
            return app.response_class(
                response=json.dumps(payload, ensure_ascii=False),
                status=int(status),
                mimetype="application/json",
            )

        def _json_error(e: Exception):
            err = coerce_exception(e)
            return app.response_class(
                response=json.dumps(err.to_dict(), ensure_ascii=False),
                status=int(err.status),
                mimetype="application/json",
            )

        def _require(fn):
            def _wrapped(*args, **kwargs):
                if not self.required_api_key:
                    return fn(*args, **kwargs)
                provided = request.headers.get("X-API-Key", "").strip()
                if provided != self.required_api_key:
                    return _json_error(AppError(code="unauthorized", message="unauthorized", status=401))
                return fn(*args, **kwargs)

            _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
            return _wrapped

        def _export_bundle(output_zip):
            output_zip = os.fspath(output_zip)
            with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("app_config.json", '{"name":"test"}')
                for name in ("app.log", "access.jsonl", "crash.log"):
                    path = os.path.join(self.log_dir, name)
                    if os.path.exists(path):
                        zf.write(path, f"logs/{name}")
            return output_zip

        self.ctx = SimpleNamespace(
            require_v2_api_key=_require,
            json_ok=_json_ok,
            json_error=_json_error,
            AppError=AppError,
            safe_int=lambda v, d=0: int(str(v)) if str(v).strip().lstrip("-").isdigit() else int(d),
            log_dir=self.log_dir,
            export_diagnostic_bundle=_export_bundle,
        )
        app.register_blueprint(create_v2_logs_blueprint(self.ctx))
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_log(self, filename: str, lines: list[str]):
        path = os.path.join(self.log_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            if lines:
                fh.write("\n")
        return path

    def test_sources_lists_all_fixed_sources(self):
        self._write_log("app.log", ["[信息][api] 启动完成 | request_id=req_1"])
        resp = self.client.get("/api/v2/pro/logs/sources")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        items = body.get("items") or []
        self.assertEqual([item["id"] for item in items], ["app", "access", "crash", "local_bridge"])
        available = {item["id"]: item["available"] for item in items}
        self.assertTrue(available["app"])
        self.assertFalse(available["local_bridge"])

    def test_tail_returns_latest_snapshot_and_cursor(self):
        path = self._write_log(
            "app.log",
            [
                "[信息][api] 第一条 | request_id=req_a",
                "[错误][api] 第二条 | request_id=req_b, status=500",
            ],
        )
        resp = self.client.get("/api/v2/pro/logs/tail?source=app&limit=1")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        items = body.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["request_id"], "req_b")
        self.assertEqual(items[0]["level"], "ERROR")
        self.assertEqual(body.get("next_cursor"), str(os.path.getsize(path)))
        self.assertFalse(body.get("reset_required"))
        self.assertTrue(body.get("source_available"))

    def test_tail_with_cursor_returns_only_appended_lines(self):
        path = self._write_log("app.log", ["[信息][api] 第一条 | request_id=req_a"])
        cursor = os.path.getsize(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[警告][api] 第二条 | request_id=req_b\n")
        resp = self.client.get(f"/api/v2/pro/logs/tail?source=app&cursor={cursor}")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        items = body.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["request_id"], "req_b")
        self.assertEqual(items[0]["level"], "WARNING")
        self.assertEqual(body.get("next_cursor"), str(os.path.getsize(path)))

    def test_tail_sets_reset_required_when_file_shrinks(self):
        path = self._write_log(
            "app.log",
            [
                "[信息][api] 第一条 | request_id=req_a",
                "[信息][api] 第二条 | request_id=req_b",
            ],
        )
        old_cursor = os.path.getsize(path)
        self._write_log("app.log", ["[信息][api] 新文件 | request_id=req_new"])
        resp = self.client.get(f"/api/v2/pro/logs/tail?source=app&cursor={old_cursor}")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        self.assertTrue(body.get("reset_required"))
        items = body.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["request_id"], "req_new")

    def test_access_jsonl_parses_request_id_and_fields(self):
        self._write_log(
            "access.jsonl",
            [
                json.dumps(
                    {
                        "ts": "2026-03-06T10:00:00+08:00",
                        "level": "INFO",
                        "module": "api",
                        "event": "API_REQ_END",
                        "request_id": "rid_access",
                        "msg_zh": "请求完成",
                        "fields": {"status": 200, "path": "/api/v2/health"},
                    },
                    ensure_ascii=False,
                )
            ],
        )
        resp = self.client.get("/api/v2/pro/logs/tail?source=access")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json() or {}
        items = body.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["request_id"], "rid_access")
        self.assertEqual(items[0]["event"], "API_REQ_END")
        self.assertEqual(items[0]["fields"]["status"], 200)

    def test_text_log_fallback_keeps_raw_message(self):
        self._write_log("crash.log", ["plain crash line without schema"])
        resp = self.client.get("/api/v2/pro/logs/tail?source=crash")
        self.assertEqual(resp.status_code, 200, resp.data)
        item = (resp.get_json() or {}).get("items")[0]
        self.assertEqual(item["level"], "INFO")
        self.assertEqual(item["module"], "crash")
        self.assertEqual(item["message"], "plain crash line without schema")
        self.assertEqual(item["raw"], "plain crash line without schema")

    def test_diagnostic_bundle_returns_zip_with_expected_files(self):
        self._write_log("app.log", ["[信息][api] hello"])
        self._write_log("access.jsonl", ['{"event":"API_REQ_END"}'])
        self._write_log("crash.log", ["boom"])
        resp = self.client.post("/api/v2/pro/logs/diagnostic-bundle")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.mimetype, "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(resp.data))
        names = set(archive.namelist())
        self.assertIn("app_config.json", names)
        self.assertIn("logs/app.log", names)
        self.assertIn("logs/access.jsonl", names)
        self.assertIn("logs/crash.log", names)

    def test_api_key_protects_log_endpoints(self):
        self.required_api_key = "secret-key"
        resp = self.client.get("/api/v2/pro/logs/sources")
        self.assertEqual(resp.status_code, 401, resp.data)
        ok = self.client.get("/api/v2/pro/logs/sources", headers={"X-API-Key": "secret-key"})
        self.assertEqual(ok.status_code, 200, ok.data)


if __name__ == "__main__":
    unittest.main()
