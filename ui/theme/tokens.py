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
    CONTROL = 6
    PANEL = 10

class Typography:
    TITLE_SIZE = 24
    BODY_SIZE = 13
    CAPTION_SIZE = 11

class Palette:
    # 动态调色板 (Apple 语义化)
    @classmethod
    def bg(cls) -> str: return _pick("#F5F6F7", "#000000")
    
    @classmethod
    def card(cls) -> str: return _pick("#FFFFFF", "#1E1E1E")
    
    @classmethod
    def border(cls) -> str: return _pick("#E6E8EB", "#333336")
    
    @classmethod
    def text_primary(cls) -> str: return _pick("#1D1D1F", "#F5F5F7")
    
    @classmethod
    def text_secondary(cls) -> str: return _pick("#86868B", "#A1A1A6")
    
    @classmethod
    def text_muted(cls) -> str: return _pick("#86868B", "#86868B")
    
    @classmethod
    def accent(cls) -> str: return _pick("#0066CC", "#2997FF")
    
    @classmethod
    def tag_bg(cls) -> str: return _pick("#F5F5F7", "#2C2C2E")

    # 旧代码兼容接口 (Deprecated: 不具有热切换能力)
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
        return _pick("#1D1D1F", "#F5F5F7")

    @staticmethod
    def text_secondary_theme() -> str:
        return _pick("#86868B", "#A1A1A6")

    @staticmethod
    def card_theme() -> str:
        return _pick("#FFFFFF", "#1E1E1E")

    @staticmethod
    def table_alt_bg() -> str:
        return _pick("#FAFBFC", "#1C1C1E")

    @staticmethod
    def table_selected_bg() -> str:
        return _pick("#E8F2FF", "#0040DD")

    @staticmethod
    def log_badge_bg(level: str) -> str:
        lv = str(level or "").upper()
        if lv == "ERROR":
            return _pick("#FDECEC", "#3D1A1A")
        if lv == "WARN":
            return _pick("#FFF4E5", "#3D2E15")
        if lv == "OK":
            return _pick("#E9F8EF", "#1A3D24")
        return _pick("#EAF6FF", "#18324D")

class Metrics:
    TOOLBAR_H = 56
    CONTROL_H = 34
    TABLE_ROW_H = 44
    INSPECTOR_W_MIN = 320
    INSPECTOR_W_DEFAULT = 400
    INSPECTOR_W_MAX = 560

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
    NEUTRAL_BG = "#F5F5F7"
    NEUTRAL_TEXT = "#86868B"
