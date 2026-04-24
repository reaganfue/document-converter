"""系統托盤管理器 — QSystemTrayIcon 的業務層包裝。

職責：
    - 建立並管理系統托盤圖示與右鍵選單
    - 處理托盤點擊事件（雙擊顯示視窗 / 右鍵選單）
    - 透過 TraySignals 通知 MainWindowV2 顯示 / 退出
    - 在托盤氣泡（showMessage）顯示完成通知（Round 3 可選）

Round 2：骨架 + Signal 定義 + QSystemTrayIcon 初始化。
Round 3 整合：填充右鍵選單 + 連接 MainWindowV2 的 show/hide/quit。

依賴：
    - PySide6.QtWidgets.QSystemTrayIcon（系統托盤 API）
    - desktop.interfaces.TraySignals（Signal 契約）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from desktop.interfaces import TraySignals

logger = logging.getLogger(__name__)


class TrayManager(QObject):
    """系統托盤管理器。

    使用方式（由 MainWindowV2 建立）：
        manager = TrayManager(icon_path=Path("app.ico"), parent=window)
        manager.signals.show_window_requested.connect(window.showNormal)
        manager.signals.quit_requested.connect(app.quit)
        manager.show()

    Signals（透過 self.signals）：
        show_window_requested()   使用者要求顯示視窗
        quit_requested()          使用者要求結束應用
        activated()               托盤圖示被啟動（單擊 / 雙擊）
    """

    def __init__(
        self,
        icon_path: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ):
        """初始化 TrayManager，建立托盤圖示與右鍵選單骨架。

        Args:
            icon_path: 托盤圖示路徑（.ico / .png）。None 時使用預設空圖示。
            parent:    Qt 父物件（通常是 MainWindowV2）。
        """
        super().__init__(parent)
        self.signals = TraySignals()
        self._tray = QSystemTrayIcon(self)
        self._menu = QMenu()

        # 設定圖示
        if icon_path and icon_path.exists():
            self._tray.setIcon(QIcon(str(icon_path)))
        else:
            logger.warning("托盤圖示不存在：%s，使用空圖示", icon_path)

        self._tray.setToolTip("文件轉檔")
        self._setup_menu()
        self._connect_signals()
        logger.debug("TrayManager 初始化完成")

    def _setup_menu(self) -> None:
        """建立托盤右鍵選單骨架。

        TODO(Round 3 整合)：
            - 「顯示視窗」action → emit signals.show_window_requested
            - 分隔線
            - 「結束」action → emit signals.quit_requested
        """
        # Round 2 骨架：空選單
        show_action = self._menu.addAction("顯示視窗")
        show_action.triggered.connect(self.signals.show_window_requested.emit)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("結束")
        quit_action.triggered.connect(self.signals.quit_requested.emit)

        self._tray.setContextMenu(self._menu)

    def _connect_signals(self) -> None:
        """連接 QSystemTrayIcon 的原生事件至 TraySignals。"""
        self._tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """處理托盤圖示啟動事件。

        雙擊 → 發送 show_window_requested；所有啟動事件 → 發送 activated。

        Args:
            reason: Qt 托盤啟動原因枚舉。
        """
        self.signals.activated.emit()
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.debug("托盤雙擊：請求顯示視窗")
            self.signals.show_window_requested.emit()

    def show(self) -> None:
        """顯示托盤圖示。應在 MainWindowV2 初始化完成後呼叫。"""
        self._tray.show()
        logger.debug("托盤圖示已顯示")

    def hide(self) -> None:
        """隱藏托盤圖示。"""
        self._tray.hide()

    def show_message(
        self,
        title: str,
        content: str,
        *,
        duration_ms: int = 3000,
    ) -> None:
        """在托盤氣泡顯示訊息（Round 3 可由 NotificationManager 觸發）。

        Args:
            title:       氣泡標題。
            content:     氣泡內容。
            duration_ms: 顯示毫秒。

        TODO(Round 3 整合)：
            - 根據 NotificationLevel 選擇 QSystemTrayIcon.MessageIcon
        """
        self._tray.showMessage(title, content, QSystemTrayIcon.MessageIcon.Information, duration_ms)

    @property
    def is_available(self) -> bool:
        """系統是否支援托盤（某些 Linux 環境不支援）。"""
        return QSystemTrayIcon.isSystemTrayAvailable()
