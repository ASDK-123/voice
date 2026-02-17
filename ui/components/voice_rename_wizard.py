from __future__ import annotations

from typing import Any, Dict, List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class VoiceRenameWizard(QDialog):
    """
    Batch rename dialog for voice_id schema: {character}#{emotion}.

    Input voices item minimal keys:
    - name (voice_id)
    - character (optional)
    - emotion (optional)
    """

    def __init__(self, voices: List[dict], parent=None):
        super().__init__(parent)
        self._voices = voices or []
        self._accepted_changes: List[Dict[str, str]] = []
        self._preview_changes: List[Dict[str, str]] = []
        self._updating = False
        self._invalid_chars = set("#\\/\n\r\t")
        self._init_ui()
        self._load_rows()
        self._recompute()

    def accepted_changes(self) -> List[Dict[str, str]]:
        return list(self._accepted_changes)

    def _init_ui(self):
        self.setWindowTitle("批量改名向导")
        self.resize(1020, 620)

        root = QVBoxLayout(self)
        tip = QLabel(
            "请修改“新角色/新情绪”。新 voice_id 会自动计算为 角色#情绪。\n"
            "规则：角色必填；情绪为空时自动 default；禁止包含 #、斜杠或换行。"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["旧 voice_id", "新角色", "新情绪", "新 voice_id", "校验状态"])
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 280)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        self.buttons = QDialogButtonBox(self)
        self.apply_btn = self.buttons.addButton("应用改名", QDialogButtonBox.AcceptRole)
        self.cancel_btn = self.buttons.addButton("取消", QDialogButtonBox.RejectRole)
        self.apply_btn.clicked.connect(self._on_accept)
        self.cancel_btn.clicked.connect(self.reject)
        root.addWidget(self.buttons)

    def _parse_voice_id(self, voice_id: str) -> tuple[str, str]:
        vid = str(voice_id or "").strip()
        if "#" in vid:
            ch, emo = vid.split("#", 1)
            return str(ch or "").strip(), str(emo or "").strip() or "default"
        return vid, "default"

    def _compose_voice_id(self, character: str, emotion: str) -> str:
        ch = str(character or "").strip()
        emo = str(emotion or "").strip() or "default"
        if not ch:
            return ""
        return f"{ch}#{emo}"

    def _row_text(self, row: int, col: int) -> str:
        it = self.table.item(row, col)
        return str(it.text() if it else "").strip()

    def _set_item_text(self, row: int, col: int, text: str, editable: bool):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, col, item)
        item.setText(str(text or ""))
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)

    def _set_row_bg(self, row: int, color: QColor | None):
        for col in range(self.table.columnCount()):
            it = self.table.item(row, col)
            if it is None:
                it = QTableWidgetItem("")
                self.table.setItem(row, col, it)
            it.setBackground(color if color is not None else QColor(255, 255, 255, 0))

    def _load_rows(self):
        self._updating = True
        self.table.setRowCount(len(self._voices))
        for r, voice in enumerate(self._voices):
            old_id = str((voice or {}).get("name") or "").strip()
            ch = str((voice or {}).get("character") or "").strip()
            emo = str((voice or {}).get("emotion") or "").strip()
            if not old_id:
                old_id = self._compose_voice_id(ch, emo) or ""
            if not ch:
                ch, _ = self._parse_voice_id(old_id)
            if not emo:
                _, emo = self._parse_voice_id(old_id)
            emo = emo or "default"
            self._set_item_text(r, 0, old_id, editable=False)
            self._set_item_text(r, 1, ch, editable=True)
            self._set_item_text(r, 2, emo, editable=True)
            self._set_item_text(r, 3, old_id, editable=False)
            self._set_item_text(r, 4, "", editable=False)
        self._updating = False

    def _on_item_changed(self, _item: QTableWidgetItem):
        if self._updating:
            return
        self._recompute()

    def _recompute(self):
        self._updating = True
        rows = self.table.rowCount()
        candidates: List[Dict[str, Any]] = []
        counts: Dict[str, int] = {}

        for r in range(rows):
            old_id = self._row_text(r, 0)
            ch = self._row_text(r, 1)
            emo_raw = self._row_text(r, 2)
            emo = emo_raw or "default"
            if not emo_raw:
                self._set_item_text(r, 2, emo, editable=True)
            new_id = self._compose_voice_id(ch, emo)

            err = ""
            if not ch:
                err = "角色不能为空"
            elif any(c in self._invalid_chars for c in ch):
                err = "角色含非法字符"
            elif any(c in self._invalid_chars for c in emo):
                err = "情绪含非法字符"

            if new_id:
                counts[new_id] = counts.get(new_id, 0) + 1

            candidates.append(
                {
                    "row": r,
                    "old_id": old_id,
                    "new_character": ch,
                    "new_emotion": emo,
                    "new_voice_id": new_id,
                    "error": err,
                }
            )

        has_error = False
        changes: List[Dict[str, str]] = []
        for it in candidates:
            r = int(it["row"])
            old_id = str(it["old_id"])
            new_id = str(it["new_voice_id"])
            err = str(it["error"] or "")
            if not err and new_id and counts.get(new_id, 0) > 1:
                err = "本批次 voice_id 冲突"

            if err:
                has_error = True
                self._set_item_text(r, 3, new_id or "<无效>", editable=False)
                self._set_item_text(r, 4, f"错误: {err}", editable=False)
                self._set_row_bg(r, QColor(255, 235, 238))
                continue

            if new_id != old_id:
                changes.append(
                    {
                        "old_voice_id": old_id,
                        "new_character": str(it["new_character"]),
                        "new_emotion": str(it["new_emotion"]) or "default",
                        "new_voice_id": new_id,
                    }
                )
                self._set_item_text(r, 4, "可应用", editable=False)
            else:
                self._set_item_text(r, 4, "未变更", editable=False)
            self._set_item_text(r, 3, new_id, editable=False)
            self._set_row_bg(r, QColor(232, 245, 233))

        self._preview_changes = changes
        self.apply_btn.setEnabled((not has_error) and len(changes) > 0)
        self._updating = False

    def _on_accept(self):
        if not self.apply_btn.isEnabled():
            return
        self._accepted_changes = list(self._preview_changes)
        self.accept()
