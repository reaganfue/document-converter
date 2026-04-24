"""通知管理器 — 應用內訊息通知的統一分發點。

職責：
    - 提供 notify() 統一入口，讓任何模組都能觸發通知（而不直接操作 UI）
    - 根據 NotificationLevel 決定顯示方式（TeachingTip / InfoBar / Toast）
    - 透過 NotificationSignals 通知 UI 層呈現通知
    - 記錄通知歷史（Round 3 可選實作）

Round 2：骨架 + Signal 定義。
Round 3 Agent C（Settings Page / 整合）：填充 notify 邏輯與 UI 連線。

依賴：
    - desktop.interfaces.NotificationSignals（Signal 契約）
    - desktop.interfaces.NotificationLevel（通知等級枚舉）
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject

from desktop.interfaces import NotificationLevel, NotificationSignals

logger = logging.getLogger(__name__)

# 通知顯示時間（毫秒）預設值
_DURATION_DEFAULTS: dict[str, int] = {
    NotificationLevel.INFO.value: 3000,
    NotificationLevel.SUCCESS.value: 3000,
    NotificationLevel.WARNING.value: 5000,
    NotificationLevel.ERROR.value: 0,      # 0 = 持續直到使用者關閉
}


class NotificationManager(QObject):
    """應用通知管理器。

    使用方式（由 MainWindowV2 建立，各 page / controller 引用）：
        manager = NotificationManager(parent=window)
        manager.signals.notify_requested.connect(window.on_notification)

        # 在任意地方發送通知：
        manager.notify("轉換完成", "已成功轉換 3 個檔案", NotificationLevel.SUCCESS)

    Signals（透過 self.signals）：
        notify_requested(str, str, str, int)
            level, title, content, duration_ms
    """

    def __init__(self, parent: Optional[QObject] = None):
        """初始化 NotificationManager。

        Args:
            parent: Qt 父物件（通常是 MainWindowV2）。
        """
        super().__init__(parent)
        self.signals = NotificationSignals()
        logger.debug("NotificationManager 初始化完成")

    def notify(
        self,
        title: str,
        content: str,
        level: NotificationLevel = NotificationLevel.INFO,
        duration_ms: Optional[int] = None,
    ) -> None:
        """發送通知請求。

        此方法不直接操作 UI，而是 emit signals.notify_requested，
        讓訂閱的 UI 元件（MainWindowV2 / HistoryPage 等）呈現通知。

        TODO(Round 3 整合)：
            - MainWindowV2 連接 self.signals.notify_requested 至
              qfluentwidgets.TeachingTip 或 InfoBar 顯示方法

        Args:
            title:       通知標題文字。
            content:     通知內容文字。
            level:       通知等級（決定顏色 / 圖示 / 預設顯示時間）。
            duration_ms: 顯示毫秒；None 時使用 level 對應的預設值。
                         0 表示持續顯示直到使用者關閉。
        """
        effective_duration = (
            duration_ms
            if duration_ms is not None
            else _DURATION_DEFAULTS.get(level.value, 3000)
        )
        logger.debug(
            "notify | level=%s title=%r content=%r duration=%dms",
            level.value, title, content, effective_duration,
        )
        self.signals.notify_requested.emit(
            level.value, title, content, effective_duration
        )

    def info(
        self,
        title: str,
        content: str = "",
        duration_ms: Optional[int] = None,
    ) -> None:
        """INFO 等級通知的便利方法。

        Args:
            title:       通知標題。
            content:     通知內容（可選）。
            duration_ms: 顯示毫秒；None 時使用 INFO 預設值（3000ms）。
        """
        self.notify(title, content, NotificationLevel.INFO, duration_ms)

    def success(
        self,
        title: str,
        content: str = "",
        duration_ms: Optional[int] = None,
    ) -> None:
        """SUCCESS 等級通知的便利方法。

        Args:
            title:       通知標題。
            content:     通知內容（可選）。
            duration_ms: 顯示毫秒；None 時使用 SUCCESS 預設值（3000ms）。
        """
        self.notify(title, content, NotificationLevel.SUCCESS, duration_ms)

    def warning(
        self,
        title: str,
        content: str = "",
        duration_ms: Optional[int] = None,
    ) -> None:
        """WARNING 等級通知的便利方法。

        Args:
            title:       通知標題。
            content:     通知內容（可選）。
            duration_ms: 顯示毫秒；None 時使用 WARNING 預設值（5000ms）。
        """
        self.notify(title, content, NotificationLevel.WARNING, duration_ms)

    def error(
        self,
        title: str,
        content: str = "",
        duration_ms: Optional[int] = None,
    ) -> None:
        """ERROR 等級通知（預設持續顯示）的便利方法。

        Args:
            title:       通知標題。
            content:     通知內容（可選）。
            duration_ms: 顯示毫秒；None 時使用 ERROR 預設值（0 = 持續顯示）。
        """
        self.notify(title, content, NotificationLevel.ERROR, duration_ms)
