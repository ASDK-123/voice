from __future__ import annotations

import os
import sys

from PyQt5.QtWidgets import QApplication
from qfluentwidgets import FluentWindow

# Ensure repo root on sys.path when run as a script.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.config_manager import ConfigManager
from ui.voice_setup_wizard import VoiceSetupWizardDialog


class _MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        # Minimal stubs used by the wizard.
        self.api_interface = type("ApiStub", (), {"toggle_server": lambda _s: None})()
        self.on_load_model_clicked = lambda: None


class _DummyClient:
    def health(self):
        return {"status": "ok", "model_loaded": False}

    def upload_asset(self, **_kwargs):
        return {"asset_id": "dummy"}

    def download_asset_content(self, _aid: str) -> bytes:
        return b"RIFF....WAVE"

    def create_voice(self, voice: dict):
        return voice

    def compile_voice(self, voice_id: str, compile_all: bool = False):
        return {"compiled": [voice_id], "compile_all": bool(compile_all)}

    def synthesize_audio(self, _req: dict) -> bytes:
        return b"RIFF....WAVE"


def main() -> int:
    app = QApplication([])
    mw = _MainWindow()
    dlg = VoiceSetupWizardDialog(mw, lambda: _DummyClient(), preset_character="Tom", preset_emotion="default")
    # Don't exec_(); just verify construction works.
    dlg.close()
    mw.close()
    print("smoke wizard construct: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

