"""桌面應用入口 — Round 3 整合版（主題套用 + 系統主題監聽）。

使用方式：
    python -m desktop          # 透過 __main__.py
    python desktop/main.py     # 直接執行（開發用）
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

# windowed 模式（pythonw / PyInstaller console=False）下 sys.stdout/stderr 為 None，
# 第三方庫（rembg 模型下載的 tqdm 進度條等）直接寫入會 AttributeError。
# 以記憶體緩衝墊底，保證任何 print / progress bar 都不會炸掉應用。
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# 確保 desktop 套件能 import converters（專案根目錄加入 sys.path）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from desktop.main_window_v2 import MainWindowV2 as MainWindow  # W-COMMERCIAL Round 2: 切換至商用版視窗

logger = logging.getLogger(__name__)

# Windows-only single-instance socket 名稱（QSettings org/app 已固化此命名）
_SINGLE_INSTANCE_KEY = "DocConverter_SingleInstance_v1"


def main() -> int:
    """應用主進入點。

    啟動流程：
        1. 建立 QApplication 並設定應用元資料
        2. 設定應用程式圖示
        3. Single-instance 檢查：若已有實例 → 通知顯示後退出
        4. 讀取已儲存的主題模式並套用
        5. 若主題為「跟隨系統」，安裝系統主題監聽器
        6. 建立並顯示 MainWindow
        7. 進入 Qt 事件迴圈

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

    # Single-instance lock：已有實例運行則通知後退出
    server = _claim_single_instance()
    if server is None:
        logger.info("文件轉檔已在背景執行，已通知既有實例顯示視窗")
        return 0

    # 套用主題（從 QSettings 讀取；預設跟隨系統）
    _apply_startup_theme(app)

    window = MainWindow()

    # 將 single-instance server 的新連線事件導向 window.show + raise
    server.newConnection.connect(lambda: _handle_show_request(server, window))

    window.show()

    return app.exec()


def _claim_single_instance() -> QLocalServer | None:
    """嘗試佔有 single-instance socket。

    回傳 QLocalServer 表示本實例為首發；回傳 None 表示已有實例運行
    （並已透過 socket 通知它顯示視窗）。

    Returns:
        QLocalServer 實例（必須由呼叫方保持參考避免 GC），或 None（已有實例）。
    """
    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(500):
        probe.write(QByteArray(b"show\n"))
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return None

    # 清理可能殘留的 socket 檔案（前一個實例異常終止時 socket 不會自動清掉）
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)

    server = QLocalServer()
    if not server.listen(_SINGLE_INSTANCE_KEY):
        logger.warning(
            "single-instance server 建立失敗：%s — 將以無 lock 模式繼續",
            server.errorString(),
        )
    return server


def _handle_show_request(server: QLocalServer, window: MainWindow) -> None:
    """收到第二次啟動的「show」訊號 → 從托盤/最小化恢復視窗。"""
    sock = server.nextPendingConnection()
    if sock is None:
        return
    sock.waitForReadyRead(500)
    sock.readAll()  # drain（不解析內容；目前只支援單一 show 命令）
    sock.disconnectFromServer()
    try:
        window.showNormal()
        window.raise_()
        window.activateWindow()
        logger.debug("已從 single-instance 訊號恢復視窗")
    except Exception:
        logger.warning("恢復視窗失敗", exc_info=True)


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
