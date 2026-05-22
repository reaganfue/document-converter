"""主題管理工具 — Nordic Design System 雙主題切換。

提供 apply_theme(mode) 整合 QFluentWidgets 的主題 API,並支援:
- 明確的亮/暗模式（'light' / 'dark'）
- 跟隨系統主題（'system' / 'auto'）
- Windows 系統主題偵測（darkdetect → winreg 降級）
- Nordic palette token 系統 + QSS template 動態 render
- 主題色:
    亮主題 fjord blue  #5E81AC
    暗主題 frost cyan  #88C0D0

公開 API:
    ThemeMode             — 主題模式枚舉（LIGHT / DARK / SYSTEM）
    BRAND_COLOR           — 預設亮主題主色（向下相容,動態查詢用 get_brand_color）
    NORDIC_LIGHT          — 亮主題 palette dict
    NORDIC_DARK           — 暗主題 palette dict
    get_palette()         — 取得當前主題的 palette
    get_brand_color()     — 取得當前主題的主色
    render_stylesheet()   — 把 styles.qss template 渲染為實際 QSS 字串
    apply_theme()         — 套用主題（含 QSS 注入）
    apply_stylesheet()    — 只套用 QSS（不切主題,主題切換時內部呼叫）
    get_current_mode()    — 讀取已儲存的模式
    save_theme_mode()     — 寫入 QSettings
    is_system_dark()      — 偵測系統暗色模式
    install_system_theme_listener() — 監聽系統主題變更（可選）
"""
from __future__ import annotations

import logging
import re
import threading
from enum import Enum
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 主題變更 Signal Bus(供 widgets 訂閱以動態 refresh 樣式)
# ---------------------------------------------------------------------------

class _ThemeBus(QObject):
    """全局主題變更廣播器。

    主題切換時由 apply_theme() emit theme_changed,
    widget 可連接此 signal 後重新呼叫自身的 _refresh_palette。
    """
    theme_changed = Signal(str)  # "light" | "dark"


# 模組級單例,所有 widget 共用
theme_bus = _ThemeBus()

# ---------------------------------------------------------------------------
# Nordic Design System Palette
# ---------------------------------------------------------------------------

NORDIC_LIGHT: dict[str, str] = {
    # 背景階層（暖白基底 Snow Storm）
    "bg_primary":      "#FAFAF9",
    "bg_secondary":    "#F2F1EE",
    "bg_elevated":     "#FFFFFF",
    "bg_hover":        "#ECEBE8",
    "bg_pressed":      "#E5E4E1",
    "bg_subtle":       "#F7F6F4",
    # 文字
    "text_primary":    "#2E3440",
    "text_secondary":  "#4C566A",
    "text_tertiary":   "#8E8E93",
    "text_disabled":   "#C7C7CC",
    "text_on_accent":  "#FFFFFF",
    "text_link":       "#5E81AC",
    # 強調色（Fjord Blue）
    "accent_primary":  "#5E81AC",
    "accent_hover":    "#6B8FB8",
    "accent_pressed":  "#4C6E94",
    "accent_subtle":   "#E1E8F0",
    "accent_subtle_hover": "#D2DCEA",
    # 狀態色（暗化以對比亮背景 — 過 WCAG AA）
    "state_success":   "#5F8050",
    "state_success_bg": "#EAF1E2",
    "state_warning":   "#A6803E",
    "state_warning_bg": "#FAF1DC",
    "state_danger":    "#A6505A",
    "state_danger_bg": "#F5E0E2",
    "state_info":      "#5E81AC",
    "state_info_bg":   "#E1E8F0",
    # 邊框
    "border_subtle":   "rgba(46, 52, 64, 0.08)",
    "border_default":  "rgba(46, 52, 64, 0.12)",
    "border_strong":   "rgba(46, 52, 64, 0.20)",
    "border_focus":    "#5E81AC",
    # 陰影（北歐風刻意低調)
    "shadow_subtle":   "rgba(46, 52, 64, 0.04)",
    "shadow_card":     "rgba(46, 52, 64, 0.06)",
    # 格式徽章背景 + 文字（淡色塊配深字)
    "fmt_pdf_bg":      "#F5E0E2",  "fmt_pdf_fg":   "#A6505A",
    "fmt_docx_bg":     "#E1E8F0",  "fmt_docx_fg":  "#3F5E80",
    "fmt_pptx_bg":     "#F5E0CC",  "fmt_pptx_fg":  "#A6651E",
    "fmt_html_bg":     "#EAF1E2",  "fmt_html_fg":  "#5F8050",
    "fmt_md_bg":       "#E1E8F0",  "fmt_md_fg":    "#3F5E80",
    "fmt_txt_bg":      "#E5E4E1",  "fmt_txt_fg":   "#4C566A",
    "fmt_png_bg":      "#EAE1F0",  "fmt_png_fg":   "#7A5E94",
    "fmt_jpg_bg":      "#EAE1F0",  "fmt_jpg_fg":   "#7A5E94",
    "fmt_image_bg":    "#EAE1F0",  "fmt_image_fg": "#7A5E94",
    "fmt_default_bg":  "#E5E4E1",  "fmt_default_fg": "#4C566A",
    # 幾何裝飾色（用於 SVG 線稿著色)
    "decor_subtle":    "rgba(94, 129, 172, 0.18)",
    "decor_strong":    "rgba(94, 129, 172, 0.32)",
}

NORDIC_DARK: dict[str, str] = {
    # 背景階層（Polar Night)
    "bg_primary":      "#2E3440",
    "bg_secondary":    "#3B4252",
    "bg_elevated":     "#434C5E",
    "bg_hover":        "#4C566A",
    "bg_pressed":      "#3B4252",
    "bg_subtle":       "#353B48",
    # 文字
    "text_primary":    "#ECEFF4",
    "text_secondary":  "#D8DEE9",
    "text_tertiary":   "#A8B0BC",
    "text_disabled":   "#6C7689",
    "text_on_accent":  "#2E3440",
    "text_link":       "#88C0D0",
    # 強調色（Frost Cyan)
    "accent_primary":  "#88C0D0",
    "accent_hover":    "#8FBCBB",
    "accent_pressed":  "#A3D5DD",
    "accent_subtle":   "#3F4F5E",
    "accent_subtle_hover": "#4A5E70",
    # 狀態色（Aurora)
    "state_success":   "#A3BE8C",
    "state_success_bg": "#3F4D3A",
    "state_warning":   "#EBCB8B",
    "state_warning_bg": "#534833",
    "state_danger":    "#BF616A",
    "state_danger_bg": "#523439",
    "state_info":      "#88C0D0",
    "state_info_bg":   "#3F4F5E",
    # 邊框
    "border_subtle":   "rgba(236, 239, 244, 0.06)",
    "border_default":  "rgba(236, 239, 244, 0.10)",
    "border_strong":   "rgba(236, 239, 244, 0.16)",
    "border_focus":    "#88C0D0",
    # 陰影
    "shadow_subtle":   "rgba(0, 0, 0, 0.15)",
    "shadow_card":     "rgba(0, 0, 0, 0.25)",
    # 格式徽章
    "fmt_pdf_bg":      "#523439",  "fmt_pdf_fg":   "#D29DA3",
    "fmt_docx_bg":     "#3F4F5E",  "fmt_docx_fg":  "#A3C0DD",
    "fmt_pptx_bg":     "#534833",  "fmt_pptx_fg":  "#E5B888",
    "fmt_html_bg":     "#3F4D3A",  "fmt_html_fg":  "#C0D3A6",
    "fmt_md_bg":       "#3F4F5E",  "fmt_md_fg":    "#A3C0DD",
    "fmt_txt_bg":      "#3B4252",  "fmt_txt_fg":   "#D8DEE9",
    "fmt_png_bg":      "#4A3F50",  "fmt_png_fg":   "#C9A8D3",
    "fmt_jpg_bg":      "#4A3F50",  "fmt_jpg_fg":   "#C9A8D3",
    "fmt_image_bg":    "#4A3F50",  "fmt_image_fg": "#C9A8D3",
    "fmt_default_bg":  "#3B4252",  "fmt_default_fg": "#D8DEE9",
    # 幾何裝飾色
    "decor_subtle":    "rgba(136, 192, 208, 0.20)",
    "decor_strong":    "rgba(136, 192, 208, 0.35)",
}

# 字型與尺寸常數
FONT_FAMILY: str = (
    "'Inter', 'Geist', 'Segoe UI Variable', "
    "'Microsoft JhengHei', '微軟正黑體', sans-serif"
)

TYPOGRAPHY_TOKENS: dict[str, str] = {
    "font_family": FONT_FAMILY,
    "font_size_caption": "12px",
    "font_size_body":    "14px",
    "font_size_body_lg": "16px",
    "font_size_title":   "20px",
    "font_size_h1":      "28px",
    "font_weight_regular":  "400",
    "font_weight_medium":   "500",
    "font_weight_semibold": "600",
}

SPACING_TOKENS: dict[str, str] = {
    "space_xs":  "4px",
    "space_sm":  "8px",
    "space_md":  "16px",
    "space_lg":  "24px",
    "space_xl":  "40px",
    "space_xxl": "64px",
}

RADIUS_TOKENS: dict[str, str] = {
    "radius_sm":   "4px",
    "radius_md":   "6px",
    "radius_lg":   "8px",
    "radius_xl":   "12px",
    "radius_pill": "999px",
}

# 向下相容:BRAND_COLOR 維持為亮主題主色字串
BRAND_COLOR: str = NORDIC_LIGHT["accent_primary"]
"""預設品牌色(亮主題 fjord blue)。動態取色請用 get_brand_color()。"""

_QSETTINGS_ORG: str = "DocConverter"
_QSETTINGS_APP: str = "DocConverter"
_QSETTINGS_KEY: str = "theme"
_DEFAULT_MODE: str = "system"


# ---------------------------------------------------------------------------
# ThemeMode 枚舉
# ---------------------------------------------------------------------------

class ThemeMode(str, Enum):
    """主題模式枚舉。

    LIGHT  — 強制亮色模式
    DARK   — 強制暗色模式
    SYSTEM — 跟隨作業系統設定("auto" 為同義詞)
    """
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


def _parse_mode(mode: ThemeMode | str) -> ThemeMode:
    """將任意模式字串正規化為 ThemeMode 枚舉。"""
    if isinstance(mode, ThemeMode):
        return mode
    normalized = str(mode).lower().strip()
    if normalized in ("system", "auto"):
        return ThemeMode.SYSTEM
    try:
        return ThemeMode(normalized)
    except ValueError:
        raise ValueError(
            f"無法識別的主題模式:{mode!r}。"
            f"有效值:{[m.value for m in ThemeMode]} 以及 'auto'。"
        )


# ---------------------------------------------------------------------------
# 系統暗色模式偵測
# ---------------------------------------------------------------------------

def is_system_dark() -> bool:
    """偵測作業系統當前是否為暗色模式。"""
    try:
        import darkdetect  # type: ignore[import]
        result = darkdetect.isDark()
        return bool(result) if result is not None else False
    except Exception as exc:
        logger.debug("darkdetect 不可用,改用 winreg 偵測:%s", exc)

    try:
        import winreg
        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except Exception as exc:
        logger.debug("winreg 讀取失敗,預設回傳亮色:%s", exc)
        return False


def _resolve_is_dark(mode: ThemeMode | str | None = None) -> bool:
    """解析當前主題是否為暗色。

    Args:
        mode: 主題模式或 None(自動偵測)。

    Returns:
        True 表示應顯示為暗色主題。
    """
    if mode is None:
        try:
            from qfluentwidgets import isDarkTheme  # type: ignore[import]
            return bool(isDarkTheme())
        except Exception:
            return is_system_dark()

    parsed = _parse_mode(mode)
    if parsed is ThemeMode.SYSTEM:
        return is_system_dark()
    return parsed is ThemeMode.DARK


# ---------------------------------------------------------------------------
# Palette 查詢
# ---------------------------------------------------------------------------

def get_palette(mode: ThemeMode | str | None = None) -> dict[str, str]:
    """取得當前主題的 Nordic palette 字典。

    Args:
        mode: 強制指定主題(ThemeMode 或字串);None 表示自動偵測。

    Returns:
        Nordic palette dict,key 為色彩 token 名稱。
    """
    return NORDIC_DARK if _resolve_is_dark(mode) else NORDIC_LIGHT


def get_brand_color(mode: ThemeMode | str | None = None) -> str:
    """取得當前主題的主色 hex 字串。

    Args:
        mode: 強制指定主題;None 表示自動偵測。

    Returns:
        accent_primary 的 hex 字串(例如 "#5E81AC")。
    """
    return get_palette(mode)["accent_primary"]


# ---------------------------------------------------------------------------
# QSS Template Rendering
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"\$\{(\w+)\}")


def _get_token_map(mode: ThemeMode | str | None = None) -> dict[str, str]:
    """組合完整 token map(palette + typography + spacing + radius)。"""
    tokens: dict[str, str] = {}
    tokens.update(get_palette(mode))
    tokens.update(TYPOGRAPHY_TOKENS)
    tokens.update(SPACING_TOKENS)
    tokens.update(RADIUS_TOKENS)
    return tokens


def render_stylesheet(mode: ThemeMode | str | None = None) -> str:
    """讀取 styles.qss template 並把所有 ${token} placeholder 替換為實際值。

    Args:
        mode: 主題模式;None 表示自動偵測當前主題。

    Returns:
        渲染後的 QSS 字串,可直接 setStyleSheet。
        若 template 檔不存在則回傳空字串(不阻塞應用啟動)。
    """
    template_path = Path(__file__).parent.parent / "resources" / "styles.qss"
    if not template_path.exists():
        logger.warning("styles.qss 不存在:%s", template_path)
        return ""

    try:
        template = template_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("styles.qss 讀取失敗:%s", exc)
        return ""

    tokens = _get_token_map(mode)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in tokens:
            logger.debug("QSS template 未知 token: ${%s}", key)
            return match.group(0)
        return tokens[key]

    return _TOKEN_PATTERN.sub(_replace, template)


def apply_stylesheet(mode: ThemeMode | str | None = None) -> None:
    """渲染 styles.qss 並套用到 QApplication。

    主題切換時內部自動呼叫;也可在 setting 變更後手動呼叫。
    """
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore[import]
    except ImportError as exc:
        logger.error("PySide6 不可用,跳過 setStyleSheet:%s", exc)
        return

    app = QApplication.instance()
    if app is None:
        logger.debug("QApplication 尚未建立,跳過 setStyleSheet")
        return

    qss = render_stylesheet(mode)
    if qss:
        app.setStyleSheet(qss)
        logger.debug("Nordic stylesheet 已套用(%d 字元)", len(qss))


# ---------------------------------------------------------------------------
# QFluentWidgets 主題套用
# ---------------------------------------------------------------------------

def apply_theme(mode: ThemeMode | str = ThemeMode.SYSTEM) -> None:
    """套用主題至整個 QApplication。

    依 mode 呼叫 QFluentWidgets 的 setTheme + setThemeColor,
    並注入對應的 Nordic QSS。

    Args:
        mode: 'light' / 'dark' / 'system' / 'auto'。

    Side Effects:
        呼叫 setTheme + setThemeColor + setStyleSheet。
    """
    try:
        from qfluentwidgets import setTheme, setThemeColor, Theme  # type: ignore[import]
    except ImportError as exc:
        logger.error("qfluentwidgets 不可用,無法套用主題:%s", exc)
        return

    is_dark = _resolve_is_dark(mode)
    qfw_theme = Theme.DARK if is_dark else Theme.LIGHT
    accent = NORDIC_DARK["accent_primary"] if is_dark else NORDIC_LIGHT["accent_primary"]

    try:
        setTheme(qfw_theme)
        setThemeColor(accent)
        logger.debug(
            "Nordic 主題已套用:is_dark=%s,accent=%s",
            is_dark, accent,
        )
    except Exception as exc:
        logger.error("setTheme / setThemeColor 呼叫失敗:%s", exc)

    # 注入 QSS(palette token 渲染後套用)
    mode_label = "dark" if is_dark else "light"
    apply_stylesheet(mode_label)

    # 廣播主題變更,讓 widget 重新從 palette 取色
    try:
        theme_bus.theme_changed.emit(mode_label)
    except Exception as exc:
        logger.debug("theme_bus 廣播失敗(忽略):%s", exc)


# ---------------------------------------------------------------------------
# QSettings 持久化
# ---------------------------------------------------------------------------

def save_theme_mode(mode: ThemeMode | str) -> None:
    """將主題模式寫入 QSettings,跨會話持久化。"""
    try:
        from PySide6.QtCore import QSettings  # type: ignore[import]
    except ImportError as exc:
        logger.error("PySide6 不可用,無法儲存主題設定:%s", exc)
        return

    resolved = _parse_mode(mode)
    settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    settings.setValue(_QSETTINGS_KEY, resolved.value)
    settings.sync()
    logger.debug("主題設定已儲存:%s", resolved.value)


def get_current_mode() -> ThemeMode:
    """從 QSettings 讀取已儲存的主題模式。"""
    try:
        from PySide6.QtCore import QSettings  # type: ignore[import]
    except ImportError as exc:
        logger.warning("PySide6 不可用,回傳預設主題:%s", exc)
        return ThemeMode.SYSTEM

    settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    raw = settings.value(_QSETTINGS_KEY, _DEFAULT_MODE)
    try:
        return _parse_mode(str(raw))
    except ValueError:
        logger.warning("QSettings 儲存了無效的主題值 %r,重設為 system", raw)
        return ThemeMode.SYSTEM


# ---------------------------------------------------------------------------
# 系統主題監聽
# ---------------------------------------------------------------------------

_listener_thread: threading.Thread | None = None
_listener_callback: Callable[[str | None], None] | None = None


def install_system_theme_listener(callback: Callable[[str | None], None]) -> None:
    """安裝系統主題變更監聽器(idempotent)。

    當作業系統從亮/暗模式切換時,在背景執行緒中呼叫 callback(theme_name)。
    """
    global _listener_thread, _listener_callback  # noqa: PLW0603

    _listener_callback = callback

    if _listener_thread is not None and _listener_thread.is_alive():
        logger.debug("系統主題監聽已存在(daemon thread 仍存活),僅更新 callback 引用")
        return

    try:
        import darkdetect  # type: ignore[import]
        if not hasattr(darkdetect, "listener"):
            logger.warning(
                "darkdetect.listener 不存在(版本 %s),跳過系統主題監聽。",
                getattr(darkdetect, "__version__", "unknown"),
            )
            return

        def _thread_target() -> None:
            try:
                def _dispatch(theme: str | None) -> None:
                    cb = _listener_callback
                    if cb is not None:
                        cb(theme)
                darkdetect.listener(_dispatch)
            except Exception as exc:
                logger.error("darkdetect.listener 執行失敗:%s", exc)

        _listener_thread = threading.Thread(
            target=_thread_target,
            name="theme-system-listener",
            daemon=True,
        )
        _listener_thread.start()
        logger.debug("系統主題監聽已啟動")

    except ImportError:
        logger.warning(
            "darkdetect 不可用,跳過系統主題監聽。"
            "系統切換亮暗時應用程式不會自動跟隨。"
        )


# ---------------------------------------------------------------------------
# 向下相容別名
# ---------------------------------------------------------------------------

def get_system_theme() -> ThemeMode:
    """偵測 Windows 系統主題(向下相容別名)。"""
    return ThemeMode.DARK if is_system_dark() else ThemeMode.LIGHT
