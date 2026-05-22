"""
desktop/pages/pdf_tools_page.py — PDF 工具頁面

提供 4 個 Tab：合併 / 拆分 / 壓縮 / 加密解密。
每個 Tab 各自持有 UI 元件，共用頁面底部的進度條與 InfoBar 通知區。

依賴注入（由 MainWindowV2 呼叫）：
    set_controller(pdf_tools_controller)   — PdfToolsController 實例
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import (
        ComboBox,
        FluentIcon,
        IndeterminateProgressBar,
        InfoBar,
        InfoBarPosition,
        PasswordLineEdit,
        PrimaryPushButton,
        PushButton,
        SegmentedWidget,
        StrongBodyLabel,
        SubtitleLabel,
        ToolButton,
    )
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import (  # type: ignore[assignment]
        QComboBox as ComboBox,
        QLineEdit as PasswordLineEdit,
        QPushButton as PrimaryPushButton,
        QPushButton as PushButton,
        QPushButton as ToolButton,
        QTabWidget as SegmentedWidget,
        QLabel as StrongBodyLabel,
        QLabel as SubtitleLabel,
        QProgressBar as IndeterminateProgressBar,
    )
    InfoBar = None  # type: ignore[assignment]
    InfoBarPosition = None  # type: ignore[assignment]
    FluentIcon = None  # type: ignore[assignment]
    _HAS_FLUENT = False

from desktop.interfaces import PageID
from desktop.pages.base_page import BasePage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 頁面範圍解析工具
# ---------------------------------------------------------------------------

def _parse_ranges(text: str, max_page: int) -> list[tuple[int, int]]:
    """解析 '1-3, 5, 7-9' 格式的頁面範圍字串。

    Args:
        text:     使用者輸入的範圍字串，以逗號分隔。
        max_page: PDF 總頁數（1-indexed 上限）。

    Returns:
        [(start, end), ...] 清單，1-indexed inclusive。

    Raises:
        ValueError: 格式無法解析、頁碼超出範圍，或 start > end。
    """
    ranges: list[tuple[int, int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            halves = part.split("-", 1)
            try:
                start = int(halves[0].strip())
                end = int(halves[1].strip())
            except ValueError:
                raise ValueError(f"無效範圍片段：{part!r}（格式應為 '起始-結束'）")
        else:
            try:
                n = int(part)
            except ValueError:
                raise ValueError(f"無效頁碼：{part!r}")
            start = end = n

        if start < 1:
            raise ValueError(f"無效範圍：{start}-{end}（頁碼最小為 1）")
        if end > max_page:
            raise ValueError(f"無效範圍：{start}-{end}（PDF 共 {max_page} 頁）")
        if start > end:
            raise ValueError(f"無效範圍：{start}-{end}（起始頁不可大於結束頁）")

        ranges.append((start, end))

    if not ranges:
        raise ValueError("頁面範圍不可為空")
    return ranges


# ---------------------------------------------------------------------------
# 主頁面
# ---------------------------------------------------------------------------

class PdfToolsPage(BasePage):
    """PDF 工具頁面 — 合併 / 拆分 / 壓縮 / 加密解密。"""

    PAGE_ID = PageID.PDF_TOOLS
    PAGE_TITLE = "PDF 工具"
    PAGE_ICON = FluentIcon.DOCUMENT if _HAS_FLUENT and FluentIcon is not None else None

    def _setup_ui(self) -> None:
        """建立頁面 UI：標題 + 四 Tab + 底部進度區。"""
        # 頁面標題
        title_label = SubtitleLabel("PDF 工具") if _HAS_FLUENT else QLabel("PDF 工具")
        self._content_layout.addWidget(title_label)

        # Tab 容器
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._content_layout.addWidget(self._tab_widget, stretch=1)

        # 建立四個 Tab
        self._merge_tab = _MergeTab(self)
        self._split_tab = _SplitTab(self)
        self._compress_tab = _CompressTab(self)
        self._encrypt_tab = _EncryptTab(self)

        self._tab_widget.addTab(self._merge_tab, "合併 PDF")
        self._tab_widget.addTab(self._split_tab, "拆分 PDF")
        self._tab_widget.addTab(self._compress_tab, "壓縮 PDF")
        self._tab_widget.addTab(self._encrypt_tab, "加密 / 解密")

        # 底部進度條
        self._progress_bar = _make_progress_bar()
        self._progress_bar.setVisible(False)
        self._content_layout.addWidget(self._progress_bar)

    def set_controller(self, controller) -> None:
        """注入 PdfToolsController，連接 Signals。

        Args:
            controller: PdfToolsController 實例。
        """
        super().set_controller(controller)
        if controller is None:
            return

        sig = controller.signals
        sig.operation_started.connect(self._on_operation_started)
        sig.operation_progress.connect(self._on_operation_progress)
        sig.operation_completed.connect(self._on_operation_completed)
        sig.operation_failed.connect(self._on_operation_failed)

        # 把 controller 傳給各 Tab
        self._merge_tab.set_controller(controller)
        self._split_tab.set_controller(controller)
        self._compress_tab.set_controller(controller)
        self._encrypt_tab.set_controller(controller)

    # -------------------------------------------------------------------------
    # Signal 處理
    # -------------------------------------------------------------------------

    def _on_operation_started(self, operation_name: str) -> None:
        """操作開始：顯示進度條，鎖定所有 Tab 的主按鈕。"""
        self._progress_bar.setVisible(True)
        _reset_progress_bar(self._progress_bar)
        for tab in (self._merge_tab, self._split_tab, self._compress_tab, self._encrypt_tab):
            tab.set_running(True)

    def _on_operation_progress(self, value: float) -> None:
        """更新進度條（0.0–1.0 → 0–100）。"""
        if hasattr(self._progress_bar, "setValue"):
            self._progress_bar.setValue(int(value * 100))

    def _on_operation_completed(self, operation_name: str, result: object) -> None:
        """操作完成：隱藏進度條，顯示成功通知。"""
        self._progress_bar.setVisible(False)
        for tab in (self._merge_tab, self._split_tab, self._compress_tab, self._encrypt_tab):
            tab.set_running(False)

        # 更新壓縮結果顯示
        if operation_name == "compress" and isinstance(result, dict):
            self._compress_tab.show_compress_result(result)

        # 拆分結果：通知產出檔案數
        content = _build_completion_message(operation_name, result)
        _show_info_bar(self, "success", "完成", content)
        logger.info("pdf_tools 操作完成: %s", operation_name)

    def _on_operation_failed(self, operation_name: str, error_message: str) -> None:
        """操作失敗：隱藏進度條，顯示錯誤通知。"""
        self._progress_bar.setVisible(False)
        for tab in (self._merge_tab, self._split_tab, self._compress_tab, self._encrypt_tab):
            tab.set_running(False)

        _show_info_bar(self, "error", "操作失敗", error_message)
        logger.warning("pdf_tools 操作失敗: %s — %s", operation_name, error_message)


# ---------------------------------------------------------------------------
# Tab 基類
# ---------------------------------------------------------------------------

class _BaseTab(QWidget):
    """各 Tab 的共同基類，提供 set_controller / set_running 介面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller = None
        self._setup_tab_ui()

    def _setup_tab_ui(self) -> None:
        """子類實作：建立 Tab 內容 UI。"""
        raise NotImplementedError

    def set_controller(self, controller) -> None:
        """注入 PdfToolsController。"""
        self._controller = controller

    def set_running(self, is_running: bool) -> None:
        """鎖定 / 解鎖主按鈕，防止操作中重複觸發。"""
        btn = getattr(self, "_primary_btn", None)
        if btn is not None:
            btn.setEnabled(not is_running)


# ---------------------------------------------------------------------------
# Tab 1：合併 PDF
# ---------------------------------------------------------------------------

class _MergeTab(_BaseTab):
    """合併 PDF Tab — 清單 + 排序 + 輸出路徑。"""

    def _setup_tab_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 檔案清單
        list_label = QLabel("PDF 清單（上方的先合併）：")
        layout.addWidget(list_label)

        self._list_widget = QListWidget()
        self._list_widget.setAcceptDrops(True)
        self._list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list_widget.setMinimumHeight(180)
        layout.addWidget(self._list_widget, stretch=1)

        # 操作按鈕列
        btn_row = QHBoxLayout()
        self._add_btn = PushButton("新增 PDF")
        self._remove_btn = PushButton("移除選中")
        self._move_up_btn = PushButton("上移")
        self._move_down_btn = PushButton("下移")
        for btn in (self._add_btn, self._remove_btn, self._move_up_btn, self._move_down_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 輸出路徑
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("輸出路徑："))
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("選擇或輸入輸出 PDF 路徑…")
        self._browse_output_btn = PushButton("瀏覽")
        out_row.addWidget(self._output_edit, stretch=1)
        out_row.addWidget(self._browse_output_btn)
        layout.addLayout(out_row)

        # 主按鈕
        self._primary_btn = PrimaryPushButton("合併")
        layout.addWidget(self._primary_btn)

        # 連線
        self._add_btn.clicked.connect(self._on_add_files)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        self._move_up_btn.clicked.connect(self._on_move_up)
        self._move_down_btn.clicked.connect(self._on_move_down)
        self._browse_output_btn.clicked.connect(self._on_browse_output)
        self._primary_btn.clicked.connect(self._on_merge)

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇 PDF 檔案", "", "PDF 檔案 (*.pdf)"
        )
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, Path(p))
            self._list_widget.addItem(item)

    def _on_remove_selected(self) -> None:
        for item in self._list_widget.selectedItems():
            self._list_widget.takeItem(self._list_widget.row(item))

    def _on_move_up(self) -> None:
        row = self._list_widget.currentRow()
        if row > 0:
            item = self._list_widget.takeItem(row)
            self._list_widget.insertItem(row - 1, item)
            self._list_widget.setCurrentRow(row - 1)

    def _on_move_down(self) -> None:
        row = self._list_widget.currentRow()
        if row < self._list_widget.count() - 1:
            item = self._list_widget.takeItem(row)
            self._list_widget.insertItem(row + 1, item)
            self._list_widget.setCurrentRow(row + 1)

    def _on_browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存合併 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._output_edit.setText(path)

    def _on_merge(self) -> None:
        if self._controller is None:
            return

        input_paths = [
            self._list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list_widget.count())
        ]
        if not input_paths:
            _show_info_bar(self, "warning", "請新增 PDF", "清單為空，請先新增要合併的 PDF。")
            return

        output_text = self._output_edit.text().strip()
        if not output_text:
            _show_info_bar(self, "warning", "請指定輸出路徑", "請選擇合併後 PDF 的儲存位置。")
            return

        output_path = Path(output_text)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".pdf")

        if not output_path.parent.exists():
            _show_info_bar(self, "error", "輸出目錄不存在", f"目錄不存在：{output_path.parent}")
            return

        self._controller.merge(input_paths=input_paths, output_path=output_path)


# ---------------------------------------------------------------------------
# Tab 2：拆分 PDF
# ---------------------------------------------------------------------------

class _SplitTab(_BaseTab):
    """拆分 PDF Tab — 模式選擇 + 來源 + 輸出目錄。"""

    def _setup_tab_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 來源檔案
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("來源 PDF："))
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("選擇或輸入來源 PDF 路徑…")
        self._browse_src_btn = PushButton("瀏覽")
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(self._browse_src_btn)
        layout.addLayout(src_row)

        # 拆分模式
        mode_group = QGroupBox("拆分模式")
        mode_layout = QVBoxLayout(mode_group)
        self._mode_per_page = QRadioButton("每頁一個 PDF")
        self._mode_ranges = QRadioButton("按頁面範圍")
        self._mode_bookmarks = QRadioButton("按書籤")
        self._mode_per_page.setChecked(True)
        mode_layout.addWidget(self._mode_per_page)

        # 範圍輸入行
        ranges_row = QHBoxLayout()
        ranges_row.addWidget(self._mode_ranges)
        self._ranges_edit = QLineEdit()
        self._ranges_edit.setPlaceholderText("例：1-3, 5, 7-9")
        self._ranges_edit.setEnabled(False)
        ranges_row.addWidget(self._ranges_edit, stretch=1)
        mode_layout.addLayout(ranges_row)
        mode_layout.addWidget(self._mode_bookmarks)
        layout.addWidget(mode_group)

        # 輸出目錄
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("輸出目錄："))
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("選擇輸出資料夾…")
        self._browse_out_dir_btn = PushButton("瀏覽")
        out_row.addWidget(self._out_dir_edit, stretch=1)
        out_row.addWidget(self._browse_out_dir_btn)
        layout.addLayout(out_row)

        # 主按鈕
        self._primary_btn = PrimaryPushButton("拆分")
        layout.addWidget(self._primary_btn)
        layout.addStretch()

        # 連線
        self._browse_src_btn.clicked.connect(self._on_browse_src)
        self._browse_out_dir_btn.clicked.connect(self._on_browse_out_dir)
        self._mode_ranges.toggled.connect(self._ranges_edit.setEnabled)
        self._primary_btn.clicked.connect(self._on_split)

    def _on_browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇來源 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._src_edit.setText(path)

    def _on_browse_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出目錄")
        if path:
            self._out_dir_edit.setText(path)

    def _on_split(self) -> None:
        if self._controller is None:
            return

        src_text = self._src_edit.text().strip()
        if not src_text:
            _show_info_bar(self, "warning", "請選擇來源 PDF", "尚未指定要拆分的 PDF 檔案。")
            return

        out_text = self._out_dir_edit.text().strip()
        if not out_text:
            _show_info_bar(self, "warning", "請選擇輸出目錄", "尚未指定拆分結果的輸出目錄。")
            return

        src_path = Path(src_text)
        out_dir = Path(out_text)

        if not src_path.exists():
            _show_info_bar(self, "error", "檔案不存在", f"找不到：{src_path}")
            return
        if not out_dir.exists():
            _show_info_bar(self, "error", "目錄不存在", f"找不到：{out_dir}")
            return

        # 決定拆分模式
        if self._mode_per_page.isChecked():
            self._controller.split(src_path, out_dir, "per_page")

        elif self._mode_ranges.isChecked():
            ranges_text = self._ranges_edit.text().strip()
            if not ranges_text:
                _show_info_bar(self, "warning", "請輸入頁面範圍", "例：1-3, 5, 7-9")
                return
            try:
                # 先取得頁數做邊界檢查
                info = self._controller.get_info(src_path)
                max_page = info.get("page_count", 0)
                if max_page == 0:
                    _show_info_bar(self, "error", "無法讀取 PDF", "PDF 可能已加密或損壞。")
                    return
                parsed = _parse_ranges(ranges_text, max_page)
            except ValueError as exc:
                _show_info_bar(self, "error", f"無效範圍：{exc}", str(exc))
                return
            self._controller.split(src_path, out_dir, "ranges", parsed)

        else:
            self._controller.split(src_path, out_dir, "bookmarks")


# ---------------------------------------------------------------------------
# Tab 3：壓縮 PDF
# ---------------------------------------------------------------------------

class _CompressTab(_BaseTab):
    """壓縮 PDF Tab — 品質選擇 + 壓縮前後大小顯示。"""

    def _setup_tab_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 來源
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("來源 PDF："))
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("選擇或輸入來源 PDF 路徑…")
        self._browse_src_btn = PushButton("瀏覽")
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(self._browse_src_btn)
        layout.addLayout(src_row)

        # 壓縮品質
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("壓縮品質："))
        self._quality_combo = ComboBox() if _HAS_FLUENT else ComboBox()
        for label in ("低（最小檔案）", "平衡", "高（接近原品質）"):
            self._quality_combo.addItem(label)
        self._quality_combo.setCurrentIndex(1)  # 預設「平衡」
        quality_row.addWidget(self._quality_combo)
        quality_row.addStretch()
        layout.addLayout(quality_row)

        # 輸出
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("輸出路徑："))
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("選擇或輸入輸出 PDF 路徑…")
        self._browse_out_btn = PushButton("瀏覽")
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(self._browse_out_btn)
        layout.addLayout(out_row)

        # 壓縮結果顯示
        self._result_label = QLabel()
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        # 主按鈕
        self._primary_btn = PrimaryPushButton("壓縮")
        layout.addWidget(self._primary_btn)
        layout.addStretch()

        # 連線
        self._browse_src_btn.clicked.connect(self._on_browse_src)
        self._browse_out_btn.clicked.connect(self._on_browse_out)
        self._primary_btn.clicked.connect(self._on_compress)

    def _quality_key(self) -> str:
        """將 ComboBox 索引轉換為 pdf_tools 品質代碼。"""
        mapping = {0: "low", 1: "balanced", 2: "high"}
        return mapping.get(self._quality_combo.currentIndex(), "balanced")

    def _on_browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇來源 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._src_edit.setText(path)

    def _on_browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存壓縮 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._out_edit.setText(path)

    def _on_compress(self) -> None:
        if self._controller is None:
            return

        src_text = self._src_edit.text().strip()
        out_text = self._out_edit.text().strip()

        if not src_text:
            _show_info_bar(self, "warning", "請選擇來源 PDF", "尚未指定要壓縮的 PDF。")
            return
        if not out_text:
            _show_info_bar(self, "warning", "請指定輸出路徑", "尚未指定壓縮後 PDF 的儲存位置。")
            return

        src_path = Path(src_text)
        out_path = Path(out_text)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".pdf")

        if not src_path.exists():
            _show_info_bar(self, "error", "檔案不存在", f"找不到：{src_path}")
            return
        if not out_path.parent.exists():
            _show_info_bar(self, "error", "輸出目錄不存在", f"目錄不存在：{out_path.parent}")
            return

        self._result_label.setVisible(False)
        self._controller.compress(src_path, out_path, self._quality_key())

    def show_compress_result(self, result: dict) -> None:
        """操作完成後更新壓縮結果顯示。

        Args:
            result: compress_pdf 回傳的 {original_size, compressed_size, ratio}。
        """
        original_kb = result.get("original_size", 0) / 1024
        compressed_kb = result.get("compressed_size", 0) / 1024
        ratio = result.get("ratio", 1.0)
        saved_pct = max(0.0, (1.0 - ratio) * 100)

        self._result_label.setText(
            f"{original_kb:.1f} KB  →  {compressed_kb:.1f} KB  （節省 {saved_pct:.1f}%）"
        )
        self._result_label.setVisible(True)


# ---------------------------------------------------------------------------
# Tab 4：加密 / 解密
# ---------------------------------------------------------------------------

class _EncryptTab(_BaseTab):
    """加密 / 解密 PDF Tab。"""

    def _setup_tab_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 模式切換（加密 / 解密）
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("操作模式："))
        self._encrypt_radio = QRadioButton("加密")
        self._decrypt_radio = QRadioButton("解密")
        self._encrypt_radio.setChecked(True)
        mode_row.addWidget(self._encrypt_radio)
        mode_row.addWidget(self._decrypt_radio)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # 來源
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("來源 PDF："))
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("選擇或輸入來源 PDF 路徑…")
        self._browse_src_btn = PushButton("瀏覽")
        src_row.addWidget(self._src_edit, stretch=1)
        src_row.addWidget(self._browse_src_btn)
        layout.addLayout(src_row)

        # 密碼區（使用者密碼）
        pw_row = QHBoxLayout()
        pw_row.addWidget(QLabel("密碼："))
        self._password_edit = _PasswordField(self)
        pw_row.addWidget(self._password_edit, stretch=1)
        layout.addLayout(pw_row)

        # 所有者密碼（僅加密模式顯示）
        owner_row = QHBoxLayout()
        self._owner_label = QLabel("所有者密碼（選填）：")
        self._owner_edit = _PasswordField(self)
        self._owner_edit.setPlaceholderText("留空則與使用者密碼相同")
        owner_row.addWidget(self._owner_label)
        owner_row.addWidget(self._owner_edit, stretch=1)
        self._owner_row_widget = QWidget()
        self._owner_row_widget.setLayout(owner_row)
        layout.addWidget(self._owner_row_widget)

        # 輸出
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("輸出路徑："))
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("選擇或輸入輸出 PDF 路徑…")
        self._browse_out_btn = PushButton("瀏覽")
        out_row.addWidget(self._out_edit, stretch=1)
        out_row.addWidget(self._browse_out_btn)
        layout.addLayout(out_row)

        # 主按鈕
        self._primary_btn = PrimaryPushButton("加密")
        layout.addWidget(self._primary_btn)
        layout.addStretch()

        # 連線
        self._browse_src_btn.clicked.connect(self._on_browse_src)
        self._browse_out_btn.clicked.connect(self._on_browse_out)
        self._primary_btn.clicked.connect(self._on_execute)
        self._encrypt_radio.toggled.connect(self._on_mode_changed)

    def _on_mode_changed(self, is_encrypt: bool) -> None:
        """切換加密 / 解密模式，更新 UI 顯示。"""
        self._owner_row_widget.setVisible(is_encrypt)
        self._primary_btn.setText("加密" if is_encrypt else "解密")

    def _on_browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇來源 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._src_edit.setText(path)

    def _on_browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存輸出 PDF", "", "PDF 檔案 (*.pdf)"
        )
        if path:
            self._out_edit.setText(path)

    def _on_execute(self) -> None:
        if self._controller is None:
            return

        src_text = self._src_edit.text().strip()
        out_text = self._out_edit.text().strip()
        password = self._password_edit.text().strip()

        if not src_text:
            _show_info_bar(self, "warning", "請選擇來源 PDF", "尚未指定來源 PDF。")
            return
        if not password:
            _show_info_bar(self, "warning", "請輸入密碼", "密碼不可為空。")
            return
        if not out_text:
            _show_info_bar(self, "warning", "請指定輸出路徑", "尚未指定輸出 PDF 路徑。")
            return

        src_path = Path(src_text)
        out_path = Path(out_text)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".pdf")

        if not src_path.exists():
            _show_info_bar(self, "error", "檔案不存在", f"找不到：{src_path}")
            return
        if not out_path.parent.exists():
            _show_info_bar(self, "error", "輸出目錄不存在", f"目錄不存在：{out_path.parent}")
            return

        if self._encrypt_radio.isChecked():
            owner_text = self._owner_edit.text().strip()
            owner_password = owner_text if owner_text else None
            self._controller.encrypt(src_path, out_path, password, owner_password)
        else:
            self._controller.decrypt(src_path, out_path, password)


# ---------------------------------------------------------------------------
# 密碼輸入欄（帶眼睛按鈕）
# ---------------------------------------------------------------------------

class _PasswordField(QWidget):
    """密碼輸入框 + 顯示/隱藏切換按鈕。

    對外暴露 .text() / .setPlaceholderText() 方法，行為與 QLineEdit 一致。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._line_edit = QLineEdit()
        self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._line_edit.setPlaceholderText("請輸入密碼…")
        layout.addWidget(self._line_edit, stretch=1)

        self._toggle_btn = PushButton("顯示")
        self._toggle_btn.setFixedWidth(52)
        self._toggle_btn.clicked.connect(self._toggle_visibility)
        layout.addWidget(self._toggle_btn)

        self._is_visible = False

    def _toggle_visibility(self) -> None:
        self._is_visible = not self._is_visible
        if self._is_visible:
            self._line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_btn.setText("隱藏")
        else:
            self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_btn.setText("顯示")

    def text(self) -> str:
        """回傳輸入文字。"""
        return self._line_edit.text()

    def setPlaceholderText(self, text: str) -> None:
        """設定 placeholder 文字。"""
        self._line_edit.setPlaceholderText(text)


# ---------------------------------------------------------------------------
# 工具函式
# ---------------------------------------------------------------------------

def _make_progress_bar() -> QProgressBar:
    """建立統一樣式的進度條（0–100）。"""
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setFixedHeight(6)
    bar.setTextVisible(False)
    return bar


def _reset_progress_bar(bar: QProgressBar) -> None:
    """重置進度條為 0。"""
    bar.setValue(0)


def _show_info_bar(
    parent: QWidget,
    level: str,
    title: str,
    content: str,
) -> None:
    """顯示 InfoBar 通知（qfluentwidgets），降級為 print log。

    Args:
        parent:  顯示的父 widget。
        level:   "info" | "success" | "warning" | "error"。
        title:   通知標題。
        content: 通知內容。
    """
    if not _HAS_FLUENT or InfoBar is None:
        logger.info("[%s] %s — %s", level.upper(), title, content)
        return

    position = InfoBarPosition.TOP if InfoBarPosition else None
    duration = 4000

    try:
        if level == "success":
            InfoBar.success(title=title, content=content, parent=parent,
                            position=position, duration=duration)
        elif level == "warning":
            InfoBar.warning(title=title, content=content, parent=parent,
                            position=position, duration=duration)
        elif level == "error":
            InfoBar.error(title=title, content=content, parent=parent,
                          position=position, duration=duration)
        else:
            InfoBar.info(title=title, content=content, parent=parent,
                         position=position, duration=duration)
    except Exception as exc:
        logger.warning("InfoBar 顯示失敗（%s）: %s — %s", exc, title, content)


def _build_completion_message(operation_name: str, result: object) -> str:
    """依操作類型建立完成通知內文。

    Args:
        operation_name: 操作名稱。
        result:         操作結果。

    Returns:
        人類可讀的完成說明字串。
    """
    if operation_name == "merge":
        return "PDF 合併完成。"
    if operation_name == "split":
        count = len(result) if isinstance(result, list) else "?"
        return f"拆分完成，共產生 {count} 個 PDF 檔案。"
    if operation_name == "compress":
        if isinstance(result, dict):
            ratio = result.get("ratio", 1.0)
            saved = max(0.0, (1.0 - ratio) * 100)
            return f"壓縮完成，節省 {saved:.1f}%。"
        return "壓縮完成。"
    if operation_name == "encrypt":
        return "加密完成。"
    if operation_name == "decrypt":
        return "解密完成。"
    return f"{operation_name} 操作完成。"
