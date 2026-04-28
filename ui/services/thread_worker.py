import uuid
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from typing import Callable, Any, Dict, Optional

class ApiCallWorker(QThread):
    """
    通用后台工作线程：执行任意耗时函数，执行完毕后发出信号。
    将 UI 主线程与底层网络请求隔离。
    """
    ok = pyqtSignal(object)
    err = pyqtSignal(object)

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            res = self._fn(*self._args, **self._kwargs)
            self.ok.emit(res)
        except Exception as e:
            self.err.emit(e)

class WorkerManager(QObject):
    """
    统一管理 Worker 的生命周期，防止局部变量被回收导致的崩溃或竞态条件。
    通常由 Service 层或 Store 层单例持有。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        # 用于追踪带 ID 的 QThread 任务（start_worker 使用）
        self._active_tasks: Dict[str, QThread] = {}

    def run_task(self, fn: Callable, on_ok: Optional[Callable] = None, on_err: Optional[Callable] = None, *args, **kwargs):
        worker = ApiCallWorker(fn, *args, **kwargs)
        self._workers.append(worker)

        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()

        if on_ok:
            worker.ok.connect(on_ok)
        if on_err:
            worker.err.connect(on_err)
            
        worker.finished.connect(_cleanup)
        worker.start()
        return worker

    def start_worker(self, worker_instance: QThread, name: str = "worker") -> str:
        """启动一个 QThread worker，追踪其生命周期，返回唯一任务 ID。"""
        task_id = str(uuid.uuid4())
        self._active_tasks[task_id] = worker_instance

        def _cleanup():
            self._active_tasks.pop(task_id, None)
            try:
                worker_instance.deleteLater()
            except Exception:
                pass

        worker_instance.finished.connect(_cleanup)
        worker_instance.start()
        return task_id

    def has_task(self, task_id: Optional[str]) -> bool:
        """检查指定 ID 的任务是否仍在运行中。"""
        if not task_id:
            return False
        worker = self._active_tasks.get(task_id)
        if worker is None:
            return False
        return worker.isRunning()

    def stop_all(self):
        """停止所有被追踪的 worker（包括 run_task 和 start_worker 启动的）。"""
        # 停止带 ID 追踪的 QThread 任务
        for task_id, worker in list(self._active_tasks.items()):
            try:
                if hasattr(worker, "stop"):
                    worker.stop()
                worker.quit()
                worker.wait(2000)
            except Exception:
                pass
        self._active_tasks.clear()

        # 停止 run_task 启动的普通 ApiCallWorker
        for worker in list(self._workers):
            try:
                worker.quit()
                worker.wait(1000)
            except Exception:
                pass
        self._workers.clear()
