from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget, QFileDialog

from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    ToolButton,
)

from .v2_client import V2Client, V2HttpError
from .theme.tokens import Palette


CONTROL_H = 44
TOOL_BTN_SZ = 40


def _ui_font(size: int, *, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(int(size))
    if bold:
        f.setBold(True)
    return f


class _Worker(QThread):
    ok = pyqtSignal(object)
    err = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            self.ok.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.err.emit(e)


@dataclass
class _State:
    character: str = ""
    emotion: str = "default"
    language: str = "zh"
    mode: str = "参考音色"
    note: str = ""
    asset_id: str = ""
    prompt_text: str = ""
    instruct_text: str = ""
    selection_policy: str = "random_per_text"
    test_text: str = ""
    voice_saved: bool = False

    def voice_id(self) -> str:
        ch = (self.character or "").strip()
        emo = (self.emotion or "").strip() or "default"
        return f"{ch}#{emo}" if ch else ""


class VoiceSetupWizardDialog(QDialog):
    """
    A zero-basics friendly wizard:
    新建角色 -> 上传 default ref -> 保存 voice -> compile -> 合成测试句

    All user-visible strings are Chinese.
    """

    def __init__(
        self,
        main_window,
        client_factory: Callable[[], V2Client],
        *,
        preset_character: str = "",
        preset_emotion: str = "default",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("一键闭环向导")
        self.resize(980, 620)
        self.setMinimumSize(820, 540)

        self.main_window = main_window
        self._client_factory = client_factory
        self._workers: list[QThread] = []
        self._tmp_dir = os.path.abspath("./data/ui_tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)
        self.media_player = QMediaPlayer()

        self.state = _State(character=(preset_character or "").strip(), emotion=(preset_emotion or "default").strip() or "default")
        self.state.test_text = "你好，我是一个新角色。现在我们来做一次合成测试。"

        self._init_ui()
        self._connect_signals()
        self._sync_fields_from_state()
        self._goto(0)

        # Auto check health shortly after opening.
        QTimer.singleShot(300, self._check_health)

    def _toast_ok(self, title: str, content: str):
        InfoBar.success(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self,
        )

    def _toast_warn(self, title: str, content: str):
        InfoBar.warning(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4500,
            parent=self,
        )

    def _toast_err(self, title: str, content: str):
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=6000,
            parent=self,
        )

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

    def _run(self, fn, on_ok, on_err):
        w = _Worker(fn)
        self._workers.append(w)

        def _cleanup():
            try:
                self._workers.remove(w)
            except Exception:
                pass
            w.deleteLater()

        def _safe_ok(res: object):
            try:
                on_ok(res)
            except Exception as e:
                # Never let UI callbacks crash the app.
                self._toast_err("内部错误", str(e))

        def _safe_err(e: object):
            try:
                if isinstance(e, V2HttpError):
                    on_err(e.short())
                else:
                    on_err(str(e))
            except Exception as ee:
                self._toast_err("内部错误", str(ee))

        w.ok.connect(_safe_ok)

        w.err.connect(_safe_err)
        # Cleanup only after thread fully exits; avoids QThread destroyed-while-running race.
        w.finished.connect(_cleanup)
        w.start()

    def _run_ex(self, fn, on_ok, on_err_exc):
        """
        Like _run(), but passes the raw exception object to on_err_exc.
        Useful when caller wants to branch on HTTP status code.
        """
        w = _Worker(fn)
        self._workers.append(w)

        def _cleanup():
            try:
                self._workers.remove(w)
            except Exception:
                pass
            w.deleteLater()

        def _safe_ok(res: object):
            try:
                on_ok(res)
            except Exception as e:
                self._toast_err("内部错误", str(e))

        def _safe_err(e: object):
            try:
                on_err_exc(e)
            except Exception as ee:
                self._toast_err("内部错误", str(ee))

        w.ok.connect(_safe_ok)
        w.err.connect(_safe_err)
        # Cleanup only after thread fully exits; avoids QThread destroyed-while-running race.
        w.finished.connect(_cleanup)
        w.start()

    def _shutdown_workers(self, wait_ms: int = 8000):
        for w in list(self._workers):
            try:
                if w.isRunning() and not w.wait(wait_ms):
                    w.terminate()
                    w.wait(1000)
            except Exception:
                pass
            try:
                if w in self._workers:
                    self._workers.remove(w)
            except Exception:
                pass
            try:
                w.deleteLater()
            except Exception:
                pass
        try:
            self.media_player.stop()
        except Exception:
            pass

    def accept(self):
        self._shutdown_workers()
        super().accept()

    def reject(self):
        self._shutdown_workers()
        super().reject()

    def closeEvent(self, event):
        self._shutdown_workers()
        super().closeEvent(event)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.setFont(_ui_font(12))

        header = QHBoxLayout()
        header.setSpacing(10)
        self.title = SubtitleLabel("一键闭环向导", self)
        self.title.setFont(_ui_font(18, bold=True))
        header.addWidget(self.title)
        header.addStretch()
        self.step_label = BodyLabel("", self)
        header.addWidget(self.step_label)
        root.addLayout(header)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 1)

        # Step pages
        self.page_health = self._build_page_health()
        self.page_role = self._build_page_role()
        self.page_upload = self._build_page_upload()
        self.page_save = self._build_page_save()
        self.page_test = self._build_page_test()

        for p in [self.page_health, self.page_role, self.page_upload, self.page_save, self.page_test]:
            self.stack.addWidget(p)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_prev = PushButton("上一步", self)
        self.btn_prev.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_prev)

        self.btn_next = PrimaryPushButton("继续", self)
        self.btn_next.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_next)

        bottom.addStretch()

        self.btn_cancel = PushButton("取消", self)
        self.btn_cancel.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_cancel)

        root.addLayout(bottom)

    def _build_page_health(self) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(12)

        l.addWidget(BodyLabel("第 1 步：检查 API 服务与模型状态", self))
        self.health_status = BodyLabel("状态：未检查", self)
        self.health_status.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(self.health_status)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.btn_check = PushButton("检查连接", self)
        self.btn_check.setIcon(FluentIcon.SYNC)
        self.btn_check.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_check)

        self.btn_start_api = PushButton("启动 API 服务", self)
        self.btn_start_api.setIcon(FluentIcon.PLAY)
        self.btn_start_api.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_start_api)

        self.btn_load_model = PushButton("加载模型", self)
        self.btn_load_model.setIcon(FluentIcon.PLAY)
        self.btn_load_model.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_load_model)

        row.addStretch()
        l.addLayout(row)

        tip = BodyLabel(
            "提示：如果你是第一次使用，建议先点击“启动 API 服务”，再点击“检查连接”。",
            self,
        )
        tip.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(tip)
        l.addStretch()
        return w

    def _build_page_role(self) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(12)

        l.addWidget(BodyLabel("第 2 步：填写角色信息", self))

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(BodyLabel("角色名", self))
        self.edit_character = LineEdit(self)
        self.edit_character.setFixedHeight(CONTROL_H)
        self.edit_character.setPlaceholderText("例如：胡桃 / 雷电将军 / Tom")
        row1.addWidget(self.edit_character, 1)
        l.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(BodyLabel("情绪标签", self))
        self.edit_emotion = LineEdit(self)
        self.edit_emotion.setFixedHeight(CONTROL_H)
        self.edit_emotion.setPlaceholderText("例如：default / happy / sad ...")
        row2.addWidget(self.edit_emotion, 1)
        l.addLayout(row2)

        self.label_voice_id = BodyLabel("voice_id：", self)
        self.label_voice_id.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(self.label_voice_id)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        row3.addWidget(BodyLabel("语言", self))
        self.combo_lang = ComboBox(self)
        self.combo_lang.addItems(["zh", "en", "ja", "ko"])
        self.combo_lang.setFixedHeight(CONTROL_H)
        row3.addWidget(self.combo_lang)
        row3.addSpacing(14)
        row3.addWidget(BodyLabel("模式", self))
        self.combo_mode = ComboBox(self)
        self.combo_mode.addItems(["参考音色", "零样本复制", "精细控制", "指令控制"])
        self.combo_mode.setFixedHeight(CONTROL_H)
        row3.addWidget(self.combo_mode, 1)
        l.addLayout(row3)

        l.addStretch()
        return w

    def _build_page_upload(self) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(12)

        l.addWidget(BodyLabel("第 3 步：上传参考音频（默认情绪）", self))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_pick_file = PushButton("选择音频文件", self)
        self.btn_pick_file.setIcon(FluentIcon.FOLDER)
        self.btn_pick_file.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_pick_file)

        self.label_file = BodyLabel("未选择文件", self)
        self.label_file.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        row.addWidget(self.label_file, 1)

        self.btn_upload = PrimaryPushButton("上传", self)
        # FluentIcon.UPLOAD is not available in some qfluentwidgets versions.
        self.btn_upload.setIcon(FluentIcon.SEND)
        self.btn_upload.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_upload)
        l.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(BodyLabel("备注", self))
        self.edit_note = LineEdit(self)
        self.edit_note.setFixedHeight(CONTROL_H)
        self.edit_note.setPlaceholderText("可选，用于搜索")
        row2.addWidget(self.edit_note, 1)
        l.addLayout(row2)

        self.label_asset = BodyLabel("asset_id：<未上传>", self)
        self.label_asset.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(self.label_asset)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self.btn_play = PushButton("试听", self)
        self.btn_play.setIcon(FluentIcon.VOLUME)
        self.btn_play.setFixedHeight(CONTROL_H)
        self.btn_play.setEnabled(False)
        row3.addWidget(self.btn_play)
        row3.addStretch()
        l.addLayout(row3)

        l.addStretch()
        return w

    def _build_page_save(self) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(12)

        l.addWidget(BodyLabel("第 4 步：保存 voice 并绑定参考音频", self))

        self.prompt_text = PlainTextEdit(self)
        self.prompt_text.setPlaceholderText("参考文本（必填）。建议写与参考音频内容一致的文本。")
        self.prompt_text.setFixedHeight(160)
        l.addWidget(self.prompt_text)

        self.instruct_text = PlainTextEdit(self)
        self.instruct_text.setPlaceholderText("指令文本（可选，指令控制模式才会用到）")
        self.instruct_text.setFixedHeight(120)
        l.addWidget(self.instruct_text)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(BodyLabel("选择策略", self))
        self.combo_policy = ComboBox(self)
        self._policy_label_to_key: Dict[str, str] = {
            "按文本随机（稳定）": "random_per_text",
            "固定（始终第一个）": "fixed",
            "按请求随机（不推荐）": "random_per_request",
        }
        self._policy_key_to_label = {v: k for k, v in self._policy_label_to_key.items()}
        self.combo_policy.addItems(list(self._policy_label_to_key.keys()))
        self.combo_policy.setFixedHeight(CONTROL_H)
        row.addWidget(self.combo_policy, 1)

        self.btn_save_voice = PrimaryPushButton("保存 voice", self)
        self.btn_save_voice.setIcon(FluentIcon.SAVE)
        self.btn_save_voice.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_save_voice)
        l.addLayout(row)

        self.label_saved = BodyLabel("状态：未保存", self)
        self.label_saved.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(self.label_saved)

        l.addStretch()
        return w

    def _build_page_test(self) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(12)

        l.addWidget(BodyLabel("第 5 步：编译 + 合成测试句", self))

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_compile = PushButton("编译（可选）", self)
        self.btn_compile.setIcon(FluentIcon.PLAY)
        self.btn_compile.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_compile)

        self.btn_synth = PrimaryPushButton("合成测试句", self)
        self.btn_synth.setIcon(FluentIcon.PLAY)
        self.btn_synth.setFixedHeight(CONTROL_H)
        row.addWidget(self.btn_synth)

        row.addStretch()
        l.addLayout(row)

        self.test_text = PlainTextEdit(self)
        self.test_text.setFixedHeight(160)
        self.test_text.setPlaceholderText("输入一段测试文本")
        l.addWidget(self.test_text)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.btn_play_out = PushButton("播放输出", self)
        self.btn_play_out.setIcon(FluentIcon.VOLUME)
        self.btn_play_out.setFixedHeight(CONTROL_H)
        self.btn_play_out.setEnabled(False)
        row2.addWidget(self.btn_play_out)
        row2.addStretch()
        l.addLayout(row2)

        self.label_out = BodyLabel("输出：<未生成>", self)
        self.label_out.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        l.addWidget(self.label_out)

        l.addStretch()
        return w

    def _connect_signals(self):
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_prev.clicked.connect(lambda: self._goto(self.stack.currentIndex() - 1))
        self.btn_next.clicked.connect(self._on_next)

        # Step1
        self.btn_check.clicked.connect(self._check_health)
        self.btn_start_api.clicked.connect(self._start_api)
        self.btn_load_model.clicked.connect(self._load_model)

        # Step2
        self.edit_character.textChanged.connect(self._on_role_changed)
        self.edit_emotion.textChanged.connect(self._on_role_changed)
        self.combo_lang.currentTextChanged.connect(self._on_role_changed)
        self.combo_mode.currentTextChanged.connect(self._on_role_changed)

        # Step3
        self.btn_pick_file.clicked.connect(self._pick_file)
        self.btn_upload.clicked.connect(self._upload)
        self.btn_play.clicked.connect(self._play_uploaded)

        # Step4
        self.btn_save_voice.clicked.connect(self._save_voice)
        self.combo_policy.currentTextChanged.connect(self._on_policy_changed)

        # Step5
        self.btn_compile.clicked.connect(self._compile)
        self.btn_synth.clicked.connect(self._synthesize)
        self.btn_play_out.clicked.connect(self._play_output)

    def _sync_fields_from_state(self):
        self.edit_character.setText(self.state.character)
        self.edit_emotion.setText(self.state.emotion)
        self.combo_lang.setCurrentText(self.state.language)
        self.combo_mode.setCurrentText(self.state.mode)
        self.edit_note.setText(self.state.note)
        self.label_asset.setText(f"asset_id：{self.state.asset_id or '<未上传>'}")
        self.prompt_text.setPlainText(self.state.prompt_text)
        self.instruct_text.setPlainText(self.state.instruct_text)
        self.combo_policy.setCurrentText(self._policy_key_to_label.get(self.state.selection_policy, "按文本随机（稳定）"))
        self.test_text.setPlainText(self.state.test_text)
        self._update_voice_id_label()

    def _update_voice_id_label(self):
        vid = self.state.voice_id()
        self.label_voice_id.setText(f"voice_id：{vid or '<未填写>'}")

    def _goto(self, idx: int):
        idx = max(0, min(4, int(idx)))
        self.stack.setCurrentIndex(idx)
        self.step_label.setText(f"步骤 {idx + 1} / 5")
        self.btn_prev.setEnabled(idx > 0)
        self.btn_next.setText("完成" if idx == 4 else "继续")
        self._refresh_next_enabled()

    def _refresh_next_enabled(self):
        idx = int(self.stack.currentIndex())
        ok = True
        if idx == 0:
            ok = True  # allow proceed; user may still configure later
        elif idx == 1:
            ok = bool(self.state.character.strip())
        elif idx == 2:
            ok = bool(self.state.asset_id.strip())
        elif idx == 3:
            ok = bool(self.state.voice_saved) and bool(self.state.voice_id())
        elif idx == 4:
            ok = True
        self.btn_next.setEnabled(ok)

    def _on_next(self):
        idx = int(self.stack.currentIndex())
        if idx == 4:
            self.accept()
            return
        self._goto(idx + 1)

    def _on_role_changed(self):
        self.state.character = (self.edit_character.text() or "").strip()
        self.state.emotion = (self.edit_emotion.text() or "").strip() or "default"
        self.state.language = str(self.combo_lang.currentText() or "zh").strip() or "zh"
        self.state.mode = str(self.combo_mode.currentText() or "参考音色").strip() or "参考音色"
        if self.state.character and not self.state.test_text.strip():
            self.state.test_text = f"你好，我是{self.state.character}。现在我们来做一次合成测试。"
            self.test_text.setPlainText(self.state.test_text)
        self._update_voice_id_label()
        self._refresh_next_enabled()

    def _on_policy_changed(self):
        label = str(self.combo_policy.currentText() or "").strip()
        self.state.selection_policy = self._policy_label_to_key.get(label, "random_per_text")

    # -------- Step1 --------
    def _check_health(self):
        if not self._begin_button_busy(self.btn_check, "检查中..."):
            return
        self.health_status.setText("状态：正在检查...")

        def _do():
            cli = self._client_factory()
            return cli.health()

        def _ok(payload: dict):
            model_loaded = bool((payload or {}).get("model_loaded", False))
            st = (payload or {}).get("status") or "ok"
            self.health_status.setText(f"状态：API 可用（{st}），模型已加载={model_loaded}")
            if not model_loaded:
                self._toast_warn("提示", "检测到模型未加载。你仍可继续填写，但编译/合成需要先加载模型。")
            self._end_button_busy(self.btn_check)

        def _err(msg: str):
            self._toast_err("连接失败", self._with_advice(msg, "请先启动 API 服务，并确认端口配置正确。"))
            self._end_button_busy(self.btn_check)

        self._run(_do, _ok, _err)

    def _start_api(self):
        try:
            self.main_window.api_interface.toggle_server()
            self._toast_ok("已触发启动", "正在尝试启动内嵌 API 服务，请稍后再次检查连接")
        except Exception as e:
            self._toast_err("启动失败", str(e))

    def _load_model(self):
        try:
            self.main_window.on_load_model_clicked()
            self._toast_ok("已触发加载", "模型加载可能需要一些时间，加载完成后请再检查连接")
        except Exception as e:
            self._toast_err("加载失败", str(e))

    # -------- Step3 --------
    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择参考音频", "", "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*)")
        if p:
            self._upload_file = p
            self.label_file.setText(p)

    def _upload(self):
        ch = (self.state.character or "").strip()
        if not ch:
            self._toast_err("提示", "请先填写角色名")
            return
        fp = getattr(self, "_upload_file", "") or ""
        if not fp or not os.path.exists(fp):
            self._toast_err("提示", "请先选择要上传的音频文件")
            return

        emo = (self.state.emotion or "default").strip() or "default"
        lang = (self.state.language or "zh").strip() or "zh"
        note = (self.edit_note.text() or "").strip()
        self.state.note = note
        if not self._begin_button_busy(self.btn_upload, "上传中..."):
            return
        self.btn_pick_file.setEnabled(False)

        def _do():
            cli = self._client_factory()
            return cli.upload_asset(file_path=fp, character=ch, emotion=emo, language=lang, note=note)

        def _ok(meta: dict):
            aid = str((meta or {}).get("asset_id") or "").strip()
            if not aid:
                self._toast_err("上传失败", "未返回 asset_id")
                self._end_button_busy(self.btn_upload)
                self.btn_pick_file.setEnabled(True)
                return
            self.state.asset_id = aid
            self.label_asset.setText(f"asset_id：{aid}")
            self.btn_play.setEnabled(True)
            self._toast_ok("上传成功", f"asset_id={aid}")
            self._refresh_next_enabled()
            self._end_button_busy(self.btn_upload)
            self.btn_pick_file.setEnabled(True)

        def _err(msg: str):
            self._toast_err("上传失败", self._with_advice(msg, "确认音频格式为 wav/mp3/flac 且 API 服务在线。"))
            self._end_button_busy(self.btn_upload)
            self.btn_pick_file.setEnabled(True)

        self._run(_do, _ok, _err)

    def _play_uploaded(self):
        aid = (self.state.asset_id or "").strip()
        if not aid:
            self._toast_err("提示", "请先上传参考音频")
            return
        if not self._begin_button_busy(self.btn_play, "下载中..."):
            return

        def _do():
            cli = self._client_factory()
            return cli.download_asset_content(aid)

        def _ok(content: bytes):
            try:
                out = os.path.join(self._tmp_dir, f"wizard_ref_{aid}.wav")
                with open(out, "wb") as f:
                    f.write(content or b"")
                url = QUrl.fromLocalFile(out)
                self.media_player.setMedia(QMediaContent(url))
                self.media_player.play()
            except Exception as e:
                self._toast_err("试听失败", str(e))
            finally:
                self._end_button_busy(self.btn_play)

        def _err(msg: str):
            self._toast_err("试听失败", self._with_advice(msg, "稍后重试，或检查该 asset 是否仍可访问。"))
            self._end_button_busy(self.btn_play)

        self._run(_do, _ok, _err)

    # -------- Step4 --------
    def _save_voice(self):
        vid = self.state.voice_id()
        if not vid:
            self._toast_err("提示", "请先填写角色名/情绪标签")
            return
        aid = (self.state.asset_id or "").strip()
        if not aid:
            self._toast_err("提示", "请先上传参考音频")
            return
        prompt_text = (self.prompt_text.toPlainText() or "").strip()
        if not prompt_text:
            self._toast_err("提示", "参考文本为必填")
            return

        instruct_text = (self.instruct_text.toPlainText() or "").strip()
        self.state.prompt_text = prompt_text
        self.state.instruct_text = instruct_text
        self.state.selection_policy = self._policy_label_to_key.get(str(self.combo_policy.currentText() or "").strip(), "random_per_text")

        voice = {
            "name": vid,
            "character": self.state.character,
            "emotion": self.state.emotion,
            "language": self.state.language,
            "mode": self.state.mode,
            "prompt_text": prompt_text,
            "instruct_text": instruct_text,
            "prompt_audio_asset_id": aid,
            "ref_asset_ids": [aid],
            "selection_policy": self.state.selection_policy,
        }

        def _do():
            cli = self._client_factory()
            return cli.create_voice(voice)

        if not self._begin_button_busy(self.btn_save_voice, "保存中..."):
            return

        def _ok(_res: dict):
            self.state.voice_saved = True
            self.label_saved.setText(f"状态：已保存（{vid}）")
            self._toast_ok("保存成功", f"voice_id={vid}")
            self._end_button_busy(self.btn_save_voice)
            self._refresh_next_enabled()

        def _err_exc(e: object):
            # If voice already exists, treat as "update" for a smoother zero-basics flow.
            if isinstance(e, V2HttpError) and int(e.status_code) == 409:
                self._toast_warn("已存在", "检测到同名 voice，已改为覆盖更新")

                def _do_update():
                    cli = self._client_factory()
                    return cli.update_voice(vid, voice)

                def _ok_update(_res: dict):
                    self.state.voice_saved = True
                    self.label_saved.setText(f"状态：已更新（{vid}）")
                    self._toast_ok("更新成功", f"voice_id={vid}")
                    self._end_button_busy(self.btn_save_voice)
                    self._refresh_next_enabled()

                def _err_update(msg: str):
                    self._end_button_busy(self.btn_save_voice)
                    self._toast_err("更新失败", self._with_advice(msg, "检查 voice 配置字段后重试。"))

                self._run(_do_update, _ok_update, _err_update)
                return

            # Normal error path
            self._end_button_busy(self.btn_save_voice)
            if isinstance(e, V2HttpError):
                self._toast_err("保存失败", self._with_advice(e.short(), "如果同名冲突可直接重试，系统会尝试覆盖更新。"))
            else:
                self._toast_err("保存失败", self._with_advice(str(e), "检查 API 状态与字段完整性后重试。"))

        self._run_ex(_do, _ok, _err_exc)

    # -------- Step5 --------
    def _compile(self):
        vid = self.state.voice_id()
        if not vid:
            self._toast_err("提示", "voice_id 为空")
            return
        if not self._begin_button_busy(self.btn_compile, "编译中..."):
            return

        def _do():
            cli = self._client_factory()
            return cli.compile_voice(vid, compile_all=False)

        def _ok(res: dict):
            compiled = (res or {}).get("compiled") if isinstance(res, dict) else None
            self._toast_ok("编译完成", f"compiled={compiled}" if compiled else "编译完成")
            self._end_button_busy(self.btn_compile)

        def _err(msg: str):
            self._toast_err("编译失败", self._with_advice(msg, "确认该 voice 已保存且 API 在线。"))
            self._end_button_busy(self.btn_compile)

        self._run(_do, _ok, _err)

    def _synthesize(self):
        vid = self.state.voice_id()
        if not vid:
            self._toast_err("提示", "voice_id 为空")
            return
        text = (self.test_text.toPlainText() or "").strip()
        if not text:
            self._toast_err("提示", "请输入测试文本")
            return
        self.state.test_text = text
        if not self._begin_button_busy(self.btn_synth, "合成中..."):
            return

        req = {
            "text": text,
            "voice_id": vid,
            "speed": 1.0,
            "response_format": "audio",
            "save_output": False,
            "prefer_async": False,
        }

        def _do():
            cli = self._client_factory()
            return cli.synthesize_audio(req)

        def _ok(wav_bytes: bytes):
            try:
                out = os.path.join(self._tmp_dir, f"wizard_out_{vid.replace('#','_')}.wav")
                with open(out, "wb") as f:
                    f.write(wav_bytes or b"")
                self._last_out_path = out
                self.label_out.setText(f"输出：{out}")
                self.btn_play_out.setEnabled(True)
                self._toast_ok("合成成功", "已生成测试音频，可点击“播放输出”")
            except Exception as e:
                self._toast_err("保存失败", str(e))
            finally:
                self._end_button_busy(self.btn_synth)

        def _err(msg: str):
            self._toast_err("合成失败", self._with_advice(msg, "先编译 voice，再缩短测试文本重试。"))
            self._end_button_busy(self.btn_synth)

        self._run(_do, _ok, _err)

    def _play_output(self):
        p = getattr(self, "_last_out_path", "") or ""
        if not p or not os.path.exists(p):
            self._toast_err("提示", "未找到可播放的输出文件")
            return
        try:
            url = QUrl.fromLocalFile(p)
            self.media_player.setMedia(QMediaContent(url))
            self.media_player.play()
        except Exception as e:
            self._toast_err("播放失败", str(e))
