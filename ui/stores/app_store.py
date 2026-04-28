from PyQt5.QtCore import QObject, pyqtSignal
from typing import List, Dict, Optional

class StateStore(QObject):
    """
    全局单一状态树 (Single Source of Truth)
    参考了 Vue/Pinia 模式。所有的组件从这里获取当前状态，并通过订阅信号自动响应变更。
    """
    # ====== Signals ======
    # 触发UI响应变更的专属信号
    theme_changed = pyqtSignal(str)              # Light / Dark / Auto
    voice_configs_changed = pyqtSignal(list)     # 所有的音色配置
    selected_voice_changed = pyqtSignal(str)     # 当前选中的角色音色 ID
    assets_list_changed = pyqtSignal(list)       # 情感附件音频列表
    project_name_changed = pyqtSignal(str)       # 全局当前工程名
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # ====== State ======
        self._theme: str = "Light"
        self._voice_configs: List[Dict] = []
        self._selected_voice: str = ""
        self._assets: List[Dict] = []
        self._project_name: str = "project"
        
    # ====== Getters ======
    @property
    def theme(self) -> str:
        return self._theme
        
    @property
    def voice_configs(self) -> List[Dict]:
        return self._voice_configs
        
    @property
    def selected_voice(self) -> str:
        return self._selected_voice
        
    @property
    def assets(self) -> List[Dict]:
        return self._assets
        
    @property
    def project_name(self) -> str:
        return self._project_name

    # ====== Actions (Setters) ======
    def set_theme(self, theme: str):
        if self._theme != theme:
            self._theme = theme
            self.theme_changed.emit(self._theme)
            
    def set_voice_configs(self, configs: List[Dict]):
        self._voice_configs = configs
        self.voice_configs_changed.emit(self._voice_configs)
        
    def set_selected_voice(self, voice_id: str):
        if self._selected_voice != voice_id:
            self._selected_voice = voice_id
            self.selected_voice_changed.emit(self._selected_voice)
            
    def set_assets(self, assets: List[Dict]):
        self._assets = assets
        self.assets_list_changed.emit(self._assets)
        
    def set_project_name(self, name: str):
        if self._project_name != name:
            self._project_name = name
            self.project_name_changed.emit(self._project_name)

_app_store_instance = None

def use_app_store(parent=None) -> StateStore:
    global _app_store_instance
    if _app_store_instance is None:
        _app_store_instance = StateStore(parent)
    return _app_store_instance
