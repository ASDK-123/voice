from typing import Callable, Dict, List, Optional

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout

from qfluentwidgets import BodyLabel, FluentIcon, SubtitleLabel, ToolButton

from ..theme.tokens import Metrics, Palette, Spacing
from ..v2_client import V2Client
from .emotion_assets_panel import EmotionAssetsPanel


class VoiceRefsSheet(QFrame):
    """
    A right-side sheet container that embeds EmotionAssetsPanel.
    This widget doesn't do animation itself; parent can control width/splitter sizes.
    """

    def __init__(self, client_factory: Callable[[], V2Client], parent=None):
        super().__init__(parent)
        self._client_factory = client_factory

        self.character = ""
        self.emotion = ""
        self.voice_id = ""
        self.last_section = "assets"

        self.setObjectName("voiceRefsSheet")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        # Start collapsed; parent will expand it when opened.
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)

        top = QHBoxLayout()
        self.title = SubtitleLabel("参考音频")
        top.addWidget(self.title)
        top.addStretch()
        self.close_btn = ToolButton(FluentIcon.CLOSE)
        self.close_btn.setToolTip("关闭（Esc）")
        top.addWidget(self.close_btn)
        root.addLayout(top)

        self.subtitle = self._make_secondary_label("未选择 voice")
        root.addWidget(self.subtitle)

        self.meta_label = self._make_secondary_label("资源：0 条 | 已绑定：0 条")
        root.addWidget(self.meta_label)

        self.panel = EmotionAssetsPanel(client_factory, parent=self)
        self.panel.set_manage_voice_binding_locally(True)
        self.panel.assets_stats_changed.connect(self._on_assets_stats_changed)
        root.addWidget(self.panel, 1)

        self.setVisible(False)
        sheet_bg = Palette.card_theme()
        self.setStyleSheet(
            f"""
            QFrame#voiceRefsSheet {{
                border: 1px solid {Palette.BORDER};
                border-radius: 14px;
                background: {sheet_bg};
            }}
            """
        )

    def _make_secondary_label(self, text: str) -> BodyLabel:
        label = BodyLabel(text)
        label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
        label.setWordWrap(False)
        return label

    def set_context(self, *, character: str, emotion: str, voice_id: str, ref_asset_ids: Optional[List[str]] = None):
        self.character = (character or "").strip()
        self.emotion = (emotion or "").strip() or "default"
        self.voice_id = (voice_id or "").strip()
        self.title.setText(f"参考音频（{self.character} / {self.emotion}）")
        self.subtitle.setText(f"当前 voice：{self.voice_id}")
        self.panel.set_context(
            character=self.character,
            emotion=self.emotion,
            voice_id=self.voice_id,
            ref_asset_ids=list(ref_asset_ids or []),
        )

    def open_sheet(self, preferred_width: int = Metrics.INSPECTOR_W_DEFAULT):
        width = max(Metrics.INSPECTOR_W_MIN, min(Metrics.INSPECTOR_W_MAX, int(preferred_width or Metrics.INSPECTOR_W_DEFAULT)))
        self.setMinimumWidth(Metrics.INSPECTOR_W_MIN)
        self.setMaximumWidth(Metrics.INSPECTOR_W_MAX)
        self.resize(width, self.height())
        self.setVisible(True)
        self.raise_()

    def close_sheet(self):
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.setVisible(False)

    def save_ui_state(self, config_manager, *, is_open: Optional[bool] = None):
        try:
            state = bool(self.isVisible() if is_open is None else is_open)
            config_manager.set("ui_voice_refs_open", state)
            config_manager.set("ui_voice_refs_last_section", str(self.last_section or "assets"))
        except Exception:
            pass

    def load_ui_state(self, config_manager) -> Dict[str, object]:
        try:
            is_open = bool(config_manager.get("ui_voice_refs_open", False))
        except Exception:
            is_open = False
        try:
            last = str(config_manager.get("ui_voice_refs_last_section", "assets") or "assets")
        except Exception:
            last = "assets"
        self.last_section = last
        return {"open": is_open, "last_section": last}

    def _on_assets_stats_changed(self, total: int, linked: int):
        self.meta_label.setText(f"资源：{int(total or 0)} 条 | 已绑定：{int(linked or 0)} 条")
