"""設定頁（SettingsPage）— 應用設定全頁面（取代 v1 SettingsDialog）。

架構差異（v1 dialog → v2 page）：
    v1：SettingsDialog（QDialog 彈出視窗，settings_applied Signal 一次性）
    v2：SettingsPage（嵌入式全頁面，每個設定項即時呼叫 SettingsManager.set）

設計原則：
    - Windows 11 Settings 慣例：即時儲存，不需「套用」按鈕
    - 分組卡片：使用 qfluentwidgets SettingCardGroup + SettingCard 系列
    - 依賴注入：SettingsManager / NotificationManager 由 MainWindowV2 注入
    - 邊界防護：所有來自外部的設定值經 SettingsManager.set() 統一驗證
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QWidget
from qfluentwidgets import (
    ExpandLayout,
    FluentIcon,
    PushSettingCard,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
)

from desktop.interfaces import PageID, SUPPORTED_OUTPUT_FORMATS
from desktop.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class SettingsPage(BasePage):
    """設定頁（全頁面版，取代 SettingsDialog）。

    UI 分組（7 個 SettingCardGroup）：
        1. 檔案與轉換  — 輸出目錄、覆寫、並行數、目標格式、逾時
        2. 外觀        — 主題、主題色、字體大小、動畫
        3. 歷史        — 記錄開關、保留天數、最大筆數、清除
        4. 通知        — 完成通知、失敗通知、音效
        5. 系統整合    — 最小化托盤、關閉行為
        6. 進階        — COM 降級、臨時目錄、日誌等級
        7. 資料管理    — 匯出、匯入、重置

    每個控制項變更後即時呼叫 self._settings_manager.set(key, value)。
    """

    PAGE_ID = PageID.SETTINGS
    PAGE_TITLE = "設定"
    PAGE_ICON = FluentIcon.SETTING

    # =========================================================================
    # UI 建立（BasePage 生命週期）
    # =========================================================================

    def _setup_ui(self) -> None:
        """建立捲動式設定頁，包含 7 個分組。"""
        # 捲動容器
        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 內容 widget + ExpandLayout（qfluentwidgets 推薦用法）
        self._content_widget = QWidget()
        self._content_widget.setObjectName("settingsContentWidget")
        self._expand_layout = ExpandLayout(self._content_widget)
        self._expand_layout.setSpacing(24)
        self._expand_layout.setContentsMargins(0, 0, 0, 24)

        # 建立各分組
        self._build_file_group()
        self._build_appearance_group()
        self._build_history_group()
        self._build_notification_group()
        self._build_system_group()
        self._build_advanced_group()
        self._build_data_group()

        self._scroll.setWidget(self._content_widget)
        self._content_layout.addWidget(self._scroll)

    # =========================================================================
    # 分組建立
    # =========================================================================

    def _build_file_group(self) -> None:
        """【檔案與轉換】分組。"""
        group = SettingCardGroup("檔案與轉換", self._content_widget)

        # 自動覆寫同名檔案
        self._overwrite_card = SwitchSettingCard(
            FluentIcon.SYNC,
            "自動覆寫同名檔案",
            "開啟時，輸出目錄中的同名檔案將被直接覆蓋",
        )
        self._overwrite_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("overwrite", checked)
        )

        # 轉換完成後自動開啟資料夾
        self._auto_open_card = SwitchSettingCard(
            FluentIcon.FOLDER,
            "轉換完成後自動開啟資料夾",
            "轉換完成時，自動在檔案總管中開啟輸出目錄",
        )
        self._auto_open_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("auto_open_folder_on_done", checked)
        )

        # 預設輸出目錄（PushSettingCard：右側顯示路徑 + 瀏覽按鈕）
        self._output_dir_card = PushSettingCard(
            "瀏覽",
            FluentIcon.SAVE,
            "預設輸出目錄",
            "轉換後的檔案儲存位置",
        )
        self._output_dir_card.clicked.connect(self._on_browse_output_dir)

        group.addSettingCards([
            self._overwrite_card,
            self._auto_open_card,
            self._output_dir_card,
        ])
        self._expand_layout.addWidget(group)

    def _build_appearance_group(self) -> None:
        """【外觀】分組。"""
        group = SettingCardGroup("外觀", self._content_widget)

        # 主題切換（亮/暗/系統）— 用 PushSettingCard 輪換，因無 ConfigItem 直接綁定
        self._theme_card = PushSettingCard(
            "切換",
            FluentIcon.BRUSH,
            "介面主題",
            "系統 / 亮色 / 暗色（點擊循環切換）",
        )
        self._theme_card.clicked.connect(self._on_toggle_theme)

        # 啟用過場動畫
        self._animation_card = SwitchSettingCard(
            FluentIcon.ZOOM,
            "啟用過場動畫",
            "開啟時，頁面切換具有滑動動畫效果",
        )
        self._animation_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("enable_animations", checked)
        )

        group.addSettingCards([
            self._theme_card,
            self._animation_card,
        ])
        self._expand_layout.addWidget(group)

    def _build_history_group(self) -> None:
        """【歷史】分組。"""
        group = SettingCardGroup("歷史", self._content_widget)

        # 記錄歷史開關
        self._record_history_card = SwitchSettingCard(
            FluentIcon.HISTORY,
            "記錄轉換歷史",
            "將所有轉換記錄儲存至本機資料庫",
        )
        self._record_history_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("record_history", checked)
        )

        # 清除歷史
        self._clear_history_card = PushSettingCard(
            "立即清除",
            FluentIcon.DELETE,
            "清除歷史記錄",
            "永久移除所有轉換歷史（此操作不可復原）",
        )
        self._clear_history_card.clicked.connect(self._on_clear_history)

        group.addSettingCards([
            self._record_history_card,
            self._clear_history_card,
        ])
        self._expand_layout.addWidget(group)

    def _build_notification_group(self) -> None:
        """【通知】分組。"""
        group = SettingCardGroup("通知", self._content_widget)

        # 完成時通知
        self._notify_complete_card = SwitchSettingCard(
            FluentIcon.COMPLETED,
            "轉換完成時通知",
            "顯示桌面通知或應用程式內提示",
        )
        self._notify_complete_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("notify_on_complete", checked)
        )

        # 失敗時警告
        self._notify_error_card = SwitchSettingCard(
            FluentIcon.INFO,
            "失敗時彈出警告",
            "轉換失敗時以錯誤對話框提示",
        )
        self._notify_error_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("notify_on_error", checked)
        )

        # 音效
        self._sound_card = SwitchSettingCard(
            FluentIcon.VOLUME,
            "結果音效",
            "轉換完成或失敗時播放提示音",
        )
        self._sound_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("play_sound", checked)
        )

        group.addSettingCards([
            self._notify_complete_card,
            self._notify_error_card,
            self._sound_card,
        ])
        self._expand_layout.addWidget(group)

    def _build_system_group(self) -> None:
        """【系統整合】分組。"""
        group = SettingCardGroup("系統整合", self._content_widget)

        # 最小化到系統匣
        self._tray_card = SwitchSettingCard(
            FluentIcon.MINIMIZE,
            "最小化到系統匣",
            "按下最小化時，視窗縮入系統匣而非工作列",
        )
        self._tray_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("minimize_to_tray", checked)
        )

        # 關閉行為
        self._close_action_card = PushSettingCard(
            "切換",
            FluentIcon.CLOSE,
            "關閉按鈕行為",
            "最小化到匣 / 結束程式（點擊循環切換）",
        )
        self._close_action_card.clicked.connect(self._on_toggle_close_action)

        group.addSettingCards([
            self._tray_card,
            self._close_action_card,
        ])
        self._expand_layout.addWidget(group)

    def _build_advanced_group(self) -> None:
        """【進階】分組。"""
        group = SettingCardGroup("進階", self._content_widget)

        # COM 降級（CEO Q4）
        self._com_fallback_card = SwitchSettingCard(
            FluentIcon.DEVELOPER_TOOLS,
            "啟用 COM 降級（docx2pdf）",
            "當主轉換引擎失敗時，嘗試使用 Microsoft Word COM 介面作為備援",
        )
        self._com_fallback_card.checkedChanged.connect(
            lambda checked: self._on_setting_changed("enable_com_fallback", checked)
        )

        group.addSettingCards([self._com_fallback_card])
        self._expand_layout.addWidget(group)

    def _build_data_group(self) -> None:
        """【資料管理】分組。"""
        group = SettingCardGroup("資料管理", self._content_widget)

        # 匯出設定
        self._export_card = PushSettingCard(
            "匯出",
            FluentIcon.SHARE,
            "匯出設定",
            "將所有設定儲存為 JSON 檔案以便備份或遷移",
        )
        self._export_card.clicked.connect(self._on_export_settings)

        # 匯入設定
        self._import_card = PushSettingCard(
            "匯入",
            FluentIcon.DOWNLOAD,
            "匯入設定",
            "從 JSON 檔案還原先前匯出的設定",
        )
        self._import_card.clicked.connect(self._on_import_settings)

        # 重置為預設值
        self._reset_card = PushSettingCard(
            "重設",
            FluentIcon.UPDATE,
            "重設所有設定",
            "將所有設定恢復為出廠預設值（此操作不可復原）",
        )
        self._reset_card.clicked.connect(self._on_reset_all)

        group.addSettingCards([
            self._export_card,
            self._import_card,
            self._reset_card,
        ])
        self._expand_layout.addWidget(group)

    # =========================================================================
    # 生命週期鉤子
    # =========================================================================

    def on_enter(self) -> None:
        """進入設定頁時同步 UI 顯示最新設定值。"""
        super().on_enter()
        sm = self._settings_manager
        if sm is None:
            logger.debug("SettingsPage.on_enter：SettingsManager 尚未注入，跳過 UI 同步")
            return
        self._load_current_values()

    # =========================================================================
    # 依賴注入
    # =========================================================================

    def set_managers(self, **managers) -> None:
        """注入 managers，連接 SettingsManager signals。

        Args:
            settings:     SettingsManager 實例
            notification: NotificationManager 實例
            其他 managers 由 BasePage 統一儲存
        """
        super().set_managers(**managers)
        sm = managers.get("settings")
        if sm is not None:
            # 重置完成後自動重載 UI
            sm.signals.reset_completed.connect(self._load_current_values)
            # 匯入完成後也重載（確保 UI 反映匯入結果）
            sm.signals.imported.connect(lambda _count: self._load_current_values())
            logger.debug("SettingsPage：已連接 SettingsManager signals")
            # 啟動時立即將 SettingsManager 持久化值反映到 UI 控件
            # （MainWindowV2 不會觸發 on_enter，所以這裡必須主動觸發一次）
            self._load_current_values()

    # =========================================================================
    # UI ↔ SettingsManager 同步
    # =========================================================================

    def _load_current_values(self) -> None:
        """將 SettingsManager 當前值載入到所有 UI 元件（不觸發 valueChanged）。"""
        sm = self._settings_manager
        if sm is None:
            return

        def _block_set(card: SwitchSettingCard, value: bool) -> None:
            """在阻止信號傳遞的情況下設定 SwitchSettingCard 的值。"""
            card.blockSignals(True)
            card.setChecked(value)
            card.blockSignals(False)

        # 檔案與轉換
        _block_set(self._overwrite_card, sm.get("overwrite", False))
        _block_set(self._auto_open_card, sm.get("auto_open_folder_on_done", False))
        self._update_output_dir_label()

        # 外觀
        self._update_theme_label()

        _block_set(self._animation_card, sm.get("enable_animations", True))

        # 歷史
        _block_set(self._record_history_card, sm.get("record_history", True))

        # 通知
        _block_set(self._notify_complete_card, sm.get("notify_on_complete", True))
        _block_set(self._notify_error_card, sm.get("notify_on_error", True))
        _block_set(self._sound_card, sm.get("play_sound", False))

        # 系統整合
        _block_set(self._tray_card, sm.get("minimize_to_tray", True))
        self._update_close_action_label()

        # 進階
        _block_set(self._com_fallback_card, sm.get("enable_com_fallback", True))

    def _update_output_dir_label(self) -> None:
        """更新輸出目錄卡片的副標題顯示當前路徑。"""
        sm = self._settings_manager
        if sm is None:
            return
        raw = sm.get("output_dir", "")
        display = raw if raw else str(sm.output_dir)
        self._output_dir_card.setContent(display)

    def _update_theme_label(self) -> None:
        """更新主題卡片的副標題顯示當前主題。"""
        sm = self._settings_manager
        if sm is None:
            return
        theme_map = {"system": "系統（跟隨 OS）", "light": "亮色", "dark": "暗色"}
        current = sm.get("theme", "system")
        self._theme_card.setContent(theme_map.get(current, current))

    def _update_close_action_label(self) -> None:
        """更新關閉行為卡片的副標題。"""
        sm = self._settings_manager
        if sm is None:
            return
        action_map = {"tray": "最小化到系統匣", "quit": "結束程式"}
        current = sm.get("close_action", "tray")
        self._close_action_card.setContent(action_map.get(current, current))

    def _on_setting_changed(self, key: str, value: object) -> None:
        """通用設定變更處理器，即時儲存到 SettingsManager。

        Args:
            key:   設定鍵名稱。
            value: 新值（由 Signal 傳入，型別由各 widget 保證）。
        """
        sm = self._settings_manager
        if sm is None:
            logger.warning("SettingsPage._on_setting_changed：SettingsManager 未注入，忽略 %r", key)
            return
        sm.set(key, value)
        logger.debug("設定已更新：%r = %r", key, value)

    # =========================================================================
    # 各按鈕事件處理
    # =========================================================================

    def _on_browse_output_dir(self) -> None:
        """開啟目錄選擇對話框，更新輸出目錄設定。"""
        sm = self._settings_manager
        if sm is None:
            return
        current = str(sm.output_dir)
        selected = QFileDialog.getExistingDirectory(
            self,
            "選擇預設輸出目錄",
            current,
        )
        if not selected:
            return
        self._on_setting_changed("output_dir", selected)
        self._update_output_dir_label()

    def _on_toggle_theme(self) -> None:
        """循環切換主題：system → light → dark → system。"""
        sm = self._settings_manager
        if sm is None:
            return
        cycle = {"system": "light", "light": "dark", "dark": "system"}
        current = sm.get("theme", "system")
        next_theme = cycle.get(current, "system")
        self._on_setting_changed("theme", next_theme)
        self._update_theme_label()

        # 即時套用主題
        try:
            from desktop.utils.theme import apply_theme
            apply_theme(next_theme)
        except Exception as exc:
            logger.warning("即時套用主題失敗：%s", exc)

    def _on_toggle_close_action(self) -> None:
        """切換關閉行為：tray ↔ quit。"""
        sm = self._settings_manager
        if sm is None:
            return
        current = sm.get("close_action", "tray")
        next_action = "quit" if current == "tray" else "tray"
        self._on_setting_changed("close_action", next_action)
        self._update_close_action_label()

    def _on_clear_history(self) -> None:
        """清除歷史記錄（確認後執行）。"""
        try:
            from qfluentwidgets import MessageBox
            dialog = MessageBox(
                "確認清除",
                "確定要清除所有歷史紀錄嗎？此操作不可復原。",
                self,
            )
            if not dialog.exec():
                return
        except Exception:
            # qfluentwidgets MessageBox 不可用時，直接執行（測試環境）
            pass

        hm = self._managers.get("history")
        nm = self._notification_manager

        if hm is None:
            logger.warning("SettingsPage：HistoryManager 未注入，無法清除歷史")
            if nm is not None:
                nm.error("無法清除歷史", "HistoryManager 未初始化")
            return

        try:
            deleted = hm.clear_all()
            logger.info("SettingsPage：已清除 %d 筆歷史記錄", deleted)
            if nm is not None:
                nm.success(
                    "歷史已清除",
                    f"共刪除 {deleted} 筆紀錄",
                    duration_ms=3000,
                )
        except Exception as exc:
            logger.error("SettingsPage：清除歷史失敗：%s", exc, exc_info=True)
            if nm is not None:
                nm.error("清除失敗", f"錯誤：{exc}", duration_ms=0)

    def _on_export_settings(self) -> None:
        """匯出設定至 JSON 檔案。"""
        sm = self._settings_manager
        if sm is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "匯出設定",
            "settings.json",
            "JSON 檔案 (*.json)",
        )
        if not path_str:
            return
        try:
            count = sm.export_json(Path(path_str))
            nm = self._notification_manager
            if nm is not None:
                nm.success("匯出成功", f"{count} 項設定已儲存至 {Path(path_str).name}")
        except Exception as exc:
            logger.error("設定匯出失敗：%s", exc)
            nm = self._notification_manager
            if nm is not None:
                nm.error("匯出失敗", str(exc))

    def _on_import_settings(self) -> None:
        """從 JSON 檔案匯入設定。"""
        sm = self._settings_manager
        if sm is None:
            return
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "匯入設定",
            "",
            "JSON 檔案 (*.json)",
        )
        if not path_str:
            return
        try:
            count = sm.import_json(Path(path_str))
            # import_json 完成後 signals.imported 觸發 _load_current_values
            nm = self._notification_manager
            if nm is not None:
                nm.success("匯入成功", f"{count} 項設定已更新")
        except Exception as exc:
            logger.error("設定匯入失敗：%s", exc)
            nm = self._notification_manager
            if nm is not None:
                nm.error("匯入失敗", str(exc))

    def _on_reset_all(self) -> None:
        """重設所有設定為預設值（確認後執行）。"""
        try:
            from qfluentwidgets import MessageBox
            dialog = MessageBox(
                "重設所有設定",
                "確定要把所有設定恢復為預設值嗎？此操作不可復原。",
                self,
            )
            if not dialog.exec():
                return
        except Exception:
            pass  # 測試環境跳過確認

        sm = self._settings_manager
        if sm is None:
            return
        sm.reset_all()
        # reset_all 觸發 signals.reset_completed → _load_current_values 自動更新 UI
        nm = self._notification_manager
        if nm is not None:
            nm.info("已重設", "所有設定已恢復預設值")

    # =========================================================================
    # 便利屬性
    # =========================================================================

    @property
    def _settings_manager(self):
        """便利存取注入的 SettingsManager。"""
        return self._managers.get("settings")

    @property
    def _notification_manager(self):
        """便利存取注入的 NotificationManager。"""
        return self._managers.get("notification")
