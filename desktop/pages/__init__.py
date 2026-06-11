"""Desktop 分頁模組 — 7 個應用頁面 + 共用基類。

匯出入口：
    BasePage         所有頁面的抽象基類
    HomePage         首頁（拖放轉換）
    BatchPage        批次頁（資料夾批次轉換）
    PdfToolsPage     PDF 工具頁（合併 / 分割 / 壓縮 / 加密 / 文字編輯）
    ImageToolsPage   圖片工具頁（去背 / 背景替換 / 邊緣處理）
    HistoryPage      歷史頁（轉換記錄 + 重新轉換）
    SettingsPage     設定頁（即時儲存全頁面）
    AboutPage        關於頁
"""
from desktop.pages.base_page import BasePage
from desktop.pages.home_page import HomePage
from desktop.pages.batch_page import BatchPage
from desktop.pages.history_page import HistoryPage
from desktop.pages.image_tools_page import ImageToolsPage
from desktop.pages.pdf_tools_page import PdfToolsPage
from desktop.pages.settings_page import SettingsPage
from desktop.pages.about_page import AboutPage

__all__ = [
    "BasePage",
    "HomePage",
    "BatchPage",
    "PdfToolsPage",
    "ImageToolsPage",
    "HistoryPage",
    "SettingsPage",
    "AboutPage",
]
