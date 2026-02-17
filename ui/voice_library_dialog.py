from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SegmentedWidget,
    TableWidget,
    ToolButton,
    RoundMenu,
)

from core.config_manager import ConfigManager
from core.models import VoiceConfig
from .v2_client import V2Client, V2Config


@dataclass(frozen=True)
class _VoiceRow:
    voice_id: str
    character: str
    emotion: str
    mode: str


def _parse_voice_id(voice_id: str) -> Tuple[str, str]:
    vid = (voice_id or "").strip()
    if not vid:
        return "", "default"
    if "#" in vid:
        character, emotion = vid.split("#", 1)
        character = (character or "").strip()
        emotion = (emotion or "").strip() or "default"
        return character, emotion
    return vid, "default"


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _tokenize(query: str) -> List[str]:
    q = (query or "").strip()
    if not q:
        return []
    # Space-separated tokens is enough (no NLP).
    parts = [p.strip() for p in q.replace("\t", " ").split(" ") if p.strip()]
    return [_norm(p) for p in parts if p]


def _match_tokens(haystack: str, tokens: List[str]) -> bool:
    h = _norm(haystack)
    return all(t in h for t in tokens)


class VoiceLibraryDialog(QDialog):
    """
    Voice Library dialog: searchable, grouped by character/emotion.
    All user-visible strings are Chinese.
    """

    SCOPE_RECENT = "最近"
    SCOPE_FAVORITE = "收藏"
    SCOPE_ALL = "全部"

    OPEN_LABEL = "打开声音库..."

    def __init__(
        self,
        config_manager: ConfigManager,
        voices: Dict[str, VoiceConfig],
        *,
        preselect_voice_id: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("声音库")
        self.resize(860, 520)
        self.setMinimumSize(720, 460)

        self.config_manager = config_manager
        self.voices = voices or {}
        self.preselect_voice_id = (preselect_voice_id or "").strip()

        # state
        self._all_rows: List[_VoiceRow] = []
        self._by_character: Dict[str, List[_VoiceRow]] = {}
        self._visible_characters: List[str] = []
        self._selected_voice_id: str = ""
        self._selected_character: str = ""
        self._selected_emotion: str = ""

        self._build_index()
        self._init_ui()
        self._connect_signals()
        self._load_initial_selection()

    @classmethod
    def pick_voice_id(
        cls,
        config_manager: ConfigManager,
        voices: Dict[str, VoiceConfig],
        *,
        preselect_voice_id: str = "",
        parent: Optional[QWidget] = None,
    ) -> Optional[str]:
        dlg = cls(config_manager, voices, preselect_voice_id=preselect_voice_id, parent=parent)
        if dlg.exec_() == QDialog.Accepted:
            return dlg.selected_voice_id()
        return None

    def selected_voice_id(self) -> str:
        return (self._selected_voice_id or "").strip()

    def _build_index(self) -> None:
        rows: List[_VoiceRow] = []
        byc: Dict[str, List[_VoiceRow]] = {}

        for voice_id, vc in (self.voices or {}).items():
            vid = (voice_id or "").strip()
            if not vid:
                continue
            character, emotion = _parse_voice_id(vid)
            mode = str(getattr(vc, "mode", "") or "")
            r = _VoiceRow(voice_id=vid, character=character, emotion=emotion, mode=mode)
            rows.append(r)
            byc.setdefault(character, []).append(r)

        # Stable ordering inside each character: default first, then emotion name.
        for character, lst in byc.items():
            def _key(x: _VoiceRow):
                return (0 if _norm(x.emotion) == "default" else 1, _norm(x.emotion), _norm(x.voice_id))

            lst.sort(key=_key)

        self._all_rows = rows
        self._by_character = byc

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Top bar
        top = QHBoxLayout()
        top.setSpacing(10)

        self.seg_scope = SegmentedWidget(self)
        self.seg_scope.addItem(self.SCOPE_RECENT, self.SCOPE_RECENT)
        self.seg_scope.addItem(self.SCOPE_FAVORITE, self.SCOPE_FAVORITE)
        self.seg_scope.addItem(self.SCOPE_ALL, self.SCOPE_ALL)
        self.seg_scope.setCurrentItem(self.SCOPE_ALL)
        top.addWidget(self.seg_scope)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索角色/情绪/voice_id")
        self.search_edit.setClearButtonEnabled(True)
        top.addWidget(self.search_edit, 1)

        self.label_selected = BodyLabel("未选择", self)
        self.label_selected.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        top.addWidget(self.label_selected)

        self.btn_clear = ToolButton(self)
        self.btn_clear.setIcon(FluentIcon.CLOSE)
        self.btn_clear.setToolTip("清除选择")
        top.addWidget(self.btn_clear)

        self.btn_refresh = ToolButton(self)
        self.btn_refresh.setIcon(FluentIcon.SYNC)
        self.btn_refresh.setToolTip("刷新 voices")
        top.addWidget(self.btn_refresh)

        root.addLayout(top)

        # Main splitter
        self.splitter = QSplitter(Qt.Horizontal, self)

        self.list_characters = ListWidget(self)
        self.list_characters.setMinimumWidth(240)

        self.table_voices = TableWidget(self)
        self.table_voices.setColumnCount(3)
        self.table_voices.setHorizontalHeaderLabels(["情绪", "voice_id", "模式"])
        self.table_voices.verticalHeader().setVisible(False)
        self.table_voices.setEditTriggers(self.table_voices.NoEditTriggers)
        self.table_voices.setSelectionBehavior(self.table_voices.SelectRows)
        self.table_voices.setSelectionMode(self.table_voices.SingleSelection)
        self.table_voices.setColumnWidth(0, 140)
        self.table_voices.setColumnWidth(1, 320)
        self.table_voices.setColumnWidth(2, 140)
        self.table_voices.horizontalHeader().setStretchLastSection(True)

        self.splitter.addWidget(self.list_characters)
        self.splitter.addWidget(self.table_voices)

        try:
            ratio = float(self.config_manager.get("ui_voice_library_splitter_ratio", 0.32) or 0.32)
            ratio = max(0.2, min(0.5, ratio))
            total = self.width() or 860
            left = int(total * ratio)
            self.splitter.setSizes([left, max(1, total - left)])
        except Exception:
            pass

        root.addWidget(self.splitter, 1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.label_hint = CaptionLabel("提示：Enter 选择，Esc 取消", self)
        bottom.addWidget(self.label_hint, 1)

        self.btn_cancel = PushButton("取消", self)
        self.btn_ok = PrimaryPushButton("选择", self)
        self.btn_ok.setEnabled(False)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_ok)
        root.addLayout(bottom)

        # Populate initial list
        self._refresh_characters()

    def _connect_signals(self) -> None:
        self.seg_scope.currentItemChanged.connect(lambda _k: self._refresh_characters())
        self.search_edit.textChanged.connect(lambda _t: self._refresh_characters())
        self.btn_clear.clicked.connect(self._clear_selection)
        self.btn_refresh.clicked.connect(self._reload_voices)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept)

        self.list_characters.currentRowChanged.connect(self._on_character_changed)
        self.list_characters.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_characters.customContextMenuRequested.connect(self._on_character_context_menu)

        self.table_voices.itemSelectionChanged.connect(self._on_voice_selected)
        self.table_voices.doubleClicked.connect(lambda _idx: self._accept())

    def _load_initial_selection(self) -> None:
        # Preselect if provided
        if self.preselect_voice_id:
            character, emotion = _parse_voice_id(self.preselect_voice_id)
            if character:
                self._select_character(character)
                if emotion:
                    self._select_emotion(emotion)
                return

        # Otherwise, try recent voice -> character
        recent = self._get_recent_voice_ids()
        for vid in recent:
            character, emotion = _parse_voice_id(vid)
            if character in self._by_character:
                self._select_character(character)
                self._select_emotion(emotion)
                return

        # Otherwise pick first character in current scope
        if self._visible_characters:
            self._select_character(self._visible_characters[0])

    def _get_recent_voice_ids(self) -> List[str]:
        try:
            v = self.config_manager.get("ui_recent_voice_ids", []) or []
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            pass
        return []

    def _v2_voices_path(self) -> str:
        try:
            p = (self.config_manager.get("v2_voices_config_path", "") or "").strip()
        except Exception:
            p = ""
        if not p:
            p = os.path.abspath("./config/voices_v2.json")
        return os.path.abspath(p)

    def _make_v2_client(self) -> V2Client:
        host = str(self.config_manager.get("api_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(self.config_manager.get("api_port", 9880) or 9880)
        api_key = str(self.config_manager.get("api_key", "") or "").strip()
        return V2Client(V2Config(host=host, port=port, api_key=api_key, timeout_s=1.5))

    def _reload_voices(self) -> None:
        # Prefer API: keeps behavior consistent when user points UI to an external API server.
        try:
            items = self._make_v2_client().list_voices()
            if isinstance(items, list):
                self._apply_voice_items(items)
                self.label_hint.setText("提示：已从 API 刷新 voices（Enter 选择，Esc 取消）")
                return
        except Exception:
            pass

        if self._reload_voices_from_disk(set_hint=False):
            self.label_hint.setText("提示：API 不可用，已从本地配置刷新 voices（Enter 选择，Esc 取消）")

    def _apply_voice_items(self, items: List[dict]) -> None:
        voices: Dict[str, VoiceConfig] = {}
        for v in items or []:
            if not isinstance(v, dict):
                continue
            name = str(v.get("name") or "").strip()
            if not name:
                continue
            voices[name] = VoiceConfig.from_dict(v)

        self.voices = voices
        self._build_index()

        keep_vid = (self._selected_voice_id or self.preselect_voice_id or "").strip()
        self._refresh_characters()
        if keep_vid and keep_vid in self.voices:
            c, e = _parse_voice_id(keep_vid)
            if c:
                self._select_character(c)
                self._select_emotion(e)
                self._on_voice_selected()
        else:
            self._load_initial_selection()

    def _reload_voices_from_disk(self, *, set_hint: bool = True) -> bool:
        path = self._v2_voices_path()
        if not os.path.exists(path):
            if set_hint:
                self.label_hint.setText(f"提示：未找到 v2 voices 文件：{path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            if set_hint:
                self.label_hint.setText(f"提示：读取 v2 voices 失败：{e}")
            return False

        items: List[dict] = []
        if isinstance(data, list):
            items = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            items = [data]

        self._apply_voice_items(items)
        if set_hint:
            self.label_hint.setText("提示：voices 已刷新（Enter 选择，Esc 取消）")
        return True

    def _set_recent_voice_ids(self, ids: List[str]) -> None:
        ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
        out: List[str] = []
        for x in ids:
            if x not in out:
                out.append(x)
        out = out[:20]
        self.config_manager.set("ui_recent_voice_ids", out)

    def _get_favorite_characters(self) -> List[str]:
        try:
            v = self.config_manager.get("ui_favorite_characters", []) or []
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            pass
        return []

    def _set_favorite_characters(self, chars: List[str]) -> None:
        chars = [str(x).strip() for x in (chars or []) if str(x).strip()]
        out: List[str] = []
        for x in chars:
            if x not in out:
                out.append(x)
        out = out[:30]
        self.config_manager.set("ui_favorite_characters", out)

    def _get_last_emotion_map(self) -> Dict[str, str]:
        try:
            m = self.config_manager.get("ui_last_emotion_by_character", {}) or {}
            if isinstance(m, dict):
                out = {}
                for k, v in m.items():
                    kk = str(k).strip()
                    vv = str(v).strip()
                    if kk and vv:
                        out[kk] = vv
                return out
        except Exception:
            pass
        return {}

    def _set_last_emotion(self, character: str, emotion: str) -> None:
        character = (character or "").strip()
        emotion = (emotion or "").strip() or "default"
        if not character:
            return
        m = self._get_last_emotion_map()
        m[character] = emotion
        self.config_manager.set("ui_last_emotion_by_character", m)

    def _current_scope(self) -> str:
        try:
            k = self.seg_scope.currentItem()
        except Exception:
            k = self.SCOPE_ALL
        if k in {self.SCOPE_RECENT, self.SCOPE_FAVORITE, self.SCOPE_ALL}:
            return k
        return self.SCOPE_ALL

    def _refresh_characters(self) -> None:
        tokens = _tokenize(self.search_edit.text())
        scope = self._current_scope()

        chars: List[str] = []
        if scope == self.SCOPE_RECENT:
            # Derive characters in MRU order
            for vid in self._get_recent_voice_ids():
                c, _e = _parse_voice_id(vid)
                if c and c in self._by_character and c not in chars:
                    chars.append(c)
        elif scope == self.SCOPE_FAVORITE:
            for c in self._get_favorite_characters():
                if c and c in self._by_character:
                    chars.append(c)
        else:
            chars = sorted([c for c in self._by_character.keys() if c], key=_norm)

        if tokens:
            matched: List[str] = []
            for c in chars:
                # Match either on character itself or any voice row under it
                if _match_tokens(c, tokens):
                    matched.append(c)
                    continue
                rows = self._by_character.get(c) or []
                ok = False
                for r in rows:
                    hay = f"{r.character} {r.emotion} {r.voice_id} {r.mode}"
                    if _match_tokens(hay, tokens):
                        ok = True
                        break
                if ok:
                    matched.append(c)
            chars = matched

        self._visible_characters = chars

        # Update list widget
        current = self._selected_character
        self.list_characters.blockSignals(True)
        self.list_characters.clear()
        fav = set(self._get_favorite_characters())
        for c in chars:
            prefix = "♥ " if c in fav else ""
            self.list_characters.addItem(prefix + c)
        self.list_characters.blockSignals(False)

        if current and current in chars:
            self._select_character(current)
        elif chars:
            self._select_character(chars[0])
        else:
            self._select_character("")

    def _select_character(self, character: str) -> None:
        character = (character or "").strip()
        self._selected_character = character
        if not character:
            self.list_characters.setCurrentRow(-1)
            self._refresh_voice_table("")
            return

        # Find row by matching label (strip heart prefix)
        for i in range(self.list_characters.count()):
            t = self.list_characters.item(i).text().strip()
            t = t[2:].strip() if t.startswith("♥") else t
            if t == character:
                self.list_characters.blockSignals(True)
                self.list_characters.setCurrentRow(i)
                self.list_characters.blockSignals(False)
                self._refresh_voice_table(character)
                return

        self._refresh_voice_table(character)

    def _on_character_changed(self, _row: int) -> None:
        item = self.list_characters.currentItem()
        if not item:
            self._refresh_voice_table("")
            return
        t = item.text().strip()
        character = t[2:].strip() if t.startswith("♥") else t
        self._selected_character = character
        self._refresh_voice_table(character)

    def _refresh_voice_table(self, character: str) -> None:
        tokens = _tokenize(self.search_edit.text())
        rows = list(self._by_character.get(character, []) or [])
        if tokens:
            out = []
            for r in rows:
                hay = f"{r.character} {r.emotion} {r.voice_id} {r.mode}"
                if _match_tokens(hay, tokens):
                    out.append(r)
            rows = out

        self.table_voices.blockSignals(True)
        self.table_voices.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table_voices.setItem(i, 0, QTableWidgetItem(r.emotion))
            self.table_voices.setItem(i, 1, QTableWidgetItem(r.voice_id))
            self.table_voices.setItem(i, 2, QTableWidgetItem(r.mode))
        self.table_voices.blockSignals(False)

        # Important: clear both UI state and the table's actual selection.
        # Otherwise, when there is only one row (common), selection doesn't "change" and
        # itemSelectionChanged won't fire, leaving "选择" disabled while a row appears highlighted.
        try:
            self.table_voices.clearSelection()
        except Exception:
            pass
        self._clear_selection(update_ui_only=False)

        # Auto-select emotion: last emotion (favorite) or default
        target_emotion = ""
        if character:
            last_map = self._get_last_emotion_map()
            if character in last_map:
                target_emotion = last_map.get(character, "")
        if not target_emotion:
            target_emotion = "default"
        self._select_emotion(target_emotion)
        self._on_voice_selected()

    def _select_emotion(self, emotion: str) -> None:
        emotion = (emotion or "").strip() or "default"
        # Find matching row; if not found, fall back to first row.
        for i in range(self.table_voices.rowCount()):
            it = self.table_voices.item(i, 0)
            if it and (it.text() or "").strip() == emotion:
                self.table_voices.selectRow(i)
                # If selection didn't change (e.g. only one row), force UI update.
                self._on_voice_selected()
                return
        if self.table_voices.rowCount() > 0:
            self.table_voices.selectRow(0)
            self._on_voice_selected()

    def _on_voice_selected(self) -> None:
        rows = self.table_voices.selectionModel().selectedRows()
        if not rows:
            self._clear_selection(update_ui_only=True)
            return
        r = rows[0].row()
        voice_id_item = self.table_voices.item(r, 1)
        emotion_item = self.table_voices.item(r, 0)
        voice_id = (voice_id_item.text() if voice_id_item else "").strip()
        emotion = (emotion_item.text() if emotion_item else "").strip()

        character, emo2 = _parse_voice_id(voice_id)
        self._selected_voice_id = voice_id
        self._selected_character = character
        self._selected_emotion = emotion or emo2

        self.label_selected.setText(f"已选：{character} / {self._selected_emotion}")
        self.btn_ok.setEnabled(bool(voice_id))

    def _clear_selection(self, *, update_ui_only: bool = False) -> None:
        if not update_ui_only:
            self._selected_voice_id = ""
            self._selected_emotion = ""
        try:
            self.table_voices.clearSelection()
        except Exception:
            pass
        self.label_selected.setText("未选择")
        self.btn_ok.setEnabled(False)

    def _accept(self) -> None:
        vid = self.selected_voice_id()
        if not vid:
            return

        c, e = _parse_voice_id(vid)
        recent = self._get_recent_voice_ids()
        recent2 = [vid] + [x for x in recent if x != vid]
        self._set_recent_voice_ids(recent2)
        if c:
            self._set_last_emotion(c, e)

        try:
            sizes = self.splitter.sizes()
            if sizes and sum(sizes) > 0:
                ratio = float(sizes[0]) / float(sum(sizes))
                self.config_manager.set("ui_voice_library_splitter_ratio", ratio)
        except Exception:
            pass

        self.accept()

    def _on_character_context_menu(self, pos) -> None:
        item = self.list_characters.itemAt(pos)
        if not item:
            return
        t = item.text().strip()
        character = t[2:].strip() if t.startswith("♥") else t
        if not character:
            return

        favs = self._get_favorite_characters()
        is_fav = character in favs

        menu = RoundMenu(parent=self.list_characters)
        if is_fav:
            menu.addAction(Action(FluentIcon.HEART, "取消收藏", self.list_characters, triggered=lambda: self._toggle_fav(character, False)))
        else:
            menu.addAction(Action(FluentIcon.HEART, "加入收藏", self.list_characters, triggered=lambda: self._toggle_fav(character, True)))
        menu.exec_(self.list_characters.mapToGlobal(pos))

    def _toggle_fav(self, character: str, on: bool) -> None:
        character = (character or "").strip()
        if not character:
            return
        favs = self._get_favorite_characters()
        if on and character not in favs:
            favs = [character] + favs
        if (not on) and character in favs:
            favs = [c for c in favs if c != character]
        self._set_favorite_characters(favs)
        self._refresh_characters()
