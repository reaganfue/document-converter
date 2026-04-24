"""QuickStatsBar — 首頁頂部快速統計列。

顯示本次 session 的轉換數字：今日加入數、進行中數、已完成數。
由 HomePage 建立並驅動更新，透過 update_counts() 刷新數字顯示。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

logger = logging.getLogger(__name__)

# 品牌紫 accent 色
_ACCENT_COLOR = "#8B5CF6"
_ACCENT_HOVER = "#7C3AED"

# 數字 label 粗體樣式
_NUMBER_STYLE = (
    "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
    f"font-size: 20px; font-weight: 700; color: {_ACCENT_COLOR};"
    "background: transparent;"
)

# 說明文字樣式
_CAPTION_STYLE = (
    "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
    "font-size: 11px; color: #6B7280;"
    "background: transparent;"
)

# 容器外框樣式
_CONTAINER_STYLE = (
    "QWidget#StatsBarContainer {"
    "  background-color: #F9FAFB;"
    "  border: 1px solid #E5E7EB;"
    "  border-radius: 8px;"
    "}"
)


class _StatItem(QWidget):
    """單一統計項：大數字 + 說明文字（垂直排列）。"""

    def __init__(self, icon: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            "font-size: 16px; background: transparent;"
        )
        layout.addWidget(icon_lbl)

        self._number_label = QLabel("0")
        self._number_label.setStyleSheet(_NUMBER_STYLE)
        layout.addWidget(self._number_label)

        caption_lbl = QLabel(label)
        caption_lbl.setStyleSheet(_CAPTION_STYLE)
        layout.addWidget(caption_lbl)

    def set_value(self, value: int) -> None:
        """更新數字顯示值。"""
        self._number_label.setText(str(value))


class StatsBar(QWidget):
    """首頁頂部統計條，顯示今日加入數 / 進行中 / 已完成。

    使用方式：
        bar = StatsBar(parent=home_page)
        bar.update_counts(today=12, in_progress=3, completed=9)

    公開方法：
        update_counts(today, in_progress, completed) — 刷新三欄數字
        reset()                                       — 歸零所有數字
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(48)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """建立三欄統計條 UI。"""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 容器 widget（帶圓角框線）
        container = QWidget()
        container.setObjectName("StatsBarContainer")
        container.setStyleSheet(_CONTAINER_STYLE)

        inner = QHBoxLayout(container)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        self._today_item = _StatItem("📅", "今日")
        self._in_progress_item = _StatItem("⟳", "進行中")
        self._completed_item = _StatItem("✓", "已完成")

        inner.addWidget(self._today_item, stretch=1)
        inner.addWidget(self._build_divider())
        inner.addWidget(self._in_progress_item, stretch=1)
        inner.addWidget(self._build_divider())
        inner.addWidget(self._completed_item, stretch=1)
        inner.addStretch()

        # 查看歷史連結
        self._history_btn = self._build_history_button()
        inner.addWidget(self._history_btn)

        outer.addWidget(container)

    def _build_divider(self) -> QWidget:
        """建立垂直分隔線。"""
        line = QWidget()
        line.setFixedWidth(1)
        line.setStyleSheet("background-color: #E5E7EB;")
        return line

    def _build_history_button(self) -> QPushButton:
        """建立「查看歷史 →」按鈕。"""
        btn = QPushButton("查看歷史 →")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            f"  font-size: 12px; color: {_ACCENT_COLOR};"
            f"  background: transparent; border: none;"
            f"  padding: 0 16px;"
            f"}}"
            f"QPushButton:hover {{ color: {_ACCENT_HOVER}; }}"
        )
        return btn

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def update_counts(self, today: int, in_progress: int, completed: int) -> None:
        """刷新三欄統計數字。

        Args:
            today:       本 session 加入的任務總數。
            in_progress: 當前 CONVERTING 狀態的任務數。
            completed:   已完成（DONE 或 ERROR）的任務數。
        """
        self._today_item.set_value(today)
        self._in_progress_item.set_value(in_progress)
        self._completed_item.set_value(completed)
        logger.debug(
            "StatsBar.update_counts: today=%d in_progress=%d completed=%d",
            today, in_progress, completed,
        )

    def reset(self) -> None:
        """歸零所有統計數字。"""
        self.update_counts(0, 0, 0)

    @property
    def history_button(self) -> QPushButton:
        """查看歷史按鈕（供外部連接 clicked signal）。"""
        return self._history_btn
