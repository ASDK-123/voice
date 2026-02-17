import sys
import io
import threading
import logging
import requests
import subprocess
import os
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
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.server_thread = None
        self.bridge_process = None  # 桥接服务进程
        self.init_ui()
        self.connect_signals()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 左侧：控制面板
        left_panel = CardWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题和文档按钮
        title_layout = QHBoxLayout()
        title = SubtitleLabel("API 服务（SillyTavern适配）")
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        doc_btn = PushButton("?")
        doc_btn.setMaximumWidth(35)
        doc_btn.clicked.connect(self.show_api_doc)
        title_layout.addWidget(doc_btn)
        
        left_layout.addLayout(title_layout)
        # 端口设置
        port_layout = QHBoxLayout()
        port_label = BodyLabel("端口:")
        self.port_spin = SpinBox(self)
        self.port_spin.setRange(1024, 65535)
        try:
            self.port_spin.setValue(int(self.main_window.config_manager.get("api_port", 9880)))
        except Exception:
            self.port_spin.setValue(9880)
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_spin, 1)
        left_layout.addLayout(port_layout)

        self.voices_cfg_label = CaptionLabel("", self)
        self.voices_cfg_label.setWordWrap(True)
        self.voices_cfg_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_layout.addWidget(self.voices_cfg_label)
        self._refresh_voices_cfg_label()
        
        # 角色列表部分
        list_header_layout = QHBoxLayout()
        char_title = SubtitleLabel("角色列表")
        list_header_layout.addWidget(char_title)
        list_header_layout.addStretch()
        
        # 手动刷新按钮
        refresh_btn = PushButton("刷新列表")
        refresh_btn.setIcon(FluentIcon.SYNC)
        refresh_btn.clicked.connect(self.refresh_character_list)
        list_header_layout.addWidget(refresh_btn)
        
        left_layout.addLayout(list_header_layout)
        
        # voices 列表（v2 优先）
        self.character_table = TableWidget()
        self.character_table.setColumnCount(4)
        self.character_table.setHorizontalHeaderLabels(["voice_id", "character", "emotion", "mode"])
        # self.character_table.setMaximumHeight(250) # 移除固定高度
        
        # 隐藏垂直表头
        self.character_table.verticalHeader().setVisible(False)
        
        # 设置列宽
        header = self.character_table.horizontalHeader()
        # 允许用户调整列宽
        header.setSectionResizeMode(QHeaderView.Interactive)
        # 设置最小宽度
        header.setMinimumSectionSize(80)
        # 让最后一列填充剩余空间
        header.setStretchLastSection(True)
        self.character_table.setColumnWidth(0, 180)
        self.character_table.setColumnWidth(1, 120)
        self.character_table.setColumnWidth(2, 100)
        self.character_table.setColumnWidth(3, 140)
        
        left_layout.addWidget(self.character_table, 1) # 增加权重，使其占据剩余空间
        
        # left_layout.addStretch() # 移除Stretch，让表格填充
        
        # 控制按钮
        self.start_btn = PrimaryPushButton("启动 API 服务")
        self.start_btn.setIcon(FluentIcon.PLAY)
        self.start_btn.clicked.connect(self.toggle_server)
        left_layout.addWidget(self.start_btn)
        
        # 流式输出开关
        self.stream_switch = SwitchButton("启用流式响应 (更快)")
        self.stream_switch.checkedChanged.connect(self.on_stream_changed)
        self.stream_switch.setEnabled(False)  # 服务未启动时禁用
        left_layout.addWidget(self.stream_switch)

        # 参考音色缓存开关
        self.spk_cache_switch = SwitchButton("启用参考音色缓存 (加速)")
        self.spk_cache_switch.checkedChanged.connect(self.on_spk_cache_changed)
        self.spk_cache_switch.setEnabled(False)
        left_layout.addWidget(self.spk_cache_switch)
        
        
        # 桥接服务按钮
        self.bridge_btn = PushButton("启动桥接服务")
        self.bridge_btn.setIcon(FluentIcon.LINK)
        self.bridge_btn.clicked.connect(self.toggle_bridge)
        left_layout.addWidget(self.bridge_btn)
        
        # 状态指示
        self.status_label = CaptionLabel("API: 已停止 | 桥接: 已停止")
        self.status_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.status_label)
        
        layout.addWidget(left_panel, 1)
        
        # 右侧：日志输出
        right_panel = CardWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        
        log_title = SubtitleLabel("运行日志")
        right_layout.addWidget(log_title)
        
        self.log_view = TextEdit(self)
        self.log_view.setReadOnly(True)
        font = QFont("Consolas", 10) # 使用 Consolas 字体，更像终端
        font.setFixedPitch(True)
        self.log_view.setFont(font)
        # 移除强制的浅色背景样式，让其跟随主题
        self.log_view.setStyleSheet("""
            TextEdit {
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 6px;
                padding: 8px;
                background-color: transparent; 
            }
        """)
        right_layout.addWidget(self.log_view)
        
        clear_btn = PushButton("清空日志")
        clear_btn.clicked.connect(self.log_view.clear)
        right_layout.addWidget(clear_btn)
        
        layout.addWidget(right_panel, 2)
        
        # 初始化角色列表（从本地加载）
        # self.refresh_local_character_list() # 不再自动加载，等待服务启动或手动刷新
    
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

    def append_log(self, text):
        """添加日志到日志窗口，支持颜色"""
        if text.strip():
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_line = f"[{timestamp}] {text}"
            
            # 使用在深浅色模式下都能看清的颜色，解决切换主题时看不清的问题
            
            color = "#808080"  # 默认灰色

            u = text.upper()
            if "[ERROR]" in u or "失败" in text or "异常" in text or "错误" in text:
                color = "#ff4500"  # OrangeRed
            elif "[WARN]" in u or "警告" in text:
                color = "#ff8c00"  # DarkOrange
            elif "[OK]" in u or "成功" in text:
                color = "#32cd32"  # LimeGreen
            elif "[INFO]" in u or "正在" in text or "开始推理" in text:
                color = "#1e90ff"  # DodgerBlue
            elif "推理文本" in text:
                color = "#9966cc"  # 统一的紫色
            
            html_line = f'<span style="color: {color}">{log_line}</span>'
            self.log_view.append(html_line)
            
            # 滚动到底部
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
            content=f'模型加载失败: {error_msg}',
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
                content=f'找不到 v2 voices 配置文件: {v2_cfg}',
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
                content=f'启动服务失败: {str(e)}',
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
            content=error_msg,
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
            
            # 使用线程发送请求防止 UI 卡顿
            threading.Thread(target=self._send_stream_request, args=(url, is_checked)).start()
        except Exception as e:
            self.log_received.emit(f"[ERROR] 设置流式输出失败: {e}")
            
    def _send_stream_request(self, url, enabled):
        """后台发送流式配置请求"""
        try:
            response = requests.post(url, json={'enabled': enabled}, timeout=2)
            if response.status_code == 200:
                state = "开启" if enabled else "关闭"
                self.log_received.emit(f"[OK] 流式输出已{state}")
            else:
                self.log_received.emit(f"[WARN] 设置流式失败: {response.status_code}")
                # 恢复 UI 状态 (需要在主线程执行，这里暂时省略，用户点击无效可手动切换回)
        except Exception as e:
            self.log_received.emit(f"[ERROR] 设置流式请求异常: {e}")

    def on_spk_cache_changed(self, is_checked):
        """参考音色缓存开关状态改变"""
        if not self.server_thread or not self.server_thread.is_running:
            return
            
        try:
            port = self.port_spin.value()
            url = f"http://127.0.0.1:{port}/api/toggle_spk_cache"
            
            # 使用线程发送请求防止 UI 卡顿
            threading.Thread(target=self._send_spk_cache_request, args=(url, is_checked)).start()
        except Exception as e:
            self.log_received.emit(f"[ERROR] 设置参考音色缓存失败: {e}")

    def _send_spk_cache_request(self, url, enabled):
        """后台发送参考音色缓存配置请求"""
        try:
            response = requests.post(url, json={'enabled': enabled}, timeout=2)
            if response.status_code == 200:
                state = "开启" if enabled else "关闭"
                self.log_received.emit(f"[OK] 参考音色缓存已{state}")
            else:
                self.log_received.emit(f"[WARN] 设置参考音色缓存失败: {response.status_code}")
        except Exception as e:
            self.log_received.emit(f"[ERROR] 设置参考音色缓存请求异常: {e}")
    
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
                content=f'启动桥接服务失败: {str(e)}',
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
        api_status = "运行中" if (self.server_thread and self.server_thread.isRunning()) else "已停止"
        bridge_status = "运行中" if (self.bridge_process and self.bridge_process.poll() is None) else "已停止"
        self.status_label.setText(f"API: {api_status} | 桥接: {bridge_status}")

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
