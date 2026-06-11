# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概覽

這是一個**完全本機運行的文件轉換工具**，v2.0 起為 **PySide6 桌面應用**（基於 QFluentWidgets，Windows 11 Fluent Design 風格）。支援 PDF / DOCX / PPTX / HTML / Markdown / TXT / Image 七種格式互轉（掃描版 PDF 自動 OCR），並內建 PDF 工具（合併/分割/壓縮/加密/文字編輯）與圖片工具（rembg 去背）。用戶雙擊 `start.bat` 即可啟動，無雲端依賴、無浮水印、無次數限制。

核心技術棧：Python 3.13 · PySide6 6.11.0 · PySide6-Fluent-Widgets 1.11.2 · PyMuPDF · python-docx · python-pptx · weasyprint · Pillow · rembg · RapidOCR

> 專案狀態：個人使用，功能已完成。預設不主動擴張功能。

## 開發指令

### 啟動桌面應用

**一般用戶**（推薦）：直接雙擊 `start.bat`（檢查 venv 後以 pythonw 無視窗啟動）。

**開發者**（已啟用 venv）：
```bash
# 啟用 venv
source venv/Scripts/activate      # Git Bash
call venv\Scripts\activate.bat    # CMD

# 啟動桌面應用
python -m desktop
```

### 執行測試

```bash
# 啟用 venv 後
pytest tests/                               # 全部測試
pytest tests/test_converters/test_pdf_converter.py   # 單一轉換器
pytest -v                                   # 詳細輸出
pytest --tb=short                           # 簡短 traceback
```

### 虛擬環境管理

```bash
# 建立（僅首次）
python -m venv venv

# 安裝依賴
venv\Scripts\pip install -r requirements.txt

# 停用
deactivate
```

`start.bat` 會檢查 `venv\Scripts\pythonw.exe` 是否存在，不存在則顯示建立說明。

### 打包為 portable exe

雙擊 `build.bat`，或在啟用 venv 後執行：

```bash
venv/Scripts/python.exe -m PyInstaller desktop_build.spec --clean --noconfirm
```

產物：`dist/文件轉檔/文件轉檔.exe`（onedir 模式，整個資料夾約 600 MB）

- `desktop_build.spec`：PyInstaller 設定檔（hiddenimports、資源路徑、onedir / windowed）
- `build.bat`：UTF-8 BOM + CRLF 打包腳本，自動清理 build/dist 後重新打包並驗證產物存在
- rembg 去背模型（~525MB）**不內嵌**：打包版首次使用去背時自動下載；離線部署把 `u2net_models/` 放到 exe 同目錄
- RapidOCR 模型（~15MB）隨 `collect_data_files('rapidocr_onnxruntime')` 內嵌，OCR 離線可用

> `docx2pdf` 在打包後仍需本機安裝 Microsoft Word 才能使用；其餘功能無額外依賴。

## 架構

### 桌面應用架構

```
python -m desktop
    │
    └─ desktop/main.py → QApplication + 單實例鎖（QLocalServer）+ MainWindow.show()
           │
           ├─ desktop/main_window_v2.py   ← 主視窗 MainWindowV2（MSFluentWindow，7 分頁導航）
           │       │
           │       ├─ desktop/pages/      ← 7 個頁面（TOP：首頁/批次/PDF 工具/圖片工具/歷史；BOTTOM：設定/關於）
           │       │   ├─ base_page.py        頁面抽象基類
           │       │   ├─ home_page.py        首頁（拖放轉換，組合 widgets/）
           │       │   ├─ batch_page.py       批次轉換頁
           │       │   ├─ pdf_tools_page.py   PDF 工具頁（合併/分割/壓縮/加密/文字編輯）
           │       │   ├─ image_tools_page.py 圖片工具頁（rembg 去背 4-tab UI）
           │       │   ├─ history_page.py     歷史頁（記錄 + 一鍵重新轉換）
           │       │   ├─ settings_page.py    設定頁（即時儲存，無套用按鈕）
           │       │   ├─ about_page.py       關於頁
           │       │   └─ components/         頁面級元件（stats_bar）
           │       │
           │       ├─ desktop/widgets/    ← 可複用 UI 元件
           │       │   ├─ drop_zone.py            拖曳投放區
           │       │   ├─ file_card.py            單檔任務卡片（進度、格式選擇）
           │       │   ├─ format_selector.py      全域格式選擇器
           │       │   ├─ progress_widget.py      總進度顯示
           │       │   └─ close_choice_dialog.py  關閉行為詢問對話框
           │       │
           │       └─ desktop/controllers/ ← 7 個 Manager（建立後注入各 Page）
           │           ├─ conversion_controller.py  任務派發 + QThreadPool Worker 管理
           │           ├─ job_manager.py            佇列管理
           │           ├─ settings_manager.py       設定持久化（QSettings）+ 驗證
           │           ├─ notification_manager.py   InfoBar 通知
           │           ├─ history_manager.py        歷史記錄（含 retention policy）
           │           ├─ tray_manager.py           系統托盤
           │           ├─ pdf_tools_controller.py   PDF 工具非同步操作
           │           └─ image_tools_controller.py 圖片工具非同步操作
           │
           ├─ desktop/database/history_db.py ← SQLite 歷史記錄層
           ├─ desktop/interfaces.py          ← Signal 契約 + PageID + 支援格式（Single Source of Truth）
           ├─ desktop/utils/                 ← theme（Nordic 雙主題）/ paths / i18n
           └─ desktop/resources/             ← 圖示（SVG/ICO）與 QSS 樣式
```

**業務層（與 UI 解耦）：**
```
desktop/controllers/ → converters/dispatcher.py    格式互轉路由
                       converters/pdf_tools.py     PDF 工具操作
                       converters/image_tools.py   去背/背景處理（模型缺失時首次使用自動下載）
                       converters/pdf_ocr.py       掃描版 PDF OCR（RapidOCR，PDFConverter 的無文字層後備）
```

### Converter Dispatch Pattern

`converters/dispatcher.py` 維護格式 → 轉換器實例的單例映射，並內建 `_SUPPORT_MATRIX` 支援矩陣。呼叫 `convert_file(input_path, output_path, source_format, target_format)` 時：

1. 查 `_CONVERTERS[source_format]` 取得對應 Converter
2. 呼叫 `converter.supports(target_format)` 確認支援
3. 呼叫 `converter.convert(input_path, output_path, target_format)`

所有 Converter 繼承 `converters/base.py` 的 `BaseConverter`：
- `source_format: str` — 此轉換器負責的來源格式
- `supported_targets: list[str]` — 支援的目標格式清單
- `convert(input_path, output_path, target_format) -> None`

**降級規則**：首選引擎失敗時 Converter 內部自動嘗試降級引擎，兩者都失敗才拋 `ConversionError`。

**PDF 輸出降級鏈**（`converters/pdf_renderer.py`，HTML/MD/TXT→PDF 共用）：
Chrome/Edge headless → wkhtmltopdf → weasyprint → reportlab，四引擎依可用性自動降級。

### 轉換器繼承關係

| Converter 類別 | 負責格式 | 主要依賴 |
|---------------|---------|---------|
| `PDFConverter` | pdf → docx/html/md/txt/image | PyMuPDF, pdf2docx, RapidOCR（掃描頁後備） |
| `WordConverter` | docx → pdf/html/md/txt | python-docx, docx2pdf, weasyprint |
| `PPTConverter` | pptx → pdf/html/txt/image | python-pptx, Pillow |
| `HTMLConverter` | html → pdf/docx/md/txt | weasyprint, BeautifulSoup4 |
| `MarkdownConverter` | md → html/pdf/docx/txt | markdown, weasyprint |
| `TXTConverter` | txt → pdf/docx/html/md | python-docx, weasyprint |
| `ImageConverter` | image → pdf/image | Pillow |

### 例外階層

```
ConversionError（基類：首選 + 降級都失敗）
├── UnsupportedFormatError（格式對不在支援矩陣中）
└── ConversionTimeoutError（超過 120 秒）
```

### 測試結構

```
tests/
├── conftest.py              # pytest fixtures（目錄隔離、假檔案）
├── fixtures/                # 程式化生成的測試檔（generate_fixtures.py 自動重建）
├── test_desktop/
│   └── test_settings_profiles.py   # 轉換 Profile CRUD（INI 隔離，不碰 Registry）
└── test_converters/
    ├── conftest.py          # sample.* fixtures（pytest 啟動時自動生成）
    ├── test_pdf_converter.py
    ├── test_pdf_renderer.py
    ├── test_pdf_ocr.py              # 掃描版 PDF OCR 端到端（生成無文字層 fixture）
    ├── test_image_tools_models.py   # rembg 模型路徑解析 / 可用性
    ├── test_word_converter.py
    ├── test_ppt_converter.py
    ├── test_html_converter.py
    ├── test_markdown_converter.py
    ├── test_txt_converter.py
    ├── test_image_converter.py
    └── test_dispatcher.py
```

## 關鍵檔案

| 檔案 | 用途 |
|------|------|
| `desktop/main.py` | 桌面應用入口（QApplication + 單實例鎖 + MainWindow.show()） |
| `desktop/main_window_v2.py` | 主視窗 `MainWindowV2`（MSFluentWindow，7 分頁導航 + Manager 注入） |
| `desktop/interfaces.py` | Signal 契約 + PageID + 支援格式清單（Single Source of Truth） |
| `desktop/controllers/conversion_controller.py` | 任務派發 + QThreadPool Worker 管理 |
| `converters/dispatcher.py` | 轉換路由引擎 + `_SUPPORT_MATRIX`，唯一公開的 `convert_file()` 入口 |
| `converters/base.py` | `BaseConverter` 抽象介面 |
| `converters/exceptions.py` | 例外類型階層 |
| `converters/pdf_renderer.py` | 四引擎 PDF 渲染降級鏈（執行緒安全單例） |
| `start.bat` | 一鍵啟動腳本（檢查 venv → pythonw 無視窗啟動） |
| `requirements.txt` | 依賴清單（PySide6 6.11.0 + QFluentWidgets 1.11.2 + 轉換引擎） |

## 已知注意事項

- **`docx2pdf` 依賴 Microsoft Word COM**：未安裝 Word 時自動降級至 `python-docx → weasyprint` 路徑。
- **PPTX → DOCX 未支援**（設計決策，非 bug）：詳見 `converters/dispatcher.py` 的 `_SUPPORT_MATRIX`。
- **掃描版 PDF 自動 OCR**（v2.2 起）：無文字層頁面在 TXT/MD/HTML 路徑自動走 RapidOCR；輸出純文字不還原版面，手寫/低解析度辨識有限。有文字層的頁面永遠走原生抽取。
- **`weasyprint>=62.0` 為 Python 3.13 必要版本**：釘低版本會造成 import warning 或失敗。
- **`.bat` 檔案必須 UTF-8 BOM + CRLF**：否則 cmd 解析中文註解會出錯。
- **rembg 模型不入版控也不內嵌打包**（~525MB）：首次使用去背時自動下載至 `~/.u2net/`；`scripts/predownload_models.py` 為離線預載選項。
- **windowed 模式 stdout 防護**：`desktop/main.py` 對 `sys.stdout/stderr is None` 墊 StringIO，防第三方進度條崩潰——新增入口時不要移除。

## Quick Start for New Claude Code Session

若要理解當前架構，建議閱讀順序：
1. `desktop/interfaces.py` — Signal 契約與 PageID（所有元件的溝通語言）
2. `desktop/main_window_v2.py` — 主視窗如何組合 7 個 page + 7 個 manager
3. `converters/dispatcher.py` — 業務層的格式路由邏輯
4. `desktop/controllers/conversion_controller.py` — UI 如何觸發轉換
