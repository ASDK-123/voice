import sys
import io
import threading
import logging
import requests
import subprocess
import os
import html
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QScrollArea, QDialog, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer
from PyQt5.QtGui import QFont, QColor

from qfluentwidgets import (
    PushButton, PrimaryPushButton, SpinBox, SubtitleLabel, BodyLabel,
    FluentIcon, InfoBar, InfoBarPosition, CardWidget, CaptionLabel, TableWidget,
    MessageBoxBase, TextEdit, isDarkTheme, SwitchButton
)

from core.worker import ModelLoaderThread
from werkzeug.serving import make_server
from core import api

from .v2_client import V2Client, V2Config, V2HttpError
from .theme.tokens import Palette

class APIDocDialog(MessageBoxBase):
    """API 文档对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("API 文档", self)
        self.viewLayout.addWidget(self.titleLabel)
        
        self.doc_text = TextEdit(self)
        self.doc_text.setReadOnly(True)
        self.doc_text.setMarkdown("""# CosyVoice API (v2 优先)

> 说明：桌面端现在推荐优先使用 v2 接口（带 `request_id` 和结构化错误码）。旧 v1 端点仍保留兼容。

## v2: 健康检查
**GET** `/api/v2/health`

## v2: voices（角色/情绪配置）
**GET** `/api/v2/voices`  
**POST** `/api/v2/voices`  
**PUT** `/api/v2/voices/{voice_id}`  
**DELETE** `/api/v2/voices/{voice_id}`

`voice_id` 推荐形式：`{character}#{emotion}`，例如 `Tom#happy`。

## v2: 参考音频 assets
**GET** `/api/v2/assets/audio?character=Tom&emotion=happy`  
**POST** `/api/v2/assets/audio`（multipart，字段：`file/audio`、`character`、`emotion`、`language`）  
**GET** `/api/v2/assets/audio/{asset_id}/content`（试听）

## v2: 合成
**POST** `/api/v2/synthesize`
```json
{
  "text": "要合成的文本",
  "voice_id": "Tom#happy",
  "speed": 1.0,
  "response_format": "audio"
}
```

## v2: 错误格式（JSON）
```json
{"error":{"code":"invalid_request","message":"...","details":{}},"request_id":"..."}
```
响应头也会带：`X-Request-Id`。

## v1（兼容）：酒馆/旧客户端
- **POST** `/`（字段：`text`,`speaker`,`speed`）
- **GET** `/speakers`
- **POST** `/api/tts`
""")
        self.doc_text.setMinimumSize(600, 400)
        self.viewLayout.addWidget(self.doc_text)
        
        # 隐藏 确定/取消 按钮，只保留一个关闭按钮
        self.yesButton.setText("关闭")
        self.yesButton.clicked.connect(self.accept)
        self.cancelButton.hide()
        
        self.widget.setMinimumWidth(650)


class LogHandler(logging.Handler):
    """日志处理器，将日志发送到信号"""
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class StreamToSignal(object):
    """重定向 stdout/stderr 到信号"""
    def __init__(self, signal):
        self.signal = signal

    def write(self, text):
        self.signal.emit(text)

    def flush(self):
        pass

class RuntimeCharacterConfig:
    """运行时角色配置适配器"""
    def __init__(self, voice_settings_interface):
        self.voice_interface = voice_settings_interface

    def get_character(self, char_name: str) -> dict:
        """获取角色配置"""
        # 遍历 voice_interface 中的配置
        for config in self.voice_interface.voice_configs:
            if config.name == char_name:
                return config.to_dict()
        return None
    
    def list_characters(self) -> list:
        """列出所有角色"""
        return [config.name for config in self.voice_interface.voice_configs]

class APIServerThread(QThread):
    """API 服务线程"""
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
        
        # 设置日志回调
        api.set_log_callback(self.on_api_log)

    def on_api_log(self, msg):
        """API 日志回调"""
        self.log_signal.emit(msg)

    def run(self):
        try:
            # 设置 API 全局变量
            api.set_globals(self.model, self.config_manager)
            
            # 创建服务器
            self.server = make_server(self.host, self.port, api.app)
            self.is_running = True
            self.started_signal.emit()
            self.log_signal.emit(f"[OK] API Server started at http://{self.host}:{self.port}")
            
            # 启动服务循环
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

class APIPageInterface(QWidget):
    """API 服务管理界面"""
    
    log_received = pyqtSignal(str)
    stream_toggle_done = pyqtSignal(bool, bool, str)  # ok, enabled, message
    spk_cache_toggle_done = pyqtSignal(bool, bool, str)  # ok, enabled, message
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.server_thread = None
        self.bridge_process = None  # 桥接服务进程
        self.init_ui()
        self.connect_signals()
        
    def init_ui(self):
        self.log_entries = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 页面标题
        page_header = QHBoxLayout()
        title = SubtitleLabel("API 服务管理")
        page_header.addWidget(title)
        page_header.addStretch()
        doc_btn = PushButton("API 文档")
        doc_btn.setIcon(FluentIcon.HELP)
        doc_btn.clicked.connect(self.show_api_doc)
        page_header.addWidget(doc_btn)
        layout.addLayout(page_header)

        # 1) 服务控制
        service_card = CardWidget(self)
        service_layout = QVBoxLayout(service_card)
        service_layout.setContentsMargins(16, 16, 16, 16)
        service_layout.setSpacing(10)
        service_layout.addWidget(SubtitleLabel("服务控制"))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(BodyLabel("端口:"))
        self.port_spin = SpinBox(self)
        self.port_spin.setRange(1024, 65535)
        try:
            self.port_spin.setValue(int(self.main_window.config_manager.get("api_port", 9880)))
        except Exception:
            self.port_spin.setValue(9880)
        controls.addWidget(self.port_spin)

        self.start_btn = PrimaryPushButton("启动 API 服务")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.start_btn.clicked.connect(self.toggle_server)
        controls.addWidget(self.start_btn)

        self.bridge_btn = PushButton("启动桥接服务")
        self.bridge_btn.setIcon(FluentIcon.LINK)
        self.bridge_btn.clicked.connect(self.toggle_bridge)
        controls.addWidget(self.bridge_btn)
        controls.addStretch()
        service_layout.addLayout(controls)

        self.voices_cfg_label = CaptionLabel("", self)
        self.voices_cfg_label.setWordWrap(True)
        self.voices_cfg_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        service_layout.addWidget(self.voices_cfg_label)
        self._refresh_voices_cfg_label()
        layout.addWidget(service_card)

        # 2) 运行开关 + 状态卡片
        runtime_card = CardWidget(self)
        runtime_layout = QVBoxLayout(runtime_card)
        runtime_layout.setContentsMargins(16, 16, 16, 16)
        runtime_layout.setSpacing(10)
        runtime_layout.addWidget(SubtitleLabel("运行开关"))

        self.stream_switch = SwitchButton("启用流式响应 (更快)")
        self.stream_switch.checkedChanged.connect(self.on_stream_changed)
        self.stream_switch.setEnabled(False)
        runtime_layout.addWidget(self.stream_switch)

        self.spk_cache_switch = SwitchButton("启用参考音色缓存 (加速)")
        self.spk_cache_switch.checkedChanged.connect(self.on_spk_cache_changed)
        self.spk_cache_switch.setEnabled(False)
        runtime_layout.addWidget(self.spk_cache_switch)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.api_status_card, self.api_status_value, self.api_status_detail = self._create_status_card("API 服务")
        self.bridge_status_card, self.bridge_status_value, self.bridge_status_detail = self._create_status_card("桥接服务")
        status_row.addWidget(self.api_status_card, 1)
        status_row.addWidget(self.bridge_status_card, 1)
        runtime_layout.addLayout(status_row)

        self.status_label = CaptionLabel("API: 已停止 | 桥接: 已停止")
        self.status_label.setAlignment(Qt.AlignLeft)
        runtime_layout.addWidget(self.status_label)
        layout.addWidget(runtime_card)

        # 3) voices 列表
        voices_card = CardWidget(self)
        voices_layout = QVBoxLayout(voices_card)
        voices_layout.setContentsMargins(16, 16, 16, 16)
        voices_layout.setSpacing(10)
        voices_header = QHBoxLayout()
        voices_header.addWidget(SubtitleLabel("Voices 列表"))
        voices_header.addStretch()
        self.refresh_btn = PushButton("刷新列表")
        self.refresh_btn.setIcon(FluentIcon.SYNC)
        self.refresh_btn.clicked.connect(self.refresh_character_list)
        voices_header.addWidget(self.refresh_btn)
        voices_layout.addLayout(voices_header)

        self.character_table = TableWidget()
        self.character_table.setColumnCount(4)
        self.character_table.setHorizontalHeaderLabels(["voice_id", "character", "emotion", "mode"])
        self.character_table.verticalHeader().setVisible(False)
        header = self.character_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(80)
        header.setStretchLastSection(True)
        self.character_table.setColumnWidth(0, 180)
        self.character_table.setColumnWidth(1, 120)
        self.character_table.setColumnWidth(2, 100)
        self.character_table.setColumnWidth(3, 140)
        voices_layout.addWidget(self.character_table, 1)
        layout.addWidget(voices_card, 3)

        # 4) 运行日志
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_layout.setSpacing(10)
        log_header = QHBoxLayout()
        log_header.addWidget(SubtitleLabel("运行日志（等级徽标）"))
        log_header.addStretch()
        clear_btn = PushButton("清空日志")
        clear_btn.clicked.connect(self.clear_logs)
        log_header.addWidget(clear_btn)
        log_layout.addLayout(log_header)

        self.log_view = TextEdit(self)
        self.log_view.setReadOnly(True)
        font = QFont("Consolas", 10)
        font.setFixedPitch(True)
        self.log_view.setFont(font)
        self.log_view.setStyleSheet(
            f"TextEdit {{ border: 1px solid {Palette.BORDER}; border-radius: 6px; padding: 8px; background-color: transparent; }}"
        )
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_card, 3)

        self.update_status_label()
    
    def refresh_local_character_list(self):
        """从本地配置加载角色列表"""
        if hasattr(self.main_window, 'voice_interface') and self.main_window.voice_interface:
            characters = []
            for config in self.main_window.voice_interface.voice_configs:
                characters.append({'name': config.name, 'mode': config.mode})
            self.update_character_list(characters)
    
    def show_api_doc(self):
        """显示 API 文档对话框"""
        dialog = APIDocDialog(self.window())
        dialog.exec_()

    def connect_signals(self):
        self.log_received.connect(self.append_log)
        self.stream_toggle_done.connect(self._on_stream_toggle_done)
        self.spk_cache_toggle_done.connect(self._on_spk_cache_toggle_done)

    def clear_logs(self):
        self.log_entries = []
        self.log_view.clear()

    @staticmethod
    def _with_advice(message: str, advice: str = "") -> str:
        msg = str(message or "").strip()
        if not msg:
            return advice or "未知错误"
        if advice and "建议：" not in msg:
            return f"{msg}。建议：{advice}"
        return msg

    def _begin_button_busy(self, btn: PushButton, busy_text: str) -> bool:
        try:
            if bool(btn.property("_busy")):
                return False
            if btn.property("_idle_text") is None:
                btn.setProperty("_idle_text", btn.text())
            btn.setProperty("_busy", True)
            btn.setEnabled(False)
            btn.setText(str(busy_text))
            return True
        except Exception:
            return False

    def _end_button_busy(self, btn: PushButton, *, enabled: bool = True):
        try:
            idle = btn.property("_idle_text")
            if idle is not None:
                btn.setText(str(idle))
            btn.setEnabled(bool(enabled))
            btn.setProperty("_busy", False)
        except Exception:
            pass

    def _create_status_card(self, title: str):
        card = CardWidget(self)
        card.setStyleSheet(f"CardWidget {{ border: 1px solid {Palette.BORDER}; border-radius: 10px; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lay.addWidget(CaptionLabel(title))
        value = BodyLabel("已停止")
        value.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-weight: 600;")
        lay.addWidget(value)
        detail = CaptionLabel("等待启动")
        detail.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        lay.addWidget(detail)
        return card, value, detail

    def _set_status_card_state(self, value_label: BodyLabel, detail_label: CaptionLabel, running: bool, detail: str):
        value_label.setText("运行中" if running else "已停止")
        value_label.setStyleSheet(
            f"color: {Palette.SUCCESS if running else Palette.DANGER}; font-weight: 600;"
        )
        detail_label.setText(detail)

    def _extract_level(self, text: str) -> str:
        u = (text or "").upper()
        if "[ERROR]" in u or "失败" in text or "异常" in text or "错误" in text:
            return "ERROR"
        if "[WARN]" in u or "警告" in text:
            return "WARN"
        if "[OK]" in u or "成功" in text:
            return "OK"
        return "INFO"

    def _level_color(self, level: str):
        if level == "ERROR":
            return Palette.DANGER, "#FDECEC"
        if level == "WARN":
            return Palette.WARNING, "#FFF4E5"
        if level == "OK":
            return Palette.SUCCESS, "#E9F8EF"
        return Palette.INFO, "#EAF6FF"

    def _format_log_html(self, timestamp: str, level: str, message: str) -> str:
        fg, bg = self._level_color(level)
        safe_msg = html.escape(message)
        return (
            f'<span style="color:{Palette.TEXT_SECONDARY}">[{timestamp}]</span> '
            f'<span style="color:{fg}; background:{bg}; border:1px solid {fg}; '
            f'border-radius:8px; padding:1px 6px; font-weight:600;">{level}</span> '
            f'<span style="color:{Palette.TEXT_PRIMARY}">{safe_msg}</span>'
        )

    def append_log(self, text):
        """添加日志到日志窗口，使用等级徽标格式。"""
        t = (text or "").strip()
        if not t:
            return

        level = self._extract_level(t)
        normalized = t
        prefix = f"[{level}]"
        if normalized.upper().startswith(prefix):
            normalized = normalized[len(prefix):].strip()
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_entries.append((timestamp, level, normalized))
        self.log_view.append(self._format_log_html(timestamp, level, normalized))

        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.End)
        self.log_view.setTextCursor(cursor)

    def toggle_server(self):
        if self.server_thread and self.server_thread.isRunning():
            # 停止服务
            self.start_btn.setEnabled(False)
            self.start_btn.setText("正在停止...")
            self.server_thread.stop()
            # 线程结束信号会处理 UI 更新
        else:
            # 启动服务
            # 检查模型是否加载
            if self.main_window.cosyvoice_model is None:
                # 检查是否有正在运行的 worker
                if self.main_window.current_worker and self.main_window.current_worker.cosyvoice:
                    self.main_window.cosyvoice_model = self.main_window.current_worker.cosyvoice
                
                if self.main_window.cosyvoice_model is None:
                    # 自动加载模型
                    self.log_received.emit("[INFO] 检测到模型未加载，正在自动加载模型...")
                    self.start_btn.setEnabled(False)
                    self.start_btn.setText("正在加载模型...")
                    
                    # 连接模型加载信号
                    # 注意：这里需要小心信号连接，避免重复连接
                    try:
                        self.main_window.model_loader_thread = ModelLoaderThread()
                        self.main_window.model_loader_thread.success.connect(self.on_auto_load_model_success)
                        self.main_window.model_loader_thread.error.connect(self.on_auto_load_model_error)
                        self.main_window.model_loader_thread.start()
                    except Exception as e:
                        self.log_received.emit(f"[ERROR] 自动加载模型失败: {str(e)}")
                        self.start_btn.setEnabled(True)
                        self.start_btn.setText("启动 API 服务")
                    return

            self.start_server_process()

    def on_auto_load_model_success(self, model):
        """自动加载模型成功回调"""
        self.main_window.cosyvoice_model = model
        self.log_received.emit("[OK] 模型加载成功")
        # 继续启动服务
        self.start_server_process()

    def on_auto_load_model_error(self, error_msg):
        """自动加载模型失败回调"""
        self.log_received.emit(f"[ERROR] 模型加载失败: {error_msg}")
        self.start_btn.setEnabled(True)
        self.start_btn.setText("启动 API 服务")
        
        InfoBar.error(
            title='加载失败',
            content=self._with_advice(f'模型加载失败: {error_msg}', "可先手动点击“加载模型”，再重试启动 API。"),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def start_server_process(self):
        """实际启动服务的流程"""
        port = self.port_spin.value()
        try:
            self.main_window.config_manager.set("api_port", int(port))
        except Exception:
            pass

        # If user configured an API key in UI settings, enforce it for v2 endpoints
        # in the embedded server process.
        try:
            ui_api_key = (self.main_window.config_manager.get("api_key", "") or "").strip()
        except Exception:
            ui_api_key = ""
        if ui_api_key:
            os.environ["V2_API_KEY"] = ui_api_key

        # Embedded server should use a real CharacterConfig so v2 /voices CRUD works.
        # IMPORTANT: keep this file separate from legacy UI voice_config_path to avoid
        # `VoiceConfig.from_dict(**data)` crashing on extra keys.
        v2_cfg = self._get_v2_voices_config_path()
        # Keep embedded behavior aligned with StartAPIServer.bat: config must exist and be a .json.
        if (not v2_cfg.lower().endswith(".json")) or (not os.path.exists(v2_cfg)):
            self._refresh_voices_cfg_label()
            self.log_received.emit(f"[WARN] v2 voices 配置文件不可用: {v2_cfg}")
            InfoBar.error(
                title='配置文件不存在',
                content=self._with_advice(f'找不到 v2 voices 配置文件: {v2_cfg}', "在设置页修正 v2 配置路径后重试。"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self
            )
            self.start_btn.setEnabled(True)
            self.start_btn.setText("启动 API 服务")
            self.start_btn.setIcon(FluentIcon.PLAY)
            return
        runtime_config = api.CharacterConfig(v2_cfg)
        self.log_received.emit(f"[INFO] v2 voices config: {v2_cfg}")
        self._refresh_voices_cfg_label()

        try:
            self.server_thread = APIServerThread(
                host="0.0.0.0",
                port=port,
                model=self.main_window.cosyvoice_model,
                config_manager=runtime_config
            )

            self.server_thread.log_signal.connect(self.log_received)
            self.server_thread.started_signal.connect(self.on_server_started)
            self.server_thread.stopped_signal.connect(self.on_server_stopped)
            self.server_thread.error_signal.connect(self.on_server_error)

            self.start_btn.setEnabled(False)
            self.start_btn.setText("正在启动...")
            self.server_thread.start()
        except Exception as e:
            self.log_received.emit(f"[ERROR] 启动服务失败: {str(e)}")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("启动 API 服务")
            self.start_btn.setIcon(FluentIcon.PLAY)
            self.port_spin.setEnabled(True)
            self.stream_switch.setEnabled(False)
            self.spk_cache_switch.setEnabled(False)
            InfoBar.error(
                title='服务启动失败',
                content=self._with_advice(f'启动服务失败: {str(e)}', "检查端口占用和模型加载状态。"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )

    def on_server_started(self):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("停止 API 服务")
        self.start_btn.setIcon(FluentIcon.PAUSE)
        self.update_status_label()
        
        # 5秒后自动刷新一次角色列表
        auto_refresh_timer = QTimer(self)
        auto_refresh_timer.setSingleShot(True)
        auto_refresh_timer.timeout.connect(self.refresh_character_list)
        auto_refresh_timer.start(5000)  # 5秒后触发
        self.port_spin.setEnabled(False)
        self.stream_switch.setEnabled(True)  # 启用开关
        self.spk_cache_switch.setEnabled(True)
        
        InfoBar.success(
            title='服务已启动',
            content=f"API 服务正在运行于端口 {self.port_spin.value()}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_server_stopped(self):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("启动 API 服务")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.update_status_label()
        self.port_spin.setEnabled(True)
        self.stream_switch.setEnabled(False)
        self.stream_switch.setChecked(False) # 停止时重置及禁用
        self.spk_cache_switch.setEnabled(False)
        self.spk_cache_switch.setChecked(False)
        self.log_received.emit("API Server stopped.")

    def on_server_error(self, error_msg):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("启动 API 服务")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.update_status_label()
        self.port_spin.setEnabled(True)
        self.stream_switch.setEnabled(False)
        self.stream_switch.setChecked(False)
        self.spk_cache_switch.setEnabled(False)
        self.spk_cache_switch.setChecked(False)
        
        InfoBar.error(
            title='服务错误',
            content=self._with_advice(error_msg, "查看日志后修正配置，再重新启动服务。"),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )
    
    def refresh_character_list(self):
        """从 API 刷新 voices 列表（v2 优先）"""
        # 检查服务器线程是否存在且在运行
        if not self.server_thread:
            self.log_received.emit("[WARN] 服务线程未初始化")
            return
        
        if not self.server_thread.is_running:
            self.log_received.emit("[WARN] 服务未运行，无法刷新角色列表")
            return
        if not self._begin_button_busy(self.refresh_btn, "刷新中..."):
            return
        
        try:
            port = int(self.port_spin.value())
            self.log_received.emit("[INFO] 正在获取 v2 voices 列表...")
            cli = self._v2_client_for_localhost(port)
            items = cli.list_voices()
            self.log_received.emit(f"[OK] 获取成功，共 {len(items)} 个 voice")
            self.update_character_list(items)
        except V2HttpError as e:
            self.log_received.emit(f"[WARN] 获取失败: {e.short()}")
        except Exception as e:
            self.log_received.emit(f"[ERROR] 获取角色列表异常: {str(e)}")
        finally:
            self._end_button_busy(self.refresh_btn)

    def _v2_client_for_localhost(self, port: int) -> V2Client:
        try:
            api_key = (self.main_window.config_manager.get("api_key", "") or "").strip()
        except Exception:
            api_key = ""
        return V2Client(V2Config(host="127.0.0.1", port=int(port), api_key=api_key, timeout_s=3.0))

    def _get_v2_voices_config_path(self) -> str:
        """Return the canonical v2 voices config path used by both UI-embedded server and external bat."""
        try:
            v2_cfg = (self.main_window.config_manager.get("v2_voices_config_path", "") or "").strip()
        except Exception:
            v2_cfg = ""
        if v2_cfg:
            return os.path.abspath(v2_cfg)
        # Conservative fallback that matches this repo's defaults and scripts.
        p = os.path.abspath("./config/super_agent.json")
        if os.path.exists(p):
            return p
        return os.path.abspath("./config/voices_v2.json")

    def _refresh_voices_cfg_label(self):
        try:
            p = self._get_v2_voices_config_path()
            ok = os.path.exists(p) and p.lower().endswith(".json")
            prefix = "v2 voices 配置文件（已找到）：" if ok else "v2 voices 配置文件（未找到）："
            self.voices_cfg_label.setText(f"{prefix}{p}")
            self.voices_cfg_label.setToolTip(p)
        except Exception:
            self.voices_cfg_label.setText("v2 voices 配置文件：<未知>")
    
    def update_character_list(self, characters):
        """更新 voices 列表（characters 参数实际为 voice items）"""
        self.character_table.setRowCount(len(characters))
        
        try:
            # 获取所有角色配置
            voice_configs = self.main_window.voice_interface.get_voice_configs()
        except:
            voice_configs = {}
        
        for row, voice in enumerate(characters):
            if not isinstance(voice, dict):
                voice = {}

            voice_id = str(voice.get("name") or voice.get("voice_id") or "").strip()
            character = str(voice.get("character") or "").strip()
            emotion = str(voice.get("emotion") or "").strip()
            mode = str(voice.get("mode") or "").strip()

            if not character and "#" in voice_id:
                parts = voice_id.split("#", 1)
                character = (parts[0] or "").strip()
                emotion = (parts[1] if len(parts) > 1 else "").strip()

            # If v2 voice doesn't carry mode, try to display legacy UI mode (display-only).
            if not mode and voice_id in voice_configs:
                try:
                    mode = str(getattr(voice_configs[voice_id], "mode", "") or "")
                except Exception:
                    pass

            voice_id_item = QTableWidgetItem(voice_id)
            character_item = QTableWidgetItem(character)
            emotion_item = QTableWidgetItem(emotion or "default")
            mode_item = QTableWidgetItem(mode or "")
            
            # 设置字体
            font = QFont('微软雅黑', 10)
            voice_id_item.setFont(font)
            character_item.setFont(font)
            emotion_item.setFont(font)
            mode_item.setFont(font)
            
            # 居中显示
            voice_id_item.setTextAlignment(Qt.AlignCenter)
            character_item.setTextAlignment(Qt.AlignCenter)
            emotion_item.setTextAlignment(Qt.AlignCenter)
            mode_item.setTextAlignment(Qt.AlignCenter)
            
            # 添加到表格
            self.character_table.setItem(row, 0, voice_id_item)
            self.character_table.setItem(row, 1, character_item)
            self.character_table.setItem(row, 2, emotion_item)
            self.character_table.setItem(row, 3, mode_item)
            
    def on_stream_changed(self, is_checked):
        """流式开关状态改变"""
        if not self.server_thread or not self.server_thread.is_running:
            return
             
        try:
            port = self.port_spin.value()
            url = f"http://127.0.0.1:{port}/api/toggle_stream"
            self.stream_switch.setEnabled(False)
            # 使用线程发送请求防止 UI 卡顿
            threading.Thread(target=self._send_stream_request, args=(url, is_checked), daemon=True).start()
        except Exception as e:
            self.stream_switch.setEnabled(True)
            self.log_received.emit(f"[ERROR] 设置流式输出失败: {e}")
             
    def _send_stream_request(self, url, enabled):
        """后台发送流式配置请求"""
        try:
            response = requests.post(url, json={'enabled': enabled}, timeout=2)
            if response.status_code == 200:
                self.stream_toggle_done.emit(True, bool(enabled), "")
            else:
                self.stream_toggle_done.emit(False, bool(enabled), f"HTTP {response.status_code}")
        except Exception as e:
            self.stream_toggle_done.emit(False, bool(enabled), str(e))

    def _on_stream_toggle_done(self, ok: bool, enabled: bool, message: str):
        self.stream_switch.setEnabled(True)
        if ok:
            state = "开启" if enabled else "关闭"
            self.log_received.emit(f"[OK] 流式输出已{state}")
            return
        self.stream_switch.blockSignals(True)
        self.stream_switch.setChecked(not bool(enabled))
        self.stream_switch.blockSignals(False)
        self.log_received.emit(f"[WARN] 设置流式失败: {message}")

    def on_spk_cache_changed(self, is_checked):
        """参考音色缓存开关状态改变"""
        if not self.server_thread or not self.server_thread.is_running:
            return
            
        try:
            port = self.port_spin.value()
            url = f"http://127.0.0.1:{port}/api/toggle_spk_cache"
            self.spk_cache_switch.setEnabled(False)
            # 使用线程发送请求防止 UI 卡顿
            threading.Thread(target=self._send_spk_cache_request, args=(url, is_checked), daemon=True).start()
        except Exception as e:
            self.spk_cache_switch.setEnabled(True)
            self.log_received.emit(f"[ERROR] 设置参考音色缓存失败: {e}")

    def _send_spk_cache_request(self, url, enabled):
        """后台发送参考音色缓存配置请求"""
        try:
            response = requests.post(url, json={'enabled': enabled}, timeout=2)
            if response.status_code == 200:
                self.spk_cache_toggle_done.emit(True, bool(enabled), "")
            else:
                self.spk_cache_toggle_done.emit(False, bool(enabled), f"HTTP {response.status_code}")
        except Exception as e:
            self.spk_cache_toggle_done.emit(False, bool(enabled), str(e))

    def _on_spk_cache_toggle_done(self, ok: bool, enabled: bool, message: str):
        self.spk_cache_switch.setEnabled(True)
        if ok:
            state = "开启" if enabled else "关闭"
            self.log_received.emit(f"[OK] 参考音色缓存已{state}")
            return
        self.spk_cache_switch.blockSignals(True)
        self.spk_cache_switch.setChecked(not bool(enabled))
        self.spk_cache_switch.blockSignals(False)
        self.log_received.emit(f"[WARN] 设置参考音色缓存失败: {message}")
    
    def toggle_bridge(self):
        """切换桥接服务状态"""
        if self.bridge_process and self.bridge_process.poll() is None:
            # 停止桥接服务
            self.stop_bridge_service()
        else:
            # 启动桥接服务
            self.start_bridge_service()
    
    def start_bridge_service(self):
        """启动桥接服务"""
        self.bridge_btn.setEnabled(False)
        self.bridge_btn.setText("正在启动桥接服务...")
        try:
            # 检查 bridge.py 是否存在
            bridge_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bridge.py')
            if not os.path.exists(bridge_path):
                self.log_received.emit("[ERROR] 找不到 bridge.py 文件")
                InfoBar.error(
                    title='启动失败',
                    content='找不到 bridge.py 文件',
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
                self.bridge_btn.setEnabled(True)
                self.bridge_btn.setText("启动桥接服务")
                self.bridge_btn.setIcon(FluentIcon.LINK)
                return
            
            # 使用系统 Python 启动 bridge.py（后台运行）
            self.log_received.emit("[INFO] 正在启动 OpenAI 桥接服务...")
            
            # Prefer configured python; fall back to current interpreter.
            try:
                python_path = (self.main_window.config_manager.get("bridge_python", "") or "").strip()
            except Exception:
                python_path = ""
            if not python_path:
                python_path = sys.executable
            self.bridge_process = subprocess.Popen(
                [python_path, bridge_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(bridge_path)
            )
            
            # 等待一小会儿检查是否启动成功
            import time
            time.sleep(1.0)
            
            if self.bridge_process.poll() is not None:
                # 进程已经退出，说明启动失败
                stderr = self.bridge_process.stderr.read().decode('utf-8', errors='ignore')
                self.log_received.emit(f"[ERROR] 桥接服务启动失败: {stderr}")
                self.bridge_process = None
                InfoBar.error(
                    title='启动失败',
                    content=f'桥接服务启动失败，请查看日志',
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
                self.bridge_btn.setEnabled(True)
                self.bridge_btn.setText("启动桥接服务")
                self.bridge_btn.setIcon(FluentIcon.LINK)
                return

            
            # 更新 UI
            self.bridge_btn.setText("停止桥接服务")
            self.bridge_btn.setIcon(FluentIcon.PAUSE)
            self.bridge_btn.setEnabled(True)
            self.update_status_label()
            
            self.log_received.emit("[OK] OpenAI 桥接服务已启动 (端口 5000)")
            
            InfoBar.success(
                title='桥接服务已启动',
                content='OpenAI 桥接服务运行于端口 5000',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            
        except Exception as e:
            self.log_received.emit(f"[ERROR] 启动桥接服务失败: {str(e)}")
            self.bridge_btn.setEnabled(True)
            self.bridge_btn.setText("启动桥接服务")
            self.bridge_btn.setIcon(FluentIcon.LINK)
            InfoBar.error(
                title='启动失败',
                content=self._with_advice(f'启动桥接服务失败: {str(e)}', "检查 bridge.py 与 Python 路径配置。"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
    
    def stop_bridge_service(self):
        """停止桥接服务"""
        self.bridge_btn.setEnabled(False)
        self.bridge_btn.setText("正在停止桥接服务...")
        try:
            if self.bridge_process:
                self.log_received.emit("[INFO] 正在停止桥接服务...")
                self.bridge_process.terminate()
                self.bridge_process.wait(timeout=5)
                self.bridge_process = None
                
                # 更新 UI
                self.bridge_btn.setText("启动桥接服务")
                self.bridge_btn.setIcon(FluentIcon.LINK)
                self.update_status_label()
                
                self.log_received.emit("[OK] 桥接服务已停止")
                
        except Exception as e:
            self.log_received.emit(f"[ERROR] 停止桥接服务失败: {str(e)}")
        finally:
            self.bridge_btn.setEnabled(True)
            is_running = bool(self.bridge_process and self.bridge_process.poll() is None)
            if is_running:
                self.bridge_btn.setText("停止桥接服务")
                self.bridge_btn.setIcon(FluentIcon.PAUSE)
            else:
                self.bridge_btn.setText("启动桥接服务")
                self.bridge_btn.setIcon(FluentIcon.LINK)

    def shutdown(self, wait_ms: int = 8000):
        """窗口关闭前的线程/进程收尾，避免 QThread 在运行中被析构。"""
        # Stop embedded API server thread.
        try:
            if self.server_thread:
                if self.server_thread.isRunning():
                    self.server_thread.stop()
                    if not self.server_thread.wait(wait_ms):
                        self.log_received.emit("[WARN] API 线程停止超时，强制终止")
                        self.server_thread.terminate()
                        self.server_thread.wait(1000)
                self.server_thread.deleteLater()
                self.server_thread = None
        except Exception as e:
            self.log_received.emit(f"[ERROR] 关闭 API 线程失败: {str(e)}")

        # Stop bridge process if running.
        try:
            if self.bridge_process and self.bridge_process.poll() is None:
                self.bridge_process.terminate()
                try:
                    self.bridge_process.wait(timeout=5)
                except Exception:
                    self.bridge_process.kill()
                    self.bridge_process.wait(timeout=2)
            self.bridge_process = None
        except Exception as e:
            self.log_received.emit(f"[ERROR] 关闭桥接进程失败: {str(e)}")
    
    def update_status_label(self):
        """更新状态标签"""
        api_running = bool(self.server_thread and self.server_thread.isRunning())
        bridge_running = bool(self.bridge_process and self.bridge_process.poll() is None)

        api_status = "运行中" if api_running else "已停止"
        bridge_status = "运行中" if bridge_running else "已停止"
        self.status_label.setText(f"API: {api_status} | 桥接: {bridge_status}")

        api_detail = f"http://127.0.0.1:{self.port_spin.value()}" if api_running else "等待启动"
        bridge_detail = "http://127.0.0.1:5000" if bridge_running else "等待启动"
        self._set_status_card_state(self.api_status_value, self.api_status_detail, api_running, api_detail)
        self._set_status_card_state(self.bridge_status_value, self.bridge_status_detail, bridge_running, bridge_detail)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
