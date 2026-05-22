"""Drop Zone Widget — 北歐風重塑版。

設計變更:
    - 三態視覺改用 setProperty("state", ...) 觸發 QSS selector
      （見 desktop/resources/styles.qss 中的 #DropZone[state="..."]）
    - 移除所有 hardcoded 色彩,改由 theme.get_palette() 動態提供
    - icon 從 emoji 改為單色 SVG line art(北歐風)
    - 字型統一使用 theme.FONT_FAMILY
    - 「選擇檔案」改為 PrimaryPushButton(沿用全局 QSS 樣式)
"""
from __future__ import annotations

import logging
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import PrimaryPushButton  # type: ignore[import]
    _HAS_FLUENT = True
except ImportError:
    PrimaryPushButton = QPushButton  # type: ignore[assignment,misc]
    _HAS_FLUENT = False

from desktop.interfaces import DropZoneSignals, SUPPORTED_INPUT_FORMATS
from desktop.utils.theme import FONT_FAMILY, get_palette, theme_bus

logger = logging.getLogger(__name__)

# 北歐風裝飾 SVG 資產
_DECOR_ROOT = Path(__file__).parent.parent / "resources" / "icons" / "decor"
_ICON_HEXAGON = _DECOR_ROOT / "hexagon.svg"

# 三態 property 值(對應 styles.qss 的 [state="..."] selector)
class _VisualState(Enum):
    IDLE = "idle"
    HOVER = "hover"
    DROPPING = "dropping"


_LABEL_IDLE = "拖入檔案開始轉換"
_LABEL_IDLE_SUB = "或點下方按鈕選擇"
_LABEL_HOVER = "放開以加入檔案"
_LABEL_DROPPING = "正在加入..."

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    f".{fmt}" for fmt in SUPPORTED_INPUT_FORMATS
)


class DropZone(QWidget):
    """大面積拖拉區(北歐風重塑版)。

    Signals(透過 self.signals 存取):
        files_dropped(list[Path]): 使用者拖入或選擇的有效檔案路徑清單。
        open_dialog_requested():   使用者點擊「選擇檔案」按鈕。

    視覺三態(透過 setProperty("state", value) + 全局 QSS 切換):
        - idle:     一般態,虛線邊框 + 暖白背景
        - hover:    拖入中,實線邊框 + 強調色淡背景
        - dropping: 放開後 200ms 內,綠色邊框 + 成功淡背景
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = DropZoneSignals()
        self._visual_state = _VisualState.IDLE

        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._setup_ui()
        self._apply_visual_state(_VisualState.IDLE)

        self._drop_reset_timer = QTimer(self)
        self._drop_reset_timer.setSingleShot(True)
        self._drop_reset_timer.setInterval(200)
        self._drop_reset_timer.timeout.connect(self._on_drop_reset_timeout)

        # 主題切換時重新從 palette 套色
        theme_bus.theme_changed.connect(self._refresh_palette)

    def _refresh_palette(self, _mode: str = "") -> None:
        """主題變更時重新套用文字色與當前視覺態樣式。"""
        self._refresh_text_styles()
        self._apply_visual_state(self._visual_state)

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建構主要 UI:SVG icon + 主提示 + 副提示 + 選擇按鈕 + 格式列。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. SVG icon(北歐風六邊形,佔位用 hexagon)
        if _ICON_HEXAGON.exists():
            self._icon = QSvgWidget(str(_ICON_HEXAGON))
            self._icon.setFixedSize(48, 48)
        else:
            self._icon = QLabel("◇")
            self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._icon.setStyleSheet("font-size: 36px; background: transparent;")
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignCenter)

        # 2. 主提示文字
        self._hint_label = QLabel(_LABEL_IDLE)
        self._hint_label.setObjectName("DropZoneHint")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

        # 3. 副提示文字
        self._sub_label = QLabel(_LABEL_IDLE_SUB)
        self._sub_label.setObjectName("DropZoneSubHint")
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub_label)

        # 4. 「選擇檔案」主要按鈕
        layout.addSpacing(4)
        self._select_btn = PrimaryPushButton("選擇檔案")
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setFixedWidth(160)
        self._select_btn.clicked.connect(self._on_select_btn_clicked)
        layout.addWidget(self._select_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 5. 支援格式說明列(極淡)
        formats_text = "支援 " + " · ".join(f.upper() for f in SUPPORTED_INPUT_FORMATS)
        self._formats_label = QLabel(formats_text)
        self._formats_label.setObjectName("DropZoneFormats")
        self._formats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formats_label.setWordWrap(True)
        layout.addWidget(self._formats_label)

        # 套用初始文字樣式
        self._refresh_text_styles()

    def _refresh_text_styles(self) -> None:
        """從 palette 取色套用到三個 QLabel。"""
        palette = get_palette()
        self._hint_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: 16px;"
            f"font-weight: 600;"
            f"color: {palette['text_primary']};"
            "background: transparent;"
        )
        self._sub_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: 13px;"
            f"color: {palette['text_secondary']};"
            "background: transparent;"
        )
        self._formats_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: 11px;"
            f"color: {palette['text_tertiary']};"
            "background: transparent;"
            "letter-spacing: 0.5px;"
        )

    # ------------------------------------------------------------------
    # 視覺狀態機(透過 property + 全局 QSS)
    # ------------------------------------------------------------------

    def _apply_visual_state(self, state: _VisualState) -> None:
        """切換視覺狀態:設定 property + 重新 polish + 更新文字。

        QSS selector `#DropZone[state="idle|hover|dropping"]` 會自動套用對應樣式。
        """
        self._visual_state = state
        self.setProperty("state", state.value)
        # 強制 Qt 重新評估 stylesheet selector
        self.style().unpolish(self)
        self.style().polish(self)

        if state is _VisualState.IDLE:
            self._hint_label.setText(_LABEL_IDLE)
            self._sub_label.setText(_LABEL_IDLE_SUB)
            self._sub_label.show()
        elif state is _VisualState.HOVER:
            self._hint_label.setText(_LABEL_HOVER)
            self._sub_label.hide()
        elif state is _VisualState.DROPPING:
            self._hint_label.setText(_LABEL_DROPPING)
            self._sub_label.hide()

        # 主提示色依狀態微調(其他元素由 QSS 處理)
        palette = get_palette()
        color = {
            _VisualState.IDLE:     palette["text_primary"],
            _VisualState.HOVER:    palette["accent_primary"],
            _VisualState.DROPPING: palette["state_success"],
        }[state]
        self._hint_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: 16px;"
            f"font-weight: 600;"
            f"color: {color};"
            "background: transparent;"
        )

    # ------------------------------------------------------------------
    # 拖拉事件
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_visual_state(_VisualState.HOVER)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._apply_visual_state(_VisualState.IDLE)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
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
                    "drop_zone: 忽略不支援的格式 %s(副檔名 %s)",
                    path.name, path.suffix,
                )

        self._drop_reset_timer.start()

        if valid_paths:
            logger.info("drop_zone: 接受 %d 個檔案", len(valid_paths))
            self.signals.files_dropped.emit(valid_paths)
        else:
            logger.warning("drop_zone: 所有檔案均不支援,已忽略")

    def _on_drop_reset_timeout(self) -> None:
        """200ms 後回復 IDLE 狀態。"""
        self._apply_visual_state(_VisualState.IDLE)

    # ------------------------------------------------------------------
    # 按鈕事件
    # ------------------------------------------------------------------

    def _on_select_btn_clicked(self) -> None:
        logger.debug("drop_zone: 使用者點擊「選擇檔案」")
        self.signals.open_dialog_requested.emit()

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def get_supported_extensions(self) -> list[str]:
        """回傳帶星號的副檔名清單(供 QFileDialog filter 使用)。"""
        return [f"*.{fmt}" for fmt in SUPPORTED_INPUT_FORMATS]

    def build_file_dialog_filter(self) -> str:
        """建構 QFileDialog 用的格式過濾字串。"""
        extensions = " ".join(self.get_supported_extensions())
        return f"支援的格式 ({extensions})"
