"""File Card Widget — Round 2（widgets-1）實作主體。

每個 ConversionJob 對應一張 FileCard，顯示在佇列區。

Round 2 職責（widgets-1 代理）：
    - 顯示：檔名、來源格式圖示、目標格式下拉、進度條、狀態文字
    - 進度條由 ConversionController.job_progress Signal 驅動更新
    - 狀態文字隨 JobStatus 變化（Pending / Converting / Done / Error）
    - 刪除按鈕發出 remove_requested Signal
    - 目標格式下拉發出 target_format_changed Signal
    - 錯誤時顯示紅色錯誤訊息文字

信任假設（Round 2 可依賴）：
    - interfaces.FileCardSignals 的 Signal 簽名不會改變
    - interfaces.ConversionJob 的欄位不會改變
    - interfaces.get_supported_targets(source_format) 回傳目標格式清單
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop.interfaces import (
    ConversionJob,
    FileCardSignals,
    JobStatus,
    get_supported_targets,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 格式圖示色彩映射（格式名稱 → 背景色）
# ------------------------------------------------------------------
_FORMAT_COLORS: dict[str, str] = {
    "pdf":  "#EF4444",  # 紅
    "docx": "#3B82F6",  # 藍
    "pptx": "#F97316",  # 橙
    "html": "#F59E0B",  # 黃
    "md":   "#8B5CF6",  # 紫
    "txt":  "#6B7280",  # 灰
    "png":  "#10B981",  # 綠
    "jpg":  "#10B981",
    "jpeg": "#10B981",
    "gif":  "#EC4899",  # 粉
    "webp": "#14B8A6",  # 青
}
_DEFAULT_FORMAT_COLOR = "#6B7280"

# ------------------------------------------------------------------
# 狀態對應文字與顏色
# ------------------------------------------------------------------
_STATUS_TEXT: dict[JobStatus, str] = {
    JobStatus.IDLE:       "待轉換",
    JobStatus.PENDING:    "排隊中",
    JobStatus.CONVERTING: "轉換中",
    JobStatus.DONE:       "完成",
    JobStatus.ERROR:      "失敗",
}
_STATUS_COLOR: dict[JobStatus, str] = {
    JobStatus.IDLE:       "#9CA3AF",
    JobStatus.PENDING:    "#9CA3AF",
    JobStatus.CONVERTING: "#8B5CF6",
    JobStatus.DONE:       "#10B981",
    JobStatus.ERROR:      "#EF4444",
}

# 卡片公共樣式
_CARD_STYLE = (
    "QFrame#FileCard {"
    "  background-color: #FFFFFF;"
    "  border: 1px solid #E5E7EB;"
    "  border-radius: 8px;"
    "}"
)


class _FormatBadge(QLabel):
    """60×60 的格式標誌（副檔名大寫白字，彩色背景）。"""

    def __init__(self, fmt: str, parent: QWidget | None = None) -> None:
        super().__init__(fmt.upper(), parent)
        color = _FORMAT_COLORS.get(fmt.lower(), _DEFAULT_FORMAT_COLOR)
        self.setFixedSize(60, 60)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {color};"
            f"  color: white;"
            f"  font-family: 'Segoe UI Variable', '微軟正黑體', monospace;"
            f"  font-size: 13px;"
            f"  font-weight: 700;"
            f"  border-radius: 8px;"
            f"}}"
        )


class FileCard(QFrame):
    """單一轉換任務的卡片式顯示元件。

    Args:
        job: 此卡片代表的 ConversionJob。
        parent: 父 Widget。

    Signals（透過 self.signals 存取）：
        remove_requested(str):              job_id — 使用者要移除此任務。
        target_format_changed(str, str):    job_id, target_format — 使用者切換輸出格式。

    公開更新方法（由外部呼叫，非 Signal）：
        update_progress(progress)    — 0.0–1.0 進度值。
        update_status(status, message) — 狀態切換 + 可選附加文字。
        mark_done(output_path)       — 標記完成並顯示「開啟」按鈕。
        mark_error(error_message)    — 標記失敗並顯示錯誤訊息。
    """

    def __init__(self, job: ConversionJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = FileCardSignals()
        self._job_id: str = job.job_id
        self._source_format: str = job.source_format
        self._output_path: Path | None = None

        self.setObjectName("FileCard")
        self.setFixedHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(_CARD_STYLE)

        self._setup_ui(job)
        self._connect_signals()

        # 套用初始狀態
        self.update_status(job.status)

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _setup_ui(self, job: ConversionJob) -> None:
        """建構完整卡片佈局：[Badge] [中間資訊] [右側控制]。"""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(12)

        self._badge = _FormatBadge(job.source_format)
        outer.addWidget(self._badge)
        outer.addWidget(self._build_center_column(job))
        outer.addWidget(self._build_right_panel(job))

    def _build_center_column(self, job: ConversionJob) -> QWidget:
        """建立中間垂直欄：檔名 + 狀態列（狀態文字 + 進度條）。"""
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._filename_label = QLabel(job.source_path.name)
        self._filename_label.setToolTip(str(job.source_path))
        self._filename_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._filename_label.setStyleSheet(
            "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "font-size: 13px; font-weight: 600; color: #111827;"
        )
        layout.addWidget(self._filename_label)
        layout.addLayout(self._build_status_row())
        return widget

    def _build_status_row(self) -> QHBoxLayout:
        """建立狀態文字 + 進度條橫排。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._status_label = QLabel("待轉換")
        self._status_label.setStyleSheet(
            "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "font-size: 11px; color: #9CA3AF;"
        )
        row.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet(
            "QProgressBar { background-color: #E5E7EB; border-radius: 2px; border: none; }"
            "QProgressBar::chunk { background-color: #8B5CF6; border-radius: 2px; }"
        )
        row.addWidget(self._progress_bar)
        return row

    def _build_right_panel(self, job: ConversionJob) -> QWidget:
        """建立右側控制面板：格式下拉 + 完成按鈕（隱藏）+ 刪除按鈕。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_format_combo(job))
        layout.addWidget(self._build_open_btn())
        layout.addWidget(self._build_open_folder_btn())
        layout.addWidget(self._build_remove_btn())
        return widget

    def _build_format_combo(self, job: ConversionJob) -> QComboBox:
        """建立目標格式下拉框，並預選 job.target_format。"""
        self._format_combo = QComboBox()
        self._format_combo.setFixedWidth(80)
        self._format_combo.setFixedHeight(32)
        targets = get_supported_targets(job.source_format)
        self._format_combo.addItems([fmt.upper() for fmt in targets])
        lower_targets = [fmt.lower() for fmt in targets]
        if job.target_format.lower() in lower_targets:
            self._format_combo.setCurrentIndex(lower_targets.index(job.target_format.lower()))
        self._format_combo.setStyleSheet(
            "QComboBox {"
            "  font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "  font-size: 12px; color: #374151; background-color: #F9FAFB;"
            "  border: 1px solid #D1D5DB; border-radius: 4px; padding: 2px 8px;"
            "}"
            "QComboBox:hover { border-color: #8B5CF6; }"
            "QComboBox::drop-down { border: none; }"
        )
        return self._format_combo

    def _build_open_btn(self) -> QPushButton:
        """建立「開啟」按鈕（DONE 狀態顯示，初始隱藏）。"""
        self._open_btn = QPushButton("開啟")
        self._open_btn.setFixedSize(60, 32)
        self._open_btn.setVisible(False)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setStyleSheet(
            "QPushButton { font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "  font-size: 11px; font-weight: 600; color: white;"
            "  background-color: #10B981; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #059669; }"
        )
        self._open_btn.clicked.connect(self._on_open_file)
        return self._open_btn

    def _build_open_folder_btn(self) -> QPushButton:
        """建立「開啟資料夾」按鈕（DONE 狀態顯示，初始隱藏）。"""
        self._open_folder_btn = QPushButton("📂")
        self._open_folder_btn.setFixedSize(32, 32)
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_folder_btn.setToolTip("開啟所在資料夾")
        self._open_folder_btn.setStyleSheet(
            "QPushButton { font-size: 14px; background-color: #F3F4F6;"
            "  border: 1px solid #D1D5DB; border-radius: 4px; }"
            "QPushButton:hover { background-color: #E5E7EB; }"
        )
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        return self._open_folder_btn

    def _build_remove_btn(self) -> QPushButton:
        """建立刪除（✕）按鈕。"""
        self._remove_btn = QPushButton("✕")
        self._remove_btn.setFixedSize(32, 32)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setToolTip("移除此任務")
        self._remove_btn.setStyleSheet(
            "QPushButton { font-size: 14px; color: #9CA3AF;"
            "  background-color: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { color: #EF4444; background-color: #FEF2F2; }"
        )
        return self._remove_btn

    # ------------------------------------------------------------------
    # Signal 連接
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """連接內部元件事件到對外 Signal。"""
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        self._remove_btn.clicked.connect(self._on_remove_clicked)

    def _on_format_changed(self, text: str) -> None:
        """ComboBox 切換格式時，發射 target_format_changed Signal。"""
        new_format = text.lower()
        logger.debug(
            "file_card[%s]: 目標格式切換為 %s", self._job_id, new_format
        )
        self.signals.target_format_changed.emit(self._job_id, new_format)

    def _on_remove_clicked(self) -> None:
        """刪除按鈕點擊，發射 remove_requested Signal。"""
        logger.debug("file_card[%s]: 使用者點擊刪除", self._job_id)
        self.signals.remove_requested.emit(self._job_id)

    # ------------------------------------------------------------------
    # 開啟檔案 / 資料夾
    # ------------------------------------------------------------------

    def _on_open_file(self) -> None:
        """開啟輸出檔案。"""
        if self._output_path is None or not self._output_path.exists():
            logger.warning("file_card[%s]: 輸出檔案不存在，無法開啟", self._job_id)
            return
        try:
            if sys.platform == "win32":
                os.startfile(self._output_path)
            else:
                subprocess.run(
                    ["xdg-open", str(self._output_path)], check=False
                )
        except OSError as exc:
            logger.error(
                "file_card[%s]: 無法開啟檔案 %s — %s",
                self._job_id, self._output_path, exc,
            )

    def _on_open_folder(self) -> None:
        """在檔案總管中定位並選取輸出檔案。"""
        if self._output_path is None:
            return
        try:
            if sys.platform == "win32":
                target = self._output_path.resolve()
                if target.exists():
                    # /select, 與路徑必須合併為單一引數，否則部分 Windows 版本
                    # 會忽略選取意圖，僅開啟父目錄（C-DESK-001 修復）。
                    # shell=False 防止路徑含特殊字元時的 shell injection。
                    # check=False 因為 explorer 成功時仍可能回傳非 0 exit code。
                    subprocess.run(
                        ["explorer", f"/select,{target}"],
                        check=False,
                        shell=False,
                    )
                else:
                    # 檔案已不存在，退而求其次開啟父目錄
                    subprocess.run(
                        ["explorer", str(target.parent)],
                        check=False,
                        shell=False,
                    )
            else:
                subprocess.run(
                    ["xdg-open", str(self._output_path.parent)],
                    check=False,
                )
        except OSError as exc:
            logger.error(
                "file_card[%s]: 無法開啟資料夾 %s — %s",
                self._job_id, self._output_path.parent, exc,
            )

    # ------------------------------------------------------------------
    # 公開更新 API（由 MainWindow 或 ConversionController 呼叫）
    # ------------------------------------------------------------------

    def update_progress(self, progress: float) -> None:
        """更新進度條顯示。

        Args:
            progress: 0.0–1.0 的進度值。超出範圍會被 clamp。
        """
        clamped = max(0.0, min(1.0, progress))
        percent = int(clamped * 100)
        self._progress_bar.setValue(percent)
        self._status_label.setText(f"轉換中 {percent}%")

    def update_status(self, status: JobStatus, message: str = "") -> None:
        """切換卡片顯示狀態。

        Args:
            status:  新的 JobStatus。
            message: 可選的附加狀態文字（如錯誤摘要）。
        """
        color = _STATUS_COLOR.get(status, "#9CA3AF")
        base_text = message or _STATUS_TEXT.get(status, status.value)

        self._status_label.setText(base_text)
        self._status_label.setStyleSheet(
            "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            f"font-size: 11px; color: {color};"
        )

        # 進度條可見性：只在 CONVERTING 時顯示
        show_progress = (status == JobStatus.CONVERTING)
        self._progress_bar.setVisible(show_progress)
        if not show_progress:
            self._progress_bar.setValue(0)

        # CONVERTING 時停用格式切換
        self._format_combo.setEnabled(
            status not in (JobStatus.CONVERTING, JobStatus.DONE, JobStatus.ERROR)
        )

        # DONE / ERROR 時停用刪除（可選：DONE 仍允許刪除）
        self._remove_btn.setEnabled(status != JobStatus.CONVERTING)

        # 顯示 / 隱藏完成按鈕
        is_done = (status == JobStatus.DONE)
        self._open_btn.setVisible(is_done)
        self._open_folder_btn.setVisible(is_done)

    def mark_done(self, output_path: Path) -> None:
        """標記任務完成，顯示「開啟」與「開啟資料夾」按鈕。

        Args:
            output_path: 轉換後輸出檔案的絕對路徑。
        """
        self._output_path = output_path
        self.update_status(JobStatus.DONE, f"完成 → {output_path.name}")
        logger.info(
            "file_card[%s]: 任務完成，輸出 %s", self._job_id, output_path
        )

    def mark_error(self, error_message: str) -> None:
        """標記任務失敗，顯示紅色錯誤訊息。

        Args:
            error_message: 人類可讀的錯誤描述，顯示在卡片狀態列。
        """
        # 截斷過長訊息，避免卡片版面破版
        truncated = error_message[:80] + "…" if len(error_message) > 80 else error_message
        self.update_status(JobStatus.ERROR, truncated)
        logger.error(
            "file_card[%s]: 任務失敗 — %s", self._job_id, error_message
        )

    # ------------------------------------------------------------------
    # 舊版相容 API（Round 1 骨架留下的簽名）
    # ------------------------------------------------------------------

    def update_status_from_job(self, job: ConversionJob) -> None:
        """根據最新 ConversionJob 快照完整更新卡片顯示。

        此方法相容 Round 1 骨架的 update_status(job) 呼叫慣例。
        新代碼建議直接呼叫 update_status / update_progress / mark_done / mark_error。

        Args:
            job: 最新的 ConversionJob 快照。
        """
        if job.status == JobStatus.CONVERTING:
            self.update_status(job.status)
            self.update_progress(job.progress)
        elif job.status == JobStatus.DONE and job.output_path is not None:
            self.mark_done(job.output_path)
        elif job.status == JobStatus.ERROR and job.error_message:
            self.mark_error(job.error_message)
        else:
            self.update_status(job.status)

    # ------------------------------------------------------------------
    # 唯讀屬性
    # ------------------------------------------------------------------

    @property
    def job_id(self) -> str:
        """此卡片對應的 job_id（唯讀）。"""
        return self._job_id
