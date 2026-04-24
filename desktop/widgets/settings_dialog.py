"""Settings Dialog — 應用程式設定對話框（Ctrl+, 開啟）。

Modal QDialog，提供四項設定：
    1. 預設輸出目錄（QLineEdit + 瀏覽按鈕）
    2. 自動覆寫同名檔案（CheckBox）
    3. 同時轉換數（SpinBox，1–8）
    4. 主題（ComboBox：跟隨系統 / 亮色 / 暗色）

設定持久化：使用 QSettings("DocConverter", "DocConverter")
             __init__ 時讀取既有設定；套用時寫回。

Signals（透過 self.signals 存取）：
    settings_applied(dict): 使用者按「套用」後發射，包含四項設定。

dict 結構：
    {
        "output_dir": str,    # 輸出資料夾絕對路徑
        "overwrite": bool,    # 同名覆寫
        "concurrent": int,    # 並行任務數（1–8）
        "theme": str          # "system" | "light" | "dark"
    }
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSettings

try:
    from qfluentwidgets import (
        CheckBox,
        ComboBox,
        LineEdit,
        PushButton,
        SpinBox,
        SubtitleLabel,
        BodyLabel,
        Dialog,
    )
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import (  # type: ignore[assignment]
        QCheckBox as CheckBox,
        QComboBox as ComboBox,
        QLineEdit as LineEdit,
        QPushButton as PushButton,
        QSpinBox as SpinBox,
        QLabel as SubtitleLabel,
        QLabel as BodyLabel,
    )
    _HAS_FLUENT = False

from desktop.interfaces import SettingsDialogSignals
from desktop.utils.paths import get_default_output_dir

# QSettings 組織 / 應用名稱（需與 QApplication 設定一致）
_ORG_NAME = "DocConverter"
_APP_NAME = "DocConverter"

# 預設設定值
_DEFAULTS: dict = {
    "output_dir": "",    # 空字串代表使用 get_default_output_dir()
    "overwrite":  False,
    "concurrent": 3,
    "theme":      "system",
}

# 主題下拉選項：(userData, displayText)
_THEME_OPTIONS: list[tuple[str, str]] = [
    ("system", "跟隨系統"),
    ("light",  "亮色"),
    ("dark",   "暗色"),
]


class SettingsDialog(QDialog):
    """應用程式設定對話框（Ctrl+, 開啟，Modal）。

    Signals（透過 self.signals 存取）：
        settings_applied(dict): 使用者按「套用」後發射完整設定字典。

    使用方式：
        dlg = SettingsDialog(parent=self)
        dlg.signals.settings_applied.connect(controller.apply_settings)
        dlg.exec()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = SettingsDialogSignals()

        self.setWindowTitle("設定")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.resize(520, 360)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._settings = QSettings(_ORG_NAME, _APP_NAME)
        self._setup_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI 建立
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """建立設定對話框 UI（QFormLayout + 底部按鈕）。"""
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(24, 20, 24, 16)

        # 標題
        title = SubtitleLabel("設定")
        if hasattr(title, "setAlignment"):
            title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(title)

        # 表單主體
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # 1. 輸出目錄
        dir_row = self._build_dir_row()
        form.addRow(BodyLabel("預設輸出目錄："), dir_row)

        # 2. 自動覆寫
        self._overwrite_check = CheckBox("自動覆寫同名檔案")
        form.addRow("", self._overwrite_check)

        # 3. 同時轉換數
        self._concurrent_spin = SpinBox()
        self._concurrent_spin.setRange(1, 8)
        self._concurrent_spin.setValue(_DEFAULTS["concurrent"])
        self._concurrent_spin.setFixedWidth(80)
        form.addRow(BodyLabel("同時轉換數："), self._concurrent_spin)

        # 4. 主題
        self._theme_combo = ComboBox()
        for value, display in _THEME_OPTIONS:
            self._theme_combo.addItem(display, userData=value)
        form.addRow(BodyLabel("主題："), self._theme_combo)

        root.addLayout(form)
        root.addStretch()

        # 底部按鈕
        root.addLayout(self._build_button_row())

    def _build_dir_row(self) -> QWidget:
        """建立輸出目錄列（LineEdit + 瀏覽按鈕）。"""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._dir_edit = LineEdit()
        self._dir_edit.setPlaceholderText("選擇輸出資料夾…")
        row.addWidget(self._dir_edit)

        browse_btn = PushButton("瀏覽")
        browse_btn.setFixedWidth(64)
        browse_btn.clicked.connect(self._on_browse_clicked)
        row.addWidget(browse_btn)

        return container

    def _build_button_row(self) -> QHBoxLayout:
        """建立底部「取消 / 套用」按鈕列。"""
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = PushButton("套用")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(apply_btn)

        return btn_row

    # ------------------------------------------------------------------
    # 設定讀寫
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        """從 QSettings 讀取既有設定並填入表單。"""
        output_dir = self._settings.value("output_dir", "")
        if not output_dir:
            output_dir = str(get_default_output_dir())
        self._dir_edit.setText(str(output_dir))

        overwrite = self._settings.value("overwrite", _DEFAULTS["overwrite"])
        # QSettings 在某些平台回傳字串
        if isinstance(overwrite, str):
            overwrite = overwrite.lower() == "true"
        self._overwrite_check.setChecked(bool(overwrite))

        concurrent = int(self._settings.value("concurrent", _DEFAULTS["concurrent"]))
        self._concurrent_spin.setValue(max(1, min(8, concurrent)))

        theme = self._settings.value("theme", _DEFAULTS["theme"])
        idx = self._find_combo_index(self._theme_combo, str(theme))
        self._theme_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _save_settings(self, settings: dict) -> None:
        """將設定字典寫回 QSettings。

        Args:
            settings: 完整設定字典，結構同 settings_applied signal。
        """
        self._settings.setValue("output_dir", settings["output_dir"])
        self._settings.setValue("overwrite",  settings["overwrite"])
        self._settings.setValue("concurrent", settings["concurrent"])
        self._settings.setValue("theme",      settings["theme"])
        self._settings.sync()

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_browse_clicked(self) -> None:
        """開啟資料夾選擇對話框，更新輸出目錄欄位。"""
        current = self._dir_edit.text().strip() or str(get_default_output_dir())
        chosen = QFileDialog.getExistingDirectory(
            self,
            "選擇輸出目錄",
            current,
            QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self._dir_edit.setText(chosen)

    def _on_apply_clicked(self) -> None:
        """收集表單設定、發射 settings_applied signal、寫回 QSettings、關閉對話框。"""
        settings = self._collect_settings()
        self._save_settings(settings)
        self.signals.settings_applied.emit(settings)
        self.accept()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _collect_settings(self) -> dict:
        """從表單元件收集當前設定值。

        Returns:
            符合 settings_applied signal 格式的設定字典。
        """
        output_dir = self._dir_edit.text().strip()
        if not output_dir:
            output_dir = str(get_default_output_dir())

        theme_data = self._theme_combo.currentData()
        if theme_data is None:
            theme_data = "system"

        return {
            "output_dir": output_dir,
            "overwrite":  self._overwrite_check.isChecked(),
            "concurrent": self._concurrent_spin.value(),
            "theme":      str(theme_data),
        }

    @staticmethod
    def _find_combo_index(combo, value: str) -> int:
        """在 combo 中找 userData == value 的索引，找不到回傳 -1。"""
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return -1

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def get_current_settings(self) -> dict:
        """回傳目前表單中的設定值（不發射 signal、不關閉對話框）。

        Returns:
            符合 settings_applied signal 格式的設定字典。
        """
        return self._collect_settings()
