"""使用者資料夾路徑管理。

負責決定輸出資料夾、設定檔位置等與使用者環境相關的路徑。

設計原則：
    - 所有路徑皆以 Path 物件回傳（不回傳 str）
    - 目錄不存在時自動建立（呼叫 ensure_dir）
    - 不依賴任何 Qt 元件（可在 QApplication 初始化前呼叫）
"""
from __future__ import annotations

import os
from pathlib import Path


# 應用程式名稱（與 QApplication.setOrganizationName 一致）
APP_NAME: str = "DocConverter"


def get_app_data_dir() -> Path:
    """回傳應用程式資料目錄（%LOCALAPPDATA%/DocConverter）。

    在 Windows 上：C:/Users/<User>/AppData/Local/DocConverter
    在其他平台（開發環境）：~/.config/DocConverter

    Returns:
        應用程式資料目錄 Path，目錄不存在時自動建立。
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".config"

    app_dir = base / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_default_output_dir() -> Path:
    """回傳預設輸出資料夾（%LOCALAPPDATA%/DocConverter/outputs）。

    Returns:
        輸出目錄 Path，目錄不存在時自動建立。
    """
    output_dir = get_app_data_dir() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def get_settings_path() -> Path:
    """回傳設定檔路徑（%LOCALAPPDATA%/DocConverter/settings.json）。

    Returns:
        設定檔 Path（檔案不存在時不自動建立）。
    """
    return get_app_data_dir() / "settings.json"


def ensure_dir(directory: Path) -> Path:
    """確保目錄存在，若不存在則建立（包含父目錄）。

    Args:
        directory: 目標目錄 Path。

    Returns:
        傳入的 directory（方便 chaining）。
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resolve_output_path(
    source_path: Path,
    target_format: str,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """根據來源檔案、目標格式和輸出目錄計算輸出路徑。

    若 overwrite=False 且目標路徑已存在，自動附加序號（file_1.pdf, file_2.pdf）。

    Args:
        source_path: 來源檔案路徑。
        target_format: 目標格式（小寫無點，例如 "pdf"）。
        output_dir: 輸出目錄。
        overwrite: 是否覆寫已存在的同名檔案。

    Returns:
        最終輸出路徑（絕對路徑）。
    """
    stem = source_path.stem
    candidate = output_dir / f"{stem}.{target_format}"

    if overwrite or not candidate.exists():
        return candidate

    counter = 1
    while True:
        candidate = output_dir / f"{stem}_{counter}.{target_format}"
        if not candidate.exists():
            return candidate
        counter += 1
