"""Desktop 分頁模組 — 5 個應用頁面 + 共用基類。

匯出入口：
    BasePage        所有頁面的抽象基類
    HomePage        首頁（Round 3 Agent A 實作）
    BatchPage       批次頁（Round 3 Agent D 實作）
    HistoryPage     歷史頁（Round 3 Agent B 實作）
    SettingsPage    設定頁（Round 3 Agent C 實作）
    AboutPage       關於頁（Round 3 Agent E 實作）
"""
from desktop.pages.base_page import BasePage
from desktop.pages.home_page import HomePage
from desktop.pages.batch_page import BatchPage
from desktop.pages.history_page import HistoryPage
from desktop.pages.settings_page import SettingsPage
from desktop.pages.about_page import AboutPage

__all__ = [
    "BasePage",
    "HomePage",
    "BatchPage",
    "HistoryPage",
    "SettingsPage",
    "AboutPage",
]
