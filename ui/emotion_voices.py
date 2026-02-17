import os
from typing import Dict, List

from PyQt5.QtCore import QEvent, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QCursor, QFont, QFontMetrics
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SearchLineEdit,
    SegmentedWidget,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    TableWidget,
    ToolButton,
)

from .v2_client import V2Client, V2Config, V2HttpError
from .asset_cleanup_dialog import UnusedAssetsCleanupDialog
from .voice_setup_wizard import VoiceSetupWizardDialog
from .theme.tokens import Palette

CONTROL_H = 44
TOOL_BTN_SZ = 40
TABLE_ROW_H = 44


DEFAULT_EMOTIONS = [
    "default",
    "happy",
    "sad",
    "angry",
    "fear",
    "surprise",
    "disgust",
    "calm",
]


def _ui_font(size: int, *, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(int(size))
    if bold:
        f.setBold(True)
    return f


class ApiCallWorker(QThread):
    ok = pyqtSignal(object)
    err = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs):
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


class EmotionVoicesInterface(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        self._workers: List[QThread] = []
        self._character_map: Dict[str, List[dict]] = {}

        self._selected_character = ""
        self._selected_emotion = "default"
        self._upload_file = ""
        self._assets_items: List[dict] = []
        self._assets_view_items: List[dict] = []

        # Per-asset prompt text draft (switching rows should always show the right text).
        self._selected_asset_id = ""
        self._prompt_drafts_by_asset_id: Dict[str, str] = {}
        self._suppress_prompt_dirty = False
        self._selected_asset_label_full = ""

        self._tmp_dir = os.path.abspath("./data/ui_tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)

        self.media_player = QMediaPlayer()
        self.setAcceptDrops(True)

        self._init_ui()
        self.refresh_all()

    def _v2_client(self) -> V2Client:
        cm = self.main_window.config_manager
        host = str(cm.get("api_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(cm.get("api_port", 9880) or 9880)
        api_key = str(cm.get("api_key", "") or "").strip()
        return V2Client(V2Config(host=host, port=port, api_key=api_key, timeout_s=10.0))

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
            duration=3500,
            parent=self,
        )

    def _toast_err(self, title: str, content: str):
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def _run(self, fn, on_ok, on_err):
        w = ApiCallWorker(fn)
        self._workers.append(w)

        def _cleanup():
            try:
                self._workers.remove(w)
            except Exception:
                pass
            w.deleteLater()

        def _ok(res: object):
            try:
                on_ok(res)
            except Exception as e:
                self._toast_err("内部错误", str(e))

        def _err(e: object):
            try:
                # Normalize v2 HTTP error: show request_id if present.
                if isinstance(e, V2HttpError):
                    on_err(e.short())
                else:
                    on_err(str(e))
            except Exception as ee:
                self._toast_err("内部错误", str(ee))

        w.ok.connect(_ok)
        w.err.connect(_err)
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

    def shutdown(self, wait_ms: int = 8000):
        self._shutdown_workers(wait_ms=wait_ms)
        try:
            self.media_player.stop()
        except Exception:
            pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # P0: larger and calmer baseline for this page
        self.setFont(_ui_font(12))

        left = CardWidget(self)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(18, 18, 18, 18)
        left_l.setSpacing(12)

        title_left = SubtitleLabel("情绪管理（v2）")
        title_left.setFont(_ui_font(18, bold=True))
        left_l.addWidget(title_left)

        hp = QHBoxLayout()
        hp.addWidget(BodyLabel("API"))
        self.host_edit = LineEdit()
        self.host_edit.setFixedWidth(210)
        self.host_edit.setFixedHeight(CONTROL_H)
        self.port_spin = SpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setFixedWidth(120)
        self.port_spin.setFixedHeight(CONTROL_H)
        hp.addWidget(self.host_edit)
        hp.addWidget(self.port_spin)
        hp.addStretch()
        self.refresh_btn = ToolButton(FluentIcon.SYNC)
        self.refresh_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(self.refresh_all)
        hp.addWidget(self.refresh_btn)
        left_l.addLayout(hp)

        ch_row = QHBoxLayout()
        ch_row.addWidget(BodyLabel("角色"))
        self.character_combo = ComboBox()
        self.character_combo.setFixedHeight(CONTROL_H)
        self.character_combo.currentTextChanged.connect(self.on_character_changed)
        ch_row.addWidget(self.character_combo, 1)
        self.new_character_btn = ToolButton(FluentIcon.ADD)
        self.new_character_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.new_character_btn.setToolTip("新建角色")
        self.new_character_btn.clicked.connect(self.create_character)
        ch_row.addWidget(self.new_character_btn)
        left_l.addLayout(ch_row)

        section_voice = BodyLabel("当前 voice 配置")
        section_voice.setFont(_ui_font(14, bold=True))
        left_l.addWidget(section_voice)
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["参考音色", "零样本复制", "精细控制", "指令控制"])
        self.mode_combo.setCurrentText("参考音色")
        self.mode_combo.setFixedHeight(CONTROL_H)
        left_l.addWidget(self.mode_combo)

        self.selection_combo = ComboBox()
        # Display in Chinese; persist as v2 policy key.
        self._policy_key_to_label = {
            "random_per_text": "按文本随机（稳定）",
            "fixed": "固定（始终第一个）",
            "random_per_request": "按请求随机（不推荐）",
        }
        self._policy_label_to_key = {v: k for k, v in self._policy_key_to_label.items()}
        self.selection_combo.addItems(list(self._policy_label_to_key.keys()))
        self.selection_combo.setCurrentText(self._policy_key_to_label["random_per_text"])
        self.selection_combo.setFixedHeight(CONTROL_H)
        left_l.addWidget(self.selection_combo)

        self.prompt_text = PlainTextEdit()
        self.prompt_text.setPlaceholderText("参考文本（当前选中参考音频；建议与音频内容一致）")
        self.prompt_text.setFixedHeight(140)
        self.prompt_text.textChanged.connect(self._on_prompt_text_changed)
        left_l.addWidget(self.prompt_text)

        self.follow_asset_prompt_switch = SwitchButton("切换参考音频时自动加载其参考文本（来自备注/已保存文本）")
        self.follow_asset_prompt_switch.setChecked(True)
        left_l.addWidget(self.follow_asset_prompt_switch)

        self.sync_prompt_to_asset_switch = SwitchButton("保存 voice 时同步参考文本到选中音频备注")
        self.sync_prompt_to_asset_switch.setChecked(True)
        left_l.addWidget(self.sync_prompt_to_asset_switch)

        self.selected_asset_label = BodyLabel("当前选中参考音频：<无>")
        self.selected_asset_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        # Keep layout stable: never allow this label to wrap and change height.
        try:
            self.selected_asset_label.setWordWrap(False)
        except Exception:
            pass
        self.selected_asset_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.selected_asset_label.setFixedHeight(24)
        left_l.addWidget(self.selected_asset_label)

        self.instruct_text = PlainTextEdit()
        self.instruct_text.setPlaceholderText("指令文本（可选）")
        self.instruct_text.setFixedHeight(110)
        left_l.addWidget(self.instruct_text)

        save_row = QHBoxLayout()
        self.save_voice_btn = PushButton("保存 voice")
        self.save_voice_btn.setFixedHeight(CONTROL_H)
        self.save_voice_btn.clicked.connect(self.save_current_voice)
        save_row.addWidget(self.save_voice_btn)
        self.compile_all_switch = SwitchButton("编译全部参考音频")
        save_row.addWidget(self.compile_all_switch)
        self.compile_btn = PrimaryPushButton("编译")
        self.compile_btn.setFixedHeight(CONTROL_H)
        self.compile_btn.clicked.connect(self.compile_current_voice)
        save_row.addWidget(self.compile_btn)
        left_l.addLayout(save_row)

        right = CardWidget(self)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(18, 18, 18, 18)
        right_l.setSpacing(12)

        header = QHBoxLayout()
        title_right = SubtitleLabel("参考音频库（assets）")
        title_right.setFont(_ui_font(18, bold=True))
        header.addWidget(title_right)
        header.addStretch()

        # P0: reduce the "button wall" - keep key actions visible, rest in "more" menu.
        self.play_btn = PushButton("试听")
        self.play_btn.setFixedHeight(CONTROL_H)
        self.play_btn.setIcon(FluentIcon.VOLUME)
        self.play_btn.clicked.connect(self.play_selected_asset)
        header.addWidget(self.play_btn)

        self.bind_btn = PrimaryPushButton("绑定到当前 voice")
        self.bind_btn.setFixedHeight(CONTROL_H)
        self.bind_btn.setIcon(FluentIcon.LINK)
        self.bind_btn.clicked.connect(self.bind_selected_assets)
        header.addWidget(self.bind_btn)

        self.more_btn = ToolButton(FluentIcon.MORE)
        self.more_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.more_btn.setToolTip("更多操作")
        self.more_btn.clicked.connect(self._show_more_menu)
        header.addWidget(self.more_btn)
        right_l.addLayout(header)

        emo_row = QHBoxLayout()
        emo_row.setSpacing(10)
        emo_row.addWidget(BodyLabel("情绪"))
        self.emotion_seg = SegmentedWidget(self)
        self.emotion_seg.currentItemChanged.connect(self._on_emotion_segment_changed)
        emo_row.addWidget(self.emotion_seg, 1)
        self.add_emotion_btn = ToolButton(FluentIcon.ADD)
        self.add_emotion_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.add_emotion_btn.setToolTip("新增情绪")
        self.add_emotion_btn.clicked.connect(self._add_emotion)
        emo_row.addWidget(self.add_emotion_btn)
        self.ensure_voice_btn = PushButton("创建该情绪 voice")
        self.ensure_voice_btn.setFixedHeight(CONTROL_H)
        self.ensure_voice_btn.setToolTip("确保角色#情绪 的 voice 存在（上传参考音频后才会在“声音库”中可选）")
        self.ensure_voice_btn.clicked.connect(self.ensure_current_emotion_voice)
        emo_row.addWidget(self.ensure_voice_btn)
        right_l.addLayout(emo_row)

        up = QHBoxLayout()
        up.addWidget(BodyLabel("语言"))
        self.lang_combo = ComboBox()
        self.lang_combo.addItems(["zh", "en", "ja", "ko"])
        self.lang_combo.setCurrentText("zh")
        self.lang_combo.setFixedHeight(CONTROL_H)
        up.addWidget(self.lang_combo)
        up.addSpacing(12)
        up.addWidget(BodyLabel("情绪标签"))
        self.emotion_edit = LineEdit()
        self.emotion_edit.setPlaceholderText("例如 default / happy / ...")
        self.emotion_edit.setFixedHeight(CONTROL_H)
        up.addWidget(self.emotion_edit, 1)
        self.choose_file_btn = ToolButton(FluentIcon.FOLDER)
        self.choose_file_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.choose_file_btn.clicked.connect(self.choose_upload_file)
        up.addWidget(self.choose_file_btn)
        self.upload_btn = PrimaryPushButton("上传")
        self.upload_btn.setFixedHeight(CONTROL_H)
        self.upload_btn.clicked.connect(self.upload_ref_audio)
        up.addWidget(self.upload_btn)
        right_l.addLayout(up)

        note_row = QHBoxLayout()
        note_row.addWidget(BodyLabel("备注"))
        self.note_edit = LineEdit()
        self.note_edit.setPlaceholderText("可选，用于搜索")
        self.note_edit.setFixedHeight(CONTROL_H)
        note_row.addWidget(self.note_edit, 1)
        self.save_note_btn = PushButton("保存备注")
        self.save_note_btn.setFixedHeight(CONTROL_H)
        self.save_note_btn.clicked.connect(self.save_selected_asset_note)
        note_row.addWidget(self.save_note_btn)
        right_l.addLayout(note_row)

        self.file_label = BodyLabel("未选择文件")
        self.file_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        right_l.addWidget(self.file_label)

        filter_row = QHBoxLayout()
        self.asset_search = SearchLineEdit(self)
        self.asset_search.setPlaceholderText("搜索 备注/路径/资源ID")
        self.asset_search.setFixedHeight(CONTROL_H)
        self.asset_search.textChanged.connect(self._apply_asset_filters)
        filter_row.addWidget(self.asset_search, 1)

        self.asset_filter_linked = ComboBox()
        self.asset_filter_linked.addItems(["全部", "已绑定", "未绑定"])
        self.asset_filter_linked.setFixedHeight(CONTROL_H)
        self.asset_filter_linked.currentTextChanged.connect(lambda _: self._apply_asset_filters())
        filter_row.addWidget(self.asset_filter_linked)

        self.asset_filter_language = ComboBox()
        self.asset_filter_language.addItems(["全部", "zh", "en", "ja", "ko"])
        self.asset_filter_language.setFixedHeight(CONTROL_H)
        self.asset_filter_language.currentTextChanged.connect(lambda _: self._apply_asset_filters())
        filter_row.addWidget(self.asset_filter_language)
        right_l.addLayout(filter_row)

        self.asset_table = TableWidget()
        self.asset_table.setColumnCount(6)
        self.asset_table.setHorizontalHeaderLabels(["资源ID", "语言", "备注", "时间", "路径", "绑定"])
        self.asset_table.verticalHeader().setVisible(False)
        self.asset_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.asset_table.customContextMenuRequested.connect(self._show_assets_context_menu)
        try:
            self.asset_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.asset_table.setSelectionMode(QAbstractItemView.SingleSelection)
        except Exception:
            pass
        self.asset_table.itemSelectionChanged.connect(self._on_asset_selection_changed)
        try:
            self.asset_table.verticalHeader().setDefaultSectionSize(TABLE_ROW_H)
        except Exception:
            pass
        hdr = self.asset_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.asset_table.setColumnWidth(0, 200)
        self.asset_table.setColumnWidth(1, 90)
        self.asset_table.setColumnWidth(2, 240)
        self.asset_table.setColumnWidth(3, 160)
        self.asset_table.setColumnWidth(4, 320)
        self.asset_table.setColumnWidth(5, 120)
        right_l.addWidget(self.asset_table, 5)

        layout.addWidget(left, 2)
        layout.addWidget(right, 5)

        cm = self.main_window.config_manager
        self.host_edit.setText(str(cm.get("api_host", "127.0.0.1") or "127.0.0.1"))
        self.port_spin.setValue(int(cm.get("api_port", 9880) or 9880))
        self.emotion_edit.setText("default")

        self._rebuild_emotions(DEFAULT_EMOTIONS)
        self._set_upload_hint()
        for w in [self, right, self.file_label, self.asset_table]:
            try:
                w.setAcceptDrops(True)
                w.installEventFilter(self)
            except Exception:
                pass

    def _set_upload_hint(self):
        if self._upload_file and os.path.exists(self._upload_file):
            self.file_label.setText(self._upload_file)
            self.file_label.setStyleSheet("")
        else:
            self.file_label.setText("未选择文件（你也可以把音频文件拖拽到窗口中）")
            self.file_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")

    # -------- refresh --------
    def refresh_all(self):
        cm = self.main_window.config_manager
        cm.set("api_host", (self.host_edit.text() or "").strip() or "127.0.0.1")
        cm.set("api_port", int(self.port_spin.value()))

        def _do():
            cli = self._v2_client()
            voices = cli.list_voices()
            ch_map: Dict[str, List[dict]] = {}
            for v in voices:
                if not isinstance(v, dict):
                    continue
                vid = str(v.get("name") or "").strip()
                ch = str(v.get("character") or "").strip()
                emo = str(v.get("emotion") or "").strip()
                if not ch and "#" in vid:
                    parts = vid.split("#", 1)
                    ch = (parts[0] or "").strip()
                    emo = (parts[1] if len(parts) > 1 else "").strip()
                    if ch:
                        v = dict(v)
                        v.setdefault("character", ch)
                        v.setdefault("emotion", emo or "default")
                if ch:
                    ch_map.setdefault(ch, []).append(v)
            return ch_map

        self._run(_do, self._on_refresh_ok, lambda m: self._toast_err("刷新失败", m))

    def _on_refresh_ok(self, ch_map: Dict[str, List[dict]]):
        self._character_map = ch_map or {}
        chars = sorted(self._character_map.keys())
        cur = (self._selected_character or "").strip()
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for c in chars:
            self.character_combo.addItem(c)
        self.character_combo.blockSignals(False)
        if chars:
            if cur and cur in chars:
                self.character_combo.setCurrentText(cur)
            else:
                self.character_combo.setCurrentText(chars[0])
        else:
            self._toast_warn("提示", "未发现 v2 voices，可先新建角色")
            self.on_character_changed("")

    def on_character_changed(self, character: str):
        self._selected_character = (character or "").strip()
        self._rebuild_emotions(self._discover_emotions_from_voices(self._selected_character))
        self._select_emotion(self._load_last_emotion_for_character(self._selected_character) or "default")
        self._refresh_emotions_from_assets(self._selected_character)

    def _discover_emotions_from_voices(self, character: str) -> List[str]:
        emotions = set(DEFAULT_EMOTIONS)
        for v in self._character_map.get(character, []) or []:
            emo = str((v or {}).get("emotion") or "").strip() or "default"
            emotions.add(emo)
        return list(emotions)

    def _rebuild_emotions(self, emotions: List[str]):
        self.emotion_seg.blockSignals(True)
        try:
            self.emotion_seg.clear()
        except Exception:
            pass
        emos = [e for e in emotions if str(e or "").strip()] or list(DEFAULT_EMOTIONS)
        ordered: List[str] = []
        for e in DEFAULT_EMOTIONS:
            if e in emos and e not in ordered:
                ordered.append(e)
        for e in sorted(emos):
            if e not in ordered:
                ordered.append(e)
        for emo in ordered:
            self.emotion_seg.addItem(emo, emo)
        self.emotion_seg.blockSignals(False)

    def _on_emotion_segment_changed(self, route_key: str):
        self._select_emotion(route_key or "default")

    def _select_emotion(self, emotion: str):
        emo = (emotion or "").strip() or "default"
        self._selected_emotion = emo
        self.emotion_edit.setText(emo)
        try:
            self.emotion_seg.setCurrentItem(emo)
        except Exception:
            pass
        self._save_last_emotion_for_character(self._selected_character, emo)
        self.refresh_assets()
        self.load_voice()

    def _load_last_emotion_for_character(self, character: str) -> str:
        ch = (character or "").strip()
        if not ch:
            return ""
        cm = self.main_window.config_manager
        m = cm.get("ui_last_emotion_by_character", {}) or {}
        if not isinstance(m, dict):
            return ""
        return str(m.get(ch) or "")

    def _save_last_emotion_for_character(self, character: str, emotion: str):
        ch = (character or "").strip()
        if not ch:
            return
        cm = self.main_window.config_manager
        m = cm.get("ui_last_emotion_by_character", {}) or {}
        if not isinstance(m, dict):
            m = {}
        m[ch] = (emotion or "").strip() or "default"
        cm.set("ui_last_emotion_by_character", m)

    def _add_emotion(self):
        if not self._selected_character:
            self._toast_warn("提示", "请先选择/创建角色")
            return
        name, ok = QInputDialog.getText(self, "新增情绪", "情绪标签（例如 happy / sad / calm）:")
        if not ok:
            return
        emo = (name or "").strip()
        if not emo:
            return
        emotions = set(self._discover_emotions_from_voices(self._selected_character))
        emotions.add(emo)
        self._rebuild_emotions(list(emotions))
        self._select_emotion(emo)

    def _refresh_emotions_from_assets(self, character: str):
        ch = (character or "").strip()
        if not ch:
            return

        def _do():
            cli = self._v2_client()
            return cli.list_assets(character=ch, emotion="", language="", kind="ref")

        def _ok(items: List[dict]):
            emos = set(self._discover_emotions_from_voices(ch))
            for it in items or []:
                if isinstance(it, dict):
                    e = str(it.get("emotion") or "").strip()
                    if e:
                        emos.add(e)
            self._rebuild_emotions(list(emos))
            self._select_emotion(self._load_last_emotion_for_character(ch) or self._selected_emotion or "default")

        self._run(_do, _ok, lambda _: None)

    # -------- assets --------
    def refresh_assets(self):
        ch = self._selected_character
        emo = self._selected_emotion
        if not ch:
            self.asset_table.setRowCount(0)
            return

        def _do():
            cli = self._v2_client()
            return cli.list_assets(character=ch, emotion=emo, language="", kind="ref")

        self._run(_do, self._set_assets_table, lambda m: self._toast_err("加载 assets 失败", m))

    def _set_assets_table(self, items: List[dict]):
        self._assets_items = items or []
        self._apply_asset_filters()

    def _apply_asset_filters(self):
        items = list(self._assets_items or [])
        q = (self.asset_search.text() or "").strip().lower() if hasattr(self, "asset_search") else ""
        link_filter = str(self.asset_filter_linked.currentText() or "全部") if hasattr(self, "asset_filter_linked") else "全部"
        lang_filter = str(self.asset_filter_language.currentText() or "全部") if hasattr(self, "asset_filter_language") else "全部"

        def _ok_item(it: dict) -> bool:
            if not isinstance(it, dict):
                return False
            if lang_filter != "全部":
                if str(it.get("language") or "").strip() != lang_filter:
                    return False
            if link_filter == "已绑定" and not it.get("linked"):
                return False
            if link_filter == "未绑定" and bool(it.get("linked")):
                return False
            if q:
                hay = " ".join(
                    [
                        str(it.get("asset_id") or ""),
                        str(it.get("note") or ""),
                        str(it.get("path") or ""),
                        str(it.get("created_at") or ""),
                    ]
                ).lower()
                if q not in hay:
                    return False
            return True

        items = [it for it in items if _ok_item(it)]
        self._render_assets_table(items)

    def _render_assets_table(self, items: List[dict]):
        items = items or []
        self._assets_view_items = list(items)
        self.asset_table.blockSignals(True)
        self.asset_table.setRowCount(len(items))
        font = QFont("Consolas", 12)
        font2 = _ui_font(12)
        for row, it in enumerate(items):
            if not isinstance(it, dict):
                it = {}
            aid = str(it.get("asset_id") or "")
            language = str(it.get("language") or "")
            note = str(it.get("note") or "")
            created_at = str(it.get("created_at") or "")
            path = str(it.get("path") or "")
            linked = "已绑定" if it.get("linked") else "未绑定"
            values = [aid, language, note, created_at, path, linked]
            for col, v in enumerate(values):
                # QTableWidgetItem plays nicer than cell widgets for selection
                from PyQt5.QtWidgets import QTableWidgetItem

                item = QTableWidgetItem(str(v))
                item.setFont(font if col == 0 else font2)
                item.setTextAlignment(Qt.AlignCenter if col != 4 else Qt.AlignLeft | Qt.AlignVCenter)
                self.asset_table.setItem(row, col, item)
        self.asset_table.blockSignals(False)
        self._on_asset_selection_changed()

    def _on_asset_selection_changed(self):
        try:
            rows = {idx.row() for idx in self.asset_table.selectedIndexes()}
            if len(rows) != 1:
                self.selected_asset_label.setText("当前选中参考音频：<无>")
                self.selected_asset_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
                self._selected_asset_id = ""
                return
            row = list(rows)[0]
            it = self._assets_view_items[row] if 0 <= row < len(self._assets_view_items) else {}
            if not isinstance(it, dict):
                it = {}

            aid = str(it.get("asset_id") or "").strip()
            note = str(it.get("note") or "").strip()
            emo = str(it.get("emotion") or "").strip() or self._selected_emotion or "default"
            label_note = note if note else "<无备注>"
            full = f"当前选中参考音频：{emo} / {aid} / {label_note}"
            self._set_selected_asset_label(full, tooltip=full)
            self.selected_asset_label.setStyleSheet("")

            # Keep note_edit aligned with selected asset (so editing metadata is intuitive).
            try:
                self.note_edit.blockSignals(True)
                self.note_edit.setText(note)
            finally:
                self.note_edit.blockSignals(False)

            # Switching rows should always update prompt_text to the selected asset's text.
            if not hasattr(self, "follow_asset_prompt_switch") or not self.follow_asset_prompt_switch.isChecked():
                self._selected_asset_id = aid
                return

            suggested = ""
            if aid and aid in self._prompt_drafts_by_asset_id:
                suggested = (self._prompt_drafts_by_asset_id.get(aid) or "").strip()
            if not suggested:
                suggested = str(it.get("prompt_text") or "").strip()
            if not suggested:
                suggested = note

            self._suppress_prompt_dirty = True
            try:
                self.prompt_text.setPlainText(str(suggested or ""))
            finally:
                self._suppress_prompt_dirty = False

            self._selected_asset_id = aid
        except Exception:
            # Never crash UI because of selection sync.
            return

    def _on_prompt_text_changed(self):
        if self._suppress_prompt_dirty:
            return
        # Draft is per selected asset (so switching rows doesn't "sometimes" stop updating).
        aid = (getattr(self, "_selected_asset_id", "") or "").strip()
        if aid:
            self._prompt_drafts_by_asset_id[aid] = (self.prompt_text.toPlainText() or "").strip()

    def _set_selected_asset_label(self, text: str, *, tooltip: str = ""):
        # Render as a single line with ellipsis to prevent vertical layout shifts.
        self._selected_asset_label_full = str(text or "")
        try:
            if tooltip:
                self.selected_asset_label.setToolTip(str(tooltip))
        except Exception:
            pass
        self._refresh_selected_asset_label()

    def _refresh_selected_asset_label(self):
        try:
            w = max(int(self.selected_asset_label.width() or 0) - 6, 50)
            fm = QFontMetrics(self.selected_asset_label.font())
            elided = fm.elidedText(self._selected_asset_label_full, Qt.ElideRight, w)
            self.selected_asset_label.setText(elided)
        except Exception:
            # Fallback to raw text; still no wrap due to fixed height.
            try:
                self.selected_asset_label.setText(self._selected_asset_label_full)
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep ellipsis correct when window resizes.
        self._refresh_selected_asset_label()

    def _show_more_menu(self):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.CLOSE, "从当前 voice 解绑", self, triggered=self.unbind_selected_assets))
        menu.addAction(Action(FluentIcon.DELETE, "删除选中资源", self, triggered=self.delete_selected_assets))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.COPY, "复制资源ID", self, triggered=self._copy_selected_asset_id))
        menu.addAction(Action(FluentIcon.FOLDER, "打开资源位置", self, triggered=self._open_selected_asset_location))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.ADD, "一键闭环向导", self, triggered=self.open_voice_setup_wizard))
        menu.addAction(Action(FluentIcon.DELETE, "清理未引用参考音频", self, triggered=self.open_unused_assets_cleanup))
        menu.exec_(QCursor.pos())

    def open_unused_assets_cleanup(self):
        dlg = UnusedAssetsCleanupDialog(
            self._v2_client,
            characters=sorted(self._character_map.keys()),
            default_character=self._selected_character,
            parent=self,
        )
        dlg.exec_()
        # Best-effort refresh after cleanup.
        try:
            self.refresh_assets()
        except Exception:
            pass

    def open_voice_setup_wizard(self):
        try:
            dlg = VoiceSetupWizardDialog(
                self.main_window,
                self._v2_client,
                preset_character=self._selected_character,
                preset_emotion=self._selected_emotion,
                parent=self,
            )
            dlg.exec_()
            # Refresh to reflect newly created voice/assets.
            try:
                self.refresh_all()
            except Exception:
                pass
        except Exception as e:
            self._toast_err("打开失败", str(e))

    def _show_assets_context_menu(self, pos):
        # Select the row under cursor first, then show context actions.
        try:
            idx = self.asset_table.indexAt(pos)
            if idx.isValid():
                self.asset_table.selectRow(idx.row())
        except Exception:
            pass

        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.VOLUME, "试听", self, triggered=self.play_selected_asset))
        menu.addAction(Action(FluentIcon.LINK, "绑定到当前 voice", self, triggered=self.bind_selected_assets))
        menu.addAction(Action(FluentIcon.CLOSE, "从当前 voice 解绑", self, triggered=self.unbind_selected_assets))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.DELETE, "删除", self, triggered=self.delete_selected_assets))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.COPY, "复制资源ID", self, triggered=self._copy_selected_asset_id))
        menu.addAction(Action(FluentIcon.FOLDER, "打开资源位置", self, triggered=self._open_selected_asset_location))
        menu.exec_(self.asset_table.mapToGlobal(pos))

    def _copy_selected_asset_id(self):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择一个资源")
            return
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(aids[0])
        self._toast_ok("已复制", aids[0])

    def _open_selected_asset_location(self):
        rows = {idx.row() for idx in self.asset_table.selectedIndexes()}
        if not rows:
            self._toast_warn("提示", "请先选择一个资源")
            return
        r = sorted(rows)[0]
        it = self.asset_table.item(r, 4)
        p = (it.text() or "").strip() if it else ""
        if not p:
            self._toast_warn("提示", "该资源没有可用的本地路径")
            return
        if os.path.exists(p):
            try:
                os.startfile(os.path.dirname(p))
            except Exception as e:
                self._toast_err("打开失败", str(e))
        else:
            self._toast_warn("提示", "路径不存在，可能需要先下载该资源")

    def choose_upload_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择参考音频", "", "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*)")
        if p:
            self._upload_file = p
            self._set_upload_hint()

    def upload_ref_audio(self):
        ch = self._selected_character
        if not ch:
            self._toast_warn("提示", "请先选择/创建角色")
            return
        fp = self._upload_file
        if not fp or not os.path.exists(fp):
            self._toast_warn("提示", "请先选择要上传的音频文件")
            return
        emo = (self.emotion_edit.text() or "").strip() or "default"
        lang = str(self.lang_combo.currentText() or "zh").strip() or "zh"
        note = (self.note_edit.text() or "").strip()
        voice_prompt_hint = (self.prompt_text.toPlainText() or "").strip() or note
        mode_val = str(self.mode_combo.currentText() or "参考音色")
        instruct_val = (self.instruct_text.toPlainText() or "").strip()
        policy_val = self._policy_label_to_key.get(str(self.selection_combo.currentText() or ""), "random_per_text")

        def _do():
            cli = self._v2_client()
            meta = cli.upload_asset(file_path=fp, character=ch, emotion=emo, language=lang, note=note)
            aid = str((meta or {}).get("asset_id") or "").strip()
            vid = f"{ch}#{emo}" if ch else ""

            created = False
            bound = False

            # Best-effort: ensure the emotion voice exists so it becomes selectable in Voice Library.
            if vid and voice_prompt_hint:
                try:
                    cli.get_voice(vid)
                except Exception:
                    payload = {
                        "name": vid,
                        "mode": mode_val,
                        "prompt_text": voice_prompt_hint,
                        "instruct_text": instruct_val,
                        "ref_asset_ids": [],
                        "selection_policy": policy_val,
                        "character": ch,
                        "emotion": emo,
                    }
                    try:
                        cli.create_voice(payload)
                        created = True
                    except Exception:
                        # Ignore conflict and other transient errors; upload still succeeded.
                        created = False

            # Best-effort: bind the new asset to the current emotion voice.
            if vid and aid:
                try:
                    voice = cli.get_voice(vid)
                    cur = voice.get("ref_asset_ids") or []
                    cur = [str(x).strip() for x in cur if str(x).strip()]
                    if aid not in cur:
                        cur.append(aid)
                        cli.update_voice(vid, {"ref_asset_ids": cur})
                    bound = True
                except Exception:
                    bound = False

            return {"meta": meta, "voice_id": vid, "created_voice": created, "bound": bound}

        def _ok(res: dict):
            meta = (res or {}).get("meta") if isinstance(res, dict) else {}
            aid = str((meta or {}).get("asset_id") or "")
            vid = str((res or {}).get("voice_id") or "")
            created = bool((res or {}).get("created_voice"))
            bound = bool((res or {}).get("bound"))
            extra = []
            if created:
                extra.append("已创建 voice")
            if bound:
                extra.append("已绑定到当前 voice")
            msg = f"asset_id={aid}"
            if vid:
                msg += f" / {vid}"
            if extra:
                msg += " / " + "、".join(extra)
            self._toast_ok("上传成功", msg)

            # Refresh voices and assets so new emotion shows up as needed.
            self._upload_file = ""
            self._set_upload_hint()
            self.refresh_all()
            if not voice_prompt_hint:
                self._toast_warn("提示", "已上传参考音频，但未创建该情绪 voice：请先填写左侧“参考文本”或右侧“备注”，再点击“创建该情绪 voice”。")

        self._run(_do, _ok, lambda m: self._toast_err("上传失败", m))

    def ensure_current_emotion_voice(self):
        ch = (self._selected_character or "").strip()
        if not ch:
            self._toast_warn("提示", "请先选择/创建角色")
            return
        emo = (self.emotion_edit.text() or "").strip() or (self._selected_emotion or "default")
        vid = f"{ch}#{emo}"
        mode_val = str(self.mode_combo.currentText() or "参考音色")
        instruct_val = (self.instruct_text.toPlainText() or "").strip()
        policy_val = self._policy_label_to_key.get(str(self.selection_combo.currentText() or ""), "random_per_text")

        prompt = (self.prompt_text.toPlainText() or "").strip()
        if not prompt:
            # Use asset note as a practical default: user usually pastes reference text there.
            prompt = (self.note_edit.text() or "").strip()

        if not prompt:
            text, ok = QInputDialog.getMultiLineText(
                self,
                "创建该情绪 voice",
                "请输入参考文本（建议与参考音频内容一致，用于编译/稳定性）：",
                "",
            )
            if not ok:
                return
            prompt = (text or "").strip()

        if not prompt:
            self._toast_warn("提示", "参考文本不能为空")
            return

        def _do():
            cli = self._v2_client()
            try:
                cli.get_voice(vid)
                return {"status": "exists"}
            except Exception:
                payload = {
                    "name": vid,
                    "mode": mode_val,
                    "prompt_text": prompt,
                    "instruct_text": instruct_val,
                    "ref_asset_ids": [],
                    "selection_policy": policy_val,
                    "character": ch,
                    "emotion": emo,
                }
                cli.create_voice(payload)
                return {"status": "created"}

        def _ok(res: dict):
            st = str((res or {}).get("status") or "")
            if st == "exists":
                self._toast_ok("voice 已存在", vid)
            else:
                self._toast_ok("已创建 voice", vid)
            self.refresh_all()

        self._run(_do, _ok, lambda m: self._toast_err("创建 voice 失败", m))

    def save_selected_asset_note(self):
        aid = (self._selected_asset_id or "").strip()
        if not aid:
            # Fallback to table selection.
            aids = self._selected_asset_ids()
            aid = aids[0] if aids else ""
        if not aid:
            self._toast_warn("提示", "请先在右侧选择一个参考音频")
            return

        note = (self.note_edit.text() or "").strip()
        if not note:
            self._toast_warn("提示", "备注不能为空")
            return

        def _do():
            cli = self._v2_client()
            # Keep note/prompt_text consistent for now: UI treats it as the per-asset reference text.
            return cli.update_asset(aid, {"note": note, "prompt_text": note})

        def _ok(_):
            self._toast_ok("已保存备注", aid)
            try:
                self.refresh_assets()
            except Exception:
                pass

        self._run(_do, _ok, lambda m: self._toast_err("保存备注失败", m))

    def _selected_asset_ids(self) -> List[str]:
        ids: List[str] = []
        rows = {idx.row() for idx in self.asset_table.selectedIndexes()}
        for r in sorted(rows):
            it = self.asset_table.item(r, 0)
            if it:
                aid = (it.text() or "").strip()
                if aid:
                    ids.append(aid)
        return ids

    def play_selected_asset(self):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要试听的 asset")
            return
        aid = aids[0]

        def _do():
            cli = self._v2_client()
            meta = cli.get_asset_meta(aid)
            p = str((meta or {}).get("path") or "").strip()
            if p and os.path.exists(p):
                return p
            data = cli.download_asset_content(aid)
            out = os.path.join(self._tmp_dir, f"preview_{aid}.wav")
            with open(out, "wb") as f:
                f.write(data)
            return out

        def _ok(path: str):
            self.media_player.stop()
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self.media_player.play()
            self._toast_ok("试听", os.path.basename(path))

        self._run(_do, _ok, lambda m: self._toast_err("试听失败", m))

    def delete_selected_assets(self):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要删除的 asset")
            return

        def _do():
            cli = self._v2_client()
            # Best-effort unbind before delete
            try:
                vid = self._voice_id()
                if vid:
                    voice = cli.get_voice(vid)
                    cur = voice.get("ref_asset_ids") or []
                    cur = [str(x).strip() for x in cur if str(x).strip()]
                    cur2 = [x for x in cur if x not in set(aids)]
                    if cur2 != cur:
                        cli.update_voice(vid, {"ref_asset_ids": cur2})
            except Exception:
                pass
            for aid in aids:
                cli.delete_asset(aid)
            return True

        self._run(_do, lambda _: (self._toast_ok("已删除", f"{len(aids)} 个 asset"), self.refresh_assets()), lambda m: self._toast_err("删除失败", m))

    # -------- voices --------
    def _voice_id(self) -> str:
        ch = (self._selected_character or "").strip()
        emo = (self._selected_emotion or "").strip() or "default"
        return f"{ch}#{emo}" if ch else ""

    def _ensure_voice(self, cli: V2Client, voice_id: str) -> dict:
        try:
            return cli.get_voice(voice_id)
        except Exception:
            prompt = (self.prompt_text.toPlainText() or "").strip()
            if not prompt:
                raise ValueError("prompt_text 不能为空（创建 voice 需要）")
            voice = {
                "name": voice_id,
                "mode": str(self.mode_combo.currentText() or "参考音色"),
                "prompt_text": prompt,
                "instruct_text": (self.instruct_text.toPlainText() or "").strip(),
                "ref_asset_ids": [],
                "selection_policy": self._policy_label_to_key.get(str(self.selection_combo.currentText() or ""), "random_per_text"),
                "character": self._selected_character,
                "emotion": self._selected_emotion,
            }
            return cli.create_voice(voice)

    def load_voice(self):
        vid = self._voice_id()
        if not vid:
            return

        def _do():
            cli = self._v2_client()
            try:
                return cli.get_voice(vid)
            except Exception:
                return {}

        def _ok(v: dict):
            if not isinstance(v, dict) or not v:
                return
            self.mode_combo.setCurrentText(str(v.get("mode") or "参考音色"))
            pol = str(v.get("selection_policy") or "random_per_text")
            self.selection_combo.setCurrentText(self._policy_key_to_label.get(pol, self._policy_key_to_label["random_per_text"]))
            self._suppress_prompt_dirty = True
            try:
                self.prompt_text.setPlainText(str(v.get("prompt_text") or ""))
                self.instruct_text.setPlainText(str(v.get("instruct_text") or ""))
            finally:
                self._suppress_prompt_dirty = False
            # Clear per-asset drafts on voice reload to avoid cross-character confusion.
            self._prompt_drafts_by_asset_id = {}
            self._selected_asset_id = ""

        self._run(_do, _ok, lambda _: None)

    def save_current_voice(self):
        vid = self._voice_id()
        if not vid:
            self._toast_warn("提示", "请先选择角色与情绪")
            return

        selected_aid = (self._selected_asset_id or "").strip()

        def _do():
            cli = self._v2_client()
            self._ensure_voice(cli, vid)
            patch = {
                "name": vid,
                "mode": str(self.mode_combo.currentText() or ""),
                "prompt_text": (self.prompt_text.toPlainText() or "").strip(),
                "instruct_text": (self.instruct_text.toPlainText() or "").strip(),
                "selection_policy": self._policy_label_to_key.get(str(self.selection_combo.currentText() or ""), "random_per_text"),
                "character": self._selected_character,
                "emotion": self._selected_emotion,
            }
            voice = cli.update_voice(vid, patch)

            # Optional: sync current prompt_text back to selected asset note/prompt_text.
            if selected_aid and hasattr(self, "sync_prompt_to_asset_switch") and self.sync_prompt_to_asset_switch.isChecked():
                pt = (patch.get("prompt_text") or "").strip()
                if pt:
                    cli.update_asset(selected_aid, {"note": pt, "prompt_text": pt})
            return voice

        def _ok(_):
            self._toast_ok("已保存", vid)
            try:
                self.refresh_assets()
            except Exception:
                pass

        self._run(_do, _ok, lambda m: self._toast_err("保存失败", m))

    def compile_current_voice(self):
        vid = self._voice_id()
        if not vid:
            self._toast_warn("提示", "请先选择角色与情绪")
            return

        def _do():
            cli = self._v2_client()
            self._ensure_voice(cli, vid)
            return cli.compile_voice(vid, compile_all=bool(self.compile_all_switch.isChecked()))

        self._run(_do, lambda r: self._toast_ok("编译完成", f"{vid} compiled={len((r or {}).get('compiled') or [])}"), lambda m: self._toast_err("编译失败", m))

    def bind_selected_assets(self):
        vid = self._voice_id()
        if not vid:
            self._toast_warn("提示", "请先选择角色与情绪")
            return
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要绑定的 asset")
            return

        def _do():
            cli = self._v2_client()
            voice = self._ensure_voice(cli, vid)
            cur = voice.get("ref_asset_ids") or []
            cur = [str(x).strip() for x in cur if str(x).strip()]
            for aid in aids:
                if aid not in cur:
                    cur.append(aid)
            return cli.update_voice(vid, {"ref_asset_ids": cur})

        def _ok(_):
            self._toast_ok("已绑定", f"{vid} +{len(aids)}")
            try:
                self.refresh_assets()
            except Exception:
                pass

        self._run(_do, _ok, lambda m: self._toast_err("绑定失败", m))

    def unbind_selected_assets(self):
        vid = self._voice_id()
        if not vid:
            self._toast_warn("提示", "请先选择角色与情绪")
            return
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要解绑的 asset")
            return

        def _do():
            cli = self._v2_client()
            voice = cli.get_voice(vid)
            cur = voice.get("ref_asset_ids") or []
            cur = [str(x).strip() for x in cur if str(x).strip()]
            cur = [x for x in cur if x not in set(aids)]
            return cli.update_voice(vid, {"ref_asset_ids": cur})

        def _ok(_):
            self._toast_ok("已解绑", f"{vid} -{len(aids)}")
            try:
                self.refresh_assets()
            except Exception:
                pass

        self._run(_do, _ok, lambda m: self._toast_err("解绑失败", m))

    # -------- character --------
    def create_character(self):
        name, ok = QInputDialog.getText(self, "新建角色", "角色名（例如 Tom）:")
        if not ok:
            return
        ch = (name or "").strip()
        if not ch:
            return
        self._selected_character = ch
        self._selected_emotion = "default"

        def _do():
            cli = self._v2_client()
            self._ensure_voice(cli, f"{ch}#default")
            return True

        self._run(_do, lambda _: (self._toast_ok("已创建", f"{ch}#default"), self.refresh_all()), lambda m: self._toast_err("创建失败", m))

    # -------- drag & drop --------
    def eventFilter(self, obj, event):
        try:
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                md = event.mimeData()
                if md and md.hasUrls():
                    # Pre-check extension for nicer UX: only accept audio files.
                    for u in md.urls():
                        p = (u.toLocalFile() or "").strip()
                        if p and os.path.splitext(p)[1].lower() in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]:
                            event.acceptProposedAction()
                            return True
                event.ignore()
                return True
            if event.type() == QEvent.Drop:
                md = event.mimeData()
                if md and md.hasUrls():
                    paths: List[str] = []
                    for u in md.urls():
                        p = (u.toLocalFile() or "").strip()
                        if p:
                            paths.append(p)
                    if paths:
                        p0 = paths[0]
                        ext = os.path.splitext(p0)[1].lower()
                        if ext in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]:
                            self._upload_file = p0
                            self._set_upload_hint()
                            self._toast_ok("已选择文件", os.path.basename(p0))
                            event.acceptProposedAction()
                            return True
                        self._toast_warn("提示", "仅支持拖拽音频文件（wav/mp3/flac/m4a/ogg）")
                        event.ignore()
                        return True
                event.ignore()
                return True
        except Exception:
            return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        try:
            md = event.mimeData()
            if md and md.hasUrls():
                event.acceptProposedAction()
                return
        except Exception:
            pass
        event.ignore()

    def dragMoveEvent(self, event):
        try:
            md = event.mimeData()
            if md and md.hasUrls():
                event.acceptProposedAction()
                return
        except Exception:
            pass
        event.ignore()

    def dropEvent(self, event):
        try:
            md = event.mimeData()
            if not (md and md.hasUrls()):
                event.ignore()
                return

            paths: List[str] = []
            for u in md.urls():
                p = (u.toLocalFile() or "").strip()
                if p:
                    paths.append(p)
            if not paths:
                event.ignore()
                return

            p0 = paths[0]
            ext = os.path.splitext(p0)[1].lower()
            if ext not in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]:
                self._toast_warn("提示", "仅支持拖拽音频文件（wav/mp3/flac/m4a/ogg）")
                event.ignore()
                return

            self._upload_file = p0
            self._set_upload_hint()
            self._toast_ok("已选择文件", os.path.basename(p0))
            event.acceptProposedAction()
        except Exception as e:
            self._toast_err("拖拽失败", str(e))
            event.ignore()
