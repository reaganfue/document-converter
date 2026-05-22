"""歷史記錄頁（HistoryPage）— 查看 / 篩選 / 刪除 / 匯出轉換歷史。

佈局：
    ┌────────────────────────────────────────────────────┐
    │ Filter bar: [搜尋] [日期▼] [格式▼] [狀態▼] [匯出] │
    ├────────────────────────────────────────────────────┤
    │ TableWidget（7 欄）         │ 詳情面板（可收合）   │
    │ 時間/檔名/格式/大小/狀態/耗時/動作               │
    ├────────────────────────────────────────────────────┤
    │ [清除歷史] 共 N 筆   ← 1/10 →                     │
    └────────────────────────────────────────────────────┘

依賴（注入）：
    - HistoryManager（透過 set_managers(history=...) 注入）
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QItemSelectionModel, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    TableWidget,
)

from desktop.interfaces import HistoryRecord, PageID
from desktop.pages.base_page import BasePage
from desktop.utils.theme import get_palette

try:
    from qfluentwidgets import PrimaryPushButton  # type: ignore[import]
except ImportError:
    from PySide6.QtWidgets import QPushButton as PrimaryPushButton  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PAGE_SIZE = 50

# 狀態顯示映射
_STATUS_DISPLAY = {
    "done":      ("成功", "#2ecc71"),
    "error":     ("失敗", "#e74c3c"),
    "cancelled": ("取消", "#95a5a6"),
    "pending":   ("處理中", "#3498db"),
}

# 格式篩選選項
_FORMAT_OPTIONS = [
    ("全部", None),
    ("PDF", "pdf"),
    ("DOCX", "docx"),
    ("PPTX", "pptx"),
    ("HTML", "html"),
    ("MD", "md"),
    ("TXT", "txt"),
    ("PNG", "png"),
]

# 狀態篩選選項
_STATUS_OPTIONS = [
    ("全部", None),
    ("成功", "done"),
    ("失敗", "error"),
    ("取消", "cancelled"),
]

# 日期篩選選項（label, days_back）
_DATE_OPTIONS = [
    ("全部", None),
    ("今天", 0),
    ("昨天", 1),
    ("本週", 7),
    ("本月", 30),
]


def _format_time(iso_str: Optional[str]) -> str:
    """將 ISO-8601 UTC 字串轉為人類可讀的相對時間。"""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        delta = now - dt
        days = delta.days
        if days == 0:
            return dt.strftime("今天 %H:%M")
        if days == 1:
            return dt.strftime("昨天 %H:%M")
        if days < 7:
            return dt.strftime("%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso_str[:16] if len(iso_str) >= 16 else iso_str


def _format_size(size_bytes: int) -> str:
    """將位元組轉為人類可讀大小字串。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    return f"{size_bytes / 1024 ** 3:.1f} GB"


def _format_duration(duration_ms: Optional[int]) -> str:
    """將毫秒轉為人類可讀耗時字串。"""
    if duration_ms is None or duration_ms <= 0:
        return "-"
    if duration_ms < 1000:
        return f"{duration_ms} ms"
    secs = duration_ms / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    mins = secs / 60
    return f"{mins:.1f}m"


def _open_path(path_str: Optional[str]) -> None:
    """用系統預設程式開啟指定路徑。"""
    if not path_str:
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(path_str)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", path_str])
        else:
            subprocess.Popen(["xdg-open", path_str])
    except OSError as exc:
        logger.warning("無法開啟路徑 %s：%s", path_str, exc)


def _open_folder(path_str: Optional[str]) -> None:
    """在檔案總管中顯示指定路徑所在資料夾。"""
    if not path_str:
        return
    folder = str(Path(path_str).parent) if Path(path_str).is_file() else path_str
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", path_str])
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", "-R", path_str])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError as exc:
        logger.warning("無法開啟資料夾 %s：%s", path_str, exc)


class _DetailPanel(QWidget):
    """詳情面板 — 顯示選中記錄的完整資訊與操作按鈕。"""

    # 觸發「一鍵再轉」:payload 為 (source_path_str, target_format)
    reconvert_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self._record: Optional[HistoryRecord] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._title_label = BodyLabel("選中記錄")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        # 來源路徑
        layout.addWidget(QLabel("來源路徑："))
        self._source_label = QLabel()
        self._source_label.setWordWrap(True)
        self._source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._source_label)

        # 輸出路徑
        layout.addWidget(QLabel("輸出路徑："))
        self._output_label = QLabel()
        self._output_label.setWordWrap(True)
        self._output_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._output_label)

        # 錯誤訊息（失敗時顯示）
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setObjectName("HistoryErrorLabel")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        layout.addSpacing(8)

        # 操作按鈕 — 一鍵再轉放在最上,鼓勵 reuse
        self._btn_reconvert = PrimaryPushButton("再次轉換")
        self._btn_open_output = PushButton("開啟結果")
        self._btn_open_source = PushButton("開啟來源")
        self._btn_open_folder = PushButton("開啟資料夾")
        layout.addWidget(self._btn_reconvert)
        layout.addWidget(self._btn_open_output)
        layout.addWidget(self._btn_open_source)
        layout.addWidget(self._btn_open_folder)

        layout.addStretch()

        # 連接按鈕
        self._btn_reconvert.clicked.connect(self._on_reconvert)
        self._btn_open_output.clicked.connect(self._on_open_output)
        self._btn_open_source.clicked.connect(self._on_open_source)
        self._btn_open_folder.clicked.connect(self._on_open_folder)

    def set_record(self, record: Optional[HistoryRecord]) -> None:
        """更新詳情面板顯示的記錄。"""
        self._record = record
        if record is None:
            self._title_label.setText("未選中記錄")
            self._source_label.setText("")
            self._output_label.setText("")
            self._error_label.hide()
            return

        src_name = Path(record.source_path).name if record.source_path else "-"
        self._title_label.setText(src_name)
        self._source_label.setText(record.source_path or "-")
        self._output_label.setText(record.output_path or "-")

        if record.error_message:
            palette = get_palette()
            self._error_label.setStyleSheet(f"color: {palette['state_danger']};")
            self._error_label.setText(f"錯誤：{record.error_message}")
            self._error_label.show()
        else:
            self._error_label.hide()

        self._btn_open_output.setEnabled(bool(record.output_path))

        # 再次轉換只在來源檔案仍存在時可用
        src_exists = bool(record.source_path) and Path(record.source_path).exists()
        self._btn_reconvert.setEnabled(src_exists)
        if not src_exists:
            self._btn_reconvert.setToolTip("來源檔案已不存在")
        else:
            self._btn_reconvert.setToolTip(
                f"重新將此檔案轉為 {record.target_format.upper()}"
            )

    def _on_reconvert(self) -> None:
        """觸發再次轉換 — 發射 signal,由 HistoryPage 處理。"""
        if self._record and self._record.source_path:
            self.reconvert_requested.emit(
                self._record.source_path,
                self._record.target_format,
            )

    def _on_open_output(self) -> None:
        if self._record:
            _open_path(self._record.output_path)

    def _on_open_source(self) -> None:
        if self._record:
            _open_path(self._record.source_path)

    def _on_open_folder(self) -> None:
        if self._record:
            path = self._record.output_path or self._record.source_path
            _open_folder(path)


class _EmptyStateWidget(QWidget):
    """空狀態提示 widget — 無記錄時顯示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        icon_label = QLabel("📋")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_label)

        text_label = BodyLabel("尚無歷史記錄")
        text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(text_label)

        self.goto_home_btn = PrimaryPushButton("前往首頁開始轉換")
        self.goto_home_btn.setFixedWidth(200)
        layout.addWidget(self.goto_home_btn, alignment=Qt.AlignCenter)


class HistoryPage(BasePage):
    """歷史記錄頁。

    顯示轉換歷史，支援篩選、分頁、批量刪除、匯出 CSV。
    由 HistoryManager 提供資料，透過 set_managers(history=...) 注入。
    """

    PAGE_ID = PageID.HISTORY
    PAGE_TITLE = "歷史"
    PAGE_ICON = FluentIcon.HISTORY

    def _setup_ui(self) -> None:
        """建立歷史頁完整 UI。"""
        self._current_page = 0
        self._total_count = 0
        self._current_filters: dict = {}
        self._records: list[HistoryRecord] = []

        # ---- 篩選工具列 ----
        self._build_filter_bar()

        # ---- 主內容區（TableWidget + 詳情面板）----
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 堆疊 widget：有資料 / 空狀態
        self._stack = QStackedWidget()

        # 表格
        self._table = TableWidget()
        self._build_table()
        self._stack.addWidget(self._table)          # index 0

        # 空狀態
        self._empty_widget = _EmptyStateWidget()
        self._empty_widget.goto_home_btn.clicked.connect(self._on_goto_home)
        self._stack.addWidget(self._empty_widget)   # index 1

        self._splitter.addWidget(self._stack)

        # 詳情面板
        self._detail_panel = _DetailPanel()
        self._detail_panel.reconvert_requested.connect(self._on_reconvert)
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 1)

        self._content_layout.addWidget(self._splitter)

        # ---- 底部操作列 ----
        self._build_footer_bar()

    def _build_filter_bar(self) -> None:
        """建立頂部篩選工具列。"""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 搜尋框
        self._search_edit = SearchLineEdit()
        self._search_edit.setPlaceholderText("搜尋檔名或路徑...")
        self._search_edit.setFixedWidth(220)
        self._search_edit.searchSignal.connect(self._on_filter_changed)
        self._search_edit.clearSignal.connect(self._on_filter_changed)
        layout.addWidget(self._search_edit)

        # 日期篩選
        self._date_combo = ComboBox()
        for label, _ in _DATE_OPTIONS:
            self._date_combo.addItem(label)
        self._date_combo.setFixedWidth(100)
        self._date_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._date_combo)

        # 格式篩選
        self._format_combo = ComboBox()
        for label, _ in _FORMAT_OPTIONS:
            self._format_combo.addItem(label)
        self._format_combo.setFixedWidth(90)
        self._format_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._format_combo)

        # 狀態篩選
        self._status_combo = ComboBox()
        for label, _ in _STATUS_OPTIONS:
            self._status_combo.addItem(label)
        self._status_combo.setFixedWidth(90)
        self._status_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self._status_combo)

        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # 匯出 CSV
        self._export_btn = PushButton("匯出 CSV")
        self._export_btn.setIcon(FluentIcon.IMAGE_EXPORT)
        self._export_btn.clicked.connect(self._on_export_csv)
        layout.addWidget(self._export_btn)

        self._content_layout.addWidget(bar)

    def _build_table(self) -> None:
        """建立歷史記錄表格。"""
        headers = ["時間", "來源檔名", "格式轉換", "大小", "狀態", "耗時", "動作"]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(0)

        # 設定列寬
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setSectionResizeMode(6, QHeaderView.Fixed)

        self._table.setColumnWidth(0, 140)
        self._table.setColumnWidth(2, 120)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 60)
        self._table.setColumnWidth(5, 60)
        self._table.setColumnWidth(6, 70)

        # 行為設定
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().hide()
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)

        # 信號連接
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

    def _build_footer_bar(self) -> None:
        """建立底部操作列（清除歷史 + 統計 + 分頁）。"""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 清除歷史按鈕
        self._clear_btn = PushButton("清除歷史")
        self._clear_btn.setIcon(FluentIcon.DELETE)
        self._clear_btn.clicked.connect(self._on_clear_all)
        layout.addWidget(self._clear_btn)

        # 統計標籤
        self._count_label = BodyLabel("共 0 筆記錄")
        layout.addWidget(self._count_label)

        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # 分頁控制
        self._prev_btn = PushButton("←")
        self._prev_btn.setFixedWidth(36)
        self._prev_btn.clicked.connect(self._on_prev_page)
        layout.addWidget(self._prev_btn)

        self._page_label = BodyLabel("1 / 1")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setFixedWidth(60)
        layout.addWidget(self._page_label)

        self._next_btn = PushButton("→")
        self._next_btn.setFixedWidth(36)
        self._next_btn.clicked.connect(self._on_next_page)
        layout.addWidget(self._next_btn)

        self._content_layout.addWidget(bar)

    # =========================================================================
    # 生命週期
    # =========================================================================

    def on_enter(self) -> None:
        """進入歷史頁時刷新記錄清單。"""
        super().on_enter()
        self._refresh()

    # =========================================================================
    # 依賴注入
    # =========================================================================

    def set_managers(self, **managers) -> None:
        """注入 managers 並連接 HistoryManager signals。

        Args:
            history:  HistoryManager 實例
            **others: 其他 managers（忽略）
        """
        super().set_managers(**managers)
        history = managers.get("history")
        if history is not None:
            history.signals.record_added.connect(lambda _: self._refresh())
            history.signals.record_updated.connect(lambda _: self._refresh())
            history.signals.record_deleted.connect(lambda _: self._refresh())
            history.signals.records_changed.connect(self._refresh)
            history.signals.error_occurred.connect(self._on_manager_error)

    @property
    def _history_manager(self):
        """便利存取注入的 HistoryManager。"""
        return self._managers.get("history")

    # =========================================================================
    # 資料載入
    # =========================================================================

    def _collect_filters(self) -> dict:
        """從篩選工具列收集目前篩選條件。"""
        filters: dict = {}

        search = self._search_edit.text().strip()
        if search:
            filters["search_term"] = search

        # 格式篩選
        fmt_idx = self._format_combo.currentIndex()
        _, fmt_val = _FORMAT_OPTIONS[fmt_idx]
        if fmt_val is not None:
            filters["source_format"] = fmt_val

        # 狀態篩選
        sts_idx = self._status_combo.currentIndex()
        _, sts_val = _STATUS_OPTIONS[sts_idx]
        if sts_val is not None:
            filters["status"] = sts_val

        # 日期篩選
        date_idx = self._date_combo.currentIndex()
        _, days_back = _DATE_OPTIONS[date_idx]
        if days_back is not None:
            from datetime import datetime, timezone, timedelta
            if days_back == 0:
                date_from = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).isoformat()
            else:
                date_from = (
                    datetime.now(timezone.utc) - timedelta(days=days_back)
                ).isoformat()
            filters["date_from"] = date_from

        return filters

    def _refresh(self) -> None:
        """重新從 HistoryManager 載入記錄並更新表格。"""
        mgr = self._history_manager
        if mgr is None:
            return

        filters = self._collect_filters()
        self._current_filters = filters

        self._total_count = mgr.count(**filters)
        total_pages = max(1, (self._total_count + _PAGE_SIZE - 1) // _PAGE_SIZE)

        # 防止 page 超界
        if self._current_page >= total_pages:
            self._current_page = max(0, total_pages - 1)

        records = mgr.list_records(
            offset=self._current_page * _PAGE_SIZE,
            limit=_PAGE_SIZE,
            **filters,
        )
        self._records = records

        self._populate_table(records)
        self._update_pagination(total_pages)
        self._count_label.setText(f"共 {self._total_count:,} 筆記錄")

        # 空狀態切換
        if not records:
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

        # 清除詳情面板
        self._detail_panel.set_record(None)

    def _populate_table(self, records: list[HistoryRecord]) -> None:
        """將記錄填入 TableWidget。"""
        self._table.setRowCount(0)
        self._table.setRowCount(len(records))

        for row, rec in enumerate(records):
            # 時間
            self._set_cell(row, 0, _format_time(rec.created_at))

            # 來源檔名（截斷）
            src_name = Path(rec.source_path).name if rec.source_path else "-"
            cell = self._set_cell(row, 1, src_name)
            if cell:
                cell.setToolTip(rec.source_path or "")

            # 格式轉換
            fmt_text = f"{rec.source_format.upper()} → {rec.target_format.upper()}"
            self._set_cell(row, 2, fmt_text)

            # 大小
            self._set_cell(row, 3, _format_size(rec.source_size_bytes))

            # 狀態
            status_text, status_color = _STATUS_DISPLAY.get(
                rec.status, (rec.status, "#666666")
            )
            status_cell = self._set_cell(row, 4, status_text)
            if status_cell:
                status_cell.setForeground(QColor(status_color))

            # 耗時
            self._set_cell(row, 5, _format_duration(rec.duration_ms))

            # 動作（開啟按鈕）
            open_btn = PushButton("開啟")
            open_btn.setEnabled(bool(rec.output_path))
            open_btn.clicked.connect(lambda checked, p=rec.output_path: _open_path(p))
            self._table.setCellWidget(row, 6, open_btn)

    def _set_cell(self, row: int, col: int, text: str):
        """設定表格儲存格文字並回傳 item。"""
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._table.setItem(row, col, item)
        return item

    def _update_pagination(self, total_pages: int) -> None:
        """更新分頁控制元件狀態。"""
        current_display = self._current_page + 1
        self._page_label.setText(f"{current_display} / {total_pages}")
        self._prev_btn.setEnabled(self._current_page > 0)
        self._next_btn.setEnabled(self._current_page < total_pages - 1)

    # =========================================================================
    # UI 事件處理
    # =========================================================================

    def _on_filter_changed(self, *args) -> None:
        """篩選條件改變時重設頁碼並刷新。"""
        self._current_page = 0
        self._refresh()

    def _on_prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._refresh()

    def _on_next_page(self) -> None:
        total_pages = max(1, (self._total_count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._refresh()

    def _on_selection_changed(self) -> None:
        """表格選取列改變時更新詳情面板。"""
        selected = self._table.selectedItems()
        if not selected:
            self._detail_panel.set_record(None)
            return
        row = self._table.currentRow()
        if 0 <= row < len(self._records):
            self._detail_panel.set_record(self._records[row])

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        """雙擊列時開啟輸出檔。"""
        if 0 <= row < len(self._records):
            _open_path(self._records[row].output_path)

    def _on_context_menu(self, pos) -> None:
        """右鍵選單。"""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._records):
            return
        rec = self._records[row]

        menu = QMenu(self)

        src_exists = bool(rec.source_path) and Path(rec.source_path).exists()
        act_reconvert = menu.addAction(f"再次轉換為 {rec.target_format.upper()}")
        act_reconvert.setEnabled(src_exists)
        menu.addSeparator()

        act_open_output = menu.addAction("開啟結果")
        act_open_output.setEnabled(bool(rec.output_path))

        act_open_source = menu.addAction("開啟來源")
        act_open_folder = menu.addAction("開啟資料夾")
        menu.addSeparator()
        act_remove = menu.addAction("從歷史移除")

        action = menu.exec(self._table.mapToGlobal(pos))

        if action == act_reconvert:
            self._on_reconvert(rec.source_path, rec.target_format)
        elif action == act_open_output:
            _open_path(rec.output_path)
        elif action == act_open_source:
            _open_path(rec.source_path)
        elif action == act_open_folder:
            _open_folder(rec.output_path or rec.source_path)
        elif action == act_remove:
            self._delete_record(rec.id)

    def _on_reconvert(self, source_path: str, target_format: str) -> None:
        """處理「再次轉換」:加入 Controller 佇列 + 切換至首頁。

        Args:
            source_path: 來源檔案絕對路徑字串。
            target_format: 目標格式(小寫無點)。
        """
        if self._controller is None:
            logger.warning("_on_reconvert: controller 未注入,無法執行")
            return

        path = Path(source_path) if source_path else None
        if path is None or not path.exists():
            InfoBar.error(
                title="檔案不存在",
                content=f"來源檔案已找不到:{source_path}",
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        try:
            self._controller.add_files([path], target_format=target_format)
        except Exception as exc:
            logger.error("_on_reconvert: add_files 失敗 — %s", exc)
            InfoBar.error(
                title="加入佇列失敗",
                content=str(exc),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        # 切換至首頁
        nav = self._managers.get("navigation")
        if nav is not None and hasattr(nav, "navigate_to"):
            try:
                nav.navigate_to(PageID.HOME.value)
            except Exception as exc:
                logger.debug("_on_reconvert: navigate_to 失敗(忽略):%s", exc)

        # 通知
        notify = self._managers.get("notification")
        if notify is not None:
            try:
                notify.success(
                    "已加入轉換佇列",
                    f"{path.name} → {target_format.upper()}",
                    duration_ms=3000,
                )
            except Exception:
                pass
        else:
            InfoBar.success(
                title="已加入轉換佇列",
                content=f"{path.name} → {target_format.upper()}",
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    def _delete_record(self, record_id: int) -> None:
        """刪除單筆記錄。"""
        mgr = self._history_manager
        if mgr is None:
            return
        mgr.delete_record(record_id)

    def _on_clear_all(self) -> None:
        """確認後清除全部歷史記錄。"""
        mgr = self._history_manager
        if mgr is None:
            return

        dlg = MessageBox(
            "清除歷史記錄",
            f"確定要清除全部 {self._total_count:,} 筆歷史記錄嗎？\n此操作不可撤回。",
            self,
        )
        if dlg.exec():
            count = mgr.clear_all()
            InfoBar.success(
                title="清除完成",
                content=f"已刪除 {count:,} 筆歷史記錄",
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    def _on_export_csv(self) -> None:
        """匯出 CSV 對話框。"""
        mgr = self._history_manager
        if mgr is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "匯出歷史記錄",
            "conversion_history.csv",
            "CSV 檔案 (*.csv)",
        )
        if not path:
            return

        self._export_btn.setEnabled(False)
        try:
            count = mgr.export_csv(Path(path), **self._current_filters)
            InfoBar.success(
                title="匯出完成",
                content=f"已匯出 {count:,} 筆記錄至 {Path(path).name}",
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                title="匯出失敗",
                content=str(exc),
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
        finally:
            self._export_btn.setEnabled(True)

    def _on_goto_home(self) -> None:
        """從空狀態跳到首頁。"""
        from desktop.interfaces import PageID
        nav = self._managers.get("navigation")
        if nav is not None and hasattr(nav, "navigate_to"):
            nav.navigate_to(PageID.HOME.value)
        else:
            logger.debug("_on_goto_home: navigation manager 未注入，忽略")

    def _on_manager_error(self, error_msg: str) -> None:
        """顯示 HistoryManager 錯誤通知。"""
        InfoBar.error(
            title="歷史記錄錯誤",
            content=error_msg,
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )
        logger.error("HistoryManager error: %s", error_msg)
