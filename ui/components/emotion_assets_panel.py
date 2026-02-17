import os
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import QEvent, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QCursor, QFont
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    Action,
    BodyLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SearchLineEdit,
    SubtitleLabel,
    TableWidget,
    ToolButton,
)

from ..v2_client import V2Client, V2HttpError
from ..theme.tokens import Metrics, Palette, Radius, Spacing


CONTROL_H = Metrics.CONTROL_H
TOOL_BTN_SZ = Metrics.CONTROL_H
TABLE_ROW_H = Metrics.TABLE_ROW_H


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


class EmotionAssetsPanel(QWidget):
    """
    Reusable assets panel for "reference audios" (v2 assets) + binding to a voice (voice.ref_asset_ids).

    Important:
    - V2Client is blocking; all calls must run in worker threads.
    - This panel is "context-bound": set_context(character, emotion, voice_id, ref_asset_ids=...) before use.
    """

    ref_pool_changed = pyqtSignal(str, object)  # voice_id, ref_asset_ids(list)
    selected_asset_changed = pyqtSignal(object)  # asset dict | None
    assets_stats_changed = pyqtSignal(int, int)  # total, linked

    def __init__(self, client_factory: Callable[[], V2Client], parent=None):
        super().__init__(parent)
        self._client_factory = client_factory
        self._workers: List[QThread] = []

        self.character = ""
        self.emotion = "default"
        self.voice_id = ""

        self._upload_file = ""
        self._assets_items: List[dict] = []
        self._assets_view_items: List[dict] = []
        self._selected_asset_id = ""
        self._play_state_by_asset: Dict[str, str] = {}
        self._ref_asset_ids: List[str] = []
        self._manage_voice_binding_locally = False

        self._tmp_dir = os.path.abspath("./data/ui_tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)
        self.media_player = QMediaPlayer()
        try:
            self.media_player.stateChanged.connect(self._on_media_state_changed)
        except Exception:
            pass

        self._init_ui()

    def set_context(
        self,
        *,
        character: str,
        emotion: str,
        voice_id: str,
        ref_asset_ids: Optional[List[str]] = None,
    ):
        self.character = (character or "").strip()
        self.emotion = (emotion or "").strip() or "default"
        self.voice_id = (voice_id or "").strip()
        self._ref_asset_ids = [str(x or "").strip() for x in (ref_asset_ids or []) if str(x or "").strip()]
        try:
            self.emotion_edit.setText(self.emotion)
        except Exception:
            pass
        self._set_enabled(bool(self.character and self.voice_id))
        self.refresh_assets()

    def set_manage_voice_binding_locally(self, enabled: bool):
        self._manage_voice_binding_locally = bool(enabled)

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
        msg = self._friendly_error_message(content)
        InfoBar.error(
            title=title,
            content=msg,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def _friendly_error_message(self, content: str) -> str:
        raw = str(content or "").strip()
        text = raw.lower()
        if ("connection" in text) or ("timeout" in text) or ("http" in text and "failed" in text):
            return f"{raw}。建议：检查 API Host/Port 与服务状态。"
        if ("not found" in text) or ("no such file" in text) or ("路径不存在" in raw):
            return f"{raw}。建议：该资源本地路径缺失，可重新下载或重新上传。"
        if ("decode" in text) or ("format" in text) or ("codec" in text):
            return f"{raw}。建议：转为 wav 后重新上传。"
        return raw

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

    def _set_enabled(self, enabled: bool):
        for w in [
            self.bind_btn,
            self.unbind_btn,
            self.play_btn,
            self.more_btn,
            self.choose_file_btn,
            self.upload_btn,
            self.save_note_btn,
            self.asset_search,
            self.asset_filter_linked,
            self.asset_filter_language,
            self.asset_table,
        ]:
            try:
                w.setEnabled(bool(enabled))
            except Exception:
                pass

    @staticmethod
    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(hi), int(v)))

    def _apply_asset_table_columns(self, width_hint: int = 0):
        try:
            avail = int(width_hint or 0)
            if avail <= 0:
                avail = int(self.asset_table.viewport().width() or 0)
            if avail <= 0:
                avail = int(self.width() or 0)
            avail = max(520, avail)
            note_w = self._clamp(int(avail * 0.24), 160, 320)
            path_w = self._clamp(int(avail * 0.30), 200, 420)
            self.asset_table.setColumnWidth(2, note_w)
            self.asset_table.setColumnWidth(4, path_w)
        except Exception:
            pass

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)

        header = QHBoxLayout()
        header.setSpacing(Spacing.SM)
        title_right = SubtitleLabel("参考音频库（assets）")
        title_right.setFont(QFont("", 18, QFont.Bold))
        header.addWidget(title_right)
        header.addStretch()

        self.bind_btn = PrimaryPushButton("绑定到当前 voice")
        self.bind_btn.setFixedHeight(CONTROL_H)
        self.bind_btn.setIcon(FluentIcon.LINK)
        self.bind_btn.clicked.connect(self.bind_selected_assets)
        header.addWidget(self.bind_btn)

        self.unbind_btn = PushButton("解绑")
        self.unbind_btn.setFixedHeight(CONTROL_H)
        self.unbind_btn.setIcon(FluentIcon.CLOSE)
        self.unbind_btn.clicked.connect(self.unbind_selected_assets)
        header.addWidget(self.unbind_btn)

        self.play_btn = PushButton("试听")
        self.play_btn.setFixedHeight(CONTROL_H)
        self.play_btn.setIcon(FluentIcon.VOLUME)
        self.play_btn.clicked.connect(self.play_selected_asset)
        header.addWidget(self.play_btn)

        self.more_btn = ToolButton(FluentIcon.MORE)
        self.more_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.more_btn.setToolTip("更多操作")
        self.more_btn.clicked.connect(self._show_more_menu)
        header.addWidget(self.more_btn)
        root.addLayout(header)

        up = QHBoxLayout()
        up.setSpacing(Spacing.SM)
        up.addWidget(BodyLabel("语言"))
        self.lang_combo = ComboBox()
        self.lang_combo.addItems(["zh", "en", "ja", "ko"])
        self.lang_combo.setCurrentText("zh")
        self.lang_combo.setFixedHeight(CONTROL_H)
        up.addWidget(self.lang_combo)
        up.addSpacing(Spacing.MD)
        up.addWidget(BodyLabel("情绪标签"))
        self.emotion_edit = LineEdit()
        self.emotion_edit.setReadOnly(True)
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
        root.addLayout(up)

        note_row = QHBoxLayout()
        note_row.setSpacing(Spacing.SM)
        note_row.addWidget(BodyLabel("备注"))
        self.note_edit = LineEdit()
        self.note_edit.setPlaceholderText("可选，用于搜索")
        self.note_edit.setFixedHeight(CONTROL_H)
        note_row.addWidget(self.note_edit, 1)
        self.save_note_btn = PushButton("保存备注")
        self.save_note_btn.setFixedHeight(CONTROL_H)
        self.save_note_btn.clicked.connect(self.save_selected_asset_note)
        note_row.addWidget(self.save_note_btn)
        root.addLayout(note_row)

        self.file_label = BodyLabel("未选择文件（也可以把音频文件拖拽到窗口中）")
        self.file_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        self.file_label.setWordWrap(False)
        self.file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.file_label.setFixedHeight(22)
        root.addWidget(self.file_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(Spacing.SM)
        self.asset_search = SearchLineEdit(self)
        self.asset_search.setPlaceholderText("搜索 备注/路径/资源ID")
        self.asset_search.setFixedHeight(CONTROL_H)
        self.asset_search.textChanged.connect(self._apply_asset_filters)
        filter_row.addWidget(self.asset_search, 1)
        self.filter_toggle_btn = PushButton("展开筛选")
        self.filter_toggle_btn.setFixedHeight(CONTROL_H)
        self.filter_toggle_btn.clicked.connect(self._toggle_filter_extras)
        filter_row.addWidget(self.filter_toggle_btn)
        root.addLayout(filter_row)

        self.filter_extra_widget = QWidget(self)
        filter_extra_row = QHBoxLayout(self.filter_extra_widget)
        filter_extra_row.setContentsMargins(0, 0, 0, 0)
        filter_extra_row.setSpacing(Spacing.SM)
        self.asset_filter_linked = ComboBox()
        self.asset_filter_linked.addItems(["全部", "已绑定", "未绑定"])
        self.asset_filter_linked.setFixedHeight(CONTROL_H)
        self.asset_filter_linked.currentTextChanged.connect(lambda _: self._apply_asset_filters())
        filter_extra_row.addWidget(self.asset_filter_linked)

        self.asset_filter_language = ComboBox()
        self.asset_filter_language.addItems(["全部", "zh", "en", "ja", "ko"])
        self.asset_filter_language.setFixedHeight(CONTROL_H)
        self.asset_filter_language.currentTextChanged.connect(lambda _: self._apply_asset_filters())
        filter_extra_row.addWidget(self.asset_filter_language)
        filter_extra_row.addStretch()
        self.filter_extra_widget.setVisible(False)
        root.addWidget(self.filter_extra_widget)

        self.asset_table = TableWidget()
        self.asset_table.setColumnCount(7)
        self.asset_table.setHorizontalHeaderLabels(["资源ID", "语言", "备注", "时间", "路径", "绑定", "操作"])
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
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._apply_asset_table_columns(width_hint=self.width())
        root.addWidget(self.asset_table, 1)

        for w in [self, self.file_label, self.asset_table]:
            try:
                w.setAcceptDrops(True)
                w.installEventFilter(self)
            except Exception:
                pass

        self._set_enabled(False)
        self.setStyleSheet(
            f"""
            QWidget {{
                font-family: 'Segoe UI', 'PingFang SC', sans-serif;
            }}
            QTableView {{
                border: 1px solid {Palette.BORDER};
                border-radius: {Radius.PANEL}px;
                background: {Palette.CARD};
                alternate-background-color: #FAFBFC;
                gridline-color: {Palette.BORDER};
            }}
            QTableView::item:selected {{
                background: #EFF6FF;
                color: {Palette.TEXT_PRIMARY};
            }}
            QLineEdit {{
                border: 1px solid {Palette.BORDER};
                border-radius: {Radius.CONTROL}px;
                padding: 0 10px;
                background: {Palette.CARD};
            }}
            """
        )

    def _toggle_filter_extras(self):
        vis = bool(self.filter_extra_widget.isVisible())
        self.filter_extra_widget.setVisible(not vis)
        self.filter_toggle_btn.setText("收起筛选" if not vis else "展开筛选")

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                md = event.mimeData()
                if md and md.hasUrls():
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
                    for u in md.urls():
                        p = (u.toLocalFile() or "").strip()
                        if p:
                            ext = os.path.splitext(p)[1].lower()
                            if ext in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]:
                                self._upload_file = p
                                self._set_upload_hint()
                                self._toast_ok("已选择文件", os.path.basename(p))
                                event.acceptProposedAction()
                                return True
                event.ignore()
                return True
        except Exception:
            return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)

    def _set_upload_hint(self):
        if self._upload_file and os.path.exists(self._upload_file):
            self.file_label.setText(self._upload_file)
            self.file_label.setStyleSheet("")
        else:
            self.file_label.setText("未选择文件（也可以把音频文件拖拽到窗口中）")
            self.file_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")

    def _client(self) -> V2Client:
        return self._client_factory()

    def refresh_assets(self):
        if not self.character:
            self.asset_table.setRowCount(0)
            self.assets_stats_changed.emit(0, 0)
            return

        def _do():
            cli = self._client()
            return cli.list_assets(character=self.character, emotion=self.emotion, language="", kind="ref")

        self._run(_do, self._set_assets_table, lambda m: self._toast_err("加载 assets 失败", m))

    def _set_assets_table(self, items: List[dict]):
        src_items = [dict(it) for it in (items or []) if isinstance(it, dict)]
        if self._manage_voice_binding_locally:
            bound = set(self._ref_asset_ids or [])
            for it in src_items:
                aid = str(it.get("asset_id") or "").strip()
                it["linked"] = bool(aid and aid in bound)
                it["ref_count"] = 1 if it["linked"] else 0
        self._assets_items = src_items
        linked_count = 0
        for it in self._assets_items:
            if isinstance(it, dict) and bool(it.get("linked")):
                linked_count += 1
        self.assets_stats_changed.emit(len(self._assets_items), linked_count)
        valid_ids = {str((it or {}).get("asset_id") or "").strip() for it in self._assets_items}
        for aid in list(self._play_state_by_asset.keys()):
            if aid not in valid_ids:
                self._play_state_by_asset.pop(aid, None)
        self._apply_asset_filters()

    def _apply_asset_filters(self):
        items = list(self._assets_items or [])
        q = (self.asset_search.text() or "").strip().lower()
        link_filter = str(self.asset_filter_linked.currentText() or "全部")
        lang_filter = str(self.asset_filter_language.currentText() or "全部")

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
        from PyQt5.QtWidgets import QTableWidgetItem

        items = items or []
        prev_selected = set(self._selected_asset_ids())
        self._assets_view_items = list(items)
        self.asset_table.blockSignals(True)
        self.asset_table.setRowCount(len(items))
        font_id = QFont("Consolas", 12)
        font2 = QFont("", 12)
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
                item = QTableWidgetItem(str(v))
                item.setFont(font_id if col == 0 else font2)
                item.setTextAlignment(Qt.AlignCenter if col != 4 else Qt.AlignLeft | Qt.AlignVCenter)
                if col == 4:
                    item.setToolTip(str(v))
                self.asset_table.setItem(row, col, item)
            btn = PushButton()
            btn.setFixedHeight(CONTROL_H)
            state = self._play_state_by_asset.get(aid, "idle")
            if state == "loading":
                btn.setText("加载中...")
                btn.setEnabled(False)
            elif state == "playing":
                btn.setText("播放中")
                btn.setEnabled(True)
            elif state == "error":
                btn.setText("重试试听")
                btn.setEnabled(True)
            else:
                btn.setText("试听")
                btn.setEnabled(True)
            btn.clicked.connect(lambda _=False, x=aid, r=row: (self.asset_table.selectRow(r), self.play_asset(x)))
            self.asset_table.setCellWidget(row, 6, btn)
        self.asset_table.blockSignals(False)
        if prev_selected:
            for row, it in enumerate(items):
                aid = str((it or {}).get("asset_id") or "").strip()
                if aid in prev_selected:
                    self.asset_table.selectRow(row)
                    break
        self._on_asset_selection_changed()

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

    def _normalized_ref_pool(self, ref_asset_ids: object) -> List[str]:
        if not isinstance(ref_asset_ids, list):
            return []
        out: List[str] = []
        seen = set()
        for x in ref_asset_ids:
            aid = str(x or "").strip()
            if not aid or aid in seen:
                continue
            seen.add(aid)
            out.append(aid)
        return out

    def _emit_local_ref_pool(self, ref_asset_ids: object):
        cur = self._normalized_ref_pool(ref_asset_ids)
        self._ref_asset_ids = list(cur)
        self.ref_pool_changed.emit(self.voice_id, cur)
        self.refresh_assets()

    def _on_asset_selection_changed(self):
        try:
            rows = {idx.row() for idx in self.asset_table.selectedIndexes()}
            if len(rows) != 1:
                self._selected_asset_id = ""
                self.selected_asset_changed.emit(None)
                return
            row = list(rows)[0]
            it = self._assets_view_items[row] if 0 <= row < len(self._assets_view_items) else {}
            if not isinstance(it, dict):
                it = {}
            aid = str(it.get("asset_id") or "").strip()
            note = str(it.get("note") or "").strip()
            self._selected_asset_id = aid
            try:
                self.note_edit.blockSignals(True)
                self.note_edit.setText(note)
            finally:
                self.note_edit.blockSignals(False)
            self.selected_asset_changed.emit(dict(it))
        except Exception:
            return

    def _show_more_menu(self):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.CLOSE, "从当前 voice 解绑", self, triggered=self.unbind_selected_assets))
        menu.addAction(Action(FluentIcon.DELETE, "删除选中资源", self, triggered=self.delete_selected_assets))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.COPY, "复制资源ID", self, triggered=self._copy_selected_asset_id))
        menu.addAction(Action(FluentIcon.FOLDER, "打开资源位置", self, triggered=self._open_selected_asset_location))
        menu.exec_(QCursor.pos())

    def _show_assets_context_menu(self, pos):
        try:
            idx = self.asset_table.indexAt(pos)
            if idx.isValid():
                self.asset_table.selectRow(idx.row())
        except Exception:
            pass

        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.LINK, "绑定到当前 voice", self, triggered=self.bind_selected_assets))
        menu.addAction(Action(FluentIcon.CLOSE, "从当前 voice 解绑", self, triggered=self.unbind_selected_assets))
        menu.addAction(Action(FluentIcon.VOLUME, "试听", self, triggered=self.play_selected_asset))
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
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择参考音频",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件(*)",
        )
        if p:
            self._upload_file = p
            self._set_upload_hint()

    def upload_ref_audio(self):
        if not self.character or not self.voice_id:
            self._toast_warn("提示", "请先选择一个 voice（角色#情绪）")
            return
        fp = self._upload_file
        if not fp or not os.path.exists(fp):
            self._toast_warn("提示", "请先选择要上传的音频文件")
            return
        lang = str(self.lang_combo.currentText() or "zh").strip() or "zh"
        note = (self.note_edit.text() or "").strip()

        def _do():
            cli = self._client()
            meta = cli.upload_asset(file_path=fp, character=self.character, emotion=self.emotion, language=lang, note=note)
            aid = str((meta or {}).get("asset_id") or "").strip()
            if aid:
                if self._manage_voice_binding_locally:
                    cur = self._normalized_ref_pool(list(self._ref_asset_ids or []))
                    if aid not in cur:
                        cur.append(aid)
                else:
                    # Best-effort: bind the new asset to current voice.
                    voice = cli.get_voice(self.voice_id)
                    cur = voice.get("ref_asset_ids") or []
                    cur = [str(x).strip() for x in cur if str(x).strip()]
                    if aid not in cur:
                        cur.append(aid)
                        cli.update_voice(self.voice_id, {"ref_asset_ids": cur})
                return {"meta": meta, "ref_asset_ids": cur}
            return {"meta": meta, "ref_asset_ids": []}

        def _ok(res: dict):
            meta = (res or {}).get("meta") if isinstance(res, dict) else {}
            aid = str((meta or {}).get("asset_id") or "")
            self._toast_ok("上传成功", f"asset_id={aid}" if aid else "已上传")
            self._upload_file = ""
            self._set_upload_hint()
            if isinstance(res, dict):
                if self._manage_voice_binding_locally:
                    self._emit_local_ref_pool(res.get("ref_asset_ids") or [])
                else:
                    self.ref_pool_changed.emit(self.voice_id, res.get("ref_asset_ids") or [])
                    self.refresh_assets()

        self._run(_do, _ok, lambda m: self._toast_err("上传失败", m))

    def save_selected_asset_note(self):
        aid = (self._selected_asset_id or "").strip()
        if not aid:
            aids = self._selected_asset_ids()
            aid = aids[0] if aids else ""
        if not aid:
            self._toast_warn("提示", "请先选择一个参考音频")
            return

        note = (self.note_edit.text() or "").strip()
        if not note:
            self._toast_warn("提示", "备注不能为空")
            return

        def _do():
            cli = self._client()
            return cli.update_asset(aid, {"note": note, "prompt_text": note})

        def _ok(_):
            self._toast_ok("已保存备注", aid)
            self.refresh_assets()

        self._run(_do, _ok, lambda m: self._toast_err("保存备注失败", m))

    def _set_play_state(self, asset_id: str, state: str):
        aid = str(asset_id or "").strip()
        if not aid:
            return
        self._play_state_by_asset[aid] = state
        self._render_assets_table(list(self._assets_view_items or []))

    def _on_media_state_changed(self, state):
        try:
            if int(state) != int(QMediaPlayer.StoppedState):
                return
        except Exception:
            return
        dirty = False
        for aid, s in list(self._play_state_by_asset.items()):
            if s == "playing":
                self._play_state_by_asset[aid] = "idle"
                dirty = True
        if dirty:
            self._render_assets_table(list(self._assets_view_items or []))

    def _preview_cache_path(self, asset_id: str, source_path: str = "") -> str:
        aid = str(asset_id or "").strip()
        ext = os.path.splitext(str(source_path or "").strip())[1].lower()
        if ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
            ext = ".wav"
        return os.path.join(self._tmp_dir, f"preview_{aid}{ext}")

    def play_asset(self, asset_id: str):
        aid = str(asset_id or "").strip()
        if not aid:
            self._toast_warn("提示", "无效的资源ID")
            return
        self._set_play_state(aid, "loading")

        def _do():
            cli = self._client()
            meta = cli.get_asset_meta(aid)
            p = str((meta or {}).get("path") or "").strip()
            if p and os.path.exists(p):
                return p
            out = self._preview_cache_path(aid, p)
            if os.path.exists(out):
                return out
            data = cli.download_asset_content(aid)
            with open(out, "wb") as f:
                f.write(data)
            return out

        def _ok(path: str):
            self.media_player.stop()
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self.media_player.play()
            self._set_play_state(aid, "playing")
            self._toast_ok("试听", os.path.basename(path))

        def _err(msg: str):
            self._set_play_state(aid, "error")
            self._toast_err("试听失败", msg)

        self._run(_do, _ok, _err)

    def play_selected_asset(self):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要试听的 asset")
            return
        self.play_asset(aids[0])

    def delete_selected_assets(self):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要删除的 asset")
            return
        ret = QMessageBox.question(
            self,
            "确认删除资源",
            f"确定删除选中的 {len(aids)} 个资源吗？\n将会先从当前 voice 解绑。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        def _do():
            cli = self._client()
            if self._manage_voice_binding_locally:
                cur = self._normalized_ref_pool(list(self._ref_asset_ids or []))
                cur2 = [x for x in cur if x not in set(aids)]
            else:
                # Best-effort unbind before delete
                try:
                    voice = cli.get_voice(self.voice_id)
                    cur = voice.get("ref_asset_ids") or []
                    cur = [str(x).strip() for x in cur if str(x).strip()]
                    cur2 = [x for x in cur if x not in set(aids)]
                    if cur2 != cur:
                        cli.update_voice(self.voice_id, {"ref_asset_ids": cur2})
                except Exception:
                    cur2 = []
            for aid in aids:
                cli.delete_asset(aid)
            return {"deleted": len(aids), "ref_asset_ids": cur2}

        def _ok(res: dict):
            n = int((res or {}).get("deleted") or 0)
            for aid in aids:
                self._play_state_by_asset.pop(str(aid), None)
            self._toast_ok("已删除", f"{n} 个 asset")
            if self._manage_voice_binding_locally:
                self._emit_local_ref_pool((res or {}).get("ref_asset_ids") or [])
            else:
                self.ref_pool_changed.emit(self.voice_id, (res or {}).get("ref_asset_ids") or [])
                self.refresh_assets()

        self._run(_do, _ok, lambda m: self._toast_err("删除失败", m))

    def bind_selected_assets(self):
        if not self.voice_id:
            self._toast_warn("提示", "请先选择一个 voice（角色#情绪）")
            return
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要绑定的 asset")
            return

        def _do():
            if self._manage_voice_binding_locally:
                cur = self._normalized_ref_pool(list(self._ref_asset_ids or []))
            else:
                cli = self._client()
                voice = cli.get_voice(self.voice_id)
                cur = voice.get("ref_asset_ids") or []
                cur = [str(x).strip() for x in cur if str(x).strip()]
            for aid in aids:
                if aid not in cur:
                    cur.append(aid)
            if not self._manage_voice_binding_locally:
                cli.update_voice(self.voice_id, {"ref_asset_ids": cur})
            return cur

        def _ok(cur: list):
            self._toast_ok("已绑定", f"{self.voice_id} +{len(aids)}")
            if self._manage_voice_binding_locally:
                self._emit_local_ref_pool(cur or [])
            else:
                self.ref_pool_changed.emit(self.voice_id, cur or [])
                self.refresh_assets()

        self._run(_do, _ok, lambda m: self._toast_err("绑定失败", m))

    def unbind_selected_assets(self):
        if not self.voice_id:
            self._toast_warn("提示", "请先选择一个 voice（角色#情绪）")
            return
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_warn("提示", "请先选择要解绑的 asset")
            return

        def _do():
            if self._manage_voice_binding_locally:
                cur = self._normalized_ref_pool(list(self._ref_asset_ids or []))
            else:
                cli = self._client()
                voice = cli.get_voice(self.voice_id)
                cur = voice.get("ref_asset_ids") or []
                cur = [str(x).strip() for x in cur if str(x).strip()]
            cur = [x for x in cur if x not in set(aids)]
            if not self._manage_voice_binding_locally:
                cli.update_voice(self.voice_id, {"ref_asset_ids": cur})
            return cur

        def _ok(cur: list):
            self._toast_ok("已解绑", f"{self.voice_id} -{len(aids)}")
            if self._manage_voice_binding_locally:
                self._emit_local_ref_pool(cur or [])
            else:
                self.ref_pool_changed.emit(self.voice_id, cur or [])
                self.refresh_assets()

        self._run(_do, _ok, lambda m: self._toast_err("解绑失败", m))

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

    def resizeEvent(self, event):
        try:
            self._apply_asset_table_columns(width_hint=int(event.size().width()))
        except Exception:
            pass
        super().resizeEvent(event)
