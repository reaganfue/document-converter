# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概覽

這是一個**完全本機運行的文件轉換工具**，v2.0 已從 Flask Web 應用遷移為 **PySide6 桌面應用**（基於 QFluentWidgets，Windows 11 Fluent Design 風格）。支援 PDF / DOCX / PPTX / HTML / Markdown / TXT / Image 七種格式的互轉。用戶雙擊 `start.bat` 即可啟動，無雲端依賴、無浮水印、無次數限制。

核心技術棧：Python 3.13 · PySide6 6.11.0 · PySide6-Fluent-Widgets 1.11.2 · PyMuPDF · python-docx · python-pptx · weasyprint · Pillow

## 開發指令

### 啟動桌面應用

**一般用戶**（推薦）：直接雙擊 `start.bat`，確認 venv 就緒後啟動桌面應用。

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
pytest tests/test_converters/               # 轉換器測試（主要）
pytest tests/test_converters/test_pdf_converter.py   # 單一轉換器
pytest -v                                   # 詳細輸出
pytest --tb=short                           # 簡短 traceback
```

> `tests/test_api.py` 已封存為 `tests/test_api.py.legacy`（舊 Flask API 測試，不再執行）。

### 虛擬環境管理

```bash
# 建立（僅首次）
python -m venv venv

# 安裝依賴
venv\Scripts\pip install -r requirements.txt

# 停用
deactivate
```

`start.bat` 會檢查 `venv\Scripts\python.exe` 是否存在，不存在則顯示錯誤說明。

### 打包為 portable exe

雙擊 `build.bat`，或在啟用 venv 後執行：

```bash
venv/Scripts/python.exe -m PyInstaller desktop_build.spec --clean --noconfirm
```

產物：`dist/文件轉檔/文件轉檔.exe`（約 337 MB，onedir 模式）

- `desktop_build.spec`：PyInstaller 設定檔（hiddenimports、資源路徑、onedir / windowed）
- `build.bat`：UTF-8 BOM + CRLF 打包腳本，自動清理 build/dist 後重新打包並驗證產物存在
- 打包後雙擊 `dist\文件轉檔\文件轉檔.exe` 即可啟動，無需安裝 Python

> `docx2pdf` 在打包後仍需本機安裝 Microsoft Word 才能使用；其餘功能無額外依賴。

## 架構

### 桌面應用架構（v2.0 當前）

```
python -m desktop
    │
    └─ desktop/main.py → QApplication + MainWindow.show()
           │
           ├─ desktop/main_window.py      ← 主視窗（Single-Window Drop Zone 模式）
           │       ├─ desktop/widgets/    ← 5 個自訂 UI 元件
           │       │   ├─ drop_zone.py       拖曳投放區
           │       │   ├─ file_card.py       單檔任務卡片（進度、格式選擇）
           │       │   ├─ format_selector.py 全域格式選擇器
           │       │   ├─ progress_widget.py 總進度顯示
           │       │   └─ settings_dialog.py 設定對話框
           │       └─ desktop/controllers/ ← 非同步轉換管理
           │           ├─ conversion_controller.py  任務派發 + Worker 管理
           │           └─ job_manager.py             佇列管理
           │
           ├─ desktop/interfaces.py       ← Signal 契約（Single Source of Truth）
           ├─ desktop/utils/theme.py      ← 主題切換（QFluentWidgets setTheme）
           ├─ desktop/utils/paths.py      ← 路徑工具
           └─ desktop/resources/
               ├─ icons/                 ← SVG 格式圖示
               └─ styles.qss             ← 客製 QSS 樣式
```

**業務層（不變）：**
```
desktop/controllers/ → converters/dispatcher.py
                              │
                              └─ 依 (source_fmt, target_fmt) 路由至具體 Converter
```

### Converter Dispatch Pattern

`converters/dispatcher.py` 維護格式 → 轉換器實例的單例映射。呼叫 `convert_file(source_path, target_format, output_dir)` 時：

1. 查 `_CONVERTERS[source_format]` 取得對應 Converter
2. 呼叫 `converter.supports(target_format)` 確認支援
3. 呼叫 `converter.convert(input_path, output_path, target_format)`

所有 Converter 繼承 `converters/base.py` 的 `BaseConverter`：
- `source_format: str` — 此轉換器負責的來源格式
- `supported_targets: list[str]` — 支援的目標格式清單
- `convert(input_path, output_path, target_format) -> None`

**降級規則**：首選引擎失敗時 Converter 內部自動嘗試降級引擎，兩者都失敗才拋 `ConversionError`。

### 轉換器繼承關係

| Converter 類別 | 負責格式 | 主要依賴 |
|---------------|---------|---------|
| `PDFConverter` | pdf → docx/html/md/txt/image | PyMuPDF, pdf2docx |
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
├── test_api.py.legacy       # 舊 Flask API 測試（已封存，不執行）
└── test_converters/
    ├── test_pdf_converter.py
    ├── test_word_converter.py
    ├── test_ppt_converter.py
    ├── test_html_converter.py
    ├── test_markdown_converter.py
    ├── test_image_converter.py
    └── test_dispatcher.py
```

## 關鍵檔案

| 檔案 | 用途 |
|------|------|
| `desktop/main.py` | 桌面應用入口（`QApplication + MainWindow.show()`） |
| `desktop/main_window.py` | 主視窗（Single-Window Drop Zone 模式） |
| `desktop/interfaces.py` | Signal 契約（Single Source of Truth） |
| `desktop/controllers/conversion_controller.py` | 任務派發 + QThreadPool Worker 管理 |
| `converters/dispatcher.py` | 轉換路由引擎，唯一公開的 `convert_file()` 入口 |
| `converters/base.py` | `BaseConverter` 抽象介面 |
| `converters/exceptions.py` | 例外類型階層 |
| `config.py` | 格式矩陣、大小限制、TTL 等常數 |
| `start.bat` | 一鍵啟動腳本（檢查 Python + venv → 啟動桌面應用） |
| `requirements.txt` | 依賴清單（含 PySide6 6.11.0 + QFluentWidgets 1.11.2） |

## 已知注意事項

- **`docx2pdf` 依賴 Microsoft Word COM**：未安裝 Word 時自動降級至 `python-docx → weasyprint` 路徑。
- **PPTX → DOCX 未支援**（v1.0 設計決策，非 bug）：詳見 `config.py` 的 `CONVERSION_MATRIX`。
- **掃描版 PDF 無法抽取文字**（需 OCR，v3 再議）：若 PDF 為純圖片，轉 TXT/MD 結果為空。
- **`weasyprint>=62.0` 為 Python 3.13 必要版本**：釘低版本會造成 import warning 或失敗。

## 已封存的遺留檔案（Legacy）

> **重要**：請勿從 `.legacy` 檔案閱讀架構，它們描述已廢止的 Flask 版本。

| 檔案 | 說明 |
|------|------|
| `app.py.legacy` | 舊 Flask 入口（路由、Job 管理、ThreadPoolExecutor） |
| `templates/index.html.draft.legacy` | 舊 Web UI 模板（Jinja2 + Alpine.js） |
| `templates/index.html` | 舊 Flask 渲染模板（靜態保留） |
| `tests/test_api.py.legacy` | 舊 Flask API 端點測試（15 個測試）|
| `static/` | 舊 Web 資源（Tailwind / Alpine.js / SVG 圖示），詳見 `static/README.md` |

## Quick Start for New Claude Code Session

若要理解當前架構，建議閱讀順序：
1. `desktop/interfaces.py` — 了解 Signal 契約（所有元件的溝通語言）
2. `desktop/main_window.py` — 了解主視窗如何組合各 widget + controller
3. `converters/dispatcher.py` — 了解業務層的格式路由邏輯
4. `desktop/controllers/conversion_controller.py` — 了解 UI 如何觸發轉換

**不要讀** `.legacy` 檔案 — 它們描述舊版 Flask 架構，與當前桌面版無關。
