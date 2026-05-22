"""File Card Widget — 北歐風重塑版。

每個 ConversionJob 對應一張 FileCard,顯示在佇列區。

設計變更:
    - 移除所有 hardcoded 色彩,改由 theme.get_palette() 動態提供
    - FormatBadge 由「濃色背景 + 白字」改為「淡色背景 + 深字」(北歐風克制)
    - 卡片邊框 1px 細 + 12px 圓角,無強陰影
    - 移除 emoji 圖示,改用 qfluentwidgets.FluentIcon 或極簡文字
    - 字型統一 theme.FONT_FAMILY
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

try:
    from qfluentwidgets import (
        ComboBox as FluentComboBox,
        FluentIcon,
        PushButton as FluentPushButton,
        ToolButton as FluentToolButton,
    )
    _HAS_FLUENT = True
except ImportError:
    FluentComboBox = QComboBox  # type: ignore[assignment,misc]
    FluentPushButton = QPushButton  # type: ignore[assignment,misc]
    FluentToolButton = QPushButton  # type: ignore[assignment,misc]
    FluentIcon = None  # type: ignore[assignment]
    _HAS_FLUENT = False

from desktop.interfaces import (
    ConversionJob,
    FileCardSignals,
    JobStatus,
    get_supported_targets,
)
from desktop.utils.theme import FONT_FAMILY, get_palette, theme_bus

logger = logging.getLogger(__name__)

# 狀態對應文字
_STATUS_TEXT: dict[JobStatus, str] = {
    JobStatus.IDLE:       "待轉換",
    JobStatus.PENDING:    "等候中",
    JobStatus.CONVERTING: "轉換中",
    JobStatus.DONE:       "完成",
    JobStatus.ERROR:      "失敗",
}


def _badge_colors_for(fmt: str) -> tuple[str, str]:
    """從當前主題 palette 取得格式徽章的 (背景, 文字) 色。

    Args:
        fmt: 格式代碼(小寫無點),例如 "pdf"。

    Returns:
        (background_color, foreground_color) 兩個 hex 字串。
    """
    palette = get_palette()
    bg = palette.get(f"fmt_{fmt.lower()}_bg", palette["fmt_default_bg"])
    fg = palette.get(f"fmt_{fmt.lower()}_fg", palette["fmt_default_fg"])
    return bg, fg


def _status_color_for(status: JobStatus) -> str:
    """從當前主題 palette 取得狀態色。"""
    palette = get_palette()
    return {
        JobStatus.IDLE:       palette["text_tertiary"],
        JobStatus.PENDING:    palette["text_tertiary"],
        JobStatus.CONVERTING: palette["accent_primary"],
        JobStatus.DONE:       palette["state_success"],
        JobStatus.ERROR:      palette["state_danger"],
    }.get(status, palette["text_tertiary"])


class _FormatBadge(QLabel):
    """56×56 的格式徽章 — 淡色背景配深字(北歐風)。"""

    def __init__(self, fmt: str, parent: QWidget | None = None) -> None:
        super().__init__(fmt.upper(), parent)
        self._fmt = fmt.lower()
        self.setFixedSize(56, 56)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_style()

    def _refresh_style(self) -> None:
        """從 palette 取色重新套用樣式(主題切換時可重呼叫)。"""
        bg, fg = _badge_colors_for(self._fmt)
        self.setStyleSheet(
            "QLabel {"
            f"  background-color: {bg};"
            f"  color: {fg};"
            f"  font-family: {FONT_FAMILY};"
            "  font-size: 12px;"
            "  font-weight: 700;"
            "  letter-spacing: 0.5px;"
            "  border-radius: 10px;"
            "  border: none;"
            "}"
        )


class FileCard(QFrame):
    """單一轉換任務的卡片式顯示元件(北歐風重塑版)。

    Args:
        job: 此卡片代表的 ConversionJob。
        parent: 父 Widget。

    Signals(透過 self.signals 存取):
        remove_requested(str):              job_id
        target_format_changed(str, str):    job_id, target_format

    公開更新方法:
        update_progress(progress)       — 0.0-1.0 進度值
        update_status(status, message)  — 狀態切換 + 可選附加文字
        mark_done(output_path)          — 標記完成,顯示「開啟」按鈕
        mark_error(error_message)       — 標記失敗,顯示錯誤訊息
    """

    def __init__(self, job: ConversionJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = FileCardSignals()
        self._job_id: str = job.job_id
        self._source_format: str = job.source_format
        self._output_path: Path | None = None

        self.setObjectName("FileCard")
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 卡片背景與邊框由全局 styles.qss 處理(QFrame#FileCard selector)

        self._setup_ui(job)
        self._connect_signals()
        self.update_status(job.status)

        # 主題切換時重新套色
        theme_bus.theme_changed.connect(self._refresh_palette)

    def _refresh_palette(self, _mode: str = "") -> None:
        """主題變更時重新套用所有依賴 palette 的內嵌樣式。"""
        try:
            self._badge._refresh_style()
        except Exception:
            pass
        self._refresh_progress_style()

        palette = get_palette()
        self._filename_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            "font-size: 14px;"
            "font-weight: 600;"
            f"color: {palette['text_primary']};"
            "background: transparent;"
        )
        # 重新套 remove 按鈕色
        self._remove_btn.setStyleSheet(
            "QPushButton {"
            "  font-size: 14px;"
            f"  color: {palette['text_tertiary']};"
            "  background-color: transparent;"
            "  border: none;"
            "  border-radius: 14px;"
            "}"
            "QPushButton:hover {"
            f"  color: {palette['state_danger']};"
            f"  background-color: {palette['state_danger_bg']};"
            "}"
        )
        # 狀態 label 透過 update_status 處理
        # 透過 update_status 重新套狀態色(根據目前文字推測 status)
        # 簡單方案:重新觸發 update_status 為當前推測態,代價極小
        # 取得目前進度態的 cur status 沒有暴露,所以這裡只更新基礎色
        if not self._progress_bar.isVisible():
            self._status_label.setStyleSheet(
                f"font-family: {FONT_FAMILY};"
                "font-size: 12px;"
                f"color: {palette['text_tertiary']};"
                "background: transparent;"
            )

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _setup_ui(self, job: ConversionJob) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(14)

        self._badge = _FormatBadge(job.source_format)
        outer.addWidget(self._badge)
        outer.addWidget(self._build_center_column(job))
        outer.addWidget(self._build_right_panel(job))

    def _build_center_column(self, job: ConversionJob) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        palette = get_palette()

        self._filename_label = QLabel(job.source_path.name)
        self._filename_label.setToolTip(str(job.source_path))
        self._filename_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._filename_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            "font-size: 14px;"
            "font-weight: 600;"
            f"color: {palette['text_primary']};"
            "background: transparent;"
        )
        layout.addWidget(self._filename_label)
        layout.addLayout(self._build_status_row())
        return widget

    def _build_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        palette = get_palette()

        self._status_label = QLabel(_STATUS_TEXT[JobStatus.IDLE])
        self._status_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            "font-size: 12px;"
            f"color: {palette['text_tertiary']};"
            "background: transparent;"
        )
        row.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._refresh_progress_style()
        row.addWidget(self._progress_bar)
        return row

    def _refresh_progress_style(self) -> None:
        palette = get_palette()
        self._progress_bar.setStyleSheet(
            "QProgressBar {"
            f"  background-color: {palette['border_subtle']};"
            "  border-radius: 2px;"
            "  border: none;"
            "}"
            "QProgressBar::chunk {"
            f"  background-color: {palette['accent_primary']};"
            "  border-radius: 2px;"
            "}"
        )

    def _build_right_panel(self, job: ConversionJob) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._build_format_combo(job))
        layout.addWidget(self._build_open_btn())
        layout.addWidget(self._build_open_folder_btn())
        layout.addWidget(self._build_remove_btn())
        return widget

    def _build_format_combo(self, job: ConversionJob) -> QComboBox:
        """目標格式下拉,讓 QSS 接手主要樣式。"""
        if _HAS_FLUENT:
            self._format_combo = FluentComboBox()
        else:
            self._format_combo = QComboBox()
        self._format_combo.setFixedWidth(88)
        self._format_combo.setFixedHeight(32)
        targets = get_supported_targets(job.source_format)
        self._format_combo.addItems([fmt.upper() for fmt in targets])
        lower_targets = [fmt.lower() for fmt in targets]
        if job.target_format.lower() in lower_targets:
            self._format_combo.setCurrentIndex(lower_targets.index(job.target_format.lower()))
        return self._format_combo

    def _build_open_btn(self) -> QPushButton:
        """完成後顯示的「開啟」按鈕。"""
        self._open_btn = FluentPushButton("開啟") if _HAS_FLUENT else QPushButton("開啟")
        self._open_btn.setFixedSize(64, 32)
        self._open_btn.setVisible(False)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self._on_open_file)
        return self._open_btn

    def _build_open_folder_btn(self) -> QPushButton:
        """「開啟資料夾」按鈕,用 FluentIcon.FOLDER 取代 📂 emoji。"""
        if _HAS_FLUENT and FluentIcon is not None:
            self._open_folder_btn = FluentToolButton(FluentIcon.FOLDER)
        else:
            self._open_folder_btn = QPushButton("…")
        self._open_folder_btn.setFixedSize(32, 32)
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_folder_btn.setToolTip("開啟所在資料夾")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        return self._open_folder_btn

    def _build_remove_btn(self) -> QPushButton:
        """刪除按鈕(✕ 為通用 unicode 符號,非 emoji)。"""
        palette = get_palette()
        self._remove_btn = QPushButton("✕")
        self._remove_btn.setFixedSize(28, 28)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setToolTip("移除此任務")
        self._remove_btn.setStyleSheet(
            "QPushButton {"
            "  font-size: 14px;"
            f"  color: {palette['text_tertiary']};"
            "  background-color: transparent;"
            "  border: none;"
            "  border-radius: 14px;"
            "}"
            "QPushButton:hover {"
            f"  color: {palette['state_danger']};"
            f"  background-color: {palette['state_danger_bg']};"
            "}"
        )
        return self._remove_btn

    # ------------------------------------------------------------------
    # Signal 連接
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        self._remove_btn.clicked.connect(self._on_remove_clicked)

    def _on_format_changed(self, text: str) -> None:
        new_format = text.lower()
        logger.debug("file_card[%s]: 目標格式切換為 %s", self._job_id, new_format)
        self.signals.target_format_changed.emit(self._job_id, new_format)

    def _on_remove_clicked(self) -> None:
        logger.debug("file_card[%s]: 使用者點擊刪除", self._job_id)
        self.signals.remove_requested.emit(self._job_id)

    # ------------------------------------------------------------------
    # 開啟檔案 / 資料夾
    # ------------------------------------------------------------------

    def _on_open_file(self) -> None:
        if self._output_path is None or not self._output_path.exists():
            logger.warning("file_card[%s]: 輸出檔案不存在", self._job_id)
            return
        try:
            if sys.platform == "win32":
                os.startfile(self._output_path)
            else:
                subprocess.run(["xdg-open", str(self._output_path)], check=False)
        except OSError as exc:
            logger.error("file_card[%s]: 無法開啟檔案 %s — %s",
                         self._job_id, self._output_path, exc)

    def _on_open_folder(self) -> None:
        if self._output_path is None:
            return
        try:
            if sys.platform == "win32":
                target = self._output_path.resolve()
                if target.exists():
                    subprocess.run(
                        ["explorer", f"/select,{target}"],
                        check=False, shell=False,
                    )
                else:
                    subprocess.run(
                        ["explorer", str(target.parent)],
                        check=False, shell=False,
                    )
            else:
                subprocess.run(
                    ["xdg-open", str(self._output_path.parent)],
                    check=False,
                )
        except OSError as exc:
            logger.error("file_card[%s]: 無法開啟資料夾 %s — %s",
                         self._job_id, self._output_path.parent, exc)

    # ------------------------------------------------------------------
    # 公開更新 API
    # ------------------------------------------------------------------

    def update_progress(self, progress: float) -> None:
        """更新進度條顯示。"""
        clamped = max(0.0, min(1.0, progress))
        percent = int(clamped * 100)
        self._progress_bar.setValue(percent)
        self._status_label.setText(f"轉換中 {percent}%")

    def update_status(self, status: JobStatus, message: str = "") -> None:
        """切換卡片顯示狀態。"""
        color = _status_color_for(status)
        base_text = message or _STATUS_TEXT.get(status, status.value)

        self._status_label.setText(base_text)
        self._status_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            "font-size: 12px;"
            f"color: {color};"
            "background: transparent;"
        )

        show_progress = (status == JobStatus.CONVERTING)
        self._progress_bar.setVisible(show_progress)
        if not show_progress:
            self._progress_bar.setValue(0)

        self._format_combo.setEnabled(
            status not in (JobStatus.CONVERTING, JobStatus.DONE, JobStatus.ERROR)
        )

        self._remove_btn.setEnabled(status != JobStatus.CONVERTING)

        is_done = (status == JobStatus.DONE)
        self._open_btn.setVisible(is_done)
        self._open_folder_btn.setVisible(is_done)

    def mark_done(self, output_path: Path) -> None:
        """標記任務完成,顯示「開啟」與「開啟資料夾」按鈕。"""
        self._output_path = output_path
        self.update_status(JobStatus.DONE, f"完成 → {output_path.name}")
        logger.info("file_card[%s]: 任務完成,輸出 %s", self._job_id, output_path)

    def mark_error(self, error_message: str) -> None:
        """標記任務失敗,顯示紅色錯誤訊息。"""
        truncated = error_message[:80] + "…" if len(error_message) > 80 else error_message
        self.update_status(JobStatus.ERROR, truncated)
        logger.error("file_card[%s]: 任務失敗 — %s", self._job_id, error_message)

    # ------------------------------------------------------------------
    # 舊版相容 API
    # ------------------------------------------------------------------

    def update_status_from_job(self, job: ConversionJob) -> None:
        """根據最新 ConversionJob 快照完整更新卡片顯示(向下相容)。"""
        if job.status == JobStatus.CONVERTING:
            self.update_status(job.status)
            self.update_progress(job.progress)
        elif job.status == JobStatus.DONE and job.output_path is not None:
            self.mark_done(job.output_path)
        elif job.status == JobStatus.ERROR and job.error_message:
            self.mark_error(job.error_message)
        else:
            self.update_status(job.status)

    @property
    def job_id(self) -> str:
        """此卡片對應的 job_id(唯讀)。"""
        return self._job_id
