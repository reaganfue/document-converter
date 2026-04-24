"""抽象頁面基類 — Round 3 所有 page 繼承此。

設計原則：
    - 統一外邊距（24px 左右，20px 上下）
    - 統一生命週期鉤子（on_enter / on_leave / on_close）
    - 提供 set_controller / set_managers 注入介面（由 MainWindowV2 呼叫）
    - 子類只需實作 _setup_ui()，不需操心佈局樣板

生命週期（由 MainWindowV2 或父類管理）：
    __init__    頁面建立（僅一次，QApplication 啟動時）
    on_enter()  頁面成為活動頁時呼叫
    on_leave()  離開頁面時呼叫
    on_close()  應用程式關閉前呼叫（清理資源）
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from desktop.interfaces import PageID


class BasePage(QWidget):
    """商用應用分頁基類。

    子類必須定義的 class 屬性：
        PAGE_ID    (PageID)  唯一頁面識別 ID
        PAGE_TITLE (str)     導航列顯示名稱
        PAGE_ICON  (object)  qfluentwidgets.FluentIcon 枚舉值

    子類必須實作的方法：
        _setup_ui()          建立頁面 UI 元件（一次性）
    """

    PAGE_ID: PageID = None    # type: ignore[assignment]
    PAGE_TITLE: str = ""
    PAGE_ICON: object = None  # qfluentwidgets.FluentIcon

    def __init__(self, parent=None):
        super().__init__(parent)

        # 設定 objectName，供 MSFluentWindow 導航路由識別
        obj_name = self.PAGE_ID.value if self.PAGE_ID else self.__class__.__name__
        self.setObjectName(obj_name)

        self._is_active: bool = False
        self._controller = None       # 由 set_controller() 注入
        self._managers: dict = {}     # 由 set_managers() 注入

        self._setup_base_ui()
        self._setup_ui()

    def _setup_base_ui(self) -> None:
        """建立通用外層 layout（子類不應覆寫）。

        提供 self._content_layout（QVBoxLayout），
        子類在 _setup_ui() 中向此 layout 添加元件。
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self._content_layout = layout

    def _setup_ui(self) -> None:
        """建立頁面具體 UI（子類必須覆寫）。

        向 self._content_layout 添加頁面所需元件。
        此方法在 __init__ 中自動呼叫一次。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 必須實作 _setup_ui()"
        )

    # =========================================================================
    # 生命週期鉤子（子類可選覆寫）
    # =========================================================================

    def on_enter(self) -> None:
        """頁面成為活動頁時呼叫（可選覆寫）。

        典型用途：
            - 刷新資料（HistoryPage：重新載入記錄清單）
            - 啟動定時器 / 動畫
        """
        self._is_active = True

    def on_leave(self) -> None:
        """離開活動頁面時呼叫（可選覆寫）。

        典型用途：
            - 停止定時器 / 動畫
            - 暫停背景任務
        """
        self._is_active = False

    def on_close(self) -> None:
        """應用程式關閉前呼叫（可選覆寫）。

        典型用途：
            - 釋放非 Qt 資源
            - 儲存頁面狀態
        """

    # =========================================================================
    # 依賴注入（由 MainWindowV2 呼叫）
    # =========================================================================

    def set_controller(self, controller) -> None:
        """注入 ConversionController（Round 3 連接 signals）。

        Args:
            controller: ConversionController 實例。
        """
        self._controller = controller

    def set_managers(self, **managers) -> None:
        """注入 manager 字典（Round 3 各 page 按需取用）。

        Args:
            history:      HistoryManager 實例
            settings:     SettingsManager 實例
            notification: NotificationManager 實例
            tray:         TrayManager 實例
        """
        self._managers = managers

    # =========================================================================
    # 便利存取
    # =========================================================================

    @property
    def is_active(self) -> bool:
        """頁面當前是否為活動頁。"""
        return self._is_active
