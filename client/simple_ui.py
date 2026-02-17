# CosyVoice 简化版前端界面
# 只包含 API 连接测试和基础 TTS 功能（支持参考音频上传）

import sys
import os
import base64
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, 
    QLineEdit, QApplication, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QUrl
from PyQt5.QtGui import QFont
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from qfluentwidgets import (
    PushButton, PrimaryPushButton, SpinBox, SubtitleLabel, BodyLabel,
    FluentIcon, InfoBar, InfoBarPosition, CardWidget, CaptionLabel,
    TextEdit, isDarkTheme, setTheme, Theme, FluentWindow, NavigationItemPosition
)

from api_client import CosyVoiceAPIClient, APIConfig


class DirectAudioGenerationThread(QThread):
    """直接音频生成线程（使用参考音频）"""
    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)
    
    def __init__(self, client: CosyVoiceAPIClient, text: str, prompt_text: str, 
                 prompt_audio_path: str, speed: float):
        super().__init__()
        self.client = client
        self.text = text
        self.prompt_text = prompt_text
        self.prompt_audio_path = prompt_audio_path
        self.speed = speed
    
    def run(self):
        try:
            audio_data = self.client.generate_audio_direct(
                self.text, self.prompt_text, self.prompt_audio_path, self.speed
            )
            if audio_data:
                self.finished.emit(audio_data)
            else:
                self.error.emit("生成音频失败")
        except Exception as e:
            self.error.emit(str(e))


class SimpleAPIPage(QWidget):
    """简化版 API 界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("api_page")
        self.api_client = CosyVoiceAPIClient()
        self.generation_thread = None
        self.prompt_audio_path = ""
        self.current_audio_path = ""
        self.media_player = QMediaPlayer()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        title = SubtitleLabel("CosyVoice API 客户端")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        layout.addWidget(title)
        
        # === API 设置卡片 ===
        api_card = CardWidget(self)
        api_layout = QVBoxLayout(api_card)
        api_layout.setSpacing(15)
        
        api_title = BodyLabel("API 服务器设置")
        api_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        api_layout.addWidget(api_title)
        
        # 主机和端口
        host_layout = QHBoxLayout()
        host_layout.addWidget(BodyLabel("主机:"))
        self.host_input = QLineEdit("localhost")
        self.host_input.setFixedWidth(200)
        host_layout.addWidget(self.host_input)
        
        host_layout.addWidget(BodyLabel("端口:"))
        self.port_input = SpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9880)
        host_layout.addWidget(self.port_input)
        host_layout.addStretch()
        api_layout.addLayout(host_layout)
        
        # 测试连接按钮
        btn_layout = QHBoxLayout()
        self.test_btn = PrimaryPushButton(FluentIcon.LINK, "测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        btn_layout.addWidget(self.test_btn)
        
        self.status_label = CaptionLabel("未连接")
        self.status_label.setStyleSheet("color: gray;")
        btn_layout.addWidget(self.status_label)
        btn_layout.addStretch()
        api_layout.addLayout(btn_layout)
        
        layout.addWidget(api_card)
        
        # === 参考音频卡片 ===
        ref_card = CardWidget(self)
        ref_layout = QVBoxLayout(ref_card)
        ref_layout.setSpacing(15)
        
        ref_title = BodyLabel("参考音频设置（零样本克隆）")
        ref_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        ref_layout.addWidget(ref_title)
        
        # 参考音频文件选择
        audio_layout = QHBoxLayout()
        audio_layout.addWidget(BodyLabel("参考音频:"))
        self.audio_path_label = QLineEdit()
        self.audio_path_label.setPlaceholderText("选择一个 WAV/MP3 音频文件...")
        self.audio_path_label.setReadOnly(True)
        audio_layout.addWidget(self.audio_path_label)
        
        self.browse_btn = PushButton(FluentIcon.FOLDER, "浏览")
        self.browse_btn.clicked.connect(self.browse_audio)
        audio_layout.addWidget(self.browse_btn)
        ref_layout.addLayout(audio_layout)
        
        # 参考音频对应文本
        ref_layout.addWidget(BodyLabel("参考音频对应的文本 (prompt_text):"))
        self.prompt_text_input = TextEdit()
        self.prompt_text_input.setPlaceholderText("输入参考音频中说话人所说的文字内容...")
        self.prompt_text_input.setFixedHeight(60)
        ref_layout.addWidget(self.prompt_text_input)
        
        layout.addWidget(ref_card)
        
        # === TTS 测试卡片 ===
        tts_card = CardWidget(self)
        tts_layout = QVBoxLayout(tts_card)
        tts_layout.setSpacing(15)
        
        tts_title = BodyLabel("语音合成")
        tts_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        tts_layout.addWidget(tts_title)
        
        # 要合成的文本
        tts_layout.addWidget(BodyLabel("要合成的文本:"))
        self.text_input = TextEdit()
        self.text_input.setPlaceholderText("请输入要合成的文本...")
        self.text_input.setFixedHeight(80)
        tts_layout.addWidget(self.text_input)
        
        # 生成和播放按钮
        gen_layout = QHBoxLayout()
        self.gen_btn = PrimaryPushButton(FluentIcon.PLAY, "生成音频")
        self.gen_btn.clicked.connect(self.generate_audio)
        gen_layout.addWidget(self.gen_btn)
        
        self.play_btn = PushButton(FluentIcon.MICROPHONE, "播放")
        self.play_btn.clicked.connect(self.play_audio)
        self.play_btn.setEnabled(False)
        gen_layout.addWidget(self.play_btn)
        
        self.stop_btn = PushButton(FluentIcon.PAUSE, "停止")
        self.stop_btn.clicked.connect(self.stop_audio)
        self.stop_btn.setEnabled(False)
        gen_layout.addWidget(self.stop_btn)
        
        gen_layout.addStretch()
        tts_layout.addLayout(gen_layout)
        
        layout.addWidget(tts_card)
        
        # === 日志卡片 ===
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        
        log_title = BodyLabel("日志")
        log_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        log_layout.addWidget(log_title)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(120)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_card)
        
        layout.addStretch()
    
    def log(self, message: str):
        """添加日志"""
        self.log_text.append(message)
    
    def browse_audio(self):
        """浏览选择参考音频"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择参考音频", "",
            "音频文件 (*.wav *.mp3 *.flac);;所有文件 (*.*)"
        )
        if file_path:
            self.prompt_audio_path = file_path
            self.audio_path_label.setText(file_path)
            self.log(f"已选择参考音频: {os.path.basename(file_path)}")
    
    def test_connection(self):
        """测试 API 连接"""
        self.api_client.config.host = self.host_input.text()
        self.api_client.config.port = self.port_input.value()
        
        self.log(f"正在连接 {self.api_client.config.base_url}...")
        self.test_btn.setEnabled(False)
        
        result = self.api_client.health_check()
        
        if result["status"] == "ok":
            self.status_label.setText("✅ 已连接")
            self.status_label.setStyleSheet("color: green;")
            self.log(f"✅ 连接成功: {result.get('data', {})}")
            InfoBar.success(
                title="连接成功",
                content=f"已连接到 {self.api_client.config.base_url}",
                parent=self,
                position=InfoBarPosition.TOP
            )
        else:
            self.status_label.setText("❌ 连接失败")
            self.status_label.setStyleSheet("color: red;")
            self.log(f"❌ 连接失败: {result.get('message', '未知错误')}")
            InfoBar.error(
                title="连接失败",
                content=result.get("message", "未知错误"),
                parent=self,
                position=InfoBarPosition.TOP
            )
        
        self.test_btn.setEnabled(True)
    
    def generate_audio(self):
        """生成音频"""
        text = self.text_input.toPlainText().strip()
        prompt_text = self.prompt_text_input.toPlainText().strip()
        
        if not text:
            InfoBar.warning(title="提示", content="请输入要合成的文本", parent=self, position=InfoBarPosition.TOP)
            return
        
        if not self.prompt_audio_path:
            InfoBar.warning(title="提示", content="请选择参考音频文件", parent=self, position=InfoBarPosition.TOP)
            return
        
        if not prompt_text:
            InfoBar.warning(title="提示", content="请输入参考音频对应的文本", parent=self, position=InfoBarPosition.TOP)
            return
        
        self.log(f"正在生成音频: {text[:30]}...")
        self.gen_btn.setEnabled(False)
        
        # 启动生成线程
        self.generation_thread = DirectAudioGenerationThread(
            self.api_client, text, prompt_text, self.prompt_audio_path, 1.0
        )
        self.generation_thread.finished.connect(self.on_audio_generated)
        self.generation_thread.error.connect(self.on_audio_error)
        self.generation_thread.start()
    
    def on_audio_generated(self, audio_data: bytes):
        """音频生成成功"""
        self.gen_btn.setEnabled(True)
        
        import tempfile
        temp_file = os.path.join(tempfile.gettempdir(), "cosyvoice_test.wav")
        with open(temp_file, "wb") as f:
            f.write(audio_data)
        
        self.log(f"✅ 音频生成成功，已保存到: {temp_file}")
        self.log(f"   文件大小: {len(audio_data) / 1024:.1f} KB")
        
        # 保存路径并启用播放按钮
        self.current_audio_path = temp_file
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        
        InfoBar.success(
            title="生成成功",
            content="点击播放按钮收听",
            parent=self,
            position=InfoBarPosition.TOP
        )
        
        # 自动播放
        self.play_audio()
    
    def play_audio(self):
        """播放音频"""
        if self.current_audio_path and os.path.exists(self.current_audio_path):
            url = QUrl.fromLocalFile(self.current_audio_path)
            self.media_player.setMedia(QMediaContent(url))
            self.media_player.play()
            self.log("Playing audio...")
    
    def stop_audio(self):
        """停止播放"""
        self.media_player.stop()
        self.log("Stopped")
    
    def on_audio_error(self, error: str):
        """音频生成失败"""
        self.gen_btn.setEnabled(True)
        self.log(f"❌ 生成失败: {error}")
        
        InfoBar.error(
            title="生成失败",
            content=error,
            parent=self,
            position=InfoBarPosition.TOP
        )


class SimpleMainWindow(FluentWindow):
    """简化版主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CosyVoice Client")
        self.resize(800, 800)
        
        self.api_page = SimpleAPIPage(self)
        self.addSubInterface(self.api_page, FluentIcon.LINK, "API 客户端")


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)
    
    window = SimpleMainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
