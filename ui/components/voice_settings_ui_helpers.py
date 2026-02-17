import os
from typing import Callable, Dict, Tuple

from PyQt5.QtWidgets import QHBoxLayout, QWidget

from qfluentwidgets import BodyLabel, FluentIcon, ToolButton

from ..theme.tokens import Metrics, Palette, StatusChip, Table


def build_strip_container(parent, object_name: str, margins: Tuple[int, int, int, int], spacing: int) -> Tuple[QWidget, QHBoxLayout]:
    widget = QWidget(parent)
    widget.setObjectName(object_name)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(int(spacing))
    return widget, layout


def make_secondary_label(text: str, *, word_wrap: bool = False) -> BodyLabel:
    label = BodyLabel(text)
    label.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
    label.setWordWrap(bool(word_wrap))
    return label


def status_chip_styles(status: str) -> Tuple[str, str]:
    if status == "uploaded":
        return StatusChip.SUCCESS_BG, StatusChip.SUCCESS_TEXT
    if status == "missing":
        return StatusChip.MISSING_BG, StatusChip.MISSING_TEXT
    if status == "warn":
        return StatusChip.WARN_BG, StatusChip.WARN_TEXT
    return StatusChip.NEUTRAL_BG, StatusChip.NEUTRAL_TEXT


def build_main_ref_cell_widget(
    *,
    info: Dict[str, str],
    source_idx: int,
    safe_str: Callable[[object], str],
    on_open_folder: Callable[[int], None],
    on_open_menu: Callable[[int, object], None],
    setup_widget_context_menu: Callable[[QWidget, int], None],
) -> QWidget:
    chip_bg, chip_fg = status_chip_styles(safe_str(info.get("status")))
    display_name = safe_str(info.get("display_name"))
    path = safe_str(info.get("path"))

    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(Table.COLUMN_GAP_DENSE)

    chip = BodyLabel(safe_str(info.get("status_text")))
    chip.setFixedHeight(StatusChip.HEIGHT)
    chip.setStyleSheet(
        f"background: {chip_bg}; color: {chip_fg}; border-radius: 6px; padding: 0 8px;"
    )
    layout.addWidget(chip)

    name_lbl = BodyLabel(display_name or "<未绑定>")
    name_lbl.setWordWrap(False)
    name_lbl.setStyleSheet(f"color: {Palette.TEXT_SECONDARY};")
    tt = path or (safe_str(info.get("aid")) if safe_str(info.get("aid")) else "<未绑定>")
    name_lbl.setToolTip(tt)
    layout.addWidget(name_lbl, 1)

    folder_btn = ToolButton(FluentIcon.FOLDER)
    folder_btn.setFixedSize(Metrics.CONTROL_H, Metrics.CONTROL_H)
    folder_btn.setToolTip("打开参考音频目录")
    folder_btn.setEnabled(bool(path and os.path.exists(path)))
    folder_btn.clicked.connect(lambda _=False, idx=source_idx: on_open_folder(idx))
    layout.addWidget(folder_btn)

    more_btn = ToolButton(FluentIcon.MORE)
    more_btn.setFixedSize(Metrics.CONTROL_H, Metrics.CONTROL_H)
    more_btn.setToolTip("更多")
    more_btn.clicked.connect(
        lambda _=False, idx=source_idx, b=more_btn: on_open_menu(
            idx, b.mapToGlobal(b.rect().bottomLeft())
        )
    )
    layout.addWidget(more_btn)

    setup_widget_context_menu(widget, source_idx)
    return widget
