"""Progress Widget — 全局進度顯示（底部狀態列）。

顯示整批轉換任務的整體進度，不負責單檔進度（單檔進度由 FileCard 負責）。

佈局（水平）：
    轉換中：3/5 檔案  [████████░░░░░░░ 60%]  [取消全部]

狀態行為：
    idle     — 整個 widget 隱藏
    running  — 顯示進度條 + 統計文字 + 取消按鈕
    done     — 綠色「全部完成 ✓」，3 秒後自動隱藏
    cancelled — 橘色「已取消」，3 秒後自動隱藏

Signals（透過 self.signals 存取）：
    cancel_requested(str): job_id 為空字串代表取消全部。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QProgressBar, QSizePolicy
from PySide6.QtCore import Qt, QTimer

try:
    from qfluentwidgets import ProgressBar, PushButton, BodyLabel, InfoBar, InfoBarPosition
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import QPushButton, QLabel as BodyLabel  # type: ignore[assignment]
    ProgressBar = QProgressBar  # type: ignore[misc]
    _HAS_FLUENT = False

from desktop.interfaces import ProgressWidgetSignals

# 完成/取消訊息停留時間（毫秒）
_MESSAGE_LINGER_MS = 3000

# 狀態對應樣式（純 Qt fallback）
_STATE_STYLE: dict[str, str] = {
    "done":      "color: #16a34a; font-weight: bold;",  # 綠色
    "cancelled": "color: #ea580c; font-weight: bold;",  # 橘色
    "running":   "",
    "idle":      "",
}


class ProgressWidget(QWidget):
    """全局進度顯示 Widget（放置於主視窗底部狀態列）。

    Signals（透過 self.signals 存取）：
        cancel_requested(str): 空字串代表取消全部任務。

    公開方法：
        set_total(total)                 — 初始化任務總數
        update(completed, in_progress_progress) — 更新進度
        set_state(state)                 — 切換顯示狀態
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = ProgressWidgetSignals()

        self._total: int = 0
        self._completed: int = 0
        self._state: str = "idle"

        self._linger_timer = QTimer(self)
        self._linger_timer.setSingleShot(True)
        self._linger_timer.timeout.connect(self.hide)

        self._setup_ui()
        self.hide()  # 初始隱藏

    # ------------------------------------------------------------------
    # UI 建立
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建立水平佈局的進度顯示 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        # 統計文字標籤
        self._stats_label = self._make_label("準備就緒")
        self._stats_label.setMinimumWidth(160)
        layout.addWidget(self._stats_label)

        # 進度條
        self._progress_bar = self._make_progress_bar()
        self._progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self._progress_bar)

        # 百分比文字
        self._pct_label = self._make_label("0%")
        self._pct_label.setMinimumWidth(40)
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._pct_label)

        # 取消全部按鈕
        self._cancel_btn = self._make_cancel_button()
        layout.addWidget(self._cancel_btn)

    def _make_label(self, text: str):
        """建立標籤元件。"""
        if _HAS_FLUENT:
            label = BodyLabel(text)
        else:
            label = BodyLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        return label

    def _make_progress_bar(self):
        """建立進度條元件。"""
        if _HAS_FLUENT:
            bar = ProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
        else:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
        return bar

    def _make_cancel_button(self):
        """建立「取消全部」按鈕。"""
        if _HAS_FLUENT:
            btn = PushButton("取消全部")
        else:
            from PySide6.QtWidgets import QPushButton
            btn = QPushButton("取消全部")
        btn.clicked.connect(self._on_cancel_clicked)
        return btn

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_cancel_clicked(self) -> None:
        """使用者點擊「取消全部」，job_id 空字串代表取消所有任務。"""
        self.signals.cancel_requested.emit("")

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def set_total(self, total: int) -> None:
        """初始化任務總數。

        Args:
            total: 本批次任務總數（正整數）。
        """
        self._total = max(0, total)
        self._completed = 0
        self._refresh_display(0)

    def update(  # noqa: A003
        self,
        completed: int,
        in_progress_progress: float = 0.0,
    ) -> None:
        """更新完成計數與當前進行中任務的進度。

        整體進度計算：
            pct = (completed + in_progress_progress) / total * 100

        Args:
            completed: 已完成（DONE 或 ERROR）的任務數。
            in_progress_progress: 當前正在執行任務的進度（0.0–1.0）。
        """
        self._completed = max(0, completed)
        if self._total > 0:
            raw = (self._completed + max(0.0, min(1.0, in_progress_progress))) / self._total
            pct = int(min(raw * 100, 100))
        else:
            pct = 0
        self._refresh_display(pct)

    def set_state(self, state: str) -> None:
        """切換 widget 顯示狀態。

        Args:
            state: "idle" | "running" | "done" | "cancelled"
        """
        self._state = state
        self._linger_timer.stop()

        if state == "idle":
            self.hide()
            return

        self.show()
        self._cancel_btn.setVisible(state == "running")

        if state == "running":
            self._stats_label.setStyleSheet("")
        elif state == "done":
            self._stats_label.setText("全部完成 ✓")
            self._stats_label.setStyleSheet(_STATE_STYLE["done"])
            self._progress_bar.setValue(100)
            self._pct_label.setText("100%")
            self._linger_timer.start(_MESSAGE_LINGER_MS)
        elif state == "cancelled":
            self._stats_label.setText("已取消")
            self._stats_label.setStyleSheet(_STATE_STYLE["cancelled"])
            self._linger_timer.start(_MESSAGE_LINGER_MS)
        else:
            # 未知狀態視同 idle
            self.hide()

    # ------------------------------------------------------------------
    # 內部更新
    # ------------------------------------------------------------------

    def _refresh_display(self, pct: int) -> None:
        """根據當前計數和百分比更新 UI 元素。

        Args:
            pct: 整體進度百分比（0–100）。
        """
        self._progress_bar.setValue(pct)
        self._pct_label.setText(f"{pct}%")
        if self._state == "running":
            self._stats_label.setText(
                f"轉換中：{self._completed}/{self._total} 檔案"
            )
            self._stats_label.setStyleSheet("")
