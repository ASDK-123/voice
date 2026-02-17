from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QLineEdit
from qfluentwidgets import (
    SwitchButton, SpinBox, SubtitleLabel, BodyLabel, 
    PushButton, LineEdit
)
from core.config_manager import ConfigManager
from .theme.tokens import Palette, Typography
import os
import logging

logger = logging.getLogger(__name__)

class SettingsInterface(QWidget):
    """设置界面 - 现在包含侧边栏内容"""
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # 标题
        title = SubtitleLabel("应用设置")
        layout.addWidget(title)

        # 模型自动加载设置
        model_layout = QHBoxLayout()
        model_label = BodyLabel("启动时自动加载模型")
        self.auto_load_switch = SwitchButton()
        self.auto_load_switch.checkedChanged.connect(self.on_auto_load_changed)
        model_layout.addWidget(model_label)
        model_layout.addStretch()
        model_layout.addWidget(self.auto_load_switch)
        layout.addLayout(model_layout)
        
        # 提示信息
        model_tip = BodyLabel("启用后，应用启动时会自动加载 CosyVoice 模型（需要等待加载完成）")
        model_tip.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: {Typography.CAPTION_SIZE}px;")
        layout.addWidget(model_tip)

        # FP16 设置
        fp16_layout = QHBoxLayout()
        fp16_label = BodyLabel("启用 FP16 混合精度 (推荐 RTX 20系及以上显卡)")
        self.fp16_switch = SwitchButton()
        self.fp16_switch.checkedChanged.connect(self.on_fp16_changed)
        fp16_layout.addWidget(fp16_label)
        fp16_layout.addStretch()
        fp16_layout.addWidget(self.fp16_switch)
        layout.addLayout(fp16_layout)

        fp16_tip = BodyLabel("开启后可大幅降低显存占用并提升推理速度。修改此设置后需要重新加载模型生效。")
        fp16_tip.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: {Typography.CAPTION_SIZE}px;")
        layout.addWidget(fp16_tip)
        
        # 最小文本长度设置
        min_text_layout = QHBoxLayout()
        min_text_label = BodyLabel("最小推理文本长度")
        self.min_text_spin = SpinBox()
        self.min_text_spin.setMinimum(0)
        self.min_text_spin.setMaximum(10)
        self.min_text_spin.valueChanged.connect(self.on_min_text_changed)
        min_text_layout.addWidget(min_text_label)
        min_text_layout.addStretch()
        min_text_layout.addWidget(self.min_text_spin)
        layout.addLayout(min_text_layout)
        
        # 提示信息
        min_text_tip = BodyLabel("使用API时,低于此长度的文本会被跳过，避免推理失败（推荐4字符）")
        min_text_tip.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: {Typography.CAPTION_SIZE}px;")
        layout.addWidget(min_text_tip)

        # 路径设置
        path_title = SubtitleLabel("路径设置")
        layout.addWidget(path_title)
        
        # 输出目录
        self.output_path_layout, self.output_path_edit = self.create_path_setting(
            "默认输出目录", "output_dir"
        )
        layout.addLayout(self.output_path_layout)
        
        # CosyVoice 模型路径
        self.cosyvoice_path_layout, self.cosyvoice_path_edit = self.create_path_setting(
            "CosyVoice 模型路径", "cosyvoice_model_path"
        )
        layout.addLayout(self.cosyvoice_path_layout)
        
        # WeText 模型路径
        self.wetext_path_layout, self.wetext_path_edit = self.create_path_setting(
            "WeText 模型路径", "wetext_model_path"
        )
        layout.addLayout(self.wetext_path_layout)

        # API v2 settings (UI uses API v2 as the default synthesis path)
        api_title = SubtitleLabel("API v2 设置")
        layout.addWidget(api_title)

        api_hp = QHBoxLayout()
        api_hp.addWidget(BodyLabel("API Host"))
        self.api_host_edit = LineEdit()
        self.api_host_edit.setPlaceholderText("127.0.0.1")
        self.api_host_edit.textChanged.connect(lambda t: self.config_manager.set("api_host", (t or "").strip()))
        self.api_host_edit.setFixedWidth(220)
        api_hp.addWidget(self.api_host_edit)

        api_hp.addSpacing(12)
        api_hp.addWidget(BodyLabel("API Port"))
        self.api_port_spin = SpinBox()
        self.api_port_spin.setRange(1024, 65535)
        self.api_port_spin.valueChanged.connect(lambda v: self.config_manager.set("api_port", int(v)))
        api_hp.addWidget(self.api_port_spin)

        api_hp.addStretch()
        layout.addLayout(api_hp)

        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(BodyLabel("API Key (可选)"))
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("留空 = 不启用鉴权")
        try:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
        except Exception:
            pass
        self.api_key_edit.textChanged.connect(lambda t: self.config_manager.set("api_key", (t or "").strip()))
        api_key_layout.addWidget(self.api_key_edit, 1)
        layout.addLayout(api_key_layout)

        # v2 voices config path (for embedded API server)
        self.v2_voices_layout, self.v2_voices_edit = self.create_path_setting(
            "v2 voices 配置文件（API Server 使用）", "v2_voices_config_path", is_dir=False
        )
        layout.addLayout(self.v2_voices_layout)

        # Bridge python override (optional)
        self.bridge_py_layout, self.bridge_py_edit = self.create_path_setting(
            "Bridge Python（可选，默认用当前解释器）", "bridge_python", is_dir=False
        )
        layout.addLayout(self.bridge_py_layout)

        layout.addStretch()

    def create_path_setting(self, title, config_key, is_dir=True):
        layout = QVBoxLayout()
        layout.setSpacing(5)
        
        label = BodyLabel(title)
        layout.addWidget(label)
        
        input_layout = QHBoxLayout()
        line_edit = LineEdit()
        
        # Connect text change to save config
        line_edit.textChanged.connect(lambda text: self.config_manager.set(config_key, text))
        
        btn = PushButton("浏览")
        btn.clicked.connect(lambda: self.browse_path(line_edit, config_key, is_dir))
        
        input_layout.addWidget(line_edit)
        input_layout.addWidget(btn)
        layout.addLayout(input_layout)
        
        return layout, line_edit

    def browse_path(self, line_edit, config_key, is_dir):
        if is_dir:
            path = QFileDialog.getExistingDirectory(self, "选择目录", line_edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", line_edit.text())
            
        if path:
            # Convert to absolute path
            abs_path = os.path.abspath(path)
            line_edit.setText(abs_path)
            self.config_manager.set(config_key, abs_path)

    def load_settings(self):
        auto_load = self.config_manager.get("auto_load_model", False)
        self.auto_load_switch.setChecked(auto_load)
        
        fp16_enabled = self.config_manager.get("fp16", False)
        self.fp16_switch.setChecked(fp16_enabled)
        
        min_text_length = self.config_manager.get("min_text_length", 5)
        self.min_text_spin.setValue(min_text_length)

        self.output_path_edit.setText(self.config_manager.get("output_dir", "./output"))
        self.cosyvoice_path_edit.setText(self.config_manager.get("cosyvoice_model_path", ""))
        self.wetext_path_edit.setText(self.config_manager.get("wetext_model_path", ""))

        # API v2
        self.api_host_edit.setText(self.config_manager.get("api_host", "127.0.0.1"))
        self.api_port_spin.setValue(int(self.config_manager.get("api_port", 9880)))
        self.api_key_edit.setText(self.config_manager.get("api_key", ""))
        self.v2_voices_edit.setText(self.config_manager.get("v2_voices_config_path", ""))
        self.bridge_py_edit.setText(self.config_manager.get("bridge_python", ""))

    def on_auto_load_changed(self, checked):
        self.config_manager.set("auto_load_model", checked)

    def on_fp16_changed(self, checked):
        self.config_manager.set("fp16", checked)
    
    def on_min_text_changed(self, value):
        self.config_manager.set("min_text_length", value)
        # 实时更新API的最小文本长度
        try:
            from core import api
            api.set_min_text_length(value)
        except Exception as e:
            logger.warning("set_min_text_length failed: %s", e)
