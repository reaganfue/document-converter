"""關閉行為選擇對話框 — 進入背景執行 vs 結束程式 + 記住選擇。

由 MainWindowV2.closeEvent 在 close_action="ask" 時呼叫。
使用 QFluentWidgets MessageBoxBase 提供 Fluent 風格遮罩對話框。

選擇結果：
    choice ∈ {"tray", "quit", None}
        - "tray"  → 進入背景執行（最小化至系統匣）
        - "quit"  → 真正結束程式
        - None    → 使用者按 ESC 取消（呼叫端應 event.ignore()）
    remember (bool) → 是否寫回 SettingsManager 永久保存此選擇
"""
from __future__ import annotations

from typing import Optional

from qfluentwidgets import BodyLabel, CheckBox, MessageBoxBase, SubtitleLabel


class CloseChoiceDialog(MessageBoxBase):
    """關閉行為選擇對話框。

    使用方式：
        dialog = CloseChoiceDialog(parent=main_window)
        if dialog.exec():
            choice = dialog.choice       # "tray" | "quit"
            if dialog.remember:
                settings.set("close_action", choice)
            ...
        else:
            event.ignore()  # 使用者取消
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self._choice: Optional[str] = None

        # 標題 + 說明
        self.titleLabel = SubtitleLabel("關閉文件轉檔？", self)
        self.bodyLabel = BodyLabel(
            "「進入背景」會把視窗縮到系統匣，應用仍在執行。\n"
            "「結束程式」會完整關閉應用。",
            self,
        )
        self.rememberCheck = CheckBox("記住此選擇，下次不再詢問", self)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.bodyLabel)
        self.viewLayout.addWidget(self.rememberCheck)

        # yesButton（主按鈕）→ 進入背景
        self.yesButton.setText("進入背景")
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._on_choose_tray)

        # cancelButton（次按鈕）→ 結束程式
        # 注意：這裡覆寫了預設「按 cancel = reject」行為，因為兩個選項都應視為使用者明確決定。
        # 真正的取消（reject）保留給 ESC 鍵。
        self.cancelButton.setText("結束程式")
        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self._on_choose_quit)

    def _on_choose_tray(self) -> None:
        self._choice = "tray"
        self.accept()

    def _on_choose_quit(self) -> None:
        self._choice = "quit"
        self.accept()

    @property
    def choice(self) -> Optional[str]:
        """使用者選擇："tray" | "quit"；ESC 取消時為 None。"""
        return self._choice

    @property
    def remember(self) -> bool:
        """是否勾選了「記住此選擇」。"""
        return self.rememberCheck.isChecked()
