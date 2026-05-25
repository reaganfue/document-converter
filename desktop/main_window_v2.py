"""商用版主視窗 — MSFluentWindow + 5 分頁導航 + 完整整合。

架構概覽：
    - 繼承 qfluentwidgets.MSFluentWindow（類 Microsoft 365 UI 風格）
    - 5 個分頁：首頁 / 批次 / 歷史 / 設定 / 關於
    - 5 個 Manager：SettingsManager / NotificationManager / HistoryManager /
                    TrayManager / ConversionController
    - 所有 Manager 初始化後注入至各 Page（set_controller / set_managers）

Round 4a 整合清單：
    - NotificationManager.signals.notify_requested → InfoBar 顯示
    - TrayManager signals → 視窗顯示 / 結束
    - Ctrl+1~5 快捷鍵切換分頁 / F5 觸發轉換 / Ctrl+Q 結束
    - 主題初始化 + settings_changed 動態切換
    - History retention policy 啟動時執行
    - closeEvent 智能行為（最小化至托盤 vs 真正結束）

視窗尺寸（CEO Q1 決策）：
    預設：1120 × 720
    最小：900 × 600
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MSFluentWindow,
    NavigationItemPosition,
)

from desktop.controllers.conversion_controller import ConversionController
from desktop.controllers.history_manager import HistoryManager
from desktop.controllers.image_tools_controller import ImageToolsController
from desktop.controllers.notification_manager import NotificationManager
from desktop.controllers.pdf_tools_controller import PdfToolsController
from desktop.controllers.settings_manager import SettingsManager
from desktop.controllers.tray_manager import TrayManager
from desktop.interfaces import PageID
from desktop.pages.about_page import AboutPage
from desktop.pages.batch_page import BatchPage
from desktop.pages.history_page import HistoryPage
from desktop.pages.home_page import HomePage
from desktop.pages.image_tools_page import ImageToolsPage
from desktop.pages.pdf_tools_page import PdfToolsPage
from desktop.pages.settings_page import SettingsPage
from desktop.utils.theme import ThemeMode, apply_theme, install_system_theme_listener
from desktop.widgets.close_choice_dialog import CloseChoiceDialog

logger = logging.getLogger(__name__)


class MainWindowV2(MSFluentWindow):
    """商用版主視窗（MSFluentWindow 整合完整版）。

    初始化順序：
        1. 視窗基本屬性（標題 / 尺寸 / 圖示）
        2. 旗標初始化（_force_quit / _first_hide_shown）
        3. 建立 5 個 Manager（settings → notification → history → tray → controller）
        4. 建立 5 個 Page
        5. 注入依賴（set_controller / set_managers）
        6. 初始化導航列
        7. 整合連線（notifications / tray / shortcuts / theme / history）

    整合 Signal 連線：
        - notification_manager.signals.notify_requested → _on_notify (InfoBar)
        - tray_manager.signals.show_window_requested   → _show_and_raise
        - tray_manager.signals.activated               → _show_and_raise
        - tray_manager.signals.quit_requested          → _real_quit
        - settings_manager.signals.setting_changed     → _on_setting_changed
    """

    WINDOW_WIDTH = 1120
    WINDOW_HEIGHT = 720
    WINDOW_MIN_WIDTH = 900
    WINDOW_MIN_HEIGHT = 600

    def __init__(self):
        super().__init__()
        self._configure_window()

        # 旗標：_force_quit 由 _real_quit() 設置，讓 closeEvent 跳過托盤分支
        self._force_quit = False
        # 旗標：第一次最小化到托盤時顯示提示氣泡
        self._first_hide_shown = False

        self._init_managers()
        self._init_controller()
        self._init_pages()
        self._inject_dependencies()
        self._init_navigation()

        # ── Round 4a 整合 ──────────────────────────────────────────────────
        self._setup_notifications()
        self._setup_tray()
        self._setup_shortcuts()
        self._apply_initial_theme()
        self._configure_history_recording()
        self._apply_history_retention()
        # ───────────────────────────────────────────────────────────────────

        logger.info("MainWindowV2 初始化完成（Round 4a 整合版）")

    # =========================================================================
    # 視窗基本配置
    # =========================================================================

    def _configure_window(self) -> None:
        """設定視窗基本屬性：標題 / 尺寸 / 最小尺寸 / 圖示。"""
        self.setWindowTitle("文件轉檔")
        self.resize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.setMinimumSize(self.WINDOW_MIN_WIDTH, self.WINDOW_MIN_HEIGHT)

        ico = self._get_icon_path()
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))
        else:
            logger.debug("app.ico 不存在，跳過圖示設定：%s", ico)

    def _init_managers(self) -> None:
        """按依賴順序建立 4 個 Manager（settings 最先）。"""
        self.settings_manager = SettingsManager(self)
        self.notification_manager = NotificationManager(self)
        self.history_manager = HistoryManager(parent=self)
        self.tray_manager = TrayManager(
            icon_path=self._get_icon_path(),
            parent=self,
        )

    def _init_controller(self) -> None:
        """建立 ConversionController + PdfToolsController + ImageToolsController。"""
        self.controller = ConversionController(self)
        self.pdf_tools_controller = PdfToolsController(self)
        self.image_tools_controller = ImageToolsController(self)

    def _init_pages(self) -> None:
        """建立 7 個頁面實例(含 PDF / Image 工具)。"""
        self.home_page = HomePage(self)
        self.batch_page = BatchPage(self)
        self.pdf_tools_page = PdfToolsPage(self)
        self.image_tools_page = ImageToolsPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)
        self.about_page = AboutPage(self)

    def _inject_dependencies(self) -> None:
        """向所有頁面注入 controller 與 managers。

        共用 ConversionController 的 pages 走 self.controller;
        PDF 工具分頁則使用獨立的 PdfToolsController。
        所有頁面都注入相同的 managers 字典(包含 self 作為 navigation manager)。
        """
        managers = {
            "history": self.history_manager,
            "settings": self.settings_manager,
            "notification": self.notification_manager,
            "tray": self.tray_manager,
            "navigation": self,  # MainWindowV2 提供 navigate_to(page_id) 方法
        }
        # 共用 ConversionController 的 pages
        conversion_pages = (
            self.home_page,
            self.batch_page,
            self.history_page,
            self.settings_page,
            self.about_page,
        )
        for page in conversion_pages:
            page.set_controller(self.controller)
            page.set_managers(**managers)

        # PDF 工具分頁用獨立 controller
        self.pdf_tools_page.set_controller(self.pdf_tools_controller)
        self.pdf_tools_page.set_managers(**managers)

        # 圖片工具分頁用獨立 controller
        self.image_tools_page.set_controller(self.image_tools_controller)
        self.image_tools_page.set_managers(**managers)

    def _init_navigation(self) -> None:
        """設定 MSFluentWindow 導航列。

        主導航(TOP):首頁 / 批次 / PDF 工具 / 歷史
        底部導航(BOTTOM):設定 / 關於
        預設頁面:首頁
        """
        self.addSubInterface(
            self.home_page,
            FluentIcon.HOME,
            "首頁",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.batch_page,
            FluentIcon.FOLDER,
            "批次",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.pdf_tools_page,
            FluentIcon.DOCUMENT,
            "PDF 工具",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.image_tools_page,
            FluentIcon.PHOTO,
            "圖片工具",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.history_page,
            FluentIcon.HISTORY,
            "歷史",
            position=NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self.settings_page,
            FluentIcon.SETTING,
            "設定",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.about_page,
            FluentIcon.INFO,
            "關於",
            position=NavigationItemPosition.BOTTOM,
        )

        # 預設顯示首頁
        self.switchTo(self.home_page)

    # =========================================================================
    # Navigation Manager API(供 pages 透過 managers["navigation"] 呼叫)
    # =========================================================================

    def navigate_to(self, page_id: str) -> None:
        """根據 PageID.value 切換到對應分頁。

        供 history_page 的「再次轉換」、空態頁的「前往首頁」等情境使用。

        Args:
            page_id: PageID Enum 的字串值(例如 "home" / "pdf_tools")。
        """
        page_map = {
            PageID.HOME.value:        self.home_page,
            PageID.BATCH.value:       self.batch_page,
            PageID.PDF_TOOLS.value:   self.pdf_tools_page,
            PageID.IMAGE_TOOLS.value: self.image_tools_page,
            PageID.HISTORY.value:     self.history_page,
            PageID.SETTINGS.value:    self.settings_page,
            PageID.ABOUT.value:       self.about_page,
        }
        page = page_map.get(page_id)
        if page is None:
            logger.warning("navigate_to: 未知 page_id=%s", page_id)
            return
        try:
            self.switchTo(page)
            logger.debug("navigate_to: 切換至 %s", page_id)
        except Exception as exc:
            logger.warning("navigate_to(%s) 失敗:%s", page_id, exc)

    # =========================================================================
    # Step 1 — Notification → InfoBar
    # =========================================================================

    def _setup_notifications(self) -> None:
        """訂閱 NotificationManager.signals.notify_requested → InfoBar 顯示。"""
        self.notification_manager.signals.notify_requested.connect(self._on_notify)

    def _on_notify(
        self,
        level: str,
        title: str,
        content: str,
        duration_ms: int,
    ) -> None:
        """依通知等級呼叫對應 InfoBar 類別方法。

        Args:
            level:       "info" | "success" | "warning" | "error"
            title:       通知標題
            content:     通知內容
            duration_ms: 顯示毫秒；0 表示持續顯示直到使用者關閉
        """
        level_map = {
            "success": InfoBar.success,
            "error": InfoBar.error,
            "warning": InfoBar.warning,
            "info": InfoBar.info,
        }
        fn = level_map.get(level, InfoBar.info)
        # duration_ms=0 → InfoBar duration=-1（不自動關閉）
        duration = duration_ms if duration_ms > 0 else -1
        try:
            fn(
                title=title,
                content=content,
                orient=1,           # Qt.Orientation.Horizontal
                isClosable=True,
                duration=duration,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
        except Exception:
            logger.warning(
                "_on_notify: InfoBar 顯示失敗 level=%s title=%r",
                level, title, exc_info=True,
            )

    # =========================================================================
    # Step 2 — Tray 整合
    # =========================================================================

    def _setup_tray(self) -> None:
        """連接 TrayManager signals，顯示托盤圖示（若系統支援）。"""
        self.tray_manager.signals.show_window_requested.connect(self._show_and_raise)
        self.tray_manager.signals.activated.connect(self._show_and_raise)
        self.tray_manager.signals.quit_requested.connect(self._real_quit)

        if self.tray_manager.is_available:
            self.tray_manager.show()
            logger.debug("系統托盤已顯示")
        else:
            logger.warning("系統不支援托盤圖示")

    def _show_and_raise(self) -> None:
        """從托盤恢復視窗（show + raise + activate）。"""
        self.show()
        self.raise_()
        self.activateWindow()

    def _real_quit(self) -> None:
        """強制結束應用（繞過 closeEvent 的托盤最小化分支）。"""
        self._force_quit = True
        self.close()

    # =========================================================================
    # Step 3 — 快捷鍵
    # =========================================================================

    def _setup_shortcuts(self) -> None:
        """安裝 Ctrl+1~5 / F5 / Ctrl+Q 快捷鍵。

        _page_shortcuts 持有 QShortcut 參考，防止被 GC 回收。
        """
        page_bindings = [
            (self.home_page, "Ctrl+1"),
            (self.batch_page, "Ctrl+2"),
            (self.pdf_tools_page, "Ctrl+3"),
            (self.image_tools_page, "Ctrl+4"),
            (self.history_page, "Ctrl+5"),
            (self.settings_page, "Ctrl+6"),
            (self.about_page, "Ctrl+7"),
        ]
        self._page_shortcuts: list[QShortcut] = []
        for page, seq in page_bindings:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda p=page: self._switch_to(p))
            self._page_shortcuts.append(sc)

        # F5：若當前在首頁，觸發「全部轉換」
        f5 = QShortcut(QKeySequence("F5"), self)
        f5.activated.connect(self._on_global_f5)
        self._page_shortcuts.append(f5)

        # Ctrl+Q：強制結束
        ctrl_q = QShortcut(QKeySequence("Ctrl+Q"), self)
        ctrl_q.activated.connect(self._real_quit)
        self._page_shortcuts.append(ctrl_q)

    def _switch_to(self, page) -> None:
        """切換至指定分頁（使用 MSFluentWindow.switchTo）。"""
        self.switchTo(page)

    def _on_global_f5(self) -> None:
        """F5 快捷鍵：只在首頁且有任務時觸發 start_all。"""
        if self.stackedWidget.currentWidget() is self.home_page:
            try:
                self.controller.start_all()
            except Exception:
                logger.warning("_on_global_f5: start_all 失敗", exc_info=True)

    # =========================================================================
    # Step 4 — 主題初始化 + 動態切換
    # =========================================================================

    def _apply_initial_theme(self) -> None:
        """套用啟動主題（從 SettingsManager 讀取），並安裝系統主題監聽。

        main.py 的 _apply_startup_theme 在 QApplication 層已套用過主題，
        此處確保 MainWindowV2 建立後設定不漂移，並掛接 setting_changed。
        """
        theme = self.settings_manager.get("theme", "system")
        apply_theme(theme)
        if theme == "system":
            install_system_theme_listener(
                lambda _=None: apply_theme(ThemeMode.SYSTEM)
            )
        self.settings_manager.signals.setting_changed.connect(
            self._on_setting_changed
        )

    def _on_setting_changed(self, key: str, value: object) -> None:
        """響應 SettingsManager 任意設定變更。

        Args:
            key:   設定鍵名。
            value: 新設定值。
        """
        if key == "theme":
            apply_theme(str(value))
            if str(value) == "system":
                install_system_theme_listener(
                    lambda _=None: apply_theme(ThemeMode.SYSTEM)
                )

    # =========================================================================
    # Step 5 — History 記錄控制（record_history 開關）
    # =========================================================================

    def _configure_history_recording(self) -> None:
        """依 record_history 設定決定 Pages 的 _history_manager 是否生效。

        若 record_history=False，將 home_page._history_manager 設為 None，
        讓 HomePage 的寫入邏輯跳過。不修改任何 pages/*.py 檔案。
        """
        enabled = self.settings_manager.get("record_history", True)
        self._apply_history_manager_to_pages(enabled)

        def _on_change(key: str, value: object) -> None:
            if key == "record_history":
                self._apply_history_manager_to_pages(bool(value))

        self.settings_manager.signals.setting_changed.connect(_on_change)

    def _apply_history_manager_to_pages(self, enabled: bool) -> None:
        """將 _history_manager 注入（或清除）至持有此屬性的 pages。

        Args:
            enabled: True → 注入 self.history_manager；False → 設為 None。
        """
        target = self.history_manager if enabled else None
        for page in (self.home_page, self.batch_page):
            if hasattr(page, "_history_manager"):
                page._history_manager = target

    # =========================================================================
    # Step 7 — History retention policy
    # =========================================================================

    def _apply_history_retention(self) -> None:
        """啟動時執行一次歷史保留策略清理。

        失敗時靜默 — 不影響主流程。
        """
        try:
            max_records = self.settings_manager.get("history_max_records", 1000)
            max_age = self.settings_manager.get("history_retention_days", 90)
            deleted = self.history_manager.apply_retention_policy(
                max_records=max_records,
                max_age_days=max_age,
            )
            if deleted > 0:
                logger.info("啟動保留策略：清除 %d 筆舊記錄", deleted)
        except Exception:
            logger.warning("_apply_history_retention 失敗（忽略）", exc_info=True)

    # =========================================================================
    # Step 6 — closeEvent 智能行為
    # =========================================================================

    def closeEvent(self, event) -> None:
        """應用關閉事件。

        流程：
            - _force_quit=True（從 _real_quit / Ctrl+Q 觸發）→ 直接關閉
            - close_action="ask"  → 彈窗詢問，依使用者選擇進入 tray / quit 分支
            - close_action="tray" 且 minimize_to_tray=True → 隱藏至托盤
            - 否則 → 真正結束（_teardown）
        """
        if self._force_quit:
            self._teardown(event)
            return

        close_action = self.settings_manager.get("close_action", "ask")

        # 第一道：ask 分支彈窗,解析後 fall through 到對應分支
        if close_action == "ask":
            dialog = CloseChoiceDialog(self)
            if not dialog.exec():
                # ESC 取消 → 不關閉應用
                event.ignore()
                return
            choice = dialog.choice or "tray"
            if dialog.remember:
                self.settings_manager.set("close_action", choice)
            close_action = choice

        minimize = self.settings_manager.get("minimize_to_tray", True)

        if close_action == "tray" and minimize:
            event.ignore()
            self.hide()
            # 首次最小化至托盤：顯示氣泡提示
            if not self._first_hide_shown:
                self._first_hide_shown = True
                try:
                    self.tray_manager.show_message(
                        "文件轉檔已最小化到系統匣",
                        "雙擊托盤圖示可重新開啟視窗；右鍵選「結束」可完整關閉。",
                    )
                except Exception:
                    logger.debug("tray show_message 失敗（忽略）", exc_info=True)
        else:
            self._teardown(event)

    def _teardown(self, event) -> None:
        """真正關閉：取消任務 → 等待 ThreadPool → 關 DB → 隱藏托盤。

        Args:
            event: QCloseEvent，呼叫 super().closeEvent(event) 完成關閉流程。
        """
        try:
            self.controller.cancel_all()
        except Exception:
            logger.warning("cancel_all 在關閉時失敗", exc_info=True)

        QThreadPool.globalInstance().waitForDone(500)

        try:
            self.history_manager.close()
        except Exception:
            logger.warning("HistoryManager.close 失敗", exc_info=True)

        try:
            self.tray_manager.hide()
        except Exception:
            logger.debug("tray_manager.hide 失敗（忽略）", exc_info=True)

        super().closeEvent(event)

    # =========================================================================
    # 工具方法
    # =========================================================================

    @staticmethod
    def _get_icon_path() -> Path:
        """回傳應用圖示路徑。"""
        return Path(__file__).parent / "resources" / "app.ico"
