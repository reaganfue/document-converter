"""主題管理工具 — 亮色/暗色主題切換。

提供 apply_theme(mode) 整合 QFluentWidgets 的主題 API，並支援：
- 明確的亮/暗模式（'light' / 'dark'）
- 跟隨系統主題（'system' / 'auto'）
- Windows 系統主題偵測（darkdetect → winreg 降級）
- 品牌色 #8B5CF6 注入

公開 API：
    ThemeMode       — 主題模式枚舉（LIGHT / DARK / SYSTEM）
    BRAND_COLOR     — 品牌紫色字串
    apply_theme()   — 套用主題
    get_current_mode() — 讀取已儲存的模式
    save_theme_mode()  — 寫入 QSettings
    is_system_dark()   — 偵測系統暗色模式
    install_system_theme_listener() — 監聽系統主題變更（可選）
"""
from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

BRAND_COLOR: str = "#8B5CF6"
"""品牌紫色，作為 QFluentWidgets setThemeColor 參數。"""

FONT_FAMILY: str = "Segoe UI Variable, 微軟正黑體, Microsoft JhengHei, sans-serif"
"""字體優先序（Windows 11 → 繁體中文 fallback → 通用）。"""

_QSETTINGS_ORG: str = "DocConverter"
_QSETTINGS_APP: str = "DocConverter"
_QSETTINGS_KEY: str = "theme"
_DEFAULT_MODE: str = "system"


# ---------------------------------------------------------------------------
# ThemeMode 枚舉（保持向下相容：支援 "auto" 作為 "system" 別名）
# ---------------------------------------------------------------------------

class ThemeMode(str, Enum):
    """主題模式枚舉。

    LIGHT  — 強制亮色模式
    DARK   — 強制暗色模式
    SYSTEM — 跟隨作業系統設定（"auto" 為同義詞，解析時會轉換）
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


def _parse_mode(mode: ThemeMode | str) -> ThemeMode:
    """將任意模式字串正規化為 ThemeMode 枚舉。

    "auto" 作為 SYSTEM 的別名，維持向下相容。

    Args:
        mode: 任意模式值。

    Returns:
        對應的 ThemeMode 枚舉值。

    Raises:
        ValueError: 若傳入無法識別的模式字串。
    """
    if isinstance(mode, ThemeMode):
        return mode
    normalized = str(mode).lower().strip()
    if normalized in ("system", "auto"):
        return ThemeMode.SYSTEM
    try:
        return ThemeMode(normalized)
    except ValueError:
        raise ValueError(
            f"無法識別的主題模式：{mode!r}。"
            f"有效值：{[m.value for m in ThemeMode]} 以及 'auto'。"
        )


# ---------------------------------------------------------------------------
# 系統暗色模式偵測
# ---------------------------------------------------------------------------

def is_system_dark() -> bool:
    """偵測作業系統當前是否為暗色模式。

    優先使用 darkdetect.isDark()；若不可用則改讀 Windows Registry
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize
    的 AppsUseLightTheme 值。

    Returns:
        True 若系統為暗色模式，False 為亮色模式或無法判斷。
    """
    try:
        import darkdetect  # type: ignore[import]
        result = darkdetect.isDark()
        return bool(result) if result is not None else False
    except Exception as exc:
        logger.debug("darkdetect 不可用，改用 winreg 偵測：%s", exc)

    try:
        import winreg
        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            # 0 = 暗色模式，1 = 亮色模式
            return value == 0
    except Exception as exc:
        logger.debug("winreg 讀取失敗，預設回傳亮色：%s", exc)
        return False


# ---------------------------------------------------------------------------
# QFluentWidgets 主題套用
# ---------------------------------------------------------------------------

def apply_theme(mode: ThemeMode | str = ThemeMode.SYSTEM) -> None:
    """套用主題至整個 QApplication。

    依 mode 呼叫 QFluentWidgets 的 setTheme + setThemeColor，
    確保應用程式所有視窗同步更新。

    Args:
        mode: 主題模式（ThemeMode 枚舉或字串 'light' / 'dark' / 'system' / 'auto'）。
              'system' 與 'auto' 皆代表跟隨作業系統設定。

    Side Effects:
        呼叫 qfluentwidgets.setTheme 與 qfluentwidgets.setThemeColor。
        不寫入 QSettings（請另呼叫 save_theme_mode）。
    """
    try:
        from qfluentwidgets import setTheme, setThemeColor, Theme  # type: ignore[import]
    except ImportError as exc:
        logger.error("qfluentwidgets 不可用，無法套用主題：%s", exc)
        return

    resolved = _parse_mode(mode)

    if resolved is ThemeMode.SYSTEM:
        qfw_theme = Theme.DARK if is_system_dark() else Theme.LIGHT
    elif resolved is ThemeMode.DARK:
        qfw_theme = Theme.DARK
    else:
        qfw_theme = Theme.LIGHT

    try:
        setTheme(qfw_theme)
        setThemeColor(BRAND_COLOR)
        logger.debug(
            "主題已套用：mode=%s → qfw_theme=%s，品牌色=%s",
            resolved.value, qfw_theme, BRAND_COLOR,
        )
    except Exception as exc:
        logger.error("setTheme / setThemeColor 呼叫失敗：%s", exc)


# ---------------------------------------------------------------------------
# QSettings 持久化
# ---------------------------------------------------------------------------

def save_theme_mode(mode: ThemeMode | str) -> None:
    """將主題模式寫入 QSettings，跨會話持久化。

    Args:
        mode: 主題模式（ThemeMode 枚舉或字串）。
    """
    try:
        from PySide6.QtCore import QSettings  # type: ignore[import]
    except ImportError as exc:
        logger.error("PySide6 不可用，無法儲存主題設定：%s", exc)
        return

    resolved = _parse_mode(mode)
    settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    settings.setValue(_QSETTINGS_KEY, resolved.value)
    settings.sync()
    logger.debug("主題設定已儲存：%s", resolved.value)


def get_current_mode() -> ThemeMode:
    """從 QSettings 讀取已儲存的主題模式。

    若 QSettings 中無記錄，回傳預設值 ThemeMode.SYSTEM。

    Returns:
        已儲存的 ThemeMode，或 ThemeMode.SYSTEM（預設）。
    """
    try:
        from PySide6.QtCore import QSettings  # type: ignore[import]
    except ImportError as exc:
        logger.warning("PySide6 不可用，回傳預設主題：%s", exc)
        return ThemeMode.SYSTEM

    settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    raw = settings.value(_QSETTINGS_KEY, _DEFAULT_MODE)
    try:
        return _parse_mode(str(raw))
    except ValueError:
        logger.warning("QSettings 儲存了無效的主題值 %r，重設為 system", raw)
        return ThemeMode.SYSTEM


# ---------------------------------------------------------------------------
# 系統主題監聽（可選）
# ---------------------------------------------------------------------------

_listener_thread: threading.Thread | None = None
_listener_callback: Callable[[str | None], None] | None = None


def install_system_theme_listener(callback: Callable[[str | None], None]) -> None:
    """安裝系統主題變更監聽器（idempotent）。

    當作業系統從亮/暗模式切換時，在背景執行緒中呼叫 callback(theme_name)，
    theme_name 為 'Light' / 'Dark' / None（由 darkdetect.listener 傳入）。

    本函式是 idempotent：若監聽執行緒已存活，僅更新 callback 引用，
    不會重複建立新執行緒。這讓呼叫方在用戶切換回 "system" 主題時
    可安全重複呼叫，不會疊加多條執行緒。

    優先使用 darkdetect.listener；若不可用則記錄 warning 後為 no-op。

    Args:
        callback: 系統主題變更時觸發的回呼函式，接受一個 str | None 參數
                  （'Light' / 'Dark' / None）。
                  注意：回呼執行於非 Qt 主執行緒，需用 QMetaObject.invokeMethod
                  或 signal/slot 機制切回主執行緒。
    """
    global _listener_thread, _listener_callback  # noqa: PLW0603

    # 更新 callback 引用（即使 thread 已存在也要更新，確保最新 callback 被使用）
    _listener_callback = callback

    # 若 daemon thread 仍存活，不重複建立（idempotent）
    if _listener_thread is not None and _listener_thread.is_alive():
        logger.debug("系統主題監聽已存在（daemon thread 仍存活），僅更新 callback 引用")
        return

    try:
        import darkdetect  # type: ignore[import]
        if not hasattr(darkdetect, "listener"):
            logger.warning(
                "darkdetect.listener 不存在（版本 %s），跳過系統主題監聽。",
                getattr(darkdetect, "__version__", "unknown"),
            )
            return

        def _thread_target() -> None:
            try:
                # 包裝呼叫：透過模組級 _listener_callback 間接轉發，
                # 確保 callback 更新後舊 thread 仍能呼叫最新的 callback。
                def _dispatch(theme: str | None) -> None:
                    cb = _listener_callback
                    if cb is not None:
                        cb(theme)

                darkdetect.listener(_dispatch)
            except Exception as exc:
                logger.error("darkdetect.listener 執行失敗：%s", exc)

        _listener_thread = threading.Thread(
            target=_thread_target,
            name="theme-system-listener",
            daemon=True,
        )
        _listener_thread.start()
        logger.debug("系統主題監聽已啟動（darkdetect.listener，daemon thread）")

    except ImportError:
        logger.warning(
            "darkdetect 不可用，跳過系統主題監聽。"
            "系統切換亮暗時應用程式不會自動跟隨。"
        )


# ---------------------------------------------------------------------------
# 向下相容別名（供既有 __init__.py 匯入使用）
# ---------------------------------------------------------------------------

def get_system_theme() -> ThemeMode:
    """偵測 Windows 系統主題（向下相容別名）。

    等同於：ThemeMode.DARK if is_system_dark() else ThemeMode.LIGHT

    Returns:
        ThemeMode.DARK 或 ThemeMode.LIGHT。
    """
    return ThemeMode.DARK if is_system_dark() else ThemeMode.LIGHT
