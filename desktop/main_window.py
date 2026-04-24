"""主視窗 — Single-Window Drop Zone 模式，Round 3 完整整合版本。

視窗佈局：
    ┌──────────────────────────────────────────────────────┐
    │  文件轉檔  [檔案(F)]  [設定(S)]                       │
    ├──────────────────────────────────────────────────────┤
    │                                                      │
    │        ┌──────────────────────────────────┐         │
    │        │    DropZone（大拖拉區）            │         │
    │        │    〔空狀態：置中顯示〕             │         │
    │        │    〔有檔時：縮小至 150px 高〕      │         │
    │        └──────────────────────────────────┘         │
    │                                                      │
    ├──────────────────────────────────────────────────────┤
    │  FormatSelector（批次格式）+ [全部轉換 F5]            │
    ├──────────────────────────────────────────────────────┤
    │  ┌──────── 檔案卡片佇列（QScrollArea） ──────────┐   │
    │  │ [FileCard] ...                               │   │
    │  └──────────────────────────────────────────────┘   │
    ├──────────────────────────────────────────────────────┤
    │  ProgressWidget（底部狀態列）                        │
    └──────────────────────────────────────────────────────┘

Signal/Slot 連接（完整清單）：
    DropZone.signals.files_dropped        → controller.add_files
    DropZone.signals.open_dialog_requested → self._on_open_dialog
    FormatSelector.signals.format_selected → self._on_batch_format
    start_button.clicked                  → controller.start_all
    ProgressWidget.signals.cancel_requested → self._on_cancel_all
    controller.signals.job_added          → self._on_job_added
    controller.signals.job_progress       → self._on_job_progress
    controller.signals.job_status_changed → self._on_job_status_changed
    controller.signals.job_completed      → self._on_job_completed
    controller.signals.job_failed         → self._on_job_failed
    controller.signals.all_completed      → self._on_all_completed
    FileCard.signals.target_format_changed → controller.set_target_format （每卡各連一次）
    FileCard.signals.remove_requested     → self._on_remove_job           （每卡各連一次）
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop.controllers.conversion_controller import ConversionController
from desktop.interfaces import ConversionJob, JobStatus
from desktop.widgets.drop_zone import DropZone
from desktop.widgets.file_card import FileCard
from desktop.widgets.format_selector import FormatSelector
from desktop.widgets.progress_widget import ProgressWidget
from desktop.widgets.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

# QFluentWidgets PushButton 降級為 QPushButton
try:
    from qfluentwidgets import PushButton  # type: ignore[import]
    _HAS_FLUENT = True
except ImportError:
    PushButton = QPushButton  # type: ignore[assignment,misc]
    _HAS_FLUENT = False


class MainWindow(QMainWindow):
    """主視窗 — 900×640px Single-Window Drop Zone 模式（Round 3 完整整合）。

    負責組裝所有 widgets，連接 ConversionController 的 Signal/Slot，
    管理 FileCard 生命週期，並同步底部 ProgressWidget 的全局進度。

    Attributes:
        WINDOW_WIDTH:  初始視窗寬度（像素）。
        WINDOW_HEIGHT: 初始視窗高度（像素）。
    """

    WINDOW_WIDTH: int = 900
    WINDOW_HEIGHT: int = 640

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文件轉檔")
        self.resize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.setMinimumSize(700, 500)
        self._set_window_icon()

        # 建立 Controller（所有 UI 事件的後端）
        self.controller = ConversionController(self)

        # 建立各 Widget
        self.drop_zone = DropZone()
        self.format_selector = FormatSelector()
        self.start_button = PushButton("全部轉換 (F5)")
        self.progress_widget = ProgressWidget()

        # 檔案卡片佇列容器（放在 QScrollArea 內）
        self._file_queue_container = QWidget()
        self._file_queue_layout = QVBoxLayout(self._file_queue_container)
        self._file_queue_layout.setContentsMargins(0, 0, 0, 0)
        self._file_queue_layout.setSpacing(8)
        self._file_queue_layout.addStretch()  # 讓卡片靠頂排列

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._file_queue_container)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 卡片註冊表：job_id → FileCard
        self._file_cards: dict[str, FileCard] = {}

        self._setup_layout()
        self._setup_menus()
        self._setup_shortcuts()
        self._connect_signals()
        self._update_empty_state()

        logger.debug("MainWindow 初始化完成")

    # ------------------------------------------------------------------
    # 視窗生命週期
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """視窗關閉時：取消所有進行中的轉換並等待 ThreadPool 清空。

        確保進行中的 QRunnable Worker 不持有已銷毀 Qt 物件的引用，
        避免關閉時出現 crash 或 access violation。

        Args:
            event: QCloseEvent，傳遞給 super() 以繼續正常關閉流程。
        """
        try:
            self.controller.cancel_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("closeEvent: cancel_all 失敗（忽略並繼續關閉）— %s", exc)
        pool = QThreadPool.globalInstance()
        pool.waitForDone(500)  # 最多等 500ms 讓 Worker 自行收尾
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI 組裝
    # ------------------------------------------------------------------

    def _setup_layout(self) -> None:
        """建立主視窗中央佈局（垂直堆疊）。"""
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # DropZone（空時佔較大空間，有檔時被限高）
        main_layout.addWidget(self.drop_zone, stretch=3)

        # 格式選擇 + 開始轉換按鈕（水平列）
        format_row = QHBoxLayout()
        format_row.setSpacing(8)
        format_row.addWidget(self.format_selector, stretch=1)
        format_row.addWidget(self.start_button)
        main_layout.addLayout(format_row)

        # 檔案卡片捲動區
        main_layout.addWidget(self._scroll, stretch=4)

        # ProgressWidget（底部狀態列）
        main_layout.addWidget(self.progress_widget)

        self.setCentralWidget(central)

    def _setup_menus(self) -> None:
        """建立選單列（檔案、設定）。"""
        menubar = self.menuBar()

        # 檔案選單
        file_menu = menubar.addMenu("檔案(&F)")

        open_action = QAction("開啟檔案(&O)...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_dialog)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction("結束(&Q)", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 設定選單
        settings_menu = menubar.addMenu("設定(&S)")

        pref_action = QAction("偏好設定(&P)...", self)
        pref_action.setShortcut("Ctrl+,")
        pref_action.triggered.connect(self._on_open_settings)
        settings_menu.addAction(pref_action)

    def _setup_shortcuts(self) -> None:
        """設定全域快捷鍵（F5 全部轉換）。"""
        start_shortcut = QShortcut(QKeySequence("F5"), self)
        start_shortcut.activated.connect(self.controller.start_all)

    def _set_window_icon(self) -> None:
        """設定視窗圖示（優先 .ico，其次 .svg）。"""
        resources_dir = Path(__file__).parent / "resources"
        ico_path = resources_dir / "app.ico"
        svg_path = resources_dir / "app_icon.svg"

        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))
            logger.debug("視窗圖示已從 .ico 載入：%s", ico_path)
        elif svg_path.exists():
            self.setWindowIcon(QIcon(str(svg_path)))
            logger.debug("視窗圖示已從 .svg 載入：%s", svg_path)
        else:
            logger.warning("找不到視窗圖示（app.ico / app_icon.svg）")

    # ------------------------------------------------------------------
    # Signal 連接
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """連接所有 Widget 與 Controller 的 Signal/Slot。"""
        # DropZone → Controller / 對話框
        self.drop_zone.signals.files_dropped.connect(self.controller.add_files)
        self.drop_zone.signals.open_dialog_requested.connect(self._on_open_dialog)

        # FormatSelector 批次格式套用
        self.format_selector.signals.format_selected.connect(self._on_batch_format)

        # 全部轉換按鈕
        self.start_button.clicked.connect(self.controller.start_all)

        # ProgressWidget 取消全部（cancel_requested 傳 job_id 字串；空字串代表取消全部）
        self.progress_widget.signals.cancel_requested.connect(self._on_cancel_all)

        # Controller → MainWindow
        self.controller.signals.job_added.connect(self._on_job_added)
        self.controller.signals.job_progress.connect(self._on_job_progress)
        self.controller.signals.job_status_changed.connect(self._on_job_status_changed)
        self.controller.signals.job_completed.connect(self._on_job_completed)
        self.controller.signals.job_failed.connect(self._on_job_failed)
        self.controller.signals.all_completed.connect(self._on_all_completed)

    # ------------------------------------------------------------------
    # Controller Signal 回調
    # ------------------------------------------------------------------

    def _on_job_added(self, job: ConversionJob) -> None:
        """新任務建立後：建立 FileCard 並加入佇列。

        Args:
            job: 由 ConversionController 建立的 ConversionJob 快照。
        """
        card = FileCard(job)
        card.signals.target_format_changed.connect(self.controller.set_target_format)
        card.signals.remove_requested.connect(self._on_remove_job)

        # 插入在 stretch 之前（保持卡片靠頂對齊）
        stretch_index = self._file_queue_layout.count() - 1
        self._file_queue_layout.insertWidget(stretch_index, card)

        self._file_cards[job.job_id] = card
        self._update_empty_state()
        self.progress_widget.set_total(len(self._file_cards))

        logger.debug("_on_job_added: job_id=%s，目前卡片數=%d", job.job_id, len(self._file_cards))

    def _on_job_progress(self, job_id: str, progress: float) -> None:
        """任務進度更新：轉發至對應 FileCard，刷新全局進度。

        Args:
            job_id:   任務 ID。
            progress: 0.0–1.0 進度值。
        """
        card = self._file_cards.get(job_id)
        if card is not None:
            card.update_progress(progress)
        self._refresh_global_progress()

    def _on_job_status_changed(self, job_id: str, status_value: str) -> None:
        """任務狀態轉換：轉發至對應 FileCard。

        Controller 發射的是 JobStatus.value（字串），需轉回枚舉。

        Args:
            job_id:       任務 ID。
            status_value: JobStatus 的 value 字串（如 "converting"）。
        """
        card = self._file_cards.get(job_id)
        if card is None:
            return
        try:
            status = JobStatus(status_value)
        except ValueError:
            logger.warning(
                "_on_job_status_changed: 無法識別狀態值 %r for job=%s",
                status_value, job_id,
            )
            return
        card.update_status(status)

    def _on_job_completed(self, job_id: str, output_path: object) -> None:
        """任務完成：轉發至對應 FileCard，刷新全局進度。

        Args:
            job_id:      任務 ID。
            output_path: 輸出檔案路徑（Path 或可轉換為 Path 的值）。
        """
        card = self._file_cards.get(job_id)
        if card is not None:
            resolved = Path(output_path) if not isinstance(output_path, Path) else output_path
            card.mark_done(resolved)
        self._refresh_global_progress()

    def _on_job_failed(self, job_id: str, error_message: str) -> None:
        """任務失敗：轉發至對應 FileCard，刷新全局進度。

        Args:
            job_id:        任務 ID。
            error_message: 人類可讀的錯誤描述。
        """
        card = self._file_cards.get(job_id)
        if card is not None:
            card.mark_error(error_message)
        self._refresh_global_progress()

    def _on_all_completed(self) -> None:
        """所有任務已完成（DONE 或 ERROR）：切換 ProgressWidget 為完成態。"""
        self.progress_widget.set_state("done")
        logger.info("_on_all_completed: 全部 %d 個任務已完成", len(self._file_cards))

    def _on_remove_job(self, job_id: str) -> None:
        """使用者要求移除任務：通知 Controller，從佇列移除 FileCard。

        Args:
            job_id: 要移除的任務 ID。
        """
        self.controller.remove_job(job_id)

        card = self._file_cards.pop(job_id, None)
        if card is not None:
            self._file_queue_layout.removeWidget(card)
            card.deleteLater()

        self._update_empty_state()
        self.progress_widget.set_total(len(self._file_cards))
        self._refresh_global_progress()
        logger.debug("_on_remove_job: job_id=%s 移除，剩餘卡片數=%d", job_id, len(self._file_cards))

    def _on_cancel_all(self, job_id: str) -> None:
        """ProgressWidget 的取消請求：若 job_id 為空則取消全部。

        Args:
            job_id: 目標任務 ID；空字串代表取消所有進行中任務。
        """
        if job_id:
            self.controller.cancel_job(job_id)
        else:
            self.controller.cancel_all()

    # ------------------------------------------------------------------
    # 使用者操作回調
    # ------------------------------------------------------------------

    def _on_open_dialog(self) -> None:
        """開啟 QFileDialog 讓使用者選擇檔案，並送入 Controller。"""
        filter_str = self.drop_zone.build_file_dialog_filter()
        files, _ = QFileDialog.getOpenFileNames(self, "選擇檔案", "", filter_str)
        if files:
            paths = [Path(f) for f in files]
            self.controller.add_files(paths)
            logger.debug("_on_open_dialog: 選擇了 %d 個檔案", len(paths))

    def _on_open_settings(self) -> None:
        """開啟設定對話框（Ctrl+,）並套用返回的設定。"""
        dlg = SettingsDialog(self)
        dlg.signals.settings_applied.connect(self._on_settings_applied)
        dlg.exec()

    def _on_settings_applied(self, settings: dict) -> None:
        """套用設定對話框回傳的設定值。

        若主題切回 "system"，重新安裝（或確認已安裝）系統主題監聽器，
        使系統亮/暗切換時 UI 能即時跟隨。

        Args:
            settings: 格式同 SettingsDialogSignals.settings_applied。
        """
        self.controller.update_settings(settings)

        theme_mode = settings.get("theme", "system")
        try:
            from desktop.utils.theme import apply_theme, install_system_theme_listener
            apply_theme(theme_mode)
            logger.debug("_on_settings_applied: 主題已套用 mode=%s", theme_mode)
            if theme_mode in ("system", "auto"):
                # install_system_theme_listener 是 idempotent：
                # 已有 daemon thread 存活時不會重複建立。
                install_system_theme_listener(
                    lambda _theme=None: apply_theme("system")
                )
                logger.debug("_on_settings_applied: 系統主題監聽器已確保安裝")
        except Exception as exc:
            logger.error("_on_settings_applied: 套用主題失敗 — %s", exc)

    def _on_batch_format(self, target_format: str) -> None:
        """FormatSelector 發出批次格式：更新所有 IDLE/PENDING 任務的目標格式。

        FileCard 沒有 set_target_format public 方法，
        直接呼叫 controller.set_target_format，controller 側更新 job.target_format。
        FileCard 的 ComboBox 是使用者端操作介面，批次套用後新格式會在下次卡片
        渲染時從 job snapshot 讀取（若使用者重開對話框）。

        Args:
            target_format: 目標格式字串（小寫無點，例如 "pdf"）。
        """
        for job_id in list(self._file_cards.keys()):
            job = self.controller.get_job(job_id)
            if job is not None and job.status in (JobStatus.IDLE, JobStatus.PENDING):
                self.controller.set_target_format(job_id, target_format)
        logger.debug("_on_batch_format: 批次套用格式 %s", target_format)

    # ------------------------------------------------------------------
    # 空狀態 + 全局進度
    # ------------------------------------------------------------------

    def _update_empty_state(self) -> None:
        """根據是否有任務卡片，調整 DropZone 高度。

        有任務時縮小 DropZone（150px），讓佇列區有更多空間；
        無任務時回復展開（無限制高度）。
        """
        has_files = bool(self._file_cards)
        if has_files:
            self.drop_zone.setMaximumHeight(150)
        else:
            self.drop_zone.setMaximumHeight(16777215)  # Qt QWIDGETSIZE_MAX

    def _refresh_global_progress(self) -> None:
        """刷新 ProgressWidget 的全局進度與狀態。

        計算：已完成任務數 + 正在進行中任務的平均進度。
        若無任務則隱藏 ProgressWidget。
        """
        total = len(self._file_cards)
        if total == 0:
            self.progress_widget.set_state("idle")
            return

        # 計算進行中任務的累計進度（取第一個 CONVERTING 任務作為 in_progress_progress）
        in_progress_progress = 0.0
        for job_id in self._file_cards:
            job = self.controller.get_job(job_id)
            if job is not None and job.status == JobStatus.CONVERTING:
                in_progress_progress = job.progress
                break

        completed = sum(
            1
            for job_id in self._file_cards
            if (job := self.controller.get_job(job_id)) is not None
            and job.status in (JobStatus.DONE, JobStatus.ERROR)
        )

        # 有任何任務在執行中或等待中，切換為 running 態
        has_active = any(
            (job := self.controller.get_job(jid)) is not None
            and job.status in (JobStatus.PENDING, JobStatus.CONVERTING)
            for jid in self._file_cards
        )
        if has_active:
            self.progress_widget.set_state("running")

        self.progress_widget.set_total(total)
        self.progress_widget.update(completed, in_progress_progress)
