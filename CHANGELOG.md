# 變更記錄

本文件依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式維護，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

---

## [1.1.0] - 2026-04-24

### 新增

- **多層 PDF 渲染降級鏈**（`converters/pdf_renderer.py`）：四個引擎按可用性順序嘗試
  - Engine 1：Chrome / Edge headless `--print-to-pdf`（無需額外安裝，Windows 11 預裝 Edge）
  - Engine 2：wkhtmltopdf CLI（若已安裝）
  - Engine 3：weasyprint（若 GTK 3 runtime 可用）
  - Engine 4：reportlab 純 Python 後備（隨本工具自動安裝，保證至少有基礎 PDF 輸出）
- `diagnose_pdf_backends()` 公開 API：回傳各引擎可用性狀態（供 `/api/health` 或除錯用）
- `reportlab==4.2.2` 加入依賴（純 Python，無額外系統依賴）

### 改善

- HTML → PDF、Markdown → PDF、TXT → PDF 全面改用 pdf_renderer 降級鏈（棄用 weasyprint 直呼）
- PPTX → PDF 降級路徑（文字抽取 → HTML → PDF）改用 pdf_renderer（棄用 weasyprint 直呼）
- **Windows 11（含 Edge）用戶無需手動安裝 GTK 3 runtime 即可使用 PDF 輸出**
- Chrome headless 使用獨立 `--user-data-dir=<tmpdir>` 避免污染系統 Chrome profile

### 技術細節

- `converters/html_converter.py`：`_to_pdf` 改呼叫 `get_renderer().render_html_to_pdf()`
- `converters/markdown_converter.py`：`_to_pdf` 改呼叫 pdf_renderer
- `converters/txt_converter.py`：`_to_pdf` 改呼叫 pdf_renderer
- `converters/ppt_converter.py`：降級路徑改用 pdf_renderer（Pillow PNG 組合 PDF 路徑保留不變）
- 新增 20 個單元測試（`tests/test_converters/test_pdf_renderer.py`）

## [1.0.0] - 2026-04-24

### 新增

- 初版發布
- 支援 7 類格式互轉：PDF / Word / PPT / HTML / Markdown / TXT / 圖片
- Flask + Alpine.js 本機 Web UI（無需安裝任何前端框架）
- 暗色/亮色雙模式，預設跟隨系統偏好（prefers-color-scheme）
- 拖放多檔批次轉換（最多 20 個檔案，單檔 50MB / 批次 200MB 上限）
- 繁體中文介面
- 一鍵啟動腳本（start.bat）—— 自動建立虛擬環境、安裝依賴、啟動伺服器
- 非同步轉換進度顯示（ThreadPoolExecutor + 輪詢 API）
- 完成後自動清理暫存（60 秒後清理，防磁碟滿）
- 行動裝置警告提示（.exe 拒絕上傳）
- 離線運行設計（首次安裝後無需網路）

### 技術決策

- 純 Python 轉檔引擎（無 LibreOffice 依賴，安裝簡單）
- MS Word COM 作為 DOCX→PDF 高保真路徑（偵測到 Word 時自動啟用）
- weasyprint 作為 HTML/MD→PDF 引擎（需 GTK 3 runtime，見 README 說明）
- UUID 子目錄隔離上傳 + TTL 自動清理（防路徑穿越攻擊 + 磁碟管理）
- 所有前端資源本機化（Tailwind CSS、Alpine.js 存放於 static/js/vendor/）
- Flask 僅監聽 localhost:5000，不對外暴露

### 已知限制

- 掃描版 PDF 不支援 OCR（計畫 v2.0 加入）
- PPT → DOCX 轉換在 v1.0 未實作（技術複雜度高）
- PDF 輸出需要 GTK 3 runtime（見 README 故障排除）
- 單次轉換最多 20 個檔案
