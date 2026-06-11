# 變更記錄

本文件依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式維護，版本號遵循 [語意化版本](https://semver.org/lang/zh-TW/)。

---

## [2.2.0] - 2026-06-11

### 新增

- **掃描版 PDF OCR**（`converters/pdf_ocr.py`）：PDF 轉 TXT / MD / HTML 時，無文字層的頁面自動以 RapidOCR（onnxruntime 後端）辨識文字
  - 完全離線：OCR 模型（~15MB）隨 pip 套件內建，無需安裝 Tesseract 等系統程式
  - 有文字層的頁面永遠走原生抽取，OCR 只作為掃描頁後備，不影響一般 PDF 的速度與精確度
  - 支援繁中 / 簡中 / 英文混排
- **轉換 Profile**：首頁新增 Profile 下拉與儲存/刪除按鈕，一鍵套用具名的「目標格式 + 輸出目錄 + 覆寫」組合（QSettings 持久化）

### 改善

- **打包體積瘦身（~1.1GB → ~600MB）**：rembg AI 去背模型（~525MB）不再內嵌 exe，改為首次使用去背時自動下載至 `~/.u2net/`，UI 同步提示下載狀態；離線部署可把 `u2net_models/` 資料夾放到 exe 同目錄
- windowed 模式（pythonw / 打包 exe）下墊底 `sys.stdout/stderr`，防止第三方下載進度條（tqdm）使應用崩潰

### 技術細節

- 新依賴：`rapidocr-onnxruntime>=1.2,<2.0`（複用既有 onnxruntime）
- 新增 22 個測試（Profile CRUD 12 + 模型解析 5 + OCR 端到端 5），總計 176 passed

## [2.1.0] - 2026-06-09

### 新增

- **PDF 工具頁**：合併 / 分割 / 壓縮 / 加密解密，以及點擊即編輯的 PDF 文字編輯（含預覽與視窗縮放）
- **圖片工具頁**：rembg AI 自動去背、背景替換、邊緣銳化羽化（4-tab UI；模型可由 `scripts/predownload_models.py` 預下載）
- **歷史頁**：轉換記錄持久化（SQLite）+ 一鍵重新轉換；每日統計跨重啟保留
- **系統整合**：系統托盤常駐、關閉行為詢問對話框、單實例鎖（重複啟動喚起既有視窗）
- **Nordic Design System**：暗色/亮色雙主題，DropZone / FileCard / ProgressWidget 全面重構

### 改善

- `start.bat` 改以 `pythonw.exe` detached 啟動，不再殘留黑色 console 視窗
- 設定頁由彈出對話框改為嵌入式全頁面，設定項即時儲存（Windows 11 Settings 慣例）
- PyInstaller 打包（`desktop_build.spec` + `build.bat`）：onedir 模式產出 portable exe

## [2.0.0] - 2026-04-25

### 變更（重大）

- **架構全面遷移**：Flask Web 應用（瀏覽器 UI + localhost:5000）→ PySide6 桌面應用（QFluentWidgets，Windows 11 Fluent Design 風格）
- UI 改為 MSFluentWindow 多分頁導航；轉換改由 QThreadPool 非同步執行
- 轉換業務層（`converters/`）完整保留，僅替換呼叫端

### 移除

- Flask / Werkzeug 依賴、Web 模板（`templates/`）與前端資源（`static/`）
- uploads/outputs TTL 清理機制（桌面版直接輸出至使用者指定目錄）

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
