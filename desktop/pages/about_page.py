"""關於頁（AboutPage）— 應用資訊、版本說明與第三方套件清單。

佈局（單頁可捲動）：
    - Logo 128×128 + 應用名稱 + 版本
    - 軟體資訊卡片（Python / Qt / 平台）
    - 作者與授權卡片
    - 第三方套件清單卡片
    - 外部連結按鈕列（GitHub / 文件 / 問題回報）
    - 檢查更新按鈕 + 狀態標籤

此頁面為靜態展示頁，無需注入 Controller 或 Manager。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    HyperlinkButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from desktop.interfaces import PageID
from desktop.pages.base_page import BasePage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 應用常數
# ---------------------------------------------------------------------------

APP_NAME = "文件轉檔"
APP_VERSION = "2.0"
BUILD_DATE = "2026-04-25"
AUTHOR = "DocConverter Team"
LICENSE_TEXT = "MIT License"
COPYRIGHT_YEAR = "2026"

GITHUB_URL = "https://github.com/your-org/doc-converter"
DOCS_URL = "https://github.com/your-org/doc-converter#readme"
ISSUES_URL = "https://github.com/your-org/doc-converter/issues"

# ---------------------------------------------------------------------------
# 第三方套件清單 — (套件名, 版本, 授權, 說明網址)
# ---------------------------------------------------------------------------

THIRD_PARTY_LIBS: list[tuple[str, str, str, str]] = [
    ("PySide6",        "6.11.0",  "LGPL-3.0",    "https://www.qt.io/qt-for-python"),
    ("qfluentwidgets", "1.11.2",  "MIT",          "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"),
    ("Pillow",         "10.4.0",  "MIT-CMU",      "https://python-pillow.org"),
    ("darkdetect",     "0.8.0",   "BSD-3-Clause", "https://github.com/albertosottile/darkdetect"),
    ("pdfplumber",     "—",       "MIT",          "https://github.com/jsvine/pdfplumber"),
    ("docx2pdf",       "—",       "MIT",          "https://github.com/AlJohri/docx2pdf"),
    ("python-docx",    "—",       "MIT",          "https://github.com/python-openxml/python-docx"),
    ("python-pptx",    "—",       "MIT",          "https://github.com/scanny/python-pptx"),
    ("markdown",       "—",       "BSD-3-Clause", "https://github.com/Python-Markdown/markdown"),
    ("PyInstaller",    "6.20.0",  "GPL-classpath","https://pyinstaller.org"),
]

# 搜索圖示資源的路徑（相對於此檔案所在目錄的上一層 resources/）
_RESOURCES_DIR = Path(__file__).parent.parent / "resources"
_ICO_PATH = _RESOURCES_DIR / "app.ico"
_SVG_PATH = _RESOURCES_DIR / "app_icon.svg"

LOGO_SIZE = 128


class AboutPage(BasePage):
    """關於頁 — 應用版本、授權與第三方套件資訊。"""

    PAGE_ID = PageID.ABOUT
    PAGE_TITLE = "關於"
    PAGE_ICON = FluentIcon.INFO

    def _setup_ui(self) -> None:
        """建立可捲動的關於頁面完整 UI。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(20)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_info_card())
        layout.addWidget(self._build_license_card())
        layout.addWidget(self._build_libs_card())
        layout.addLayout(self._build_links_row())
        layout.addLayout(self._build_update_section())
        layout.addStretch(1)

        scroll.setWidget(content)
        self._content_layout.addWidget(scroll)

    # =========================================================================
    # 區塊建構方法
    # =========================================================================

    def _build_header(self) -> QVBoxLayout:
        """Logo + 應用名稱 + 版本號 + 簡短描述。"""
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(8)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = self._load_logo_pixmap()
        if pixmap is not None:
            logo_label.setPixmap(pixmap)
        layout.addWidget(logo_label)

        name_label = TitleLabel(APP_NAME)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        version_label = SubtitleLabel(f"v{APP_VERSION}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        desc_label = BodyLabel("一款跨格式的桌面文件轉換工具")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc_label)

        return layout

    def _build_info_card(self) -> CardWidget:
        """軟體資訊卡片：版本、建置日期、Python、Qt、平台。"""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("軟體資訊"))

        rows = [
            ("版本",    APP_VERSION),
            ("建置日期", BUILD_DATE),
            ("Python",  "3.10+"),
            ("UI 框架", "PySide6 + QFluentWidgets"),
            ("平台",    "Windows 11"),
        ]
        for label_text, value_text in rows:
            layout.addLayout(self._info_row(label_text, value_text))

        return card

    def _build_license_card(self) -> CardWidget:
        """作者與授權卡片。"""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("作者與授權"))

        rows = [
            ("作者",  AUTHOR),
            ("授權",  LICENSE_TEXT),
            ("版權",  f"© {COPYRIGHT_YEAR}"),
        ]
        for label_text, value_text in rows:
            layout.addLayout(self._info_row(label_text, value_text))

        return card

    def _build_libs_card(self) -> CardWidget:
        """第三方套件清單卡片（表格式）。"""
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel("第三方套件"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)

        # 表頭
        headers = ("名稱", "版本", "授權")
        for col, header in enumerate(headers):
            lbl = CaptionLabel(header)
            grid.addWidget(lbl, 0, col)

        # 資料列
        for row_idx, (pkg_name, version, license_id, _url) in enumerate(
            THIRD_PARTY_LIBS, start=1
        ):
            grid.addWidget(BodyLabel(pkg_name), row_idx, 0)
            grid.addWidget(BodyLabel(version),  row_idx, 1)
            grid.addWidget(BodyLabel(license_id), row_idx, 2)

        layout.addLayout(grid)
        return card

    def _build_links_row(self) -> QHBoxLayout:
        """外部連結按鈕列：GitHub / 文件 / 回報問題。"""
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(12)

        links = [
            ("GitHub",    GITHUB_URL),
            ("文件",       DOCS_URL),
            ("回報問題",   ISSUES_URL),
        ]
        for label_text, url in links:
            btn = self._make_hyperlink_button(label_text, url)
            layout.addWidget(btn)

        return layout

    def _build_update_section(self) -> QVBoxLayout:
        """檢查更新按鈕 + 狀態標籤。"""
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(6)

        update_btn = PushButton()
        update_btn.setIcon(FluentIcon.UPDATE)
        update_btn.setText("檢查更新")
        update_btn.clicked.connect(self._on_check_update)
        layout.addWidget(update_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._update_status_label = CaptionLabel(
            f"目前已是最新版本（v{APP_VERSION}，{BUILD_DATE}）"
        )
        self._update_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._update_status_label)

        return layout

    # =========================================================================
    # 私有輔助方法
    # =========================================================================

    def _load_logo_pixmap(self) -> QPixmap | None:
        """嘗試從 resources/ 載入應用圖示，返回縮放後的 QPixmap。

        優先順序：app.ico → app_icon.svg → None（呼叫端跳過顯示）。

        Returns:
            縮放至 128×128 的 QPixmap，若所有路徑均不存在則回傳 None。
        """
        for path in (_ICO_PATH, _SVG_PATH):
            if path.exists():
                pix = QPixmap(str(path))
                if not pix.isNull():
                    return pix.scaled(
                        LOGO_SIZE,
                        LOGO_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        logger.warning("AboutPage: 找不到應用圖示（嘗試路徑：%s, %s）", _ICO_PATH, _SVG_PATH)
        return None

    @staticmethod
    def _info_row(label_text: str, value_text: str) -> QHBoxLayout:
        """建立一列左側 CaptionLabel + 右側 BodyLabel 的水平佈局。

        Args:
            label_text: 欄位名稱，顯示於左側。
            value_text: 欄位值，顯示於右側。

        Returns:
            水平 QHBoxLayout。
        """
        row = QHBoxLayout()
        row.addWidget(CaptionLabel(label_text))
        row.addStretch(1)
        row.addWidget(BodyLabel(value_text))
        return row

    @staticmethod
    def _make_hyperlink_button(label_text: str, url: str) -> HyperlinkButton:
        """建立可點擊的超連結按鈕，點擊後以系統預設瀏覽器開啟 URL。

        HyperlinkButton 初始化後需透過 setUrl / setText 設定，
        而非建構子參數（不同版本 qfluentwidgets API 相容性處理）。

        Args:
            label_text: 按鈕顯示文字。
            url:        點擊後開啟的 URL 字串。

        Returns:
            已設定好文字與 URL 的 HyperlinkButton。
        """
        btn = HyperlinkButton()
        btn.setText(label_text)
        try:
            btn.setUrl(url)
        except TypeError:
            # 若 setUrl 不接受字串，改用 QUrl
            btn.setUrl(QUrl(url))
        return btn

    # =========================================================================
    # 事件處理
    # =========================================================================

    def _on_check_update(self) -> None:
        """「檢查更新」按鈕點擊處理器（Stub）。

        目前僅更新狀態標籤。未來可擴展為呼叫 GitHub Releases API，
        比對遠端版本號與 APP_VERSION 後給出升級或「已是最新」提示。
        """
        self._update_status_label.setText(
            f"已是最新版本（v{APP_VERSION}，{BUILD_DATE}）"
        )
        logger.debug("AboutPage: 使用者點擊「檢查更新」，目前為 stub 實作")
