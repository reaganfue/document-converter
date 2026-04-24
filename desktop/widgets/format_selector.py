"""Format Selector Widget — 批次目標格式選擇器。

頂部工具列元件：讓使用者一鍵指定佇列中所有「未開始」任務的目標格式。
注意：單檔格式切換屬 FileCard 範疇（widgets-1），本 widget 僅處理批次套用。

佈局（水平）：
    批次目標格式：[PDF ▼]  [套用到全部]

Signals（透過 self.signals 存取）：
    format_selected(str): 使用者按「套用到全部」後發射，值為小寫無點格式字串。
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Qt

try:
    from qfluentwidgets import ComboBox, PushButton, BodyLabel
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import QComboBox, QPushButton, QLabel as BodyLabel  # type: ignore[assignment]
    _HAS_FLUENT = False

from desktop.interfaces import FormatSelectorSignals, SUPPORTED_OUTPUT_FORMATS

# 顯示用大寫標籤
_FORMAT_DISPLAY: dict[str, str] = {fmt: fmt.upper() for fmt in SUPPORTED_OUTPUT_FORMATS}
_DEFAULT_FORMAT = "pdf"


class FormatSelector(QWidget):
    """批次目標格式選擇器（頂部工具列）。

    提供整批套用格式功能，點擊「套用到全部」後才發射 format_selected signal，
    讓 MainWindow 把所有未開始的 FileCard 目標格式統一設定。

    Signals（透過 self.signals 存取）：
        format_selected(str): 小寫無點格式字串（例如 "pdf"）。

    公開屬性：
        current_format (str): 目前 ComboBox 選中的格式（唯讀 property）。

    公開方法：
        set_format(fmt): 程式化設定 ComboBox 選中項（不發射 signal）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = FormatSelectorSignals()
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 建立
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建立批次格式選擇器 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 左側標籤
        if _HAS_FLUENT:
            label = BodyLabel("批次目標格式：")
        else:
            label = BodyLabel("批次目標格式：")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)

        # 格式下拉選單
        self._combo = self._build_combo()
        self._combo.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self._combo)

        # 套用到全部按鈕
        self._apply_btn = self._build_apply_button()
        layout.addWidget(self._apply_btn)

        layout.addStretch()

    def _build_combo(self):
        """建立格式下拉選單，填充 SUPPORTED_OUTPUT_FORMATS。"""
        if _HAS_FLUENT:
            combo = ComboBox()
        else:
            from PySide6.QtWidgets import QComboBox
            combo = QComboBox()

        for fmt in SUPPORTED_OUTPUT_FORMATS:
            display = _FORMAT_DISPLAY.get(fmt, fmt.upper())
            combo.addItem(display, userData=fmt)

        # 預設選中 PDF
        default_idx = self._find_combo_index(combo, _DEFAULT_FORMAT)
        if default_idx >= 0:
            combo.setCurrentIndex(default_idx)

        return combo

    def _build_apply_button(self):
        """建立「套用到全部」按鈕。"""
        if _HAS_FLUENT:
            btn = PushButton("套用到全部")
        else:
            from PySide6.QtWidgets import QPushButton
            btn = QPushButton("套用到全部")

        btn.clicked.connect(self._on_apply_clicked)
        return btn

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_apply_clicked(self) -> None:
        """使用者點擊「套用到全部」，發射 format_selected signal。"""
        self.signals.format_selected.emit(self.current_format)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _find_combo_index(combo, fmt: str) -> int:
        """在 combo 中尋找 userData == fmt 的索引，找不到回傳 -1。"""
        for i in range(combo.count()):
            if combo.itemData(i) == fmt:
                return i
        return -1

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    @property
    def current_format(self) -> str:
        """回傳當前選中的格式（小寫無點，例如 "pdf"）。"""
        data = self._combo.currentData()
        if data:
            return str(data).lower()
        return self._combo.currentText().lower()

    def set_format(self, fmt: str) -> None:
        """程式化設定 ComboBox 選中項（不發射 format_selected signal）。

        Args:
            fmt: 目標格式字串，小寫無點（例如 "pdf"）。
                 若不在支援清單中則忽略。
        """
        idx = self._find_combo_index(self._combo, fmt.lower())
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
