"""首頁（HomePage）— 快速單次轉換主頁。

佈局（上到下）：
    1. QuickStatsBar  — 頂部統計條（今日 / 進行中 / 已完成）
    2. DropZone       — 拖拉區（有檔時縮為 80px compact 模式）
    3. FormatSelector + 全部轉換按鈕（水平列）
    4. FileCard 佇列（QScrollArea，動態增刪）
    5. ProgressWidget — 底部全局進度條

Signal 連接：
    - DropZone → ConversionController.add_files
    - FormatSelector → 批次套用格式
    - PrimaryPushButton / F5 → ConversionController.start_all
    - ConversionController signals → FileCard 更新 / StatsBar 刷新

依賴注入（由 MainWindowV2 呼叫）：
    set_controller(controller)                         — ConversionController
    set_managers(history, settings, notification, ...) — Manager 注入
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import FluentIcon, PrimaryPushButton
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import QPushButton as PrimaryPushButton  # type: ignore[assignment]
    FluentIcon = None  # type: ignore[assignment]
    _HAS_FLUENT = False

from desktop.interfaces import ConversionJob, JobStatus, PageID
from desktop.pages.base_page import BasePage
from desktop.pages.components.stats_bar import StatsBar
from desktop.widgets.drop_zone import DropZone
from desktop.widgets.file_card import FileCard
from desktop.widgets.format_selector import FormatSelector
from desktop.widgets.progress_widget import ProgressWidget

logger = logging.getLogger(__name__)

# Drop Zone 高度常數
_DROP_ZONE_COMPACT_HEIGHT = 80   # 有檔案時的收合高度（px）
_DROP_ZONE_MAX_HEIGHT = 16777215 # Qt QWIDGETSIZE_MAX — 無上限（空狀態展開）


class HomePage(BasePage):
    """快速轉換主頁。

    Attributes:
        PAGE_ID:    PageID.HOME
        PAGE_TITLE: "首頁"
        PAGE_ICON:  FluentIcon.HOME
    """

    PAGE_ID = PageID.HOME
    PAGE_TITLE = "首頁"
    PAGE_ICON = FluentIcon.HOME if _HAS_FLUENT else None

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建立首頁完整 UI（由 BasePage.__init__ 自動呼叫）。"""
        # 內部狀態
        self._file_cards: dict[str, FileCard] = {}
        self._notification_manager = None
        self._history_manager = None

        # 1. 頂部統計條（固定 48px）
        self.stats_bar = StatsBar()
        self._content_layout.addWidget(self.stats_bar)

        # 2. DropZone（空時彈性展開，有檔時收合）
        self.drop_zone = DropZone()
        self._content_layout.addWidget(self.drop_zone, stretch=3)

        # 3. 格式選擇列 + 全部轉換按鈕
        self._content_layout.addLayout(self._build_format_row())

        # 4. FileCard 佇列（QScrollArea）
        self._content_layout.addWidget(self._build_queue_scroll(), stretch=5)

        # 5. 底部全局進度條（初始隱藏）
        self.progress_widget = ProgressWidget()
        self._content_layout.addWidget(self.progress_widget)

        # 初始化空狀態
        self._update_empty_state()

    def _build_format_row(self) -> QHBoxLayout:
        """建立格式選擇列：[FormatSelector] [全部轉換 (F5)]。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.format_selector = FormatSelector()
        row.addWidget(self.format_selector, stretch=1)

        if _HAS_FLUENT:
            self.start_button = PrimaryPushButton("全部轉換 (F5)")
        else:
            self.start_button = PrimaryPushButton("全部轉換 (F5)")
        row.addWidget(self.start_button)

        return row

    def _build_queue_scroll(self) -> QScrollArea:
        """建立 FileCard 佇列捲動區域。"""
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(8)
        self.queue_layout.addStretch()  # 卡片從頂部向下堆疊

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.queue_container)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        return self.scroll

    # ------------------------------------------------------------------
    # 依賴注入
    # ------------------------------------------------------------------

    def set_controller(self, controller) -> None:
        """注入 ConversionController 並連接所有 signals。

        Args:
            controller: ConversionController 實例。
        """
        super().set_controller(controller)
        self._connect_controller_signals()

    def set_managers(self, **managers) -> None:
        """注入 manager dict，按需取用。

        Keyword Args:
            history:      HistoryManager 實例（可選）
            settings:     SettingsManager 實例（可選）
            notification: NotificationManager 實例（可選）
            tray:         TrayManager 實例（可選）
        """
        super().set_managers(**managers)
        self._history_manager = managers.get("history")
        self._notification_manager = managers.get("notification")

        # 啟動時立即從 DB 載入今日統計（MainWindowV2 不會觸發 on_enter）
        self._refresh_stats()

    # ------------------------------------------------------------------
    # Signal 連接
    # ------------------------------------------------------------------

    def _connect_controller_signals(self) -> None:
        """連接 DropZone / FormatSelector / ProgressWidget 與 Controller signals。"""
        if self._controller is None:
            logger.warning("HomePage._connect_controller_signals: controller 尚未注入")
            return

        # DropZone → Controller
        self.drop_zone.signals.files_dropped.connect(self._controller.add_files)
        self.drop_zone.signals.open_dialog_requested.connect(self._on_open_dialog)

        # FormatSelector → 批次套用
        self.format_selector.signals.format_selected.connect(self._on_batch_format)

        # 全部轉換按鈕
        self.start_button.clicked.connect(self._on_start)

        # ProgressWidget 取消按鈕
        self.progress_widget.signals.cancel_requested.connect(
            lambda _job_id: self._controller.cancel_all()
        )

        # 查看歷史按鈕（若 MainWindowV2 提供導航 signal 則在外部連接）
        # 此處僅 log，由上層視窗負責實際跳轉
        self.stats_bar.history_button.clicked.connect(
            lambda: logger.debug("HomePage: 使用者點擊「查看歷史」")
        )

        # Controller signals → UI 更新
        sigs = self._controller.signals
        sigs.job_added.connect(self._on_job_added)
        sigs.job_progress.connect(self._on_job_progress)
        sigs.job_status_changed.connect(self._on_job_status_changed)
        sigs.job_completed.connect(self._on_job_completed)
        sigs.job_failed.connect(self._on_job_failed)
        sigs.all_completed.connect(self._on_all_completed)

    # ------------------------------------------------------------------
    # 生命週期
    # ------------------------------------------------------------------

    def on_enter(self) -> None:
        """進入首頁時刷新統計數字。"""
        super().on_enter()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # UI 操作 slots
    # ------------------------------------------------------------------

    def _on_open_dialog(self) -> None:
        """DropZone 請求開啟檔案對話框。"""
        filter_str = self.drop_zone.build_file_dialog_filter()
        files, _ = QFileDialog.getOpenFileNames(self, "選擇檔案", "", filter_str)
        if files and self._controller is not None:
            self._controller.add_files([Path(f) for f in files])

    def _on_batch_format(self, target_format: str) -> None:
        """FormatSelector 觸發批次格式套用：更新全部已載入 FileCard。"""
        if self._controller is None:
            return
        for job_id in list(self._file_cards.keys()):
            try:
                self._controller.set_target_format(job_id, target_format)
            except Exception:
                logger.debug(
                    "HomePage._on_batch_format: job_id=%s set_target_format 呼叫失敗",
                    job_id,
                )

    def _on_start(self) -> None:
        """全部轉換按鈕點擊：啟動 Controller 並更新 ProgressWidget。"""
        if self._controller is None:
            return
        count = len(self._file_cards)
        if count == 0:
            logger.debug("HomePage._on_start: 佇列為空，跳過")
            return

        self._controller.start_all()
        self.progress_widget.set_total(count)
        self.progress_widget.set_state("running")

        if self._notification_manager is not None:
            try:
                self._notification_manager.info(
                    "開始轉換", f"共 {count} 個檔案"
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Controller signal handlers
    # ------------------------------------------------------------------

    def _on_job_added(self, job: ConversionJob) -> None:
        """新任務加入：建立 FileCard 並插入佇列。"""
        card = FileCard(job)
        card.signals.target_format_changed.connect(
            self._on_card_format_changed
        )
        card.signals.remove_requested.connect(self._on_remove_job)

        # 插入到 stretch 前（stretch 永遠在最後）
        insert_pos = max(0, self.queue_layout.count() - 1)
        self.queue_layout.insertWidget(insert_pos, card)
        self._file_cards[job.job_id] = card

        self._update_empty_state()
        self.progress_widget.set_total(len(self._file_cards))
        self._refresh_stats()
        logger.debug(
            "HomePage._on_job_added: job_id=%s 加入佇列，共 %d 個",
            job.job_id, len(self._file_cards),
        )

    def _on_card_format_changed(self, job_id: str, target_format: str) -> None:
        """FileCard 單獨切換格式時，同步到 Controller。"""
        if self._controller is None:
            return
        try:
            self._controller.set_target_format(job_id, target_format)
        except Exception:
            logger.debug(
                "HomePage._on_card_format_changed: job_id=%s 更新格式失敗", job_id
            )

    def _on_job_progress(self, job_id: str, progress: float) -> None:
        """更新對應 FileCard 的進度條。"""
        card = self._file_cards.get(job_id)
        if card is not None:
            card.update_progress(progress)
        self._refresh_stats()

    def _on_job_status_changed(self, job_id: str, status_value: str) -> None:
        """更新對應 FileCard 的狀態標籤。"""
        card = self._file_cards.get(job_id)
        if card is not None:
            try:
                status = JobStatus(status_value)
                card.update_status(status)
            except ValueError:
                logger.debug(
                    "HomePage._on_job_status_changed: 未知 status_value=%s", status_value
                )
        self._refresh_stats()

    def _on_job_completed(self, job_id: str, output_path) -> None:
        """任務成功完成：更新卡片、寫入歷史、發送通知。"""
        card = self._file_cards.get(job_id)
        output = Path(output_path) if not isinstance(output_path, Path) else output_path

        if card is not None:
            card.mark_done(output)

        self._record_history_completion(job_id, output)

        if self._notification_manager is not None:
            try:
                self._notification_manager.success(
                    "轉換完成", output.name, duration_ms=3000
                )
            except Exception:
                pass

        self._refresh_stats()
        logger.info("HomePage._on_job_completed: job_id=%s → %s", job_id, output)

    def _on_job_failed(self, job_id: str, error_message: str) -> None:
        """任務失敗：更新卡片、寫入歷史、發送錯誤通知。"""
        card = self._file_cards.get(job_id)
        if card is not None:
            card.mark_error(error_message)

        self._record_history_failure(job_id, error_message)

        if self._notification_manager is not None:
            try:
                self._notification_manager.error(
                    "轉換失敗", f"錯誤：{error_message[:80]}", duration_ms=0
                )
            except Exception:
                pass

        self._refresh_stats()
        logger.error("HomePage._on_job_failed: job_id=%s — %s", job_id, error_message)

    def _on_all_completed(self) -> None:
        """所有任務完成：切換 ProgressWidget 為 done 狀態。"""
        self.progress_widget.set_state("done")
        self._refresh_stats()
        logger.info("HomePage._on_all_completed: 全部任務結束")

    def _on_remove_job(self, job_id: str) -> None:
        """使用者移除 FileCard：通知 Controller 並清除 UI。"""
        if self._controller is not None:
            try:
                self._controller.remove_job(job_id)
            except Exception:
                logger.debug(
                    "HomePage._on_remove_job: controller.remove_job(%s) 失敗", job_id
                )

        card = self._file_cards.pop(job_id, None)
        if card is not None:
            self.queue_layout.removeWidget(card)
            card.deleteLater()

        self._update_empty_state()
        self.progress_widget.set_total(len(self._file_cards))
        self._refresh_stats()
        logger.debug("HomePage._on_remove_job: job_id=%s 已移除", job_id)

    # ------------------------------------------------------------------
    # 歷史管理（寬容呼叫，B agent 並行實作）
    # ------------------------------------------------------------------

    def _record_history_completion(self, job_id: str, output_path: Path) -> None:
        """寫入成功歷史記錄（HistoryManager 可能尚未實作，寬容呼叫）。"""
        if self._history_manager is None:
            return
        try:
            job = self._get_job_from_controller(job_id)
            if job is not None:
                self._history_manager.record_completion(job, output_path)
        except Exception as exc:
            logger.debug(
                "HomePage._record_history_completion: job_id=%s — %s", job_id, exc
            )

    def _record_history_failure(self, job_id: str, error_message: str) -> None:
        """寫入失敗歷史記錄（HistoryManager 可能尚未實作，寬容呼叫）。"""
        if self._history_manager is None:
            return
        try:
            job = self._get_job_from_controller(job_id)
            if job is not None:
                self._history_manager.record_failure(job, error_message)
        except Exception as exc:
            logger.debug(
                "HomePage._record_history_failure: job_id=%s — %s", job_id, exc
            )

    def _get_job_from_controller(self, job_id: str) -> ConversionJob | None:
        """從 Controller 內部取得 ConversionJob 快照（防禦性存取）。"""
        if self._controller is None:
            return None
        try:
            jobs = getattr(self._controller, "_jobs", {})
            return jobs.get(job_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # UI 狀態更新
    # ------------------------------------------------------------------

    def _update_empty_state(self) -> None:
        """根據佇列是否有卡片，切換 DropZone compact / 展開模式。"""
        has_files = bool(self._file_cards)
        if has_files:
            self.drop_zone.setMaximumHeight(_DROP_ZONE_COMPACT_HEIGHT)
            self.drop_zone.setMinimumHeight(_DROP_ZONE_COMPACT_HEIGHT)
        else:
            self.drop_zone.setMinimumHeight(200)
            self.drop_zone.setMaximumHeight(_DROP_ZONE_MAX_HEIGHT)

    def _refresh_stats(self) -> None:
        """重算並更新頂部 StatsBar 三欄數字。

        今日   = 本地今日 00:00 至今 DB 中所有歷史紀錄筆數（跨 session 持久）
        進行中 = 當前 session CONVERTING 狀態的任務數
        已完成 = 本地今日 00:00 至今 DB 中 status="done" 的紀錄數（跨 session 持久）

        進行中只能從當前 session 算 — DB 紀錄都是終態（done/error/cancelled），
        重啟應用後本來就不會有殘留的進行中任務。
        """
        # 進行中：當前 session 計數
        in_progress = 0
        if self._controller is not None:
            jobs_dict = getattr(self._controller, "_jobs", {})
            for job_id in self._file_cards:
                job = jobs_dict.get(job_id)
                if job is not None and job.status == JobStatus.CONVERTING:
                    in_progress += 1

        # 今日 / 已完成：從 DB 讀，跨 session 持久
        today_count = 0
        completed_count = 0
        if self._history_manager is not None:
            try:
                today_start = self._today_start_utc_iso()
                today_count = self._history_manager.count(date_from=today_start)
                completed_count = self._history_manager.count(
                    status="done", date_from=today_start
                )
            except Exception as exc:
                logger.debug("_refresh_stats: HistoryManager 查詢失敗 — %s", exc)

        self.stats_bar.update_counts(today_count, in_progress, completed_count)

    @staticmethod
    def _today_start_utc_iso() -> str:
        """回傳本地今日 00:00 對應的 UTC ISO-8601 字串。

        DB 中 created_at 以 UTC ISO-8601 儲存，需把使用者感受的「本地今日」
        轉成相同基準才能正確比對。
        """
        from datetime import datetime, timezone
        local_now = datetime.now().astimezone()
        local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_today_start.astimezone(timezone.utc).isoformat()
