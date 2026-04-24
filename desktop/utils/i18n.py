"""國際化（i18n）基礎骨架。

Round 2：pass-through 模式（t(key) → key or default）。
未來擴展：
    - 讀取 locale JSON 檔案（例如 desktop/locales/zh_TW.json）
    - 依系統語系自動切換
    - 支援 placeholder 替換（t("n_files", n=3) → "3 個檔案"）

使用方式：
    from desktop.utils.i18n import t
    label.setText(t("convert.button", default="開始轉換"))
"""
from __future__ import annotations


def t(key: str, default: str | None = None, **kwargs) -> str:
    """翻譯鍵查詢。

    Round 2 實作：直接回傳 default（若提供）或 key 本身。

    Args:
        key:     翻譯鍵，慣例格式為 "section.sub_key"（例如 "home.convert_button"）。
        default: 找不到翻譯時的備援文字；None 時回傳 key。
        **kwargs: 佔位符替換（Round 2 忽略，未來版本使用）。

    Returns:
        翻譯後的字串（Round 2 直接回傳 default 或 key）。

    Examples:
        >>> t("home.convert_button", default="開始轉換")
        '開始轉換'
        >>> t("unknown.key")
        'unknown.key'
    """
    return default if default is not None else key
