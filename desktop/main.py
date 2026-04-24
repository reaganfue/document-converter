"""桌面應用入口 — Round 3 整合版（主題套用 + 系統主題監聽）。

使用方式：
    python -m desktop          # 透過 __main__.py
    python desktop/main.py     # 直接執行（開發用）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 確保 desktop 套件能 import converters（專案根目錄加入 sys.path）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from desktop.main_window_v2 import MainWindowV2 as MainWindow  # W-COMMERCIAL Round 2: 切換至商用版視窗

logger = logging.getLogger(__name__)


def main() -> int:
    """應用主進入點。

    啟動流程：
        1. 建立 QApplication 並設定應用元資料
        2. 設定應用程式圖示
        3. 讀取已儲存的主題模式並套用
        4. 若主題為「跟隨系統」，安裝系統主題監聽器
        5. 建立並顯示 MainWindow
        6. 進入 Qt 事件迴圈

    Returns:
        Qt 事件迴圈的退出碼（0 表示正常退出）。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("文件轉檔")
    app.setOrganizationName("DocConverter")
    app.setApplicationVersion("1.0.0")

    # 設定應用程式圖示（工作列、Alt+Tab）
    resources_dir = Path(__file__).parent / "resources"
    ico_path = resources_dir / "app.ico"
    svg_path = resources_dir / "app_icon.svg"
    if ico_path.exists():
        app.setWindowIcon(QIcon(str(ico_path)))
    elif svg_path.exists():
        app.setWindowIcon(QIcon(str(svg_path)))

    # 套用主題（從 QSettings 讀取；預設跟隨系統）
    _apply_startup_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()


def _apply_startup_theme(app: QApplication) -> None:
    """讀取儲存的主題模式並套用；若為 SYSTEM 則安裝監聽器。

    將主題邏輯拆分至獨立函式，讓 main() 保持在 50 行有效代碼內。

    Args:
        app: 當前 QApplication 實例（未使用，保留供未來 palette 整合）。
    """
    try:
        from desktop.utils.theme import (
            ThemeMode,
            apply_theme,
            get_current_mode,
            install_system_theme_listener,
        )

        mode = get_current_mode()
        apply_theme(mode)
        logger.debug("啟動主題已套用：mode=%s", mode.value)

        if mode is ThemeMode.SYSTEM:
            # darkdetect.listener 的 callback 接收一個字串引數（主題名稱）
            # 但 install_system_theme_listener 期望 Callable[[], None]
            # 此處用 lambda 吸收引數，保持 API 相容
            install_system_theme_listener(
                lambda _=None: apply_theme(ThemeMode.SYSTEM)
            )
            logger.debug("系統主題監聽器已安裝")

    except Exception as exc:
        logger.error("啟動主題套用失敗，應用程式以預設主題繼續：%s", exc)


if __name__ == "__main__":
    sys.exit(main())
