import json
import os
from typing import Dict, Any

class ConfigManager:
    """配置管理器，用于持久化保存应用设置"""
    
    def __init__(self, config_path: str = "app_config.json"):
        # Keep a dedicated v2 voices config file. The legacy UI voice config loader
        # (`ui/voice_settings.py`) crashes on unknown keys (e.g. character/emotion/ref_asset_ids).
        default_v2_voices = os.path.abspath("./config/super_agent.json")
        if not os.path.exists(default_v2_voices):
            default_v2_voices = os.path.abspath("./config/voices_v2.json")

        self.config_path = config_path
        self.config: Dict[str, Any] = {
            "theme": "Light",
            "voice_config_path": "",
            "project_name": "project",
            "output_dir": "./output",
            "cosyvoice_model_path": os.path.abspath("./pretrained_models/Fun-CosyVoice3-0.5B"),
            "wetext_model_path": os.path.abspath("./pretrained_models/wetext"),
            "fp16": False,  # Whether to use FP16 mixed precision

            # v2 API client defaults (used by UI pages)
            "api_host": "127.0.0.1",
            "api_port": 9880,
            "api_key": "",

            # Embedded API server: v2 voices config file path (separate from legacy UI voice_config_path)
            "v2_voices_config_path": default_v2_voices,

            # Optional overrides
            "bridge_python": "",  # empty = use sys.executable

            # UI synthesis backend: prefer v2 API (cache/jobs/emotion voices) when available.
            "ui_use_v2_generation": True,

            # UI startup behavior
            "ui_auto_start_api_server": True,

            # Voice Library (voice picker) UI state
            "ui_recent_voice_ids": [],
            "ui_favorite_characters": [],
            "ui_last_emotion_by_character": {},
            "ui_voice_library_splitter_ratio": 0.32,
        }
        self.load_config()

    def load_config(self):
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception as e:
                print(f"Error loading config: {e}")

    def save_config(self):
        """保存配置"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value
        self.save_config()
