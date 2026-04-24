"""批次頁（BatchPage）— 進階佇列管理。

定位：
    Home Page 是「快速轉換 1-5 個檔案」的視覺化卡片流。
    Batch Page 是「進階：一次丟 20-100 個檔案，分優先級、篩選、排序、暫停/續跑」
    的高密度表格介面。兩頁面共用同一 ConversionController（同一個 _jobs 字典）。

佈局：
    ┌──────────────────────────────────────────────────────────┐
    │ [➕ 加入檔案] [📁 加入資料夾] [清空]  [搜尋🔍] [篩選▼]  │  ← 工具列
    ├──────────────────────────────────────────────────────────┤
    │ ☑ 檔名      | 來源 | 目標 | 大小 | 優先 | 狀態  | 進度  │  ← 表頭
    │ ☑ report.pdf| PDF  | DOCX | 1.2M | 高   | 轉換  | 45%  │
    │ ☐ photo.jpg | JPG  | PDF  | 3.4M | 中   | 等待  | -    │
    ├──────────────────────────────────────────────────────────┤
    │ [▶ 開始全部] [⏸ 暫停] [❌ 取消選中]        已選 2/10   │  ← 底部列
    └──────────────────────────────────────────────────────────┘

Round 3 Agent D 職責：
    - 工具列：加入檔案、加入資料夾、清空、搜尋、狀態篩選
    - 表格：8 欄（勾選、檔名、來源、目標、大小、優先、狀態、進度）
    - 右鍵選單：重跑、優先級調整、複製路徑、移除
    - 底部列：開始全部、暫停、取消選中、計數標籤
    - 完整連接 ConversionController signals
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    TableWidget,
)

from desktop.interfaces import ConversionJob, JobStatus, PageID, SUPPORTED_INPUT_FORMATS
from desktop.pages.base_page import BasePage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 背景資料夾掃描 Worker（H-COMM-003：避免主執行緒 rglob 凍結 UI）
# ---------------------------------------------------------------------------

class _FolderScanWorkerSignals(QObject):
    """Worker 的跨執行緒 Signal 載體。

    QRunnable 本身不是 QObject，無法直接宣告 Signal，
    因此透過此輔助類別中繼傳遞信號。
    """

    progress = Signal(int)   # 已掃到的檔案數（每 100 個發射一次）
    finished = Signal(list)  # 最終 file list（List[Path]）
    error = Signal(str)      # 異常訊息


class _FolderScanWorker(QRunnable):
    """以背景執行緒遞迴掃描資料夾中的支援格式檔案。

    Args:
        root:          掃描根目錄路徑字串。
        glob_patterns: 要搜尋的 glob 模式 tuple，例如 ("*.pdf", "*.docx")。
    """

    def __init__(self, root: str, glob_patterns: tuple[str, ...]) -> None:
        super().__init__()
        self.signals = _FolderScanWorkerSignals()
        self._root = root
        self._glob_patterns = glob_patterns
        self._cancelled = False

    def cancel(self) -> None:
        """請求中止掃描（下一個檔案迭代時生效）。"""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        """掃描入口（由 QThreadPool 在工作執行緒呼叫）。"""
        try:
            files: list[Path] = []
            last_emit = 0
            root_path = Path(self._root)

            for pattern in self._glob_patterns:
                for filepath in root_path.rglob(pattern):
                    if self._cancelled:
                        self.signals.finished.emit([])
                        return
                    files.append(filepath)
                    if len(files) - last_emit >= 100:
                        self.signals.progress.emit(len(files))
                        last_emit = len(files)

            self.signals.finished.emit(files)
        except Exception as exc:
            self.signals.error.emit(str(exc))


# ---------------------------------------------------------------------------
# 欄位索引常數（避免魔術數字）
# ---------------------------------------------------------------------------
_COL_CHECK = 0
_COL_NAME = 1
_COL_SOURCE = 2
_COL_TARGET = 3
_COL_SIZE = 4
_COL_PRIORITY = 5
_COL_STATUS = 6
_COL_PROGRESS = 7
_COL_COUNT = 8

# ---------------------------------------------------------------------------
# 優先級定義
# ---------------------------------------------------------------------------
_PRIORITY_LABELS = ["低", "中", "高"]
_PRIORITY_DEFAULT_IDX = 1  # 中

# ---------------------------------------------------------------------------
# 狀態值（JobStatus.value）→ 表格顯示文字
# ---------------------------------------------------------------------------
_STATUS_DISPLAY: dict[str, str] = {
    "idle":       "等待",
    "pending":    "等待",
    "converting": "轉換中",
    "done":       "完成",
    "error":      "失敗",
}

# ---------------------------------------------------------------------------
# 支援的副檔名 glob 模式（供加入資料夾遞迴搜尋）
# ---------------------------------------------------------------------------
_SUPPORTED_GLOBS = tuple(
    f"*.{ext}" for ext in SUPPORTED_INPUT_FORMATS
)

# QFileDialog 檔案過濾字串
_FILE_FILTER = "支援的格式 (" + " ".join(
    f"*.{ext}" for ext in SUPPORTED_INPUT_FORMATS
) + ")"


# ---------------------------------------------------------------------------
# BatchPage
# ---------------------------------------------------------------------------

class BatchPage(BasePage):
    """進階批次佇列管理頁面。

    設計原則：
    - 使用 TableWidget 高密度展示大量任務（20-100 個檔案）
    - 與 Home Page 共用同一 ConversionController，_jobs 字典為單一真實來源
    - 狀態篩選與搜尋在本地 O(N) 執行，不需要額外後端查詢
    - job_id 透過 _job_rows dict 雙向對應 row index，移除列後自動重建
    """

    PAGE_ID = PageID.BATCH
    PAGE_TITLE = "批次"
    PAGE_ICON = FluentIcon.FOLDER

    # =========================================================================
    # UI 建立（_setup_ui）
    # =========================================================================

    def _setup_ui(self) -> None:
        """建立批次頁完整 UI：工具列 + 表格 + 底部列。"""
        # 狀態追蹤（在 signal 連接前初始化）
        self._notification_manager = None
        self._job_rows: dict[str, int] = {}  # job_id → table row index
        self._current_scan_worker: _FolderScanWorker | None = None  # 保留引用避免 GC

        self._build_toolbar()
        self._build_table()
        self._build_bottom_bar()
        self._connect_internal_signals()

    def _build_toolbar(self) -> None:
        """建立工具列（加入、資料夾、清空、搜尋、篩選）。"""
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        self.add_files_btn = PushButton(FluentIcon.ADD, "加入檔案")
        self.add_folder_btn = PushButton(FluentIcon.FOLDER_ADD, "加入資料夾")
        self.clear_btn = PushButton(FluentIcon.DELETE, "清空")

        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜尋檔名...")
        self.search_edit.setFixedWidth(220)

        self.status_filter = ComboBox()
        self.status_filter.addItems(["全部", "等待", "轉換中", "完成", "失敗"])
        self.status_filter.setFixedWidth(110)

        toolbar_layout.addWidget(self.add_files_btn)
        toolbar_layout.addWidget(self.add_folder_btn)
        toolbar_layout.addWidget(self.clear_btn)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.search_edit)
        toolbar_layout.addWidget(self.status_filter)

        self._content_layout.addLayout(toolbar_layout)

    def _build_table(self) -> None:
        """建立任務表格（8 欄）。"""
        self.table = TableWidget()
        self.table.setColumnCount(_COL_COUNT)
        self.table.setHorizontalHeaderLabels(
            ["", "檔名", "來源", "目標", "大小", "優先", "狀態", "進度"]
        )

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)

        # 固定寬度欄（checkbox、格式、大小、優先、狀態）
        self.table.setColumnWidth(_COL_CHECK, 32)
        self.table.setColumnWidth(_COL_SOURCE, 60)
        self.table.setColumnWidth(_COL_TARGET, 60)
        self.table.setColumnWidth(_COL_SIZE, 80)
        self.table.setColumnWidth(_COL_PRIORITY, 60)
        self.table.setColumnWidth(_COL_STATUS, 75)
        self.table.setColumnWidth(_COL_PROGRESS, 65)

        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(True)
        self.table.setBorderRadius(8)
        self.table.setBorderVisible(True)

        self._content_layout.addWidget(self.table, stretch=1)

    def _build_bottom_bar(self) -> None:
        """建立底部操作列（開始、暫停、取消選中、計數標籤）。"""
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        self.start_btn = PrimaryPushButton(FluentIcon.PLAY, "開始全部")
        self.pause_btn = PushButton(FluentIcon.PAUSE, "暫停")
        self.cancel_selected_btn = PushButton(FluentIcon.CANCEL, "取消選中")

        self.count_label = QLabel("已選 0/0")
        self.count_label.setStyleSheet("color: #888888; font-size: 13px;")

        bottom_layout.addWidget(self.start_btn)
        bottom_layout.addWidget(self.pause_btn)
        bottom_layout.addWidget(self.cancel_selected_btn)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.count_label)

        self._content_layout.addLayout(bottom_layout)

    def _connect_internal_signals(self) -> None:
        """連接頁面內部 UI 元件的 Signal（不依賴外部 controller）。"""
        self.add_files_btn.clicked.connect(self._on_add_files)
        self.add_folder_btn.clicked.connect(self._on_add_folder)
        self.clear_btn.clicked.connect(self._on_clear)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.status_filter.currentTextChanged.connect(self._apply_filter)
        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn.clicked.connect(self._on_pause)
        self.cancel_selected_btn.clicked.connect(self._on_cancel_selected)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.itemSelectionChanged.connect(self._update_count_label)

    # =========================================================================
    # 依賴注入（由 MainWindowV2 呼叫）
    # =========================================================================

    def set_controller(self, controller) -> None:
        """注入 ConversionController 並連接所有 signals。

        Args:
            controller: ConversionController 實例（含 .signals 屬性）。
        """
        self._controller = controller
        sigs = controller.signals
        sigs.job_added.connect(self._on_job_added)
        sigs.job_progress.connect(self._on_job_progress)
        sigs.job_status_changed.connect(self._on_job_status_changed)
        sigs.job_completed.connect(self._on_job_completed)
        sigs.job_failed.connect(self._on_job_failed)
        logger.debug("BatchPage: ConversionController signals 已連接")

    def set_managers(self, notification=None, **kwargs) -> None:
        """注入 manager 字典，提取 notification manager。

        Args:
            notification: NotificationManager 實例（可為 None）。
            **kwargs:     其餘 manager（history / settings / tray）。
        """
        self._notification_manager = notification
        self._managers = {"notification": notification, **kwargs}

    # =========================================================================
    # 生命週期鉤子
    # =========================================================================

    def on_enter(self) -> None:
        """進入批次頁時刷新計數標籤。"""
        super().on_enter()
        self._update_count_label()

    # =========================================================================
    # 工具列動作
    # =========================================================================

    def _on_add_files(self) -> None:
        """開啟檔案對話框，將選取的檔案加入佇列。"""
        if not self._controller:
            logger.warning("BatchPage._on_add_files: controller 尚未注入")
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇要轉換的檔案", "", _FILE_FILTER
        )
        if file_paths:
            self._controller.add_files([Path(p) for p in file_paths])

    def _on_add_folder(self) -> None:
        """開啟目錄對話框，在背景執行緒遞迴搜尋支援的格式並加入佇列。

        H-COMM-003 修復：改用 QRunnable + QThreadPool 背景掃描，
        避免大型資料夾（100K+ 檔案）的同步 rglob 凍結主執行緒 5-30 秒。
        """
        if not self._controller:
            logger.warning("BatchPage._on_add_folder: controller 尚未注入")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if not dir_path:
            return

        # 若有上一個尚未完成的掃描，先取消
        if self._current_scan_worker is not None:
            self._current_scan_worker.cancel()

        self._notify_info("正在掃描資料夾", "大型資料夾可能需要一些時間...")

        worker = _FolderScanWorker(dir_path, _SUPPORTED_GLOBS)
        worker.signals.finished.connect(self._on_folder_scan_finished)
        worker.signals.error.connect(self._on_folder_scan_error)

        # 保存引用以防 GC 在 Worker 完成前回收物件
        self._current_scan_worker = worker

        QThreadPool.globalInstance().start(worker)
        logger.debug("BatchPage._on_add_folder: 開始背景掃描 %s", dir_path)

    def _on_folder_scan_finished(self, files: list) -> None:
        """背景掃描完成後於主執行緒處理結果。

        Args:
            files: 掃描到的 Path 物件清單；若被取消則為空清單。
        """
        self._current_scan_worker = None

        if not files:
            self._notify_info("無支援格式", "在所選資料夾中找不到支援的檔案格式")
            return

        self._notify_info("掃描完成", f"找到 {len(files)} 個支援的檔案")

        if self._controller:
            self._controller.add_files(files)
        logger.debug("BatchPage._on_folder_scan_finished: 加入 %d 個檔案", len(files))

    def _on_folder_scan_error(self, error_msg: str) -> None:
        """背景掃描發生例外時回報錯誤。

        Args:
            error_msg: 例外訊息字串。
        """
        self._current_scan_worker = None
        logger.error("BatchPage._on_folder_scan_error: %s", error_msg)
        self._notify_info("掃描失敗", error_msg)

    def _on_clear(self) -> None:
        """移除所有任務（等待 + 完成 + 失敗，不移除進行中的）。"""
        if not self._controller:
            return

        # 取快照避免邊界效應（dict 在迭代中修改）
        job_ids = list(self._job_rows.keys())
        for job_id in job_ids:
            self._controller.remove_job(job_id)
            self._remove_row(job_id)

        self._update_count_label()

    # =========================================================================
    # 底部列動作
    # =========================================================================

    def _on_start(self) -> None:
        """開始佇列中所有 PENDING 狀態的任務。"""
        if self._controller:
            self._controller.start_all()

    def _on_pause(self) -> None:
        """取消所有進行中的任務（簡化實作：等同 cancel_all）。

        Note:
            未來可透過 JobManager 實作真正的暫停/續跑機制。
            目前 cancellation 即等同暫停（使用者需手動重新開始）。
        """
        if self._controller:
            self._controller.cancel_all()

    def _on_cancel_selected(self) -> None:
        """取消表格中所有被選中列的任務。"""
        if not self._controller:
            return

        selected_rows = sorted(
            {idx.row() for idx in self.table.selectedIndexes()},
            reverse=True,  # 從最大 row 開始，避免 row index 偏移
        )
        for row in selected_rows:
            job_id = self._job_id_at_row(row)
            if job_id:
                self._controller.cancel_job(job_id)

    # =========================================================================
    # 右鍵選單
    # =========================================================================

    def _on_context_menu(self, pos) -> None:
        """在滑鼠位置顯示右鍵選單。

        Args:
            pos: QPoint，相對於 table viewport 的座標。
        """
        row = self.table.indexAt(pos).row()
        if row < 0:
            return

        job_id = self._job_id_at_row(row)
        if not job_id:
            return

        menu = QMenu(self)

        rerun_action = menu.addAction("重跑")
        rerun_action.triggered.connect(lambda: self._rerun_job(job_id))

        menu.addSeparator()

        priority_up_action = menu.addAction("優先級提升")
        priority_up_action.triggered.connect(lambda: self._adjust_priority(job_id, delta=1))

        priority_down_action = menu.addAction("優先級降低")
        priority_down_action.triggered.connect(lambda: self._adjust_priority(job_id, delta=-1))

        menu.addSeparator()

        copy_action = menu.addAction("複製來源路徑")
        copy_action.triggered.connect(lambda: self._copy_source_path(job_id))

        remove_action = menu.addAction("移除")
        remove_action.triggered.connect(lambda: self._remove_job(job_id))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    # =========================================================================
    # ConversionController Signal 回調
    # =========================================================================

    def _on_job_added(self, job: ConversionJob) -> None:
        """新任務建立後，在表格末尾插入一列。

        Args:
            job: ConversionJob 實例（完整欄位）。
        """
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._job_rows[job.job_id] = row

        # 欄 0：勾選框（Qt 原生 checkable item）
        check_item = QTableWidgetItem()
        check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check_item.setCheckState(Qt.CheckState.Unchecked)
        self.table.setItem(row, _COL_CHECK, check_item)

        # 欄 1：檔名
        name_item = QTableWidgetItem(job.source_path.name)
        name_item.setToolTip(str(job.source_path))
        self.table.setItem(row, _COL_NAME, name_item)

        # 欄 2：來源格式
        self.table.setItem(row, _COL_SOURCE, QTableWidgetItem(job.source_format.upper()))

        # 欄 3：目標格式
        self.table.setItem(row, _COL_TARGET, QTableWidgetItem(job.target_format.upper()))

        # 欄 4：檔案大小
        size_text = self._format_file_size(job.source_path)
        self.table.setItem(row, _COL_SIZE, QTableWidgetItem(size_text))

        # 欄 5：優先級（預設為「中」）
        self.table.setItem(row, _COL_PRIORITY, QTableWidgetItem(_PRIORITY_LABELS[_PRIORITY_DEFAULT_IDX]))

        # 欄 6：狀態
        self.table.setItem(row, _COL_STATUS, QTableWidgetItem("等待"))

        # 欄 7：進度
        self.table.setItem(row, _COL_PROGRESS, QTableWidgetItem("-"))

        self._update_count_label()
        logger.debug("BatchPage._on_job_added: job=%s → row=%d", job.job_id, row)

    def _on_job_progress(self, job_id: str, progress: float) -> None:
        """更新指定任務的進度欄。

        M-COMM-004 修復：重用既有 QTableWidgetItem（setText），
        避免每次進度更新都建立新物件造成 GC 壓力。

        Args:
            job_id:   任務 ID。
            progress: 進度值 0.0–1.0。
        """
        row = self._job_rows.get(job_id)
        if row is None:
            return

        pct = int(progress * 100)
        self._set_cell_text(row, _COL_PROGRESS, f"{pct}%")

    def _on_job_status_changed(self, job_id: str, status_value: str) -> None:
        """更新指定任務的狀態欄顯示。

        job_status_changed 發出的是 JobStatus.value（字串），
        例如 "idle" / "pending" / "converting" / "done" / "error"。

        Args:
            job_id:       任務 ID。
            status_value: JobStatus.value 字串。
        """
        row = self._job_rows.get(job_id)
        if row is None:
            return

        display_text = _STATUS_DISPLAY.get(status_value, status_value)
        self._set_cell_text(row, _COL_STATUS, display_text)

    def _on_job_completed(self, job_id: str, output_path: object) -> None:
        """任務成功完成，更新狀態和進度至完成態。

        Args:
            job_id:      任務 ID。
            output_path: 輸出路徑（Path 物件）。
        """
        row = self._job_rows.get(job_id)
        if row is None:
            return

        self._set_cell_text(row, _COL_STATUS, "完成")
        self._set_cell_text(row, _COL_PROGRESS, "100%")
        logger.debug("BatchPage._on_job_completed: job=%s output=%s", job_id, output_path)

    def _on_job_failed(self, job_id: str, error_message: str) -> None:
        """任務失敗，更新狀態欄顯示錯誤。

        Args:
            job_id:        任務 ID。
            error_message: 錯誤描述字串。
        """
        row = self._job_rows.get(job_id)
        if row is None:
            return

        self._set_cell_text(row, _COL_STATUS, "失敗")
        status_item = self.table.item(row, _COL_STATUS)
        if status_item:
            status_item.setToolTip(error_message)
        logger.debug("BatchPage._on_job_failed: job=%s error=%s", job_id, error_message)

    # =========================================================================
    # 搜尋與篩選
    # =========================================================================

    def _apply_filter(self) -> None:
        """根據搜尋文字和狀態篩選器隱藏/顯示表格列。

        搜尋：不區分大小寫的檔名子字串比對。
        狀態：完全比對狀態欄顯示文字（「全部」顯示所有列）。
        """
        search_text = self.search_edit.text().strip().lower()
        filter_status = self.status_filter.currentText()

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, _COL_NAME)
            status_item = self.table.item(row, _COL_STATUS)

            if name_item is None or status_item is None:
                continue

            name_matches = (
                not search_text or search_text in name_item.text().lower()
            )
            status_matches = (
                filter_status == "全部" or filter_status == status_item.text()
            )

            self.table.setRowHidden(row, not (name_matches and status_matches))

    # =========================================================================
    # 右鍵選單動作實作
    # =========================================================================

    def _rerun_job(self, job_id: str) -> None:
        """重跑指定任務（簡化：重置狀態後排入佇列）。

        Note:
            ConversionController 目前不提供正式的 rerun API。
            簡化實作：先 remove，再重新以原始路徑 add_files。
            若 job 已不在 controller._jobs，直接通知使用者。
        """
        if not self._controller:
            return

        job = self._controller.get_job(job_id)
        if job is None:
            self._notify_info("無法重跑", f"任務 {job_id[:8]} 已不存在")
            return

        source_path = job.source_path
        self._controller.remove_job(job_id)
        self._remove_row(job_id)
        self._controller.add_files([source_path])
        logger.debug("BatchPage._rerun_job: job=%s 重新加入佇列 path=%s", job_id, source_path)

    def _adjust_priority(self, job_id: str, delta: int) -> None:
        """調整指定任務的優先級顯示（+1 提升 / -1 降低）。

        優先級僅影響表格顯示，未來可整合至 JobManager 排程。

        Args:
            job_id: 任務 ID。
            delta:  +1 提升、-1 降低（以 _PRIORITY_LABELS 索引計算）。
        """
        row = self._job_rows.get(job_id)
        if row is None:
            return

        priority_item = self.table.item(row, _COL_PRIORITY)
        if priority_item is None:
            return

        current_label = priority_item.text()
        if current_label not in _PRIORITY_LABELS:
            current_label = _PRIORITY_LABELS[_PRIORITY_DEFAULT_IDX]

        current_idx = _PRIORITY_LABELS.index(current_label)
        new_idx = max(0, min(len(_PRIORITY_LABELS) - 1, current_idx + delta))
        self._set_cell_text(row, _COL_PRIORITY, _PRIORITY_LABELS[new_idx])

    def _copy_source_path(self, job_id: str) -> None:
        """將來源路徑字串複製至系統剪貼簿。

        Args:
            job_id: 任務 ID。
        """
        if not self._controller:
            return

        job = self._controller.get_job(job_id)
        if job is None:
            return

        clipboard = QApplication.clipboard()
        clipboard.setText(str(job.source_path))
        self._notify_info("已複製", str(job.source_path))

    def _remove_job(self, job_id: str) -> None:
        """從 controller 移除任務，並同步刪除表格列。

        Args:
            job_id: 任務 ID。
        """
        if self._controller:
            self._controller.remove_job(job_id)
        self._remove_row(job_id)
        self._update_count_label()

    # =========================================================================
    # 表格輔助方法
    # =========================================================================

    def _set_cell_text(self, row: int, col: int, text: str) -> None:
        """更新表格 cell 文字，重用既有 QTableWidgetItem 以降低 GC 壓力。

        M-COMM-004 修復：若該 cell 已有 Item 則呼叫 setText()，
        否則建立新的 QTableWidgetItem 並寫入。

        Args:
            row:  表格列索引。
            col:  表格欄索引。
            text: 要顯示的文字。
        """
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self.table.setItem(row, col, item)
        else:
            item.setText(text)

    def _job_id_at_row(self, row: int) -> str | None:
        """根據 row index 反查 job_id。

        Args:
            row: 表格列索引。

        Returns:
            job_id 字串，或 None（若無對應任務）。
        """
        for job_id, r in self._job_rows.items():
            if r == row:
                return job_id
        return None

    def _remove_row(self, job_id: str) -> None:
        """從表格移除指定 job_id 對應的列，並重建 _job_rows 索引。

        因為 QTableWidget.removeRow() 會讓其後所有列的 index 減 1，
        需要對 _job_rows 中大於被移除 row 的所有值做修正。

        Args:
            job_id: 要移除的任務 ID。
        """
        row = self._job_rows.pop(job_id, None)
        if row is None:
            return

        self.table.removeRow(row)

        # 修正後續列的 row index
        self._job_rows = {
            jid: (r - 1 if r > row else r)
            for jid, r in self._job_rows.items()
        }

    def _update_count_label(self) -> None:
        """更新底部列的「已選 X/Y」計數標籤。"""
        total = self.table.rowCount()
        selected = len({idx.row() for idx in self.table.selectedIndexes()})
        self.count_label.setText(f"已選 {selected}/{total}")

    # =========================================================================
    # 格式化輔助
    # =========================================================================

    @staticmethod
    def _format_file_size(path: Path) -> str:
        """讀取檔案大小並格式化為人類可讀字串。

        Args:
            path: 檔案路徑。

        Returns:
            格式化字串，例如 "1.2 MB"；讀取失敗時回傳 "-"。
        """
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            return "-"

        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    # =========================================================================
    # 通知輔助
    # =========================================================================

    def _notify_info(self, title: str, content: str) -> None:
        """透過 NotificationManager 發送 INFO 通知（若可用）。

        Args:
            title:   通知標題。
            content: 通知內容。
        """
        if self._notification_manager is not None:
            try:
                self._notification_manager.info(title, content)
            except Exception as exc:
                logger.debug("BatchPage._notify_info: notification failed: %s", exc)
        else:
            logger.debug("BatchPage 通知 [%s]: %s", title, content)
