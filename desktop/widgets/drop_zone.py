"""Drop Zone Widget — Round 2（widgets-1）實作主體。

Round 2 職責（widgets-1 代理）：
    - 實作 dragEnterEvent / dragMoveEvent / dropEvent（過濾支援格式）
    - 視覺狀態機：idle / hover / dropping（邊框 + 背景色變化）
    - 點擊區域觸發 QFileDialog，發出 open_dialog_requested Signal
    - 解析拖入的 URL 清單為 Path 清單，過濾不支援格式後發出 files_dropped
    - 使用 SUPPORTED_INPUT_FORMATS 進行過濾

信任假設（Round 2 可依賴）：
    - interfaces.DropZoneSignals 的 Signal 簽名不會改變
    - interfaces.SUPPORTED_INPUT_FORMATS 是過濾依據
"""
from __future__ import annotations

import logging
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop.interfaces import DropZoneSignals, SUPPORTED_INPUT_FORMATS

logger = logging.getLogger(__name__)


class _VisualState(Enum):
    """DropZone 三態視覺狀態機。"""
    IDLE = auto()
    HOVER = auto()
    DROPPING = auto()


# QSS 樣式常數 — 每個狀態對應一個字串模板
_STYLE_IDLE = (
    "QWidget#DropZone {"
    "  border: 2px dashed #D1D5DB;"
    "  border-radius: 12px;"
    "  background-color: #F9FAFB;"
    "}"
)

_STYLE_HOVER = (
    "QWidget#DropZone {"
    "  border: 2px dashed #8B5CF6;"
    "  border-radius: 12px;"
    "  background-color: #F5F3FF;"
    "}"
)

_STYLE_DROPPING = (
    "QWidget#DropZone {"
    "  border: 2px solid #10B981;"
    "  border-radius: 12px;"
    "  background-color: #ECFDF5;"
    "}"
)

_LABEL_IDLE = "⬆  拖拉檔案到此處\n或按 Ctrl+O 選擇"
_LABEL_HOVER = "放開以加入檔案"
_LABEL_DROPPING = "正在加入..."

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    f".{fmt}" for fmt in SUPPORTED_INPUT_FORMATS
)


class DropZone(QWidget):
    """大面積拖拉區（Round 3 整合後佔主視窗約 70% 高度）。

    Signals（透過 self.signals 存取）：
        files_dropped(list[Path]):    使用者拖入或選擇的有效檔案路徑清單。
        open_dialog_requested():      使用者點擊「選擇檔案」按鈕。

    視覺規格（Round 2 實作）：
        - idle:     border 2px dashed #D1D5DB，背景 #F9FAFB
        - hover:    border 2px dashed #8B5CF6，背景 #F5F3FF
        - dropping: border 2px solid #10B981，背景 #ECFDF5（200ms 後回 idle）
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = DropZoneSignals()
        self._visual_state = _VisualState.IDLE

        # 基本屬性
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._setup_ui()
        self._apply_visual_state(_VisualState.IDLE)

        # dropping 狀態的復原計時器（200ms）
        self._drop_reset_timer = QTimer(self)
        self._drop_reset_timer.setSingleShot(True)
        self._drop_reset_timer.setInterval(200)
        self._drop_reset_timer.timeout.connect(self._on_drop_reset_timeout)

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建構主要 UI 佈局：圖示 + 提示文字 + 選擇檔案按鈕。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._build_icon_label())
        layout.addWidget(self._build_hint_label())
        layout.addWidget(self._build_formats_label())
        layout.addWidget(self._build_select_btn(), alignment=Qt.AlignmentFlag.AlignCenter)

    def _build_icon_label(self) -> QLabel:
        """建立大型圖示 Label。"""
        icon_label = QLabel("📁")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(
            "font-size: 48px; background: transparent; border: none;"
        )
        return icon_label

    def _build_hint_label(self) -> QLabel:
        """建立主提示文字 Label（可在狀態切換時更新文字）。"""
        self._hint_label = QLabel(_LABEL_IDLE)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setStyleSheet(
            "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "font-size: 15px; color: #6B7280; background: transparent; border: none;"
        )
        return self._hint_label

    def _build_formats_label(self) -> QLabel:
        """建立支援格式說明 Label。"""
        formats_text = "支援格式：" + "  ".join(
            f.upper() for f in SUPPORTED_INPUT_FORMATS
        )
        label = QLabel(formats_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(
            "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "font-size: 11px; color: #9CA3AF; background: transparent; border: none;"
        )
        return label

    def _build_select_btn(self) -> QPushButton:
        """建立「選擇檔案」按鈕並連接事件。"""
        self._select_btn = QPushButton("選擇檔案")
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setFixedHeight(36)
        self._select_btn.setMaximumWidth(160)
        self._select_btn.setStyleSheet(
            "QPushButton {"
            "  font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
            "  font-size: 13px; font-weight: 600; color: white;"
            "  background-color: #8B5CF6; border: none; border-radius: 6px; padding: 0 20px;"
            "}"
            "QPushButton:hover { background-color: #7C3AED; }"
            "QPushButton:pressed { background-color: #6D28D9; }"
        )
        self._select_btn.clicked.connect(self._on_select_btn_clicked)
        return self._select_btn

    # ------------------------------------------------------------------
    # 視覺狀態機
    # ------------------------------------------------------------------

    def _apply_visual_state(self, state: _VisualState) -> None:
        """切換視覺狀態，更新 QSS 樣式與提示文字。"""
        self._visual_state = state

        if state == _VisualState.IDLE:
            self.setStyleSheet(_STYLE_IDLE)
            self._hint_label.setText(_LABEL_IDLE)
            self._hint_label.setStyleSheet(
                "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
                "font-size: 15px; color: #6B7280; background: transparent; border: none;"
            )
        elif state == _VisualState.HOVER:
            self.setStyleSheet(_STYLE_HOVER)
            self._hint_label.setText(_LABEL_HOVER)
            self._hint_label.setStyleSheet(
                "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
                "font-size: 15px; color: #8B5CF6; background: transparent; border: none;"
            )
        elif state == _VisualState.DROPPING:
            self.setStyleSheet(_STYLE_DROPPING)
            self._hint_label.setText(_LABEL_DROPPING)
            self._hint_label.setStyleSheet(
                "font-family: 'Segoe UI Variable', '微軟正黑體', sans-serif;"
                "font-size: 15px; color: #10B981; background: transparent; border: none;"
            )

    # ------------------------------------------------------------------
    # 拖拉事件
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """接受含有本地檔案 URL 的拖拉操作。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_visual_state(_VisualState.HOVER)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        """持續接受拖拉移動，維持 HOVER 視覺。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        """拖拉離開視窗，回復 IDLE 狀態。"""
        self._apply_visual_state(_VisualState.IDLE)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """處理放下事件：解析路徑、過濾格式、發射 Signal。"""
        event.acceptProposedAction()
        self._apply_visual_state(_VisualState.DROPPING)

        valid_paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in _SUPPORTED_EXTENSIONS:
                valid_paths.append(path)
            else:
                logger.debug(
                    "drop_zone: 忽略不支援的格式 %s（副檔名 %s）",
                    path.name,
                    path.suffix,
                )

        # 啟動 200ms 回復計時器
        self._drop_reset_timer.start()

        if valid_paths:
            logger.info(
                "drop_zone: 接受 %d 個檔案，發射 files_dropped", len(valid_paths)
            )
            self.signals.files_dropped.emit(valid_paths)
        else:
            logger.warning("drop_zone: 拖入的所有檔案均不是支援的格式，已忽略")

    def _on_drop_reset_timeout(self) -> None:
        """200ms 計時結束，回復 IDLE 狀態。"""
        self._apply_visual_state(_VisualState.IDLE)

    # ------------------------------------------------------------------
    # 按鈕事件
    # ------------------------------------------------------------------

    def _on_select_btn_clicked(self) -> None:
        """「選擇檔案」按鈕點擊：發射 open_dialog_requested。"""
        logger.debug("drop_zone: 使用者點擊「選擇檔案」，發射 open_dialog_requested")
        self.signals.open_dialog_requested.emit()

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def get_supported_extensions(self) -> list[str]:
        """回傳帶點的副檔名清單（供 QFileDialog filter 使用）。

        例：['*.pdf', '*.docx', '*.png', ...]
        """
        return [f"*.{fmt}" for fmt in SUPPORTED_INPUT_FORMATS]

    def build_file_dialog_filter(self) -> str:
        """建構 QFileDialog 用的格式過濾字串。

        Returns:
            例：'支援的格式 (*.pdf *.docx *.png ...)'
        """
        extensions = " ".join(self.get_supported_extensions())
        return f"支援的格式 ({extensions})"
