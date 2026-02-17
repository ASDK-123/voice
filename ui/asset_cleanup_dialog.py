from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QHeaderView, QVBoxLayout

from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    TableWidget,
    ToolButton,
)

from .v2_client import V2Client, V2HttpError
from .theme.tokens import Palette


CONTROL_H = 44
TOOL_BTN_SZ = 40
TABLE_ROW_H = 44


def _ui_font(size: int, *, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(int(size))
    if bold:
        f.setBold(True)
    return f


def _fmt_ts(ts: Any) -> str:
    try:
        t = int(ts or 0)
        if t <= 0:
            return ""
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts or "")


def _fmt_mb(n: Any) -> str:
    try:
        b = int(n or 0)
        return f"{b / (1024 * 1024):.1f} MB"
    except Exception:
        return ""


@dataclass
class _Row:
    asset_id: str
    character: str
    emotion: str
    language: str
    note: str
    created_at: str
    size_mb: str
    path: str


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


class UnusedAssetsCleanupDialog(QDialog):
    """
    Clean up unused ref assets (v2).

    All user-visible strings are Chinese.
    """

    def __init__(
        self,
        client_factory: Callable[[], V2Client],
        *,
        characters: Optional[List[str]] = None,
        default_character: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("清理未引用参考音频")
        self.resize(1040, 620)
        self.setMinimumSize(860, 520)

        self._client_factory = client_factory
        self._characters = [c for c in (characters or []) if str(c or "").strip()]
        self._default_character = (default_character or "").strip()

        self._tmp_dir = os.path.abspath("./data/ui_tmp")
        os.makedirs(self._tmp_dir, exist_ok=True)

        self._workers: List[QThread] = []
        self._items_raw: List[dict] = []
        self._rows: List[_Row] = []

        self.media_player = QMediaPlayer()

        self._init_ui()
        self._connect_signals()
        self.refresh()

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

    def _run(self, fn, on_ok, on_err):
        w = _Worker(fn)
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

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.setFont(_ui_font(12))

        title = SubtitleLabel("清理未引用参考音频", self)
        title.setFont(_ui_font(18, bold=True))
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(10)

        top.addWidget(BodyLabel("角色", self))
        self.character_combo = ComboBox(self)
        self.character_combo.setFixedHeight(CONTROL_H)
        self.character_combo.addItem("全部")
        for c in sorted(set(self._characters)):
            self.character_combo.addItem(c)
        if self._default_character:
            self.character_combo.setCurrentText(self._default_character)
        top.addWidget(self.character_combo)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索 asset_id / 备注 / 路径")
        self.search_edit.setFixedHeight(CONTROL_H)
        self.search_edit.setClearButtonEnabled(True)
        top.addWidget(self.search_edit, 1)

        self.refresh_btn = ToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setFixedSize(TOOL_BTN_SZ, TOOL_BTN_SZ)
        self.refresh_btn.setToolTip("刷新")
        top.addWidget(self.refresh_btn)

        root.addLayout(top)

        self.summary_label = BodyLabel("正在加载...", self)
        self.summary_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        root.addWidget(self.summary_label)

        self.table = TableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["选中", "角色", "情绪", "asset_id", "大小", "创建时间", "备注", "路径"])
        self.table.verticalHeader().setVisible(False)
        try:
            self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_H)
        except Exception:
            pass
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 210)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 150)
        self.table.setColumnWidth(6, 220)
        self.table.setColumnWidth(7, 320)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_select_all = PushButton("全选", self)
        self.btn_select_all.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_select_all)

        self.btn_select_none = PushButton("全不选", self)
        self.btn_select_none.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_select_none)

        bottom.addSpacing(16)

        self.btn_preview = PushButton("预览清理（不删除）", self)
        self.btn_preview.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_preview)

        self.btn_delete = PrimaryPushButton("删除选中", self)
        self.btn_delete.setFixedHeight(CONTROL_H)
        self.btn_delete.setIcon(FluentIcon.DELETE)
        bottom.addWidget(self.btn_delete)

        bottom.addStretch()

        self.btn_play = PushButton("试听选中", self)
        self.btn_play.setFixedHeight(CONTROL_H)
        self.btn_play.setIcon(FluentIcon.VOLUME)
        bottom.addWidget(self.btn_play)

        self.btn_close = PushButton("关闭", self)
        self.btn_close.setFixedHeight(CONTROL_H)
        bottom.addWidget(self.btn_close)

        root.addLayout(bottom)

    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh)
        self.search_edit.textChanged.connect(self._apply_filters)
        self.character_combo.currentTextChanged.connect(lambda _: self.refresh())
        self.btn_close.clicked.connect(self.close)
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_select_none.clicked.connect(lambda: self._set_all_checked(False))
        self.btn_preview.clicked.connect(lambda: self._run_cleanup(dry_run=True))
        self.btn_delete.clicked.connect(lambda: self._run_cleanup(dry_run=False))
        self.btn_play.clicked.connect(self._play_selected)

    def _set_all_checked(self, checked: bool):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _selected_asset_ids(self) -> List[str]:
        ids: List[str] = []
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            it_aid = self.table.item(r, 3)
            if not it0 or not it_aid:
                continue
            if it0.checkState() == Qt.Checked:
                aid = (it_aid.text() or "").strip()
                if aid:
                    ids.append(aid)
        return ids

    def refresh(self):
        self.summary_label.setText("正在加载未引用资源...")
        self.table.setRowCount(0)
        character = (self.character_combo.currentText() or "").strip()
        if character == "全部":
            character = ""

        def _do():
            cli = self._client_factory()
            return cli.list_unused_assets(character=character, kind="ref")

        def _ok(items: List[dict]):
            self._items_raw = items if isinstance(items, list) else []
            self._apply_filters()

        self._run(_do, _ok, lambda m: self._toast_err("加载失败", m))

    def _apply_filters(self):
        q = (self.search_edit.text() or "").strip().lower()
        items = self._items_raw or []
        if q:
            def _hit(x: dict) -> bool:
                s = " ".join(
                    [
                        str(x.get("asset_id") or ""),
                        str(x.get("note") or ""),
                        str(x.get("path") or ""),
                        str(x.get("emotion") or ""),
                        str(x.get("character") or ""),
                    ]
                ).lower()
                return q in s

            items = [x for x in items if isinstance(x, dict) and _hit(x)]

        rows: List[_Row] = []
        total_bytes = 0
        for x in items:
            if not isinstance(x, dict):
                continue
            try:
                total_bytes += int(x.get("size") or 0)
            except Exception:
                pass
            rows.append(
                _Row(
                    asset_id=str(x.get("asset_id") or ""),
                    character=str(x.get("character") or ""),
                    emotion=str(x.get("emotion") or ""),
                    language=str(x.get("language") or ""),
                    note=str(x.get("note") or ""),
                    created_at=_fmt_ts(x.get("created_at")),
                    size_mb=_fmt_mb(x.get("size")),
                    path=str(x.get("path") or ""),
                )
            )

        self._rows = rows
        self._render(rows)
        self.summary_label.setText(f"当前可清理 {len(rows)} 个参考音频，预计释放 {_fmt_mb(total_bytes)}")

    def _render(self, rows: List[_Row]):
        self.table.setRowCount(len(rows))
        f_id = QFont("Consolas", 12)
        f = _ui_font(12)
        for r, row in enumerate(rows):
            from PyQt5.QtWidgets import QTableWidgetItem

            it0 = QTableWidgetItem("")
            it0.setFlags(it0.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it0.setCheckState(Qt.Unchecked)
            it0.setTextAlignment(Qt.AlignCenter)
            it0.setFont(f)
            self.table.setItem(r, 0, it0)

            values = [
                row.character,
                row.emotion or "default",
                row.asset_id,
                row.size_mb,
                row.created_at,
                row.note,
                row.path,
            ]
            for col, v in enumerate(values, start=1):
                it = QTableWidgetItem(str(v))
                it.setFont(f_id if col == 3 else f)
                it.setTextAlignment(Qt.AlignCenter if col not in {7} else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(r, col, it)

    def _run_cleanup(self, *, dry_run: bool):
        aids = self._selected_asset_ids()
        if not aids:
            self._toast_err("提示", "请先勾选要清理的资源")
            return

        def _do():
            cli = self._client_factory()
            return cli.cleanup_assets(aids, dry_run=dry_run)

        def _ok(res: dict):
            if not isinstance(res, dict):
                self._toast_ok("完成", "操作已完成")
                return
            reclaimed = _fmt_mb(res.get("bytes_reclaimed"))
            skipped = res.get("skipped") or []
            if dry_run:
                self._toast_ok("预览完成", f"预计释放 {reclaimed}，跳过 {len(skipped)} 项")
            else:
                self._toast_ok("清理完成", f"已删除 {int(res.get('deleted') or 0)} 项，释放 {reclaimed}")
                self.refresh()

        self._run(_do, _ok, lambda m: self._toast_err("清理失败", m))

    def _play_selected(self):
        rows = {idx.row() for idx in self.table.selectedIndexes()}
        if not rows:
            self._toast_err("提示", "请先选中一行再试听")
            return
        r = sorted(rows)[0]
        it = self.table.item(r, 3)
        aid = (it.text() or "").strip() if it else ""
        if not aid:
            self._toast_err("提示", "未找到 asset_id")
            return

        def _do():
            cli = self._client_factory()
            return cli.download_asset_content(aid)

        def _ok(content: bytes):
            try:
                out = os.path.join(self._tmp_dir, f"preview_{aid}.wav")
                with open(out, "wb") as f:
                    f.write(content or b"")
                url = QUrl.fromLocalFile(out)
                self.media_player.setMedia(QMediaContent(url))
                self.media_player.play()
            except Exception as e:
                self._toast_err("试听失败", str(e))

        self._run(_do, _ok, lambda m: self._toast_err("试听失败", m))

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

    def closeEvent(self, event):
        self._shutdown_workers()
        super().closeEvent(event)
