def _is_dark_theme() -> bool:
    try:
        from qfluentwidgets import isDarkTheme
        return bool(isDarkTheme())
    except Exception:
        return False


def _pick(light: str, dark: str) -> str:
    return str(dark if _is_dark_theme() else light)


class Spacing:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 20
    XXL = 24


class Radius:
    CONTROL = 10
    PANEL = 14


class Typography:
    TITLE_SIZE = 24
    BODY_SIZE = 13
    CAPTION_SIZE = 11


class Palette:
    BG = "#F5F6F7"
    CARD = "#FFFFFF"
    BORDER = "#E6E8EB"
    TEXT_PRIMARY = "#1D1D1F"
    TEXT_SECONDARY = "#6E6E73"
    TEXT_MUTED = "#64748B"
    ACCENT = "#0369A1"
    ACCENT_HOVER = "#075985"
    FOCUS_RING = "#0EA5E9"
    INFO = "#0EA5E9"
    SUCCESS = "#1F9D55"
    WARNING = "#D97706"
    DANGER = "#DC2626"
    TAG_BG = "#F2F3F5"

    @staticmethod
    def text_primary_theme() -> str:
        return _pick("#1D1D1F", "#F3F4F6")

    @staticmethod
    def text_secondary_theme() -> str:
        return _pick("#6E6E73", "#C8CDD4")

    @staticmethod
    def card_theme() -> str:
        return _pick("#FFFFFF", "#1E1E1E")

    @staticmethod
    def table_alt_bg() -> str:
        return _pick("#FAFBFC", "#262A2F")

    @staticmethod
    def table_selected_bg() -> str:
        return _pick("#EFF6FF", "#2B3C50")

    @staticmethod
    def log_badge_bg(level: str) -> str:
        lv = str(level or "").upper()
        if lv == "ERROR":
            return _pick("#FDECEC", "#4A2326")
        if lv == "WARN":
            return _pick("#FFF4E5", "#4C3A1F")
        if lv == "OK":
            return _pick("#E9F8EF", "#1F4B32")
        return _pick("#EAF6FF", "#1F3E52")


class Metrics:
    TOOLBAR_H = 56
    CONTROL_H = 36
    TABLE_ROW_H = 40
    INSPECTOR_W_MIN = 400
    INSPECTOR_W_DEFAULT = 480
    INSPECTOR_W_MAX = 640


class Table:
    COLUMN_GAP_DENSE = 4


class StatusChip:
    HEIGHT = 22
    SUCCESS_BG = "#E9F8EF"
    SUCCESS_TEXT = "#1F9D55"
    WARN_BG = "#FFF4E5"
    WARN_TEXT = "#D97706"
    MISSING_BG = "#FDECEC"
    MISSING_TEXT = "#DC2626"
    NEUTRAL_BG = "#F2F3F5"
    NEUTRAL_TEXT = "#6E6E73"
