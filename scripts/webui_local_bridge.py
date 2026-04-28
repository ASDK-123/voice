from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_HOST = "127.0.0.1"
HELPER_PORT = 9879
DEFAULT_API_PORT = 9880
LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}
LOG_DIR = REPO_ROOT / "data" / "logs"
LOG_PATH = LOG_DIR / "webui_local_bridge_api.log"

STATE_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "api_process": None,
    "api_pid": None,
    "last_error": "",
    "last_start_at": 0.0,
    "last_command": [],
}


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _load_app_config() -> dict[str, Any]:
    path = REPO_ROOT / "app_config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick_python() -> str:
    candidates = [
        REPO_ROOT / ".pixi" / "envs" / "default" / "Scripts" / "python.exe",
        REPO_ROOT / ".pixi" / "envs" / "default" / "python.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


def _resolve_v2_config_path() -> str:
    cfg = str(_load_app_config().get("v2_voices_config_path") or "").strip()
    candidates = []
    if cfg:
        p = Path(cfg)
        candidates.append(p if p.is_absolute() else (REPO_ROOT / p))
    candidates.append(REPO_ROOT / "config" / "super_agent.json")
    candidates.append(REPO_ROOT / "config" / "voices_v2.json")
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            return str(candidate.resolve())
    raise FileNotFoundError("找不到可用的 v2 voices 配置文件")


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        value = f"http://127.0.0.1:{DEFAULT_API_PORT}"
    return value.rstrip("/")


def _parse_local_base_url(base_url: str) -> tuple[str, int]:
    normalized = _normalize_base_url(base_url)
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").strip().lower()
    if host not in LOCAL_HOSTS:
        raise ValueError("当前 TTS 地址不是本机地址，无法使用本地启动桥")
    port = int(parsed.port or DEFAULT_API_PORT)
    return host or "127.0.0.1", port


def _request_json(method: str, url: str, *, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 2.0) -> dict[str, Any]:
    body = None
    req_headers = dict(headers or {})
    if payload is not None:
        body = _json_bytes(payload)
        req_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    request = Request(url, data=body, headers=req_headers, method=method.upper())
    with urlopen(request, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8") or "{}")


def _probe_api(base_url: str, api_key: str, timeout: float = 1.5) -> dict[str, Any]:
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        payload = _request_json("GET", f"{_normalize_base_url(base_url)}/api/v2/health", headers=headers, timeout=timeout)
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        if not isinstance(data, dict):
            data = {}
        return {
            "reachable": True,
            "model_loaded": bool(data.get("model_loaded", False)),
            "payload": data,
            "error": "",
        }
    except HTTPError as exc:
        return {
            "reachable": False,
            "model_loaded": False,
            "payload": {},
            "error": f"HTTP {exc.code}",
        }
    except URLError as exc:
        return {
            "reachable": False,
            "model_loaded": False,
            "payload": {},
            "error": str(exc.reason or exc),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "model_loaded": False,
            "payload": {},
            "error": str(exc),
        }


def _build_api_command(port: int) -> list[str]:
    python_exe = _pick_python()
    config_path = _resolve_v2_config_path()
    return [
        python_exe,
        "core/api.py",
        "--config",
        config_path,
        "--host",
        "0.0.0.0",
        "--port",
        str(int(port)),
    ]


def _spawn_api_process(port: int, api_key: str) -> subprocess.Popen[Any]:
    with STATE_LOCK:
        current = STATE.get("api_process")
        if current is not None and getattr(current, "poll", None) and current.poll() is None:
            return current

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if api_key:
        env["V2_API_KEY"] = api_key
    else:
        env.pop("V2_API_KEY", None)

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    log_file = open(LOG_PATH, "ab")
    proc = subprocess.Popen(
        _build_api_command(port),
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=creationflags,
    )
    with STATE_LOCK:
        STATE["api_process"] = proc
        STATE["api_pid"] = proc.pid
        STATE["last_start_at"] = time.time()
        STATE["last_command"] = _build_api_command(port)
        STATE["last_error"] = ""
    return proc


def _post_reload(base_url: str, api_key: str, timeout: float = 20.0) -> dict[str, Any]:
    headers = {"X-API-Key": api_key} if api_key else {}
    payload = _request_json(
        "POST",
        f"{_normalize_base_url(base_url)}/api/v2/pro/system/reload",
        headers=headers,
        timeout=timeout,
    )
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    return data if isinstance(data, dict) else {}


def ensure_runtime_ready(base_url: str, api_key: str, timeout_s: float = 90.0) -> dict[str, Any]:
    normalized = _normalize_base_url(base_url)
    _host, port = _parse_local_base_url(normalized)
    started_service = False
    triggered_reload = False
    deadline = time.time() + max(timeout_s, 5.0)

    probe = _probe_api(normalized, api_key, timeout=1.2)
    if not probe["reachable"]:
        _spawn_api_process(port, api_key)
        started_service = True

    while time.time() < deadline:
        probe = _probe_api(normalized, api_key, timeout=1.5)
        if probe["reachable"]:
            if probe["model_loaded"]:
                return {
                    "status": "ready",
                    "base_url": normalized,
                    "started_service": started_service,
                    "triggered_reload": triggered_reload,
                    "model_loaded": True,
                    "api_pid": STATE.get("api_pid"),
                    "health": probe["payload"],
                }
            if not triggered_reload:
                _post_reload(normalized, api_key, timeout=30.0)
                triggered_reload = True
        time.sleep(1.0)

    with STATE_LOCK:
        STATE["last_error"] = probe.get("error") or "等待服务就绪超时"
    return {
        "status": "timeout",
        "base_url": normalized,
        "started_service": started_service,
        "triggered_reload": triggered_reload,
        "model_loaded": bool(probe.get("model_loaded")),
        "api_pid": STATE.get("api_pid"),
        "health": probe.get("payload") or {},
        "error": probe.get("error") or "等待服务或模型加载超时",
    }


class LocalBridgeHandler(BaseHTTPRequestHandler):
    server_version = "UnitaleLocalBridge/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"status": "ok"})

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            self._send_json(200, {
                "status": "ok",
                "data": {
                    "helper": "online",
                    "api_pid": STATE.get("api_pid"),
                    "last_error": STATE.get("last_error") or "",
                    "last_start_at": STATE.get("last_start_at") or 0,
                },
            })
            return
        self._send_json(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:
        if self.path.startswith("/api/ensure-runtime"):
            payload = self._read_json()
            base_url = str(payload.get("baseUrl") or "").strip()
            api_key = str(payload.get("apiKey") or "").strip()
            timeout_ms = int(payload.get("timeoutMs") or 90000)
            try:
                result = ensure_runtime_ready(base_url, api_key, timeout_s=timeout_ms / 1000.0)
                if result.get("status") == "ready":
                    self._send_json(200, {"status": result.get("status"), "data": result})
                else:
                    self._send_json(504, {
                        "status": result.get("status"),
                        "message": str(result.get("error") or "等待本地服务或模型加载超时"),
                        "data": result,
                    })
            except Exception as exc:
                with STATE_LOCK:
                    STATE["last_error"] = str(exc)
                self._send_json(500, {"status": "error", "message": str(exc)})
            return
        self._send_json(404, {"status": "error", "message": "not found"})


def run_server(host: str = HELPER_HOST, port: int = HELPER_PORT) -> int:
    server = ThreadingHTTPServer((host, port), LocalBridgeHandler)
    print(f"[local-bridge] listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebUI 本地启动桥")
    parser.add_argument("--host", default=HELPER_HOST)
    parser.add_argument("--port", type=int, default=HELPER_PORT)
    parser.add_argument("--ping", action="store_true")
    args = parser.parse_args(argv)

    if args.ping:
        try:
            _request_json("GET", f"http://{args.host}:{int(args.port)}/health", timeout=1.0)
            return 0
        except Exception:
            return 1

    return run_server(host=str(args.host), port=int(args.port))


if __name__ == "__main__":
    raise SystemExit(main())
