import sys
import os
import datetime
import gc
from typing import List, Optional

import requests
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QUrl, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from qfluentwidgets import (
    FluentWindow, FluentIcon, NavigationItemPosition, InfoBar, InfoBarPosition, setTheme, Theme,
    ComboBox, BodyLabel, PushButton
)

from core.models import TaskSegment
from core.worker import AudioGenerationWorker, V2AudioGenerationWorker, ModelLoaderThread, ModelUnloaderThread
from core.utils import merge_audio_files
from core.config_manager import ConfigManager

from .text_edit import TextEditInterface
from .task_plan import TaskPlanInterface
from .voice_settings import VoiceSettingsInterface
from .settings import SettingsInterface
from .api_page import APIPageInterface


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


class CosyVoiceProApp(FluentWindow):
    """主应用程序窗口"""
    
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.cosyvoice_model = None
        self.current_worker = None
        self.model_loader_thread = None
        self.model_unloader_thread = None
        self.generation_probe_thread = None
        
        # Qt5 Audio Setup
        self.media_player = QMediaPlayer()
        # self.audio_output = QAudioOutput() # Qt5 doesn't need this for simple playback
        # self.media_player.setAudioOutput(self.audio_output)
        
        self.init_window()
        self.init_navigation()
        self.connect_signals()
        self.load_initial_config()
        
        # 在 GUI 加载完成后，检查是否需要加载模型
        QTimer.singleShot(500, self.load_model_if_enabled)
        # 默认自动启动内嵌 API 服务（可通过 app_config.json: ui_auto_start_api_server 关闭）
        QTimer.singleShot(800, self.auto_start_api_server_if_enabled)
    
    def init_window(self):
        self.setWindowTitle("CosyVoice Desktop")
        self.resize(1400, 900)
        
        # 设置窗口图标
        icon_path = "./icon.ico"
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        # 应用主题
        theme = self.config_manager.get("theme", "Light")
        if theme == "Light":
            setTheme(Theme.LIGHT)
        elif theme == "Dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)
    
    def init_navigation(self):
        # 界面1: 文本编辑
        self.text_interface = TextEditInterface(self.config_manager)
        self.text_interface.setObjectName("TextEditInterface")
        
        # 界面2: 任务计划
        self.task_interface = TaskPlanInterface(self.config_manager)
        self.task_interface.setObjectName("TaskPlanInterface")
        
        # 界面3: 语音设置
        self.voice_interface = VoiceSettingsInterface(self.config_manager)
        self.voice_interface.setObjectName("VoiceSettingsInterface")
        
        # 界面4: 设置
        self.settings_interface = SettingsInterface(self.config_manager)
        self.settings_interface.setObjectName("SettingsInterface")
        
        # 界面5: API 服务
        self.api_interface = APIPageInterface(self)
        self.api_interface.setObjectName("APIPageInterface")

        self.addSubInterface(
            self.text_interface, 
            FluentIcon.EDIT, 
            "文本编辑",
            NavigationItemPosition.TOP
        )
        
        self.addSubInterface(
            self.task_interface, 
            FluentIcon.CALENDAR, 
            "任务计划",
            NavigationItemPosition.TOP
        )
        
        self.addSubInterface(
            self.voice_interface, 
            FluentIcon.MICROPHONE, 
            "语音设置",
            NavigationItemPosition.TOP
        )
        
        self.addSubInterface(
            self.api_interface, 
            FluentIcon.GLOBE, 
            "TTS API服务",
            NavigationItemPosition.TOP
        )
        self.navigationInterface.addItem(
            routeKey='EmotionVoicesInterface',
            icon=FluentIcon.TAG,
            text='情绪管理',
            onClick=self.open_emotion_redirect,
            selectable=False,
            position=NavigationItemPosition.TOP,
            tooltip='已合并到语音设置'
        )
        
        # 在侧边栏添加模型加载按钮
        self.navigationInterface.addItem(
            routeKey='load_model',
            icon=FluentIcon.PLAY,
            text='加载模型',
            onClick=self.on_load_model_clicked,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
            tooltip='加载模型'
        )

        # 在侧边栏添加模型卸载按钮
        self.navigationInterface.addItem(
            routeKey='unload_model',
            icon=FluentIcon.CLOSE,
            text='卸载模型',
            onClick=self.on_unload_model_clicked,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
            tooltip='卸载模型'
        )

        # 在侧边栏添加主题切换
        self.navigationInterface.addItem(
            routeKey='theme_toggle',
            icon=FluentIcon.CONSTRACT,
            text='切换主题',
            onClick=self.toggle_theme,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
            tooltip='切换主题'
        )

        # 在侧边栏添加 GitHub 链接
        self.navigationInterface.addItem(
            routeKey='github_repo',
            icon=FluentIcon.GITHUB,
            text='GitHub 仓库',
            onClick=lambda: QDesktopServices.openUrl(QUrl("https://github.com/Moeary/CosyVoiceDesktop")),
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
            tooltip='访问 GitHub 仓库'
        )

        self.addSubInterface(
            self.settings_interface, 
            FluentIcon.SETTING, 
            "设置",
            NavigationItemPosition.BOTTOM
        )
        
    def connect_signals(self):
        # 语音设置应用
        self.voice_interface.apply_button.clicked.connect(self.apply_voice_settings)
        # 语音配置加载后自动应用
        self.voice_interface.config_loaded.connect(self.apply_voice_settings)
        
        # 文本编辑按钮
        self.text_interface.quick_run_button.clicked.connect(self.quick_run)
        self.text_interface.to_task_button.clicked.connect(self.to_task_plan)
        
        # 任务计划按钮
        self.task_interface.run_single_segment.connect(self.run_single_segment)
        self.task_interface.run_all_segments.connect(self.run_all_segments)
        self.task_interface.merge_audio.connect(self.merge_all_audio)
        self.task_interface.play_audio.connect(self.play_audio)
        
        # 监听配置变化
        self.task_interface.project_edit.textChanged.connect(
            lambda text: self.config_manager.set("project_name", text)
        )
    
    def on_theme_changed_in_nav(self, text):
        """侧边栏主题改变"""
        self.config_manager.set("theme", text)
        if text == "Light":
            setTheme(Theme.LIGHT)
        elif text == "Dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)

    def open_emotion_redirect(self):
        """Compatibility entry: emotion management merged into voice settings."""
        try:
            self.switchTo(self.voice_interface)
            self.voice_interface.open_refs_sheet_for_current_row()
            InfoBar.info(
                title="已合并",
                content="情绪管理已合并到“语音设置”页面",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2200,
                parent=self,
            )
        except Exception as e:
            InfoBar.warning(
                title="跳转失败",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self,
            )

    def load_initial_config(self):
        """加载初始配置"""
        # 加载项目名和输出目录
        project_name = self.config_manager.get("project_name", "project")
        # output_dir = self.config_manager.get("output_dir", "./output") # output_dir is now managed globally
        
        self.task_interface.project_edit.setText(project_name)
        # self.task_interface.output_edit.setText(output_dir)
        self.task_interface.project_name = project_name
        # self.task_interface.output_dir = output_dir
        
        # v2 voices is the single source of truth.
        try:
            self.voice_interface.load_v2_voices()
        except Exception as e:
            print(f"load v2 voices failed: {e}")

        # If v2 voices is empty but legacy config exists, guide user to import once.
        try:
            if not self.voice_interface.voice_configs and os.path.exists("./config/config.json"):
                InfoBar.warning(
                    title="提示",
                    content="检测到旧的语音设置文件（config/config.json）。建议在“语音设置”页点击“导入旧配置到 v2”。",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self,
                )
        except Exception:
            pass
        
        # 确保初始配置被应用
        self.apply_voice_settings()

    def apply_voice_settings(self):
        """应用语音设置"""
        configs = self.voice_interface.get_voice_configs()
        self.text_interface.set_voice_configs(configs)
        self.task_interface.set_all_voice_configs(configs)
    
    def toggle_theme(self):
        """在Light和Dark之间切换主题"""
        from qfluentwidgets import qconfig
        if qconfig.theme == Theme.DARK:
            setTheme(Theme.LIGHT)
            self.config_manager.set("theme", "Light")
        else:
            setTheme(Theme.DARK)
            self.config_manager.set("theme", "Dark")
        
        InfoBar.success(
            title='成功',
            content='主题已切换',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1500,
            parent=self
        )
    
    def on_load_model_clicked(self):
        """手动加载模型"""
        if self.cosyvoice_model is not None:
            InfoBar.warning(
                title='模型已加载',
                content='CosyVoice 模型已经加载，无需重复加载。',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        
        # 创建并启动模型加载线程
        self.model_loader_thread = ModelLoaderThread()
        self.model_loader_thread.success.connect(self.on_model_loaded_success)
        self.model_loader_thread.error.connect(self.on_model_loaded_error)
        self.model_loader_thread.start()
    
    def on_model_loaded_success(self, model):
        """模型加载成功"""
        self.cosyvoice_model = model
        
        InfoBar.success(
            title='成功',
            content='CosyVoice 模型加载成功！',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )
    
    def on_model_loaded_error(self, error_msg):
        """模型加载失败"""
        InfoBar.error(
            title='加载失败',
            content=f'模型加载失败: {error_msg[:50]}',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )
    
    def on_unload_model_clicked(self):
        """手动卸载模型"""
        if self.cosyvoice_model is None:
            InfoBar.warning(
                title='没有模型',
                content='当前没有加载任何模型。',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        
        # 检查是否有任务正在运行
        if self.current_worker and self.current_worker.isRunning():
            InfoBar.warning(
                title='任务正在运行',
                content='请等待当前任务完成后再卸载模型。',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        
        # 创建并启动模型卸载线程
        model_to_unload = self.cosyvoice_model
        self.cosyvoice_model = None  # 立即清空引用
        
        self.model_unloader_thread = ModelUnloaderThread(model_to_unload)
        self.model_unloader_thread.finished.connect(self.on_model_unloaded_success)
        self.model_unloader_thread.error.connect(self.on_model_unloaded_error)
        self.model_unloader_thread.start()
    
    def on_model_unloaded_success(self):
        """模型卸载成功"""
        InfoBar.success(
            title='成功',
            content='CosyVoice 模型已卸载！',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )
    
    def on_model_unloaded_error(self, error_msg):
        """模型卸载失败"""
        InfoBar.error(
            title='卸载失败',
            content=f'模型卸载失败: {error_msg[:50]}',
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )
    
    def quick_run(self):
        """一键运行"""
        segments = self.text_interface.get_text_segments()
        if not segments:
            InfoBar.warning(
                title="无内容",
                content="请输入文本并应用语音模式",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return
        
        # 创建任务段落
        task_segments = [
            TaskSegment(i+1, text, config) 
            for i, (text, config) in enumerate(segments)
        ]
        
        # 开始生成
        self.start_generation(task_segments)
    
    def to_task_plan(self):
        """转到任务计划"""
        segments = self.text_interface.get_text_segments()
        if not segments:
            InfoBar.warning(
                title="无内容",
                content="请输入文本并应用语音模式",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return
        
        # 加载到任务计划
        self.task_interface.load_segments(segments)
        
        # 切换到任务计划界面
        self.switchTo(self.task_interface)
        
        InfoBar.success(
            title="转换成功",
            content=f"已加载 {len(segments)} 个任务段落",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )
    
    def run_single_segment(self, index: int):
        """运行单个段落"""
        segment = self.task_interface.task_segments[index]
        self.task_interface.add_log(f"[INFO] 开始生成第 {segment.index} 段...")
        self.start_generation([segment])
    
    def run_all_segments(self):
        """运行所有段落"""
        segments = self.task_interface.task_segments
        if not segments:
            InfoBar.warning(
                title="无任务",
                content="请先添加任务段落",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return
        
        self.task_interface.add_log(f"[INFO] 开始生成全部 {len(segments)} 段...")
        self.start_generation(segments)
    
    def start_generation(self, segments: List[TaskSegment]):
        """开始音频生成"""
        if self.current_worker and self.current_worker.isRunning():
            InfoBar.warning(
                title="正在运行",
                content="已有任务正在运行中",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        if self.generation_probe_thread and self.generation_probe_thread.isRunning():
            InfoBar.warning(
                title="正在检查",
                content="正在检查 v2 API 状态，请稍候",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return

        # Create worker thread: prefer v2 API for cache/jobs/emotion voices when available.
        use_v2 = bool(self.config_manager.get("ui_use_v2_generation", True))
        if not use_v2:
            worker = AudioGenerationWorker(
                segments,
                self.task_interface.output_dir,
                self.task_interface.project_name,
                self.cosyvoice_model,
            )
            self._start_generation_worker(worker)
            return

        host = str(self.config_manager.get("api_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(self.config_manager.get("api_port", 9880) or 9880)
        api_key = str(self.config_manager.get("api_key", "") or "").strip()
        probe = V2HealthProbeThread(host, port, api_key, timeout_s=0.5)
        self.generation_probe_thread = probe

        def _on_probe_done(res: object):
            self.generation_probe_thread = None
            try:
                probe.deleteLater()
            except Exception:
                pass

            result = res if isinstance(res, dict) else {}
            base_url = str(result.get("base_url") or f"http://{host}:{port}")
            api_key_local = str(result.get("api_key") or api_key)
            ok = bool(result.get("ok", False))
            err = str(result.get("error") or "").strip()

            if ok:
                worker2 = V2AudioGenerationWorker(
                    segments,
                    self.task_interface.output_dir,
                    self.task_interface.project_name,
                    base_url=base_url,
                    api_key=api_key_local,
                    timeout_s=60.0,
                )
                self._start_generation_worker(worker2)
                return

            if err:
                self.task_interface.add_log("[INFO] v2 API 不可用，回退到本地推理。")
            else:
                self.task_interface.add_log("[INFO] v2 API 不可用或模型未加载，回退到本地推理。")
            worker2 = AudioGenerationWorker(
                segments,
                self.task_interface.output_dir,
                self.task_interface.project_name,
                self.cosyvoice_model,
            )
            self._start_generation_worker(worker2)

        probe.done.connect(_on_probe_done)
        probe.start()

    def get_active_cosyvoice_model(self):
        """返回当前可用的 CosyVoice 模型实例（兼容不同 worker 类型）。"""
        if self.cosyvoice_model is not None:
            return self.cosyvoice_model
        worker = self.current_worker
        if worker is None:
            return None
        return getattr(worker, "cosyvoice", None)

    def _start_generation_worker(self, worker: QThread):
        self.current_worker = worker

        # 连接信号
        self.current_worker.progress.connect(self.task_interface.add_log)
        self.current_worker.segment_finished.connect(self.task_interface.update_segment_audio)
        self.current_worker.finished.connect(self.on_generation_finished)
        self.current_worker.error.connect(self.on_generation_error)

        # 进入运行态，避免重复触发
        self._set_generation_ui_running(True)

        # 启动线程
        self.current_worker.start()

    def _set_generation_ui_running(self, running: bool):
        """同步主流程生成相关控件的运行态。"""
        if hasattr(self, "task_interface") and self.task_interface:
            try:
                self.task_interface.set_generation_running(running)
            except Exception:
                self.task_interface.run_all_button.setEnabled(not running)

        if hasattr(self, "text_interface") and self.text_interface:
            self.text_interface.quick_run_button.setEnabled(not running)
            self.text_interface.quick_run_button.setText("运行中..." if running else "一键运行")
            self.text_interface.to_task_button.setEnabled(not running)
    
    def on_generation_finished(self, files: List[str]):
        """生成完成"""
        self.task_interface.add_log(f"[OK] 生成完成，共 {len(files)} 个文件")
        
        # 更新模型引用
        if self.current_worker and hasattr(self.current_worker, "cosyvoice"):
            self.cosyvoice_model = getattr(self.current_worker, "cosyvoice", None)
        
        # 恢复按钮
        self._set_generation_ui_running(False)
        
        InfoBar.success(
            title="生成完成",
            content=f"成功生成 {len(files)} 个音频文件",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )
    
    def on_generation_error(self, error: str):
        """生成错误"""
        self.task_interface.add_log(f"[ERROR] {error}")
        self._set_generation_ui_running(False)
        
        InfoBar.error(
            title="生成失败",
            content=error,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )
    
    def merge_all_audio(self):
        """合成所有音频 - 按版本合成所有片段"""
        segments = self.task_interface.task_segments
        files_to_merge = []
        
        for segment in segments:
            if not segment.versions:
                continue
            
            # 获取当前选中的版本号
            version_idx = segment.current_version
            
            # 获取该版本的所有片段并按顺序添加
            if 0 <= version_idx < len(segment.versions):
                version_files = segment.versions[version_idx]
                files_to_merge.extend(version_files)
                
                # 日志输出
                if len(version_files) > 1:
                    self.task_interface.add_log(
                        f"[INFO] 段落{segment.index}: v{version_idx+1} ({len(version_files)}个片段)"
                    )
                else:
                    self.task_interface.add_log(
                        f"[INFO] 段落{segment.index}: v{version_idx+1}"
                    )
        
        if not files_to_merge:
            InfoBar.warning(
                title="无音频",
                content="没有可合成的音频文件",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return
        
        self.task_interface.add_log(f"[INFO] 开始合成 {len(files_to_merge)} 个音频片段...")
        
        # 合成
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_file = merge_audio_files(
            files_to_merge, 
            self.task_interface.output_dir,
            f"{self.task_interface.project_name}_merged_{timestamp}.wav"
        )
        
        if merged_file:
            self.task_interface.add_log(f"[OK] 合成完成: {os.path.basename(merged_file)}")
            InfoBar.success(
                title="合成完成",
                content=f"已保存到: {merged_file}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
        else:
            self.task_interface.add_log("[ERROR] 合成失败")
            InfoBar.error(
                title="合成失败",
                content="音频合成时发生错误",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
    
    def play_audio(self, filepath: str):
        """播放音频"""
        if not os.path.exists(filepath):
            InfoBar.warning(
                title="文件不存在",
                content="音频文件不存在",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        
        url = QUrl.fromLocalFile(filepath)
        self.media_player.setMedia(QMediaContent(url))
        self.media_player.play()
        
        self.task_interface.add_log(f"[INFO] 播放: {os.path.basename(filepath)}")
    
    def load_model_if_enabled(self):
        """如果设置中启用了自动加载，则加载模型"""
        auto_load = self.config_manager.get("auto_load_model", False)
        
        if not auto_load:
            return
        
        # 从 utils 模块加载函数
        from core.utils import load_cosyvoice_model
        
        try:
            self.cosyvoice_model = load_cosyvoice_model()
            # 显示成功提示
            InfoBar.success(
                title='模型加载成功',
                content="CosyVoice 模型已加载，现在可以生成语音了",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
        except Exception as e:
            print(f"Failed to load model: {e}")
            InfoBar.warning(
                title='模型加载失败',
                content=f"未能加载 CosyVoice 模型，请检查模型文件",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

    def auto_start_api_server_if_enabled(self):
        """UI 启动后自动开启内嵌 API 服务（默认开启）。"""
        try:
            enabled = bool(self.config_manager.get("ui_auto_start_api_server", True))
        except Exception:
            enabled = True
        if not enabled:
            return
        try:
            # Avoid double-toggling if already running.
            if getattr(self.api_interface, "server_thread", None) and self.api_interface.server_thread.isRunning():
                return
            self.api_interface.toggle_server()
        except Exception as e:
            # Non-fatal: keep UI usable.
            print(f"auto_start_api_server_if_enabled failed: {e}")

    def _stop_qthread(self, thread: Optional[QThread], *, wait_ms: int = 8000):
        if not thread:
            return
        try:
            stopper = getattr(thread, "stop", None)
            if callable(stopper):
                stopper()
        except Exception:
            pass
        try:
            if thread.isRunning() and not thread.wait(wait_ms):
                thread.terminate()
                thread.wait(1000)
        except Exception:
            pass
        try:
            thread.deleteLater()
        except Exception:
            pass

    def closeEvent(self, event):
        # Stop API page resources first (embedded server thread + bridge process).
        try:
            if getattr(self, "api_interface", None):
                self.api_interface.shutdown()
        except Exception:
            pass

        # Stop page-level workers that may still be doing HTTP/file operations.
        try:
            refs_panel = getattr(getattr(getattr(self, "voice_interface", None), "refs_sheet", None), "panel", None)
            if refs_panel and hasattr(refs_panel, "shutdown"):
                refs_panel.shutdown()
        except Exception:
            pass

        # Stop top-level workers.
        self._stop_qthread(self.current_worker)
        self.current_worker = None
        self._stop_qthread(self.model_loader_thread)
        self.model_loader_thread = None
        self._stop_qthread(self.model_unloader_thread)
        self.model_unloader_thread = None
        self._stop_qthread(self.generation_probe_thread)
        self.generation_probe_thread = None

        # Stop voice-settings background workers if active.
        try:
            vi = getattr(self, "voice_interface", None)
            if vi:
                self._stop_qthread(getattr(vi, "import_worker", None))
                vi.import_worker = None
        except Exception:
            pass

        try:
            self.media_player.stop()
        except Exception:
            pass

        super().closeEvent(event)
