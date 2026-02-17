import os
import hashlib
import shutil
import time
import uuid

from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QHeaderView, QMessageBox, QColorDialog, QSplitter, QDialog, QApplication, QPlainTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QColor

from qfluentwidgets import (
    PushButton, PrimaryPushButton, TableWidget, LineEdit,
    ComboBox, FluentIcon, SubtitleLabel, ToolButton, InfoBar, InfoBarPosition, BodyLabel,
    RoundMenu, Action
)

from core.models import VoiceConfig
from core.config_manager import ConfigManager
from core.v2.legacy_import import import_legacy_voice_config_to_v2
from core.v2.assets_sqlite import AssetsSqliteStore

from .asset_cleanup_dialog import UnusedAssetsCleanupDialog
from .voice_setup_wizard import VoiceSetupWizardDialog
from .v2_client import V2Client, V2Config
from .components.voice_refs_sheet import VoiceRefsSheet
from .components.voice_rename_wizard import VoiceRenameWizard
from .services import VoiceStore
from .theme.tokens import Metrics, Palette, Radius, Spacing, StatusChip, Table

class LegacyImportWorker(QThread):
    """导入旧 voices 配置到 v2 voices + v2 assets（后台线程）"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, legacy_path: str, v2_path: str, db_path: str, assets_dir: str):
        super().__init__()
        self.legacy_path = legacy_path
        self.v2_path = v2_path
        self.db_path = db_path
        self.assets_dir = assets_dir

    def run(self):
        try:
            res = import_legacy_voice_config_to_v2(
                legacy_config_path=self.legacy_path,
                v2_voices_config_path=self.v2_path,
                v2_assets_db_path=self.db_path,
                v2_assets_dir=self.assets_dir,
            )
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class V2CallWorker(QThread):
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

class VoiceSettingsInterface(QWidget):
    """语音设置界面"""
    
    config_loaded = pyqtSignal()  # 配置加载完成信号
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.voice_configs: List[VoiceConfig] = []
        # v2 voices rows (raw dicts) aligned with self.voice_configs by index.
        # Keep unknown keys here so editing this table doesn't drop v2-only fields.
        self._v2_rows: List[dict] = []
        self._voice_store = VoiceStore(config_manager)
        self.config_dir = Path("./config")
        self.config_dir.mkdir(exist_ok=True)
        self.import_worker = None  # 导入线程
        self._api_workers: List[QThread] = []
        self._api_status_busy = False
        self._v2_assets_db_path = os.path.abspath("./data/api_v2_assets.sqlite3")
        self._v2_assets_dir = os.path.abspath("./data/assets/audio")
        # Visible table rows map to source indexes in self.voice_configs/self._v2_rows.
        self._visible_source_indexes: List[int] = []
        self.is_edit_mode = False
        self.rename_wizard: Optional[VoiceRenameWizard] = None
        self.is_compact_mode = False
        self._compact_breakpoint_px = 1280
        try:
            self._min_left_table_width = int(self.config_manager.get("ui_voice_settings_min_left_table_width", 1040) or 1040)
        except Exception:
            self._min_left_table_width = 1040
        try:
            self._auto_collapse_inspector = bool(self.config_manager.get("ui_voice_settings_auto_collapse_inspector", True))
        except Exception:
            self._auto_collapse_inspector = True
        try:
            wrap_lines = int(self.config_manager.get("ui_voice_settings_ref_text_wrap_lines", 2) or 2)
        except Exception:
            wrap_lines = 2
        self._ref_text_wrap_lines = max(1, min(4, wrap_lines))
        try:
            self._show_full_prompt_audio_path = bool(self.config_manager.get("ui_voice_settings_show_full_prompt_audio_path", False))
        except Exception:
            self._show_full_prompt_audio_path = False
        try:
            self._show_path_full = bool(self.config_manager.get("ui_voice_settings_show_path_full", False))
        except Exception:
            self._show_path_full = False
        try:
            self._compact_hidden_columns = self.config_manager.get("ui_voice_settings_compact_hidden_columns", ["指令文本"]) or ["指令文本"]
        except Exception:
            self._compact_hidden_columns = ["指令文本"]
        self._refs_open_pref = False
        self._was_refs_open_before_compact = False
        self._is_temporary_inspector_open = False
        self._pending_delete: Optional[dict] = None
        try:
            self._compile_all_refs = bool(self.config_manager.get("ui_voice_settings_compile_all_refs", False))
        except Exception:
            self._compile_all_refs = False
        try:
            self._refs_panel_width = int(self.config_manager.get("ui_voice_settings_refs_panel_width", 520) or 520)
        except Exception:
            self._refs_panel_width = 520
        self._refs_panel_width = max(Metrics.INSPECTOR_W_MIN, min(Metrics.INSPECTOR_W_MAX, self._refs_panel_width))
        self._delete_timer = QTimer(self)
        self._delete_timer.setSingleShot(True)
        self._delete_timer.timeout.connect(self._commit_pending_delete)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        layout.addWidget(self.build_top_toolbar())
        layout.addWidget(self.build_status_strip())

        # 配置表格
        self.table = TableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["角色 / 情绪", "模式", "参考文本", "主参考", "指令文本", "颜色"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(Metrics.TABLE_ROW_H)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(56)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(3, 220)
        self.table.setColumnWidth(4, 220)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(5, 74)

        self.table.verticalHeader().setVisible(False)
        try:
            self.table.doubleClicked.connect(self._on_table_double_clicked)
        except Exception:
            pass

        # Main area: left table + right-side reference sheet
        self.main_splitter = QSplitter(Qt.Horizontal, self)
        self.main_splitter.setChildrenCollapsible(False)

        left_panel = QWidget(self)
        left_l = QVBoxLayout(left_panel)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(Spacing.SM)
        left_l.addWidget(self.table, 1)

        self.main_splitter.addWidget(left_panel)

        self.refs_sheet = VoiceRefsSheet(self._v2_client, parent=self)
        self.refs_sheet.close_btn.clicked.connect(self.close_refs_sheet)
        self.refs_sheet.panel.ref_pool_changed.connect(self._on_ref_pool_changed)
        self.refs_sheet.panel.selected_asset_changed.connect(self._on_selected_asset_changed)
        self.main_splitter.addWidget(self.refs_sheet)
        refs_state = self.refs_sheet.load_ui_state(self.config_manager)
        self._refs_open_pref = bool((refs_state or {}).get("open", False))

        self.refs_sheet.setVisible(False)
        try:
            self.main_splitter.setSizes([1000, 0])
        except Exception:
            pass
        try:
            self.main_splitter.splitterMoved.connect(self._on_splitter_moved)
        except Exception:
            pass

        try:
            self.table.currentCellChanged.connect(lambda *_: self._on_table_selection_changed())
        except Exception:
            pass

        layout.addWidget(self.main_splitter, 1)

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(Spacing.SM)

        self.add_button = PushButton("添加配置")
        self.add_button.clicked.connect(self.add_config)
        button_layout.addWidget(self.add_button)

        self.undo_delete_btn = PushButton("↩ 撤销删除")
        self.undo_delete_btn.setVisible(False)
        self.undo_delete_btn.clicked.connect(self.undo_pending_delete)
        button_layout.addWidget(self.undo_delete_btn)
        
        # self.remove_button = PushButton("➖ 删除配置")
        # self.remove_button.clicked.connect(self.remove_config)
        # button_layout.addWidget(self.remove_button)
        
        button_layout.addStretch()
        
        self.load_button = PushButton("加载")
        self.load_button.clicked.connect(self.load_config)
        button_layout.addWidget(self.load_button)

        self.save_button = PushButton("保存")
        self.save_button.clicked.connect(self.save_config)
        button_layout.addWidget(self.save_button)

        self.apply_button = PrimaryPushButton("应用")
        self.apply_button.clicked.connect(self.apply_config)
        button_layout.addWidget(self.apply_button)

        self.compile_button = PushButton("编译当前 voice")
        self.compile_button.setToolTip("通过 v2 API 编译当前选中 voice")
        self.compile_button.clicked.connect(self.compile_current_voice_v2)
        button_layout.addWidget(self.compile_button)
        self._set_uniform_control_height(
            self.manage_refs_btn,
            self.open_inspector_btn,
            self.edit_mode_btn,
            self.tools_btn,
            self.add_button,
            self.undo_delete_btn,
            self.load_button,
            self.save_button,
            self.apply_button,
            self.compile_button,
            self.character_filter_combo,
        )

        layout.addLayout(button_layout)
        self._apply_page_styles()
        self._update_v2_path_label()

        # Default load: v2 voices config (single source of truth).
        self.load_v2_voices()
    
        self._on_table_selection_changed()
        self._update_edit_mode_ui()
        self._show_legacy_import_hint_if_needed()
        self.apply_compact_layout(self.width())
        self._refresh_api_status()
        if self._refs_open_pref and not self.is_compact_mode:
            self._set_inspector_visible(True, reason="init_restore")

    def build_top_toolbar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("voiceSettingsTopToolbar")
        l = QHBoxLayout(bar)
        l.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        l.setSpacing(Spacing.SM)

        title = SubtitleLabel("语音设置")
        l.addWidget(title)
        l.addSpacing(Spacing.SM)
        l.addWidget(BodyLabel("角色分组"))

        self.character_filter_combo = ComboBox(self)
        self.character_filter_combo.setMinimumWidth(220)
        self.character_filter_combo.currentTextChanged.connect(self.on_character_filter_changed)
        l.addWidget(self.character_filter_combo)

        self.group_count_label = BodyLabel("0 角色")
        self.group_count_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        l.addWidget(self.group_count_label)
        l.addStretch()

        self.refs_summary_label = BodyLabel("参考池：-")
        self.refs_summary_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        l.addWidget(self.refs_summary_label)

        self.main_ref_status_label = BodyLabel("主参考：-")
        self.main_ref_status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        l.addWidget(self.main_ref_status_label)
        l.addSpacing(Spacing.SM)

        self.manage_refs_btn = PushButton("管理参考音频")
        self.manage_refs_btn.setIcon(FluentIcon.LINK)
        self.manage_refs_btn.clicked.connect(self.open_refs_sheet_for_current_row)
        l.addWidget(self.manage_refs_btn)

        self.open_inspector_btn = PushButton("打开参考面板")
        self.open_inspector_btn.setIcon(FluentIcon.LINK)
        self.open_inspector_btn.setVisible(False)
        self.open_inspector_btn.clicked.connect(self.open_refs_sheet_for_current_row)
        l.addWidget(self.open_inspector_btn)

        self.edit_mode_btn = PushButton("进入编辑模式")
        self.edit_mode_btn.setIcon(FluentIcon.EDIT)
        self.edit_mode_btn.setToolTip("浏览模式下不会修改任何字段。")
        self.edit_mode_btn.clicked.connect(self.toggle_edit_mode)
        l.addWidget(self.edit_mode_btn)

        self.tools_btn = PushButton("工具")
        self.tools_btn.clicked.connect(self.show_tools_menu)
        l.addWidget(self.tools_btn)
        return bar

    def build_status_strip(self) -> QWidget:
        strip = QWidget(self)
        strip.setObjectName("voiceSettingsStatusStrip")
        l = QHBoxLayout(strip)
        l.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        l.setSpacing(Spacing.SM)
        l.addWidget(BodyLabel("v2 配置"))

        self.v2_path_label = BodyLabel("<未设置>")
        self.v2_path_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        self.v2_path_label.setWordWrap(False)
        l.addWidget(self.v2_path_label, 1)

        self.path_toggle_btn = ToolButton(FluentIcon.MORE)
        self.path_toggle_btn.setToolTip("切换全路径/文件名")
        self.path_toggle_btn.clicked.connect(self._toggle_v2_path_view)
        l.addWidget(self.path_toggle_btn)

        self.copy_path_btn = ToolButton(FluentIcon.COPY)
        self.copy_path_btn.setToolTip("复制 v2 配置路径")
        self.copy_path_btn.clicked.connect(self._copy_v2_path)
        l.addWidget(self.copy_path_btn)

        l.addSpacing(Spacing.SM)
        self.api_status_label = BodyLabel("API：检测中")
        self.api_status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        self.api_status_label.setWordWrap(False)
        l.addWidget(self.api_status_label)

        self.api_status_refresh_btn = ToolButton(FluentIcon.SYNC)
        self.api_status_refresh_btn.setToolTip("刷新 API 状态")
        self.api_status_refresh_btn.clicked.connect(self._refresh_api_status)
        l.addWidget(self.api_status_refresh_btn)

        l.addSpacing(Spacing.SM)
        self.selected_ref_label = BodyLabel("当前选中参考音频：<无>")
        self.selected_ref_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        self.selected_ref_label.setWordWrap(False)
        l.addWidget(self.selected_ref_label, 1)
        return strip
    
    def _v2_client(self) -> V2Client:
        host = str(self.config_manager.get("api_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(self.config_manager.get("api_port", 9880) or 9880)
        api_key = str(self.config_manager.get("api_key", "") or "").strip()
        return V2Client(V2Config(host=host, port=port, api_key=api_key, timeout_s=10.0))

    def _run_api_task(self, fn, on_ok, on_err):
        w = V2CallWorker(fn)
        self._api_workers.append(w)

        def _cleanup():
            try:
                self._api_workers.remove(w)
            except Exception:
                pass
            w.deleteLater()

        def _ok(res: object):
            try:
                on_ok(res)
            finally:
                _cleanup()

        def _err(e: object):
            try:
                on_err(e)
            finally:
                _cleanup()

        w.ok.connect(_ok)
        w.err.connect(_err)
        w.start()

    def _set_api_status(self, *, online: bool, detail: str = ""):
        if online:
            self.api_status_label.setText("API：在线")
            self.api_status_label.setStyleSheet(f"color: {Palette.SUCCESS};")
            self.api_status_label.setToolTip(detail or "v2 服务可用")
        else:
            self.api_status_label.setText("API：离线")
            self.api_status_label.setStyleSheet(f"color: {Palette.DANGER};")
            self.api_status_label.setToolTip(detail or "v2 服务不可用")

    def _err_text(self, e: object) -> str:
        short = getattr(e, "short", None)
        if callable(short):
            try:
                return str(short())
            except Exception:
                pass
        return str(e)

    def _refresh_api_status(self):
        if self._api_status_busy:
            return
        self._api_status_busy = True
        try:
            self.api_status_label.setText("API：检测中")
            self.api_status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        except Exception:
            pass

        def _do():
            cli = self._v2_client()
            cli.cfg.timeout_s = 1.2
            return cli.health()

        def _ok(res: object):
            self._api_status_busy = False
            self._set_api_status(online=True, detail=str(res or ""))

        def _err(e: object):
            self._api_status_busy = False
            self._set_api_status(online=False, detail=self._err_text(e))

        self._run_api_task(_do, _ok, _err)

    def _safe_str(self, v: object) -> str:
        return str(v or "").strip()

    def _set_uniform_control_height(self, *widgets):
        for w in widgets:
            try:
                w.setFixedHeight(Metrics.CONTROL_H)
            except Exception:
                pass

    def _apply_page_styles(self):
        self.setStyleSheet(
            f"""
            QWidget {{
                font-family: 'Segoe UI', 'PingFang SC', sans-serif;
            }}
            QWidget#voiceSettingsTopToolbar {{
                border: 1px solid {Palette.BORDER};
                border-radius: {Radius.PANEL}px;
                background: {Palette.CARD};
            }}
            QWidget#voiceSettingsStatusStrip {{
                border: 1px solid {Palette.BORDER};
                border-radius: {Radius.CONTROL}px;
                background: {Palette.CARD};
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
                border: 1px solid transparent;
                border-radius: {Radius.CONTROL}px;
                padding: 0 10px;
                background: transparent;
            }}
            QLineEdit:focus {{
                border: 1px solid {Palette.BORDER};
                background: {Palette.CARD};
            }}
            QPlainTextEdit {{
                border: 1px solid transparent;
                border-radius: {Radius.CONTROL}px;
                padding: 6px 8px;
                background: transparent;
            }}
            QPlainTextEdit:focus {{
                border: 1px solid {Palette.BORDER};
                background: {Palette.CARD};
            }}
            """
        )

    def _toggle_v2_path_view(self):
        self._show_path_full = not bool(self._show_path_full)
        try:
            self.config_manager.set("ui_voice_settings_show_path_full", bool(self._show_path_full))
        except Exception:
            pass
        self._update_v2_path_label()

    def _copy_v2_path(self):
        try:
            p = os.path.abspath(self._v2_voices_path())
        except Exception:
            p = ""
        if p:
            QApplication.clipboard().setText(p)
            InfoBar.success(
                title="已复制",
                content=os.path.basename(p),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=1500,
                parent=self,
            )

    def _update_v2_path_label(self):
        try:
            v2p = os.path.abspath(self._v2_voices_path())
        except Exception:
            v2p = ""
        if not v2p:
            self.v2_path_label.setText("<未设置>")
            self.v2_path_label.setToolTip("")
            return
        text = v2p if self._show_path_full else os.path.basename(v2p)
        self.v2_path_label.setText(text)
        self.v2_path_label.setToolTip(v2p)

    def _compact_hidden_column_indexes(self) -> Set[int]:
        if not isinstance(self._compact_hidden_columns, list):
            self._compact_hidden_columns = ["指令文本"]
        mapping = {
            "角色/情绪": 0,
            "角色 / 情绪": 0,
            "模式": 1,
            "参考文本": 2,
            "主参考": 3,
            "指令文本": 4,
            "颜色": 5,
        }
        out: Set[int] = set()
        for name in self._compact_hidden_columns:
            idx = mapping.get(self._safe_str(name))
            if idx is not None:
                out.add(idx)
        return out

    def _apply_compact_columns(self, compact: bool):
        hidden_set = self._compact_hidden_column_indexes()
        for col in range(self.table.columnCount()):
            should_hide = bool(compact and col in hidden_set)
            self.table.setColumnHidden(col, should_hide)
        self.table.setColumnWidth(5, 56 if compact else 74)
        self.table.setColumnWidth(0, 210 if compact else 220)
        self.table.setColumnWidth(3, 200 if compact else 220)
        self.table.setColumnWidth(4, 180 if compact else 220)

    def _should_force_collapse_inspector(self, total_width: int) -> bool:
        if not bool(self._auto_collapse_inspector):
            return False
        total_width = int(total_width or self.width() or 0)
        if total_width <= 0:
            return False
        planned = int(self._refs_panel_width or Metrics.INSPECTOR_W_DEFAULT)
        planned = max(Metrics.INSPECTOR_W_MIN, min(Metrics.INSPECTOR_W_MAX, planned))
        left_width = total_width - planned
        return left_width < int(self._min_left_table_width)

    def _status_chip_styles(self, status: str) -> Tuple[str, str]:
        if status == "uploaded":
            return StatusChip.SUCCESS_BG, StatusChip.SUCCESS_TEXT
        if status == "missing":
            return StatusChip.MISSING_BG, StatusChip.MISSING_TEXT
        if status == "warn":
            return StatusChip.WARN_BG, StatusChip.WARN_TEXT
        return StatusChip.NEUTRAL_BG, StatusChip.NEUTRAL_TEXT

    def _main_ref_view(self, source_idx: int) -> Dict[str, str]:
        row = self._v2_rows[source_idx] if 0 <= source_idx < len(self._v2_rows) and isinstance(self._v2_rows[source_idx], dict) else {}
        resolved_path, primary_aid = self._resolve_prompt_audio_from_row(row)
        current_prompt_audio = self._safe_str((row or {}).get("prompt_audio"))
        cfg_prompt_audio = self._safe_str(self.voice_configs[source_idx].prompt_audio) if 0 <= source_idx < len(self.voice_configs) else ""
        candidate_path = resolved_path or current_prompt_audio or cfg_prompt_audio
        path_exists = bool(candidate_path and os.path.exists(candidate_path))
        if path_exists:
            status = "uploaded"
            status_text = "已上传"
        elif primary_aid or candidate_path:
            status = "missing"
            status_text = "缺失"
        else:
            status = "neutral"
            status_text = "未绑定"

        if self._show_full_prompt_audio_path:
            display_name = candidate_path or "<未绑定>"
        else:
            display_name = os.path.basename(candidate_path) if candidate_path else "<未绑定>"

        return {
            "status": status,
            "status_text": status_text,
            "path": candidate_path,
            "aid": self._safe_str(primary_aid),
            "display_name": display_name,
        }

    def _render_prompt_text_cell(self, source_idx: int, text: str) -> QWidget:
        txt = str(text or "")
        lines = max(1, min(4, int(self._ref_text_wrap_lines)))
        if self.is_edit_mode:
            editor = QPlainTextEdit()
            editor.setPlainText(txt)
            editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            editor.setFixedHeight(20 * lines + 12)
            editor.textChanged.connect(lambda idx=source_idx, w=editor: self.update_config_prompt_text(idx, w.toPlainText()))
            self.setup_widget_context_menu(editor, source_idx)
            return editor

        wrap = BodyLabel(txt if txt else "<未填写参考文本>")
        wrap.setWordWrap(True)
        wrap.setToolTip(txt)
        wrap.setStyleSheet(f"color: {Palette.TEXT_PRIMARY};")
        wrap.setFixedHeight(18 * lines + 4)
        self.setup_widget_context_menu(wrap, source_idx)
        return wrap

    def _open_main_ref_folder(self, source_idx: int):
        info = self._main_ref_view(source_idx)
        path = self._safe_str(info.get("path"))
        if not path or not os.path.exists(path):
            InfoBar.warning(
                title="主参考不可用",
                content="当前主参考文件不存在，无法打开目录",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return
        try:
            os.startfile(os.path.dirname(path))
        except Exception as e:
            InfoBar.error(
                title="打开失败",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self,
            )

    def _open_main_ref_context_menu(self, source_idx: int, global_pos):
        menu = RoundMenu(parent=self)
        info = self._main_ref_view(source_idx)
        path = self._safe_str(info.get("path"))
        if self.is_edit_mode:
            menu.addAction(Action(FluentIcon.FOLDER, "选择主参考音频...", self, triggered=lambda idx=source_idx: self.browse_audio_file(idx)))
            menu.addSeparator()
        menu.addAction(Action(FluentIcon.FOLDER, "打开所在目录", self, triggered=lambda idx=source_idx: self._open_main_ref_folder(idx)))
        if path:
            menu.addAction(Action(FluentIcon.COPY, "复制完整路径", self, triggered=lambda p=path: QApplication.clipboard().setText(p)))
        menu.exec_(global_pos)

    def _render_main_ref_cell(self, source_idx: int) -> QWidget:
        info = self._main_ref_view(source_idx)
        chip_bg, chip_fg = self._status_chip_styles(self._safe_str(info.get("status")))
        display_name = self._safe_str(info.get("display_name"))
        path = self._safe_str(info.get("path"))

        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(4, 2, 4, 2)
        l.setSpacing(Table.COLUMN_GAP_DENSE)

        chip = BodyLabel(self._safe_str(info.get("status_text")))
        chip.setFixedHeight(StatusChip.HEIGHT)
        chip.setStyleSheet(
            f"background: {chip_bg}; color: {chip_fg}; border-radius: 6px; padding: 0 8px;"
        )
        l.addWidget(chip)

        name_lbl = BodyLabel(display_name or "<未绑定>")
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        tt = path or (self._safe_str(info.get("aid")) if self._safe_str(info.get("aid")) else "<未绑定>")
        name_lbl.setToolTip(tt)
        l.addWidget(name_lbl, 1)

        folder_btn = ToolButton(FluentIcon.FOLDER)
        folder_btn.setFixedSize(Metrics.CONTROL_H, Metrics.CONTROL_H)
        folder_btn.setToolTip("打开参考音频目录")
        folder_btn.setEnabled(bool(path and os.path.exists(path)))
        folder_btn.clicked.connect(lambda _=False, idx=source_idx: self._open_main_ref_folder(idx))
        l.addWidget(folder_btn)

        more_btn = ToolButton(FluentIcon.MORE)
        more_btn.setFixedSize(Metrics.CONTROL_H, Metrics.CONTROL_H)
        more_btn.setToolTip("更多")
        more_btn.clicked.connect(
            lambda _=False, idx=source_idx, b=more_btn: self._open_main_ref_context_menu(
                idx, b.mapToGlobal(b.rect().bottomLeft())
            )
        )
        l.addWidget(more_btn)
        self.setup_widget_context_menu(w, source_idx)
        return w

    def _on_table_double_clicked(self, index):
        try:
            if not self.is_edit_mode or index.column() != 0:
                return
            vr = int(index.row())
            if 0 <= vr < len(self._visible_source_indexes):
                self.open_voice_inline_editor(self._visible_source_indexes[vr])
        except Exception:
            pass

    def open_voice_inline_editor(self, source_idx: int):
        if not self.is_edit_mode or not (0 <= source_idx < len(self.voice_configs)):
            return
        ch, emo, _ = self._voice_parts_by_source_index(source_idx)
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑角色与情绪")
        dlg.resize(420, 180)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.SM)

        root.addWidget(BodyLabel("角色"))
        ch_edit = LineEdit(dlg)
        ch_edit.setText(ch)
        ch_edit.setPlaceholderText("角色名")
        ch_edit.setClearButtonEnabled(True)
        ch_edit.setFixedHeight(Metrics.CONTROL_H)
        root.addWidget(ch_edit)

        root.addWidget(BodyLabel("情绪"))
        emo_edit = LineEdit(dlg)
        emo_edit.setText(emo or "default")
        emo_edit.setPlaceholderText("default")
        emo_edit.setClearButtonEnabled(True)
        emo_edit.setFixedHeight(Metrics.CONTROL_H)
        root.addWidget(emo_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = PushButton("取消", dlg)
        save_btn = PrimaryPushButton("保存", dlg)
        cancel_btn.clicked.connect(dlg.reject)
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        if dlg.exec_() != QDialog.Accepted:
            return
        new_character = self._safe_str(ch_edit.text())
        new_emotion = self._safe_str(emo_edit.text()) or "default"
        ok, msg = self.validate_voice_parts(new_character, new_emotion)
        if not ok:
            InfoBar.warning(
                title="名称格式不合法",
                content=msg,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2200,
                parent=self,
            )
            return
        self.update_config_voice_parts(source_idx, new_character, new_emotion)
        self._refresh_character_filter_items()
        self.update_table()
        self._select_visible_row_by_source_index(source_idx)

    def compose_voice_id(self, character: str, emotion: str) -> str:
        ch = self._safe_str(character)
        emo = self._safe_str(emotion) or "default"
        if not ch:
            return ""
        return f"{ch}#{emo}"

    def validate_voice_parts(self, character: str, emotion: str) -> tuple[bool, str]:
        ch = self._safe_str(character)
        emo = self._safe_str(emotion) or "default"
        if not ch:
            return False, "角色名称不能为空"
        invalid_chars = set('#\\/\n\r\t')
        if any(c in invalid_chars for c in ch):
            return False, "角色名不能包含 #、斜杠或换行字符"
        if any(c in invalid_chars for c in emo):
            return False, "情绪标签不能包含 #、斜杠或换行字符"
        return True, ""

    def update_config_voice_parts(self, index: int, character: str, emotion: str):
        if not (0 <= index < len(self.voice_configs)):
            return
        ok, msg = self.validate_voice_parts(character, emotion)
        if not ok:
            return
        voice_id = self.compose_voice_id(character, emotion)
        if not voice_id:
            return
        self.voice_configs[index].name = voice_id
        if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
            row = dict(self._v2_rows[index] or {})
            row["name"] = voice_id
            row["character"] = self._safe_str(character)
            row["emotion"] = self._safe_str(emotion) or "default"
            self._v2_rows[index] = row

    def _on_voice_parts_edit_finished(self, index: int, character: str, emotion: str):
        if not self.is_edit_mode:
            return
        ok, msg = self.validate_voice_parts(character, emotion)
        if not ok:
            InfoBar.warning(
                title="名称格式不合法",
                content=msg,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2400,
                parent=self,
            )
            return
        self.update_config_voice_parts(index, character, emotion)
        self._refresh_character_filter_items()
        self.update_table()
        self._select_visible_row_by_source_index(index)

    def _update_edit_mode_ui(self):
        try:
            if self.is_edit_mode:
                self.edit_mode_btn.setText("退出编辑模式")
                self.edit_mode_btn.setIcon(FluentIcon.EDIT)
            else:
                self.edit_mode_btn.setText("进入编辑模式")
                self.edit_mode_btn.setIcon(FluentIcon.EDIT)
            if hasattr(self, "add_button"):
                self.add_button.setEnabled(self.is_edit_mode)
        except Exception:
            pass

    def toggle_edit_mode(self):
        self.is_edit_mode = not self.is_edit_mode
        self._update_edit_mode_ui()
        self.update_table()
        InfoBar.success(
            title="编辑模式已更新",
            content="当前为编辑模式" if self.is_edit_mode else "当前为浏览模式（只读）",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1800,
            parent=self,
        )

    def _show_legacy_import_hint_if_needed(self):
        legacy_path = os.path.abspath("./config/config.json")
        if not os.path.exists(legacy_path):
            return
        try:
            dismissed = bool(self.config_manager.get("ui_voice_settings_legacy_hint_dismissed", False))
        except Exception:
            dismissed = False
        if dismissed:
            return
        InfoBar.warning(
            title="检测到旧配置",
            content="旧配置迁移入口已移到“工具”。迁移一次后可忽略该提示。",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4200,
            parent=self,
        )
        try:
            self.config_manager.set("ui_voice_settings_legacy_hint_dismissed", True)
        except Exception:
            pass

    def show_tools_menu(self):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.EDIT, "批量改名向导...", self, triggered=self.open_rename_wizard))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.ADD, "一键闭环向导...", self, triggered=self.open_voice_setup_wizard))
        menu.addAction(Action(FluentIcon.DELETE, "清理未引用参考音频...", self, triggered=self.open_unused_assets_cleanup))
        menu.addSeparator()
        compile_all_action = Action(FluentIcon.TAG, "编译时包含全部参考音频", self, triggered=self.toggle_compile_all_refs)
        try:
            compile_all_action.setCheckable(True)
            compile_all_action.setChecked(bool(self._compile_all_refs))
        except Exception:
            pass
        menu.addAction(compile_all_action)
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.UP, "导入旧配置到 v2", self, triggered=self.import_legacy_to_v2))
        menu.exec_(self.tools_btn.mapToGlobal(self.tools_btn.rect().bottomLeft()))

    def toggle_compile_all_refs(self):
        self._compile_all_refs = not bool(self._compile_all_refs)
        try:
            self.config_manager.set("ui_voice_settings_compile_all_refs", bool(self._compile_all_refs))
        except Exception:
            pass
        InfoBar.success(
            title="编译设置已更新",
            content="当前为：包含全部参考音频" if self._compile_all_refs else "当前为：仅主参考音频",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1800,
            parent=self,
        )

    def _on_splitter_moved(self, _pos: int, _index: int):
        if not self.refs_sheet.isVisible():
            return
        try:
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > 0:
                self._refs_panel_width = int(sizes[1])
                self._refs_panel_width = max(Metrics.INSPECTOR_W_MIN, min(Metrics.INSPECTOR_W_MAX, self._refs_panel_width))
                self.config_manager.set("ui_voice_settings_refs_panel_width", self._refs_panel_width)
        except Exception:
            pass

    def open_unused_assets_cleanup(self):
        chars = sorted(
            {
                self._parse_voice_name(vc.name).get("character", "")
                for vc in self.voice_configs
                if vc and self._parse_voice_name(vc.name).get("character", "")
            }
        )
        idx = self._current_row_index()
        default_character = ""
        if 0 <= idx < len(self.voice_configs):
            default_character = self._parse_voice_name(self.voice_configs[idx].name).get("character", "")
        dlg = UnusedAssetsCleanupDialog(
            self._v2_client,
            characters=chars,
            default_character=default_character,
            parent=self,
        )
        dlg.exec_()
        try:
            if self.refs_sheet.isVisible():
                self.refs_sheet.panel.refresh_assets()
        except Exception:
            pass

    def open_voice_setup_wizard(self):
        idx = self._current_row_index()
        preset_character = ""
        preset_emotion = "default"
        if 0 <= idx < len(self.voice_configs):
            parts = self._parse_voice_name(self._safe_str(self.voice_configs[idx].name))
            preset_character = parts.get("character", "")
            preset_emotion = parts.get("emotion", "default")
        try:
            dlg = VoiceSetupWizardDialog(
                self.window(),
                self._v2_client,
                preset_character=preset_character,
                preset_emotion=preset_emotion,
                parent=self,
            )
            dlg.exec_()
        except Exception as e:
            InfoBar.error(
                title="打开失败",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return
        self.load_v2_voices()
        self._on_table_selection_changed()

    def open_rename_wizard(self):
        voices_payload: List[dict] = []
        for i, vc in enumerate(self.voice_configs):
            row = self._v2_rows[i] if 0 <= i < len(self._v2_rows) and isinstance(self._v2_rows[i], dict) else {}
            parts = self._parse_voice_name(self._safe_str(vc.name))
            voices_payload.append(
                {
                    "name": self._safe_str(vc.name),
                    "character": self._safe_str(row.get("character")) or parts.get("character", ""),
                    "emotion": self._safe_str(row.get("emotion")) or parts.get("emotion", "default"),
                }
            )
        if not voices_payload:
            InfoBar.warning(
                title="提示",
                content="当前没有可改名的 voice 配置",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2200,
                parent=self,
            )
            return

        self.rename_wizard = VoiceRenameWizard(voices_payload, parent=self)
        if self.rename_wizard.exec_() != self.rename_wizard.Accepted:
            return
        changes = self.rename_wizard.accepted_changes()
        self.apply_rename_changes(changes)

    def apply_rename_changes(self, changes: List[dict]):
        changes = changes or []
        if not changes:
            InfoBar.warning(
                title="未应用",
                content="没有可应用的改名项",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=1800,
                parent=self,
            )
            return

        selected_idx = self._current_row_index()
        selected_old_id = ""
        if 0 <= selected_idx < len(self.voice_configs):
            selected_old_id = self._safe_str(self.voice_configs[selected_idx].name)

        index_by_old: Dict[str, int] = {}
        for i, vc in enumerate(self.voice_configs):
            vid = self._safe_str(vc.name)
            if vid:
                index_by_old[vid] = i

        applied = 0
        skipped = 0
        changed_selected_to = ""
        for ch in changes:
            old_id = self._safe_str((ch or {}).get("old_voice_id"))
            new_id = self._safe_str((ch or {}).get("new_voice_id"))
            new_character = self._safe_str((ch or {}).get("new_character"))
            new_emotion = self._safe_str((ch or {}).get("new_emotion")) or "default"
            idx = index_by_old.get(old_id, -1)
            if idx < 0 or not new_id:
                skipped += 1
                continue
            if self._safe_str(self.voice_configs[idx].name) == new_id:
                skipped += 1
                continue
            self.voice_configs[idx].name = new_id
            if 0 <= idx < len(self._v2_rows) and isinstance(self._v2_rows[idx], dict):
                row = dict(self._v2_rows[idx] or {})
                row["name"] = new_id
                row["character"] = new_character
                row["emotion"] = new_emotion
                self._v2_rows[idx] = row
            applied += 1
            if old_id == selected_old_id:
                changed_selected_to = new_id

        self._refresh_character_filter_items()
        self.update_table()
        if changed_selected_to:
            for i, vc in enumerate(self.voice_configs):
                if self._safe_str(vc.name) == changed_selected_to:
                    self._select_visible_row_by_source_index(i)
                    break
        elif 0 <= selected_idx < len(self.voice_configs):
            self._select_visible_row_by_source_index(selected_idx)
        self._on_table_selection_changed()

        InfoBar.success(
            title="批量改名完成",
            content=f"成功 {applied} 条，跳过 {skipped} 条",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2600,
            parent=self,
        )

    def _set_inspector_visible(self, visible: bool, reason: str = "") -> bool:
        if visible:
            idx = self._current_row_index()
            if not (0 <= idx < len(self.voice_configs)):
                if reason not in {"init_restore", "compact_restore"}:
                    InfoBar.warning(
                        title="提示",
                        content="请先在表格中选择一个 voice",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=2600,
                        parent=self,
                    )
                return False
            forced = self._should_force_collapse_inspector(self.width())
            temporary_open = bool(
                forced
                and int(self.width() or 0) >= int(self._compact_breakpoint_px)
                and reason in {"manual_open", "manual_open_compact"}
            )
            if forced and not temporary_open and reason not in {"manual_open", "manual_open_compact"}:
                return False
            voice_name = str(self.voice_configs[idx].name or "").strip()
            ctx = self._parse_voice_name(voice_name)
            if not ctx.get("voice_id"):
                return False
            row = self._v2_rows[idx] if 0 <= idx < len(self._v2_rows) and isinstance(self._v2_rows[idx], dict) else {}
            ref_ids = row.get("ref_asset_ids") if isinstance(row, dict) else []
            if not isinstance(ref_ids, list):
                ref_ids = []
            self.refs_sheet.set_context(
                character=ctx["character"],
                emotion=ctx["emotion"],
                voice_id=ctx["voice_id"],
                ref_asset_ids=list(ref_ids),
            )
            self.refs_sheet.open_sheet(preferred_width=self._refs_panel_width)
            try:
                width = int(self._refs_panel_width or Metrics.INSPECTOR_W_DEFAULT)
                width = max(Metrics.INSPECTOR_W_MIN, min(Metrics.INSPECTOR_W_MAX, width))
                if temporary_open:
                    allowed = max(300, int(self.width()) - int(self._min_left_table_width))
                    width = max(300, min(width, allowed))
                self.main_splitter.setSizes([max(1, self.width() - width), width])
            except Exception:
                pass
            self._is_temporary_inspector_open = temporary_open
            if not temporary_open:
                self._refs_open_pref = True
                self.refs_sheet.save_ui_state(self.config_manager, is_open=True)
            return True

        self.refs_sheet.close_sheet()
        try:
            self.main_splitter.setSizes([1000, 0])
        except Exception:
            pass
        if reason != "compact_auto":
            if self._is_temporary_inspector_open:
                self.refs_sheet.save_ui_state(self.config_manager, is_open=self._refs_open_pref)
            else:
                self._refs_open_pref = False
                self.refs_sheet.save_ui_state(self.config_manager, is_open=False)
        else:
            self.refs_sheet.save_ui_state(self.config_manager, is_open=self._refs_open_pref)
        self._is_temporary_inspector_open = False
        try:
            row = self.table.currentRow()
            if row >= 0:
                self.table.selectRow(row)
            self.table.setFocus()
        except Exception:
            pass
        return True

    def apply_compact_layout(self, width: int):
        width = int(width or 0)
        force_collapse = self._should_force_collapse_inspector(width)
        compact = width < int(self._compact_breakpoint_px) or force_collapse
        changed_mode = compact != bool(self.is_compact_mode)
        self._apply_compact_columns(compact)
        if compact:
            self.manage_refs_btn.setVisible(False)
            self.open_inspector_btn.setVisible(True)
            if force_collapse and width >= int(self._compact_breakpoint_px):
                self.open_inspector_btn.setText("打开参考面板（临时）")
            else:
                self.open_inspector_btn.setText("打开参考面板")
            if not self.is_compact_mode:
                self.is_compact_mode = True
                self._was_refs_open_before_compact = bool(self.refs_sheet.isVisible() or self._refs_open_pref)
                if self.refs_sheet.isVisible():
                    self._set_inspector_visible(False, reason="compact_auto")
            if changed_mode:
                self.update_table()
            return

        self.manage_refs_btn.setVisible(True)
        self.open_inspector_btn.setVisible(False)
        if self.is_compact_mode:
            self.is_compact_mode = False
            should_restore = bool(self._was_refs_open_before_compact or self._refs_open_pref)
            self._was_refs_open_before_compact = False
            if should_restore:
                self._set_inspector_visible(True, reason="compact_restore")
        if changed_mode:
            self.update_table()

    def _voice_parts_by_source_index(self, source_idx: int) -> Tuple[str, str, str]:
        if not (0 <= source_idx < len(self.voice_configs)):
            return "", "default", ""
        vid = self._normalize_voice_name(self._safe_str(self.voice_configs[source_idx].name))
        if not vid:
            return "", "default", ""
        ch, emo = self._parse_voice_id(vid)
        return ch, emo, vid

    def _visible_row_from_source_index(self, source_idx: int) -> int:
        try:
            return self._visible_source_indexes.index(source_idx)
        except Exception:
            return -1

    def _select_visible_row_by_source_index(self, source_idx: int):
        r = self._visible_row_from_source_index(source_idx)
        if r >= 0:
            try:
                self.table.selectRow(r)
            except Exception:
                pass

    def _is_default_emotion(self, emotion: str) -> bool:
        return self._safe_str(emotion).lower() == "default"

    def _character_filter_selected(self) -> str:
        txt = self._safe_str(self.character_filter_combo.currentText()) if hasattr(self, "character_filter_combo") else ""
        if not txt or txt == "全部角色":
            return ""
        return txt

    def _ordered_source_indexes_for_view(self) -> List[int]:
        selected_character = self._character_filter_selected()
        rows: List[Tuple[str, str, str, int]] = []
        for idx in range(len(self.voice_configs)):
            ch, emo, vid = self._voice_parts_by_source_index(idx)
            if selected_character and ch != selected_character:
                continue
            if not vid:
                continue
            rows.append((self._safe_str(ch), self._safe_str(emo), self._safe_str(vid), idx))

        def _sort_key(x: Tuple[str, str, str, int]):
            ch, emo, vid, _ = x
            return (ch, 0 if self._is_default_emotion(emo) else 1, emo, vid)

        rows.sort(key=_sort_key)
        return [x[3] for x in rows]

    def _refresh_character_filter_items(self):
        if not hasattr(self, "character_filter_combo"):
            return
        cur = self._safe_str(self.character_filter_combo.currentText()) or "全部角色"

        chars: Set[str] = set()
        for idx in range(len(self.voice_configs)):
            ch, _, _ = self._voice_parts_by_source_index(idx)
            if ch:
                chars.add(ch)
        ordered = sorted(chars)

        self.character_filter_combo.blockSignals(True)
        self.character_filter_combo.clear()
        self.character_filter_combo.addItem("全部角色")
        for ch in ordered:
            self.character_filter_combo.addItem(ch)
        if cur in {"全部角色", ""}:
            self.character_filter_combo.setCurrentText("全部角色")
        elif cur in ordered:
            self.character_filter_combo.setCurrentText(cur)
        else:
            self.character_filter_combo.setCurrentText("全部角色")
        self.character_filter_combo.blockSignals(False)

        try:
            self.group_count_label.setText(f"{len(ordered)} 角色")
        except Exception:
            pass

    def on_character_filter_changed(self, _text: str):
        self.update_table()
        self._on_table_selection_changed()

    def _assets_store_or_none(self) -> Optional[AssetsSqliteStore]:
        try:
            return self._assets_store()
        except Exception:
            return None

    def _first_ref_asset_id(self, row: dict) -> str:
        ref_ids = row.get("ref_asset_ids") if isinstance(row, dict) else []
        if not isinstance(ref_ids, list):
            return ""
        for x in ref_ids:
            aid = self._safe_str(x)
            if aid:
                return aid
        return ""

    def _resolve_prompt_audio_from_row(self, row: dict) -> Tuple[str, str]:
        """
        Resolve prompt audio path for display/compat:
        1) existing prompt_audio if non-empty and exists
        2) first resolvable ref_asset_ids -> assets.path
        """
        if not isinstance(row, dict):
            return "", ""

        p = self._safe_str(row.get("prompt_audio"))
        if p and os.path.exists(p):
            return os.path.abspath(p), self._first_ref_asset_id(row)

        ref_ids = row.get("ref_asset_ids") or []
        if not isinstance(ref_ids, list):
            ref_ids = []

        store = self._assets_store_or_none()
        for x in ref_ids:
            aid = self._safe_str(x)
            if not aid:
                continue
            meta = None
            if store is not None:
                try:
                    meta = store.get(aid)
                except Exception:
                    meta = None
            if not isinstance(meta, dict):
                try:
                    meta = self._v2_client().get_asset_meta(aid)
                except Exception:
                    meta = None
            if isinstance(meta, dict):
                mp = self._safe_str(meta.get("path"))
                if mp and os.path.exists(mp):
                    return os.path.abspath(mp), aid
        return "", self._first_ref_asset_id(row)

    def _sync_prompt_audio_from_row(self, source_idx: int):
        if not (0 <= source_idx < len(self._v2_rows)):
            return
        row = self._v2_rows[source_idx] if isinstance(self._v2_rows[source_idx], dict) else {}
        resolved_path, _ = self._resolve_prompt_audio_from_row(row)
        if resolved_path:
            row["prompt_audio"] = resolved_path
            self._v2_rows[source_idx] = row
            if 0 <= source_idx < len(self.voice_configs):
                self.voice_configs[source_idx].prompt_audio = resolved_path
        else:
            if 0 <= source_idx < len(self.voice_configs):
                self.voice_configs[source_idx].prompt_audio = self._safe_str(row.get("prompt_audio"))

    def _backfill_done_paths(self) -> Set[str]:
        try:
            raw = self.config_manager.get("ui_v2_prompt_audio_backfill_done_paths", []) or []
        except Exception:
            raw = []
        out: Set[str] = set()
        if isinstance(raw, list):
            for p in raw:
                s = self._safe_str(p)
                if s:
                    out.add(s)
        return out

    def _phase_c_backfill_prompt_audio_once(self, path: str, backfilled_count: int):
        if backfilled_count <= 0:
            return
        norm = os.path.normcase(os.path.abspath(path or ""))
        if not norm:
            return
        done = self._backfill_done_paths()
        if norm in done:
            return
        try:
            self._save_v2_voices_to(path)
            done.add(norm)
            self.config_manager.set("ui_v2_prompt_audio_backfill_done_paths", sorted(done))
            InfoBar.success(
                title="已修复参考音频路径",
                content=f"已为 {backfilled_count} 条 voice 回填主参考路径",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self,
            )
        except Exception as e:
            print(f"phase C prompt_audio backfill failed: {e}")

    def _current_row_index(self) -> int:
        try:
            r = int(self.table.currentRow())
        except Exception:
            r = -1
        if 0 <= r < len(self._visible_source_indexes):
            return self._visible_source_indexes[r]
        if r < 0 and self.table.selectedIndexes():
            try:
                r = int(self.table.selectedIndexes()[0].row())
            except Exception:
                r = -1
        if 0 <= r < len(self._visible_source_indexes):
            return self._visible_source_indexes[r]
        return -1

    def _parse_voice_name(self, voice_name: str) -> Dict[str, str]:
        vid = (voice_name or "").strip()
        if not vid:
            return {"character": "", "emotion": "", "voice_id": ""}
        if "#" in vid:
            ch, emo = vid.split("#", 1)
            ch = (ch or "").strip()
            emo = (emo or "").strip() or "default"
            return {"character": ch, "emotion": emo, "voice_id": self.compose_voice_id(ch, emo)}
        return {"character": vid, "emotion": "default", "voice_id": self.compose_voice_id(vid, "default")}

    def _on_table_selection_changed(self):
        self._update_v2_path_label()

        idx = self._current_row_index()
        if not (0 <= idx < len(self._v2_rows)):
            try:
                self.refs_summary_label.setText("参考池：-")
                self.main_ref_status_label.setText("主参考：-")
                self.main_ref_status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
                self.manage_refs_btn.setEnabled(False)
                self.open_inspector_btn.setEnabled(False)
                self.selected_ref_label.setText("当前选中参考音频：<无>")
                self.selected_ref_label.setToolTip("")
            except Exception:
                pass
            return

        self.manage_refs_btn.setEnabled(True)
        self.open_inspector_btn.setEnabled(True)
        row = self._v2_rows[idx] if 0 <= idx < len(self._v2_rows) else {}
        ref_ids = row.get("ref_asset_ids") if isinstance(row, dict) else []
        if not isinstance(ref_ids, list):
            ref_ids = []
        self.refs_summary_label.setText(f"参考池：{len(ref_ids)} 条")
        primary_path, primary_aid = self._resolve_prompt_audio_from_row(row if isinstance(row, dict) else {})
        if primary_aid and primary_path:
            self.main_ref_status_label.setText(f"主参考：可用（{primary_aid}）")
            self.main_ref_status_label.setToolTip(primary_path)
            self.main_ref_status_label.setStyleSheet(f"color: {Palette.SUCCESS};")
        elif primary_aid and not primary_path:
            self.main_ref_status_label.setText(f"主参考：缺失（{primary_aid}）")
            self.main_ref_status_label.setToolTip("资产记录存在但本地路径不可用")
            self.main_ref_status_label.setStyleSheet(f"color: {Palette.DANGER};")
        elif ref_ids:
            self.main_ref_status_label.setText("主参考：未解析")
            self.main_ref_status_label.setToolTip("ref_asset_ids 存在，但未能解析到可用 path")
            self.main_ref_status_label.setStyleSheet(f"color: {Palette.WARNING};")
        else:
            self.main_ref_status_label.setText("主参考：未绑定")
            self.main_ref_status_label.setToolTip("")
            self.main_ref_status_label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")

        if self.refs_sheet.isVisible():
            voice_name = str(self.voice_configs[idx].name if 0 <= idx < len(self.voice_configs) else "")
            ctx = self._parse_voice_name(voice_name)
            if ctx.get("voice_id"):
                self.refs_sheet.set_context(
                    character=ctx["character"],
                    emotion=ctx["emotion"],
                    voice_id=ctx["voice_id"],
                    ref_asset_ids=list(ref_ids),
                )

    def open_refs_sheet_for_current_row(self):
        reason = "manual_open_compact" if self.is_compact_mode else "manual_open"
        self._set_inspector_visible(True, reason=reason)

    def close_refs_sheet(self):
        self._set_inspector_visible(False, reason="manual_close")

    def _on_ref_pool_changed(self, voice_id: str, ref_asset_ids: object):
        idx = -1
        vid = self._safe_str(voice_id)
        if vid:
            for i, vc in enumerate(self.voice_configs):
                if self._normalize_voice_name(self._safe_str(vc.name)) == vid:
                    idx = i
                    break
        if idx < 0:
            idx = self._current_row_index()
        if not (0 <= idx < len(self._v2_rows)):
            return
        if not isinstance(ref_asset_ids, list):
            ref_asset_ids = []
        row = self._v2_rows[idx] if 0 <= idx < len(self._v2_rows) else {}
        if isinstance(row, dict):
            row["ref_asset_ids"] = list(ref_asset_ids)
            self._v2_rows[idx] = row
        self._sync_prompt_audio_from_row(idx)
        self._persist_current_v2_voices_quiet()
        self.update_table()
        self._select_visible_row_by_source_index(idx)
        self._on_table_selection_changed()

    def _on_selected_asset_changed(self, asset: object):
        idx = self._current_row_index()
        if not (0 <= idx < len(self.voice_configs)):
            return
        if not isinstance(asset, dict):
            self.selected_ref_label.setText("当前选中参考音频：<无>")
            self.selected_ref_label.setToolTip("")
            return

        aid = str(asset.get("asset_id") or "").strip()
        note = str(asset.get("note") or "").strip()
        emo = str(asset.get("emotion") or "").strip() or "default"
        label = f"当前选中参考音频：{emo} / {aid} / {note if note else '<无备注>'}"
        self.selected_ref_label.setText(label)
        self.selected_ref_label.setToolTip(label)

        new_text = note or str(asset.get("prompt_text") or "").strip()
        if not new_text:
            return
        try:
            vr = self._visible_row_from_source_index(idx)
            w = self.table.cellWidget(vr, 2) if vr >= 0 else None
            if isinstance(w, QPlainTextEdit):
                w.setPlainText(new_text)
            elif isinstance(w, BodyLabel):
                w.setText(new_text)
                w.setToolTip(new_text)
        except Exception:
            pass

    def keyPressEvent(self, event):
        try:
            if (event.modifiers() & Qt.ControlModifier) and event.key() == Qt.Key_Z:
                if self._pending_delete:
                    self.undo_pending_delete()
                    event.accept()
                    return
            if event.key() == Qt.Key_Escape and self.refs_sheet.isVisible():
                self.close_refs_sheet()
                event.accept()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def add_config(self):
        if not self.is_edit_mode:
            return
        config = VoiceConfig(
            name=f"新角色{len(self.voice_configs) + 1}#default",
            mode="零样本复制",
            color=f"#{hash(f'config{len(self.voice_configs)}') % 0xFFFFFF:06x}"
        )
        self.voice_configs.append(config)
        self._v2_rows.append({})
        self.update_table()
    

    def update_table(self):
        selected_source_idx = self._current_row_index()
        visible = self._ordered_source_indexes_for_view()
        self._visible_source_indexes = list(visible)
        self.table.setRowCount(len(visible))
        row_h = 48 if self.is_compact_mode else (56 if int(self._ref_text_wrap_lines) >= 2 else Metrics.TABLE_ROW_H)

        for i, source_idx in enumerate(visible):
            config = self.voice_configs[source_idx]
            self._sync_prompt_audio_from_row(source_idx)
            self.table.setRowHeight(i, row_h)

            # 角色 / 情绪（摘要 + 弹层编辑）
            parts = self._parse_voice_name(config.name)
            name_widget = QWidget()
            name_layout = QVBoxLayout(name_widget)
            name_layout.setContentsMargins(4, 2, 4, 2)
            name_layout.setSpacing(1)

            top_row = QHBoxLayout()
            top_row.setContentsMargins(0, 0, 0, 0)
            top_row.setSpacing(Table.COLUMN_GAP_DENSE)
            ch_label = BodyLabel(parts["character"] or "<未命名>")
            ch_label.setStyleSheet(f"color: {Palette.TEXT_PRIMARY}; font-weight: 600;")
            top_row.addWidget(ch_label)
            emo_label = BodyLabel(parts["emotion"] or "default")
            emo_txt = self._safe_str(parts["emotion"] or "default")
            if len(emo_txt) > 12:
                emo_label.setText(f"{emo_txt[:11]}…")
                emo_label.setToolTip(emo_txt)
            emo_label.setMaximumWidth(96)
            emo_label.setStyleSheet(
                f"color: {Palette.TEXT_SECONDARY}; background: {Palette.TAG_BG}; border: 1px solid {Palette.BORDER};"
                f" border-radius: 8px; padding: 0 6px;"
            )
            top_row.addWidget(emo_label)
            top_row.addStretch()
            if self.is_edit_mode:
                edit_btn = ToolButton(FluentIcon.EDIT)
                edit_btn.setToolTip("编辑角色和情绪")
                edit_btn.clicked.connect(lambda _=False, idx=source_idx: self.open_voice_inline_editor(idx))
                self.setup_widget_context_menu(edit_btn, source_idx)
                top_row.addWidget(edit_btn)
            name_layout.addLayout(top_row)

            voice_id_label = BodyLabel(parts["voice_id"] or "<无效 voice_id>")
            voice_id_label.setStyleSheet(f"color: {Palette.TEXT_MUTED}; font-size: 10px;")
            if not self.is_compact_mode:
                name_layout.addWidget(voice_id_label)
            else:
                name_widget.setToolTip(parts["voice_id"] or "")
            self.setup_widget_context_menu(name_widget, source_idx)
            self.table.setCellWidget(i, 0, name_widget)
            
            # 模式
            mode_combo = ComboBox()
            mode_combo.addItems(["零样本复制", "参考音色", "精细控制", "指令控制"])
            mode_combo.setCurrentText(config.mode)
            mode_combo.setEnabled(self.is_edit_mode)
            mode_combo.setFixedHeight(Metrics.CONTROL_H)
            mode_combo.currentTextChanged.connect(lambda text, idx=source_idx: self.update_config_mode(idx, text))
            self.setup_widget_context_menu(mode_combo, source_idx)
            self.table.setCellWidget(i, 1, mode_combo)
            
            # 参考文本（两行可读）
            self.table.setCellWidget(i, 2, self._render_prompt_text_cell(source_idx, config.prompt_text))
            # 主参考（状态化 + 文件名 + 打开目录）
            self.table.setCellWidget(i, 3, self._render_main_ref_cell(source_idx))
            
            # 指令文本
            instruct_edit = LineEdit()
            instruct_edit.setText(config.instruct_text)
            instruct_edit.setReadOnly(not self.is_edit_mode)
            instruct_edit.setFixedHeight(Metrics.CONTROL_H)
            instruct_edit.textChanged.connect(lambda text, idx=source_idx: self.update_config_instruct_text(idx, text))
            self.setup_widget_context_menu(instruct_edit, source_idx)
            self.table.setCellWidget(i, 4, instruct_edit)
            
            # 颜色
            color_widget = QWidget()
            color_layout = QHBoxLayout(color_widget)
            color_layout.setContentsMargins(0, 0, 0, 0)
            color_layout.setAlignment(Qt.AlignCenter)
            
            color_button = PushButton()
            color_button.setFixedSize(22 if self.is_compact_mode else 50, Metrics.CONTROL_H)
            color_button.setCursor(Qt.PointingHandCursor)
            color_button.setEnabled(self.is_edit_mode)
            # 圆角矩形样式
            color_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {config.color};
                    border: 1px solid {Palette.BORDER};
                    border-radius: {8 if self.is_compact_mode else 10}px;
                }}
                QPushButton:hover {{
                    border: 1px solid #d0d0d0;
                }}
            """)
            color_button.clicked.connect(lambda checked, idx=source_idx: self.choose_color(idx))
            self.setup_widget_context_menu(color_button, source_idx)
            
            color_layout.addWidget(color_button)
            self.table.setCellWidget(i, 5, color_widget)

        self._refresh_character_filter_items()
        if selected_source_idx >= 0 and selected_source_idx in self._visible_source_indexes:
            self._select_visible_row_by_source_index(selected_source_idx)
        elif self._visible_source_indexes:
            self.table.selectRow(0)

    def setup_widget_context_menu(self, widget, row_index):
        """为子控件设置右键菜单"""
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget, r=row_index: self.on_child_context_menu(pos, w, r)
        )

    def on_child_context_menu(self, pos, widget, row_index):
        """处理子控件的右键菜单"""
        # 选中当前行
        self._select_visible_row_by_source_index(row_index)
        
        menu = RoundMenu(parent=self)
        has_action = False
        
        # 如果是文本框，添加标准文本操作
        if isinstance(widget, LineEdit):
            if self.is_edit_mode and not widget.isReadOnly():
                menu.addAction(Action(FluentIcon.CUT, "剪切", triggered=widget.cut))
                has_action = True
            menu.addAction(Action(FluentIcon.COPY, "复制", triggered=widget.copy))
            has_action = True
            if self.is_edit_mode and not widget.isReadOnly():
                menu.addAction(Action(FluentIcon.PASTE, "粘贴", triggered=widget.paste))
                has_action = True
        elif isinstance(widget, QPlainTextEdit):
            if self.is_edit_mode and not widget.isReadOnly():
                menu.addAction(Action(FluentIcon.CUT, "剪切", triggered=widget.cut))
                has_action = True
            menu.addAction(Action(FluentIcon.COPY, "复制", triggered=widget.copy))
            has_action = True
            if self.is_edit_mode and not widget.isReadOnly():
                menu.addAction(Action(FluentIcon.PASTE, "粘贴", triggered=widget.paste))
                has_action = True

        if self.is_edit_mode:
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.ADD, "在上方插入配置", self, triggered=lambda: self.insert_config(row_index)))
            menu.addAction(Action(FluentIcon.ADD, "在下方插入配置", self, triggered=lambda: self.insert_config(row_index + 1)))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.UP, "上移", self, triggered=lambda: self.move_config(row_index, -1)))
            menu.addAction(Action(FluentIcon.DOWN, "下移", self, triggered=lambda: self.move_config(row_index, 1)))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.DELETE, "删除配置", self, triggered=lambda: self.request_delete_config(row_index)))
            has_action = True
        if has_action:
            menu.exec_(widget.mapToGlobal(pos))
    
    def update_config_name(self, index: int, name: str):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            self.voice_configs[index].name = name
            if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                self._v2_rows[index]["name"] = name
    
    def update_config_mode(self, index: int, mode: str):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            self.voice_configs[index].mode = mode
            if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                self._v2_rows[index]["mode"] = mode
    
    def update_config_prompt_text(self, index: int, text: str):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            self.voice_configs[index].prompt_text = text
            if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                self._v2_rows[index]["prompt_text"] = text
    
    def update_config_prompt_audio(self, index: int, audio: str):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            self.voice_configs[index].prompt_audio = audio
            if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                self._v2_rows[index]["prompt_audio"] = audio
    
    def update_config_instruct_text(self, index: int, text: str):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            self.voice_configs[index].instruct_text = text
            if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                self._v2_rows[index]["instruct_text"] = text
    
    def browse_audio_file(self, index: int):
        if not self.is_edit_mode:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "", 
            "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*)"
        )
        if file_path and 0 <= index < len(self.voice_configs):
            # Import into v2 assets store so it can be managed via the voice-settings inspector.
            try:
                meta = self._import_ref_audio_for_row(index=index, source_path=file_path)
                self.voice_configs[index].prompt_audio = meta.get("path", file_path)
            except Exception as e:
                # Fallback: keep direct path so the voice still works, but it won't appear in assets list.
                self.voice_configs[index].prompt_audio = file_path
                InfoBar.warning(
                    title="导入参考音频失败",
                    content=f"将直接使用文件路径（不会进入资产库）: {str(e)}",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4500,
                    parent=self,
                )
            self.update_table()
            self._select_visible_row_by_source_index(index)
    
    def choose_color(self, index: int):
        if not self.is_edit_mode:
            return
        if 0 <= index < len(self.voice_configs):
            color = QColorDialog.getColor(QColor(self.voice_configs[index].color), self)
            if color.isValid():
                self.voice_configs[index].color = color.name()
                if 0 <= index < len(self._v2_rows) and isinstance(self._v2_rows[index], dict):
                    self._v2_rows[index]["color"] = color.name()
                self.update_table()


    def insert_config(self, index: int):
        """插入配置"""
        if not self.is_edit_mode:
            return
        config = VoiceConfig(
            name=f"新角色{len(self.voice_configs) + 1}#default",
            mode="零样本复制",
            color=f"#{hash(f'config{len(self.voice_configs)}') % 0xFFFFFF:06x}"
        )
        
        if 0 <= index <= len(self.voice_configs):
            self.voice_configs.insert(index, config)
            self._v2_rows.insert(index, {})
        else:
            self.voice_configs.append(config)
            self._v2_rows.append({})
            
        self.update_table()

    def move_config(self, index: int, direction: int):
        """移动配置"""
        if not self.is_edit_mode:
            return
        new_index = index + direction
        if 0 <= index < len(self.voice_configs) and 0 <= new_index < len(self.voice_configs):
            self.voice_configs[index], self.voice_configs[new_index] = self.voice_configs[new_index], self.voice_configs[index]
            if 0 <= index < len(self._v2_rows) and 0 <= new_index < len(self._v2_rows):
                self._v2_rows[index], self._v2_rows[new_index] = self._v2_rows[new_index], self._v2_rows[index]
            self.update_table()
            self._select_visible_row_by_source_index(new_index)

    def request_delete_config(self, index: int):
        if not self.is_edit_mode:
            return
        if not (0 <= index < len(self.voice_configs)):
            return
        voice_id = self._safe_str(self.voice_configs[index].name)
        ret = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除配置 \"{voice_id}\" 吗？\n你可以在 8 秒内撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self.delete_config(index)

    def delete_config(self, index: int):
        """软删除：8 秒内可撤销"""
        if not (0 <= index < len(self.voice_configs)):
            return
        self._commit_pending_delete()

        deleted_cfg = self.voice_configs.pop(index)
        deleted_row = self._v2_rows.pop(index) if 0 <= index < len(self._v2_rows) else {}
        self._pending_delete = {
            "index": int(index),
            "voice_config": deleted_cfg,
            "v2_row": deleted_row,
        }
        self.update_table()
        self.undo_delete_btn.setVisible(True)
        self._delete_timer.start(8000)

        InfoBar.warning(
            title="已删除配置",
            content=f"{self._safe_str(deleted_cfg.name)}（8 秒内可撤销）",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self,
        )

    def undo_pending_delete(self):
        pending = self._pending_delete
        if not isinstance(pending, dict):
            return
        self._delete_timer.stop()
        idx = int(pending.get("index", len(self.voice_configs)))
        cfg = pending.get("voice_config")
        row = pending.get("v2_row")
        if cfg is not None:
            idx = max(0, min(idx, len(self.voice_configs)))
            self.voice_configs.insert(idx, cfg)
            self._v2_rows.insert(idx, row if isinstance(row, dict) else {})
            self.update_table()
            self._select_visible_row_by_source_index(idx)
        self._pending_delete = None
        self.undo_delete_btn.setVisible(False)
        InfoBar.success(
            title="已撤销",
            content="配置已恢复",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=1800,
            parent=self,
        )

    def _commit_pending_delete(self):
        if not self._pending_delete:
            return
        self._pending_delete = None
        self.undo_delete_btn.setVisible(False)

    def save_config(self, file_path=None):
        self._commit_pending_delete()
        # v2-first: save/load operate on v2 voices config file.
        if not file_path:
            default_name = "voices_v2.json"
            try:
                current = (self.config_manager.get("v2_voices_config_path", "") or "").strip()
            except Exception:
                current = ""
            if current:
                default_name = os.path.basename(current)
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存 v2 voices 配置",
                str(self.config_dir / default_name),
                "JSON文件 (*.json);;所有文件 (*)",
            )

        if not file_path:
            return

        try:
            self._save_v2_voices_to(file_path)
            self.config_manager.set("v2_voices_config_path", os.path.abspath(file_path))
            self._maybe_reload_v2_server_voices()
            InfoBar.success(
                title="保存成功",
                content="v2 voices 配置已保存",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                title="保存失败",
                content=f"保存 v2 voices 配置时发生错误: {str(e)}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
    
    def load_config(self, file_path=None):
        self._commit_pending_delete()
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "加载 v2 voices 配置",
                str(self.config_dir),
                "JSON文件 (*.json);;所有文件 (*)",
            )

        if not file_path or not os.path.exists(file_path):
            return

        try:
            self.config_manager.set("v2_voices_config_path", os.path.abspath(file_path))
            self.load_v2_voices()
            self._maybe_reload_v2_server_voices()
            self.config_loaded.emit()
            InfoBar.success(
                title="加载成功",
                content="v2 voices 配置已加载并自动应用",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                title="加载失败",
                content=f"加载 v2 voices 配置时发生错误: {str(e)}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
    
    def apply_config(self):
        self._commit_pending_delete()
        # Auto-save to current v2 voices file.
        try:
            v2_path = (self.config_manager.get("v2_voices_config_path", "") or "").strip()
        except Exception:
            v2_path = ""
        if not v2_path:
            v2_path = os.path.abspath("./config/voices_v2.json")
            self.config_manager.set("v2_voices_config_path", v2_path)

        try:
            self._save_v2_voices_to(v2_path)
            self._maybe_reload_v2_server_voices()
        except Exception as e:
            print(f"Auto-save v2 voices failed: {e}")

        InfoBar.success(
            title="应用成功",
            content="v2 voices 配置已应用并保存",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )
    
    def get_voice_configs(self) -> Dict[str, VoiceConfig]:
        return {config.name: config for config in self.voice_configs}

    def _v2_voices_path(self) -> str:
        return self._voice_store.voices_path()

    def load_v2_voices(self):
        """Load v2 voices JSON into this legacy table model while preserving raw dict fields."""
        path = self._v2_voices_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        items = self._voice_store.list_voices(path=path)

        self.voice_configs = []
        self._v2_rows = []
        backfilled_count = 0
        for v in items:
            name = str(v.get("name") or "").strip()
            if not name:
                continue
            row = dict(v)
            ch, emo = self._parse_voice_id(name)
            row["character"] = self._safe_str(row.get("character")) or ch
            row["emotion"] = self._safe_str(row.get("emotion")) or emo
            resolved_path, _ = self._resolve_prompt_audio_from_row(row)
            if resolved_path and not self._safe_str(row.get("prompt_audio")):
                row["prompt_audio"] = resolved_path
                backfilled_count += 1
            vc = VoiceConfig(
                name=name,
                mode=str(v.get("mode") or "零样本复制"),
                prompt_text=str(v.get("prompt_text") or ""),
                prompt_audio=str(resolved_path or row.get("prompt_audio") or ""),
                instruct_text=str(v.get("instruct_text") or ""),
                color=str(v.get("color") or "#FF6B6B"),
            )
            self.voice_configs.append(vc)
            self._v2_rows.append(row)

        self._refresh_character_filter_items()
        self.update_table()
        # Phase C: one-time persist backfilled prompt_audio paths for compatibility.
        self._phase_c_backfill_prompt_audio_once(path, backfilled_count)

    def _parse_voice_id(self, voice_id: str) -> tuple[str, str]:
        voice_id = (voice_id or "").strip()
        if "#" in voice_id:
            ch, emo = voice_id.split("#", 1)
            return (ch.strip(), (emo or "default").strip() or "default")
        return (voice_id, "default")

    def _normalize_voice_name(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        if "#" not in name:
            return f"{name}#default"
        ch, emo = name.split("#", 1)
        ch = ch.strip()
        emo = (emo or "default").strip() or "default"
        return f"{ch}#{emo}" if ch else name

    def _assets_store(self) -> AssetsSqliteStore:
        os.makedirs(os.path.dirname(self._v2_assets_db_path), exist_ok=True)
        os.makedirs(self._v2_assets_dir, exist_ok=True)
        return AssetsSqliteStore(self._v2_assets_db_path)

    def _sha1_file(self, path: str) -> str:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _import_ref_audio_for_row(self, *, index: int, source_path: str) -> dict:
        """Import one audio file into v2 assets and bind it to this voice row (ref_asset_ids + prompt_audio)."""
        if not (0 <= index < len(self.voice_configs)):
            raise IndexError("row index out of range")
        source_path = os.path.abspath(source_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(source_path)

        while len(self._v2_rows) < len(self.voice_configs):
            self._v2_rows.append({})

        row = dict(self._v2_rows[index] or {})
        voice_id = self._normalize_voice_name(self.voice_configs[index].name)
        character, emotion = self._parse_voice_id(voice_id)

        store = self._assets_store()
        sha1 = self._sha1_file(source_path)

        # Best-effort dedupe by sha1 within (character, emotion).
        for meta in store.list(character=character, emotion=emotion, kind="ref", limit=5000):
            if (meta.get("sha1") or "") == sha1 and os.path.exists(meta.get("path") or ""):
                aid = str(meta.get("asset_id") or "").strip()
                if aid:
                    row.setdefault("ref_asset_ids", [])
                    if not isinstance(row.get("ref_asset_ids"), list):
                        row["ref_asset_ids"] = []
                    if aid not in row["ref_asset_ids"]:
                        row["ref_asset_ids"].append(aid)
                    row["prompt_audio"] = meta.get("path")
                    row["character"] = character
                    row["emotion"] = emotion
                    row["name"] = voice_id
                    row.setdefault("selection_policy", "random_per_text")
                    self._v2_rows[index] = row
                    self.voice_configs[index].name = voice_id
                    return meta

        ext = os.path.splitext(source_path)[1].lower() or ".wav"
        asset_id = f"ref_{uuid.uuid4().hex[:12]}"
        out_path = os.path.abspath(os.path.join(self._v2_assets_dir, f"{asset_id}{ext}"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.copy2(source_path, out_path)

        meta = {
            "asset_id": asset_id,
            "kind": "ref",
            "filename": os.path.basename(source_path),
            "path": out_path,
            "size": int(os.path.getsize(out_path)),
            "sha1": sha1,
            "created_at": int(time.time()),
            "character": character,
            "emotion": emotion,
            "language": row.get("language") or "zh",
            "note": row.get("note") or "",
            "linked": 1,
        }
        store.upsert(meta)

        row.setdefault("ref_asset_ids", [])
        if not isinstance(row.get("ref_asset_ids"), list):
            row["ref_asset_ids"] = []
        if asset_id not in row["ref_asset_ids"]:
            row["ref_asset_ids"].append(asset_id)
        row["prompt_audio"] = out_path
        row["character"] = character
        row["emotion"] = emotion
        row["name"] = voice_id
        row.setdefault("selection_policy", "random_per_text")

        self._v2_rows[index] = row
        self.voice_configs[index].name = voice_id
        return meta

    def _save_v2_voices_to(self, path: str) -> None:
        path = os.path.abspath(path)
        while len(self._v2_rows) < len(self.voice_configs):
            self._v2_rows.append({})
        if len(self._v2_rows) > len(self.voice_configs):
            self._v2_rows = self._v2_rows[: len(self.voice_configs)]

        out: List[dict] = []
        for i, vc in enumerate(self.voice_configs):
            row = dict(self._v2_rows[i] or {})
            voice_id = self._normalize_voice_name(vc.name)
            if not voice_id:
                continue
            character, emotion = self._parse_voice_id(voice_id)

            row["name"] = voice_id
            row["character"] = row.get("character") or character
            row["emotion"] = row.get("emotion") or emotion
            row["mode"] = vc.mode
            row["prompt_text"] = vc.prompt_text
            row["instruct_text"] = vc.instruct_text
            row["color"] = vc.color
            row.setdefault("selection_policy", "random_per_text")

            if "ref_asset_ids" in row and not isinstance(row.get("ref_asset_ids"), list):
                row["ref_asset_ids"] = []

            # Phase A: if ref pool exists, resolve primary ref path as compatibility prompt_audio.
            if not self._safe_str(row.get("prompt_audio")):
                resolved_path, _ = self._resolve_prompt_audio_from_row(row)
                if resolved_path:
                    row["prompt_audio"] = resolved_path
                    vc.prompt_audio = resolved_path

            # If user typed or loaded a prompt_audio outside assets dir, import it once.
            p = (vc.prompt_audio or "").strip()
            if p and os.path.exists(p):
                p_abs = os.path.abspath(p)
                assets_dir_abs = os.path.abspath(self._v2_assets_dir)
                if not p_abs.startswith(assets_dir_abs):
                    meta = self._import_ref_audio_for_row(index=i, source_path=p_abs)
                    vc.prompt_audio = meta.get("path", vc.prompt_audio)
                    row["prompt_audio"] = vc.prompt_audio
                else:
                    row["prompt_audio"] = p_abs
            else:
                fallback_p = (row.get("prompt_audio") or vc.prompt_audio or "").strip()
                if not fallback_p:
                    resolved_path, _ = self._resolve_prompt_audio_from_row(row)
                    fallback_p = resolved_path
                row["prompt_audio"] = fallback_p

            out.append(row)
            self._v2_rows[i] = row
            vc.name = voice_id
            vc.prompt_audio = self._safe_str(row.get("prompt_audio"))

        self._voice_store.save_rows(out, path=path)

    def _maybe_reload_v2_server_voices(self):
        """
        Best-effort: if the embedded API server is running, reload voices from disk so
        /api/v2/voices reflects latest changes immediately.
        """
        try:
            cli = self._v2_client()
            cli.cfg.timeout_s = 0.8
            cli.reload_voices()
        except Exception:
            # Server might be stopped; ignore.
            pass
        self._refresh_api_status()

    def _persist_current_v2_voices_quiet(self):
        try:
            v2_path = self._v2_voices_path()
            self._save_v2_voices_to(v2_path)
            self._maybe_reload_v2_server_voices()
        except Exception as e:
            print(f"persist current v2 voices failed: {e}")

    def import_legacy_to_v2(self):
        """Import legacy config/config.json voices into current v2 voices + v2 assets store."""
        legacy_default = os.path.abspath("./config/config.json")
        legacy_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择旧 voices 配置（legacy）",
            os.path.dirname(legacy_default),
            "JSON文件 (*.json);;所有文件 (*)",
        )
        if not legacy_path:
            return

        v2_path = self._v2_voices_path()
        os.makedirs(os.path.dirname(v2_path), exist_ok=True)
        os.makedirs(os.path.dirname(self._v2_assets_db_path), exist_ok=True)
        os.makedirs(self._v2_assets_dir, exist_ok=True)

        self.tools_btn.setEnabled(False)
        self.import_worker = LegacyImportWorker(
            legacy_path=os.path.abspath(legacy_path),
            v2_path=os.path.abspath(v2_path),
            db_path=os.path.abspath(self._v2_assets_db_path),
            assets_dir=os.path.abspath(self._v2_assets_dir),
        )
        self.import_worker.finished.connect(self._on_import_finished)
        self.import_worker.error.connect(self._on_import_error)
        self.import_worker.start()

    def _on_import_finished(self, res: dict):
        self.tools_btn.setEnabled(True)

        try:
            imported_voices = int(res.get("imported_voices") or 0)
            imported_assets = int(res.get("imported_assets") or 0)
            skipped_assets = int(res.get("skipped_assets") or 0)
            errors = res.get("errors") or []
        except Exception:
            imported_voices, imported_assets, skipped_assets, errors = 0, 0, 0, []

        self.load_v2_voices()
        self.config_loaded.emit()
        self._maybe_reload_v2_server_voices()

        msg = f"已导入 voices: {imported_voices}，参考音频资产: {imported_assets}，跳过: {skipped_assets}"
        if errors:
            msg += f"（错误 {len(errors)} 条，详见控制台）"
            for e in errors[:20]:
                print(f"[legacy import] {e}")

        InfoBar.success(
            title="导入完成",
            content=msg,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4500,
            parent=self,
        )

    def _on_import_error(self, err: str):
        self.tools_btn.setEnabled(True)
        InfoBar.error(
            title="导入失败",
            content=str(err),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def resizeEvent(self, event):
        try:
            w = int(event.size().width()) if event is not None else int(self.width())
            self.apply_compact_layout(w)
        except Exception:
            pass
        super().resizeEvent(event)

    def closeEvent(self, event):
        try:
            self._delete_timer.stop()
        except Exception:
            pass
        try:
            self.config_manager.set("ui_voice_settings_show_path_full", bool(self._show_path_full))
            self.config_manager.set("ui_voice_settings_compact_hidden_columns", list(self._compact_hidden_columns))
            self.config_manager.set("ui_voice_settings_min_left_table_width", int(self._min_left_table_width))
            self.config_manager.set("ui_voice_settings_auto_collapse_inspector", bool(self._auto_collapse_inspector))
            self.config_manager.set("ui_voice_settings_ref_text_wrap_lines", int(self._ref_text_wrap_lines))
            self.config_manager.set("ui_voice_settings_show_full_prompt_audio_path", bool(self._show_full_prompt_audio_path))
            self.config_manager.set("ui_voice_settings_compile_all_refs", bool(self._compile_all_refs))
        except Exception:
            pass
        try:
            self.refs_sheet.save_ui_state(self.config_manager, is_open=self._refs_open_pref)
        except Exception:
            pass
        for w in list(self._api_workers):
            try:
                if w.isRunning() and not w.wait(2000):
                    w.terminate()
                    w.wait(500)
            except Exception:
                pass
        self._api_workers = []
        self._commit_pending_delete()
        super().closeEvent(event)

    def compile_current_voice_v2(self):
        idx = self._current_row_index()
        if not (0 <= idx < len(self.voice_configs)):
            InfoBar.warning(
                title="提示",
                content="请先在表格中选择一个 voice",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2200,
                parent=self,
            )
            return
        voice_id = self._normalize_voice_name(self._safe_str(self.voice_configs[idx].name))
        if not voice_id:
            InfoBar.warning(
                title="提示",
                content="当前 voice_id 无效，无法编译",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2200,
                parent=self,
            )
            return

        self._commit_pending_delete()
        try:
            self._persist_current_v2_voices_quiet()
        except Exception:
            pass

        self.compile_button.setEnabled(False)
        self.compile_button.setText("编译中...")

        compile_all = bool(self._compile_all_refs)

        def _do():
            return self._v2_client().compile_voice(voice_id, compile_all=compile_all)

        def _ok(res: object):
            self.compile_button.setEnabled(True)
            self.compile_button.setText("编译当前 voice")
            compiled = []
            if isinstance(res, dict):
                compiled = list((res or {}).get("compiled") or [])
            InfoBar.success(
                title="编译完成",
                content=f"{voice_id} / compiled={len(compiled)} / {'全部参考' if compile_all else '主参考'}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4200,
                parent=self,
            )
            self._refresh_api_status()

        def _err(e: object):
            self.compile_button.setEnabled(True)
            self.compile_button.setText("编译当前 voice")
            InfoBar.error(
                title="编译失败",
                content=self._err_text(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
            self._refresh_api_status()

        self._run_api_task(_do, _ok, _err)
