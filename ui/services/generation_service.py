from typing import List, Optional
from PyQt5.QtCore import QObject, pyqtSignal, Qt

from qfluentwidgets import InfoBar, InfoBarPosition

from core.models import TaskSegment
from core.worker import AudioGenerationWorker, V2AudioGenerationWorker
from ui.services.process_manager import V2HealthProbeThread
from .thread_worker import WorkerManager

class GenerationService(QObject):
    """
    负责统一调度音频合成任务，管理 V1(直连推理)/V2(API代理) 的后备回退机制。
    将原本耦合在 main_window.py 中的 start_generation 逻辑抽离。
    """
    
    # 向外暴露统一的日志与进度信号
    progress = pyqtSignal(str)
    segment_finished = pyqtSignal(int, list)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, config_manager, worker_manager: WorkerManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.worker_manager = worker_manager
        self.generation_probe_thread = None
        
        # 记录当前的 Worker 以支持查阅状态和强行终止
        self.current_generator_id: Optional[str] = None
        self._cosyvoice_model_ref = None # 如果有本地直接加载的模型，通过这里引用
        
    def set_cosyvoice_model(self, model):
        """传入底层模型对象（仅本地直连推理时需要）"""
        self._cosyvoice_model_ref = model
        
    def start_generation(self, segments: List[TaskSegment], output_dir: str, project_name: str, parent_widget=None):
        """发起生成流程，带 V2 回退检测"""
        
        if self.worker_manager.has_task(self.current_generator_id):
            InfoBar.warning(
                title="正在运行",
                content="已有生成任务正在运行中",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=parent_widget
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
                parent=parent_widget,
            )
            return

        use_v2 = bool(self.config_manager.get("ui_use_v2_generation", True))
        if not use_v2:
            self._start_legacy_worker(segments, output_dir, project_name)
            return

        host = str(self.config_manager.get("api_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(self.config_manager.get("api_port", 9880) or 9880)
        api_key = str(self.config_manager.get("api_key", "") or "").strip()
        
        probe = V2HealthProbeThread(host, port, api_key, timeout_s=0.5)
        self.generation_probe_thread = probe
        
        def _on_probe_done(res: object):
            result = res if isinstance(res, dict) else {}
            base_url = str(result.get("base_url") or f"http://{host}:{port}")
            api_key_local = str(result.get("api_key") or api_key)
            ok = bool(result.get("ok", False))
            err = str(result.get("error") or "").strip()

            if ok:
                worker = V2AudioGenerationWorker(
                    segments,
                    output_dir,
                    project_name,
                    base_url=base_url,
                    api_key=api_key_local,
                    timeout_s=60.0,
                )
                self._start_worker(worker, "V2AudioGeneration")
                return

            if err:
                self.progress.emit("[INFO] v2 API 不可用，回退到本地推理。")
            else:
                self.progress.emit("[INFO] v2 API 不可用或模型未加载，回退到本地推理。")
                
            self._start_legacy_worker(segments, output_dir, project_name)

        def _on_probe_finished():
            if self.generation_probe_thread is probe:
                self.generation_probe_thread = None
            probe.deleteLater()

        probe.done.connect(_on_probe_done)
        probe.finished.connect(_on_probe_finished)
        probe.start()

    def _start_legacy_worker(self, segments, output_dir, project_name):
        worker = AudioGenerationWorker(
            segments,
            output_dir,
            project_name,
            self._cosyvoice_model_ref,
        )
        self._start_worker(worker, "LegacyAudioGeneration")
        
    def _start_worker(self, worker_instance, task_name: str):
        # 将 Worker 的信号桥接到 Service，以分离 UI 组件的耦合
        worker_instance.progress.connect(self.progress)
        worker_instance.segment_finished.connect(self.segment_finished)
        worker_instance.generation_finished.connect(self.finished)
        worker_instance.error.connect(self.error)

        # 在线程真正结束后回写模型引用，避免后续重复加载模型。
        def _capture_model():
            model = getattr(worker_instance, "cosyvoice", None)
            if model is not None:
                self._cosyvoice_model_ref = model

        worker_instance.finished.connect(_capture_model)
        
        # 将线程托管给 WorkerManager，让它处理 GC
        self.current_generator_id = self.worker_manager.start_worker(worker_instance, name=task_name)

    def shutdown(self):
        """停止 service 内持有但不受 WorkerManager 追踪的线程。"""
        probe = self.generation_probe_thread
        self.generation_probe_thread = None
        if not probe:
            return
        try:
            if probe.isRunning() and not probe.wait(2000):
                probe.terminate()
                probe.wait(500)
        except Exception:
            pass
        try:
            probe.deleteLater()
        except Exception:
            pass
