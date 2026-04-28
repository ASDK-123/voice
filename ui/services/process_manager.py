import os
import sys
import subprocess
import time
import requests
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from werkzeug.serving import make_server
import core.api as api

class APIServerThread(QThread):
    """API 服务线程。抽取自 api_page.py"""
    log_signal = pyqtSignal(str)
    started_signal = pyqtSignal()
    stopped_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, host, port, model, config_manager):
        super().__init__()
        self.host = host
        self.port = port
        self.model = model
        self.config_manager = config_manager
        self.server = None
        self.is_running = False
        
        api.set_log_callback(self.on_api_log)

    def on_api_log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        try:
            api.set_globals(self.model, self.config_manager)
            self.server = make_server(self.host, self.port, api.app)
            self.is_running = True
            self.started_signal.emit()
            self.log_signal.emit(f"[OK] API Server started at http://{self.host}:{self.port}")
            self.server.serve_forever()
        except Exception as e:
            self.error_signal.emit(str(e))
            self.log_signal.emit(f"[ERROR] API Server error: {e}")
        finally:
            self.is_running = False
            self.stopped_signal.emit()

    def stop(self):
        if self.server:
            self.server.shutdown()


class BridgeServiceWorker(QThread):
    """桥接服务启停后台 worker，避免主线程阻塞。"""

    done = pyqtSignal(str, bool, object, str)  # action, ok, process, message

    def __init__(self, action: str, *, process=None, bridge_path: str = "", python_path: str = ""):
        super().__init__()
        self.action = str(action or "").strip().lower()
        self.process = process
        self.bridge_path = str(bridge_path or "").strip()
        self.python_path = str(python_path or "").strip()

    def run(self):
        try:
            if self.action == "start":
                if (not self.bridge_path) or (not os.path.exists(self.bridge_path)):
                    self.done.emit("start", False, None, "找不到 bridge.py 文件")
                    return
                py = self.python_path or sys.executable
                proc = subprocess.Popen(
                    [py, self.bridge_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(self.bridge_path),
                )
                time.sleep(1.0)
                if proc.poll() is not None:
                    self.done.emit("start", False, None, f"桥接服务启动失败（exit={proc.returncode}）")
                    return
                self.done.emit("start", True, proc, "")
                return

            if self.action == "stop":
                proc = self.process
                if not proc:
                    self.done.emit("stop", True, None, "")
                    return
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=2)
                    self.done.emit("stop", True, None, "")
                except Exception as e:
                    self.done.emit("stop", False, None, str(e))
                return

            self.done.emit(self.action, False, None, f"不支持的桥接操作: {self.action}")
        except Exception as e:
            self.done.emit(self.action, False, None, str(e))

class V2HealthProbeThread(QThread):
    """后台探测 v2 API 健康状态，避免主线程阻塞。"""

    done = pyqtSignal(object)

    def __init__(self, host: str, port: int, api_key: str = "", timeout_s: float = 0.5):
        super().__init__()
        self.host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        self.port = int(port or 9880)
        self.api_key = str(api_key or "").strip()
        self.timeout_s = float(timeout_s)

    def run(self):
        base_url = f"http://{self.host}:{self.port}"
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        result = {
            "ok": False,
            "base_url": base_url,
            "api_key": self.api_key,
            "error": "",
            "model_loaded": False,
        }
        try:
            resp = requests.get(f"{base_url}/api/v2/health", headers=headers, timeout=self.timeout_s)
            if int(resp.status_code) < 400:
                payload = resp.json() or {}
                loaded = bool(payload.get("model_loaded", False))
                result["model_loaded"] = loaded
                result["ok"] = loaded
            else:
                result["error"] = f"HTTP {resp.status_code}"
        except Exception as e:
            result["error"] = str(e)
        self.done.emit(result)
