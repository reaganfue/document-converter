# 文件轉檔工具

**本機運行 | 永久免費 | 無浮水印 | 無次數限制 | 離線可用**

---

## 簡介

一個完全在您電腦本機運行的多格式文件轉換**桌面應用**（PySide6 + Fluent Design，Windows 11 風格介面）。不需要上傳檔案到任何雲端伺服器，不需要付費，沒有浮水印，沒有次數限制，安裝完成後可離線使用。

**為什麼要用這個，而不是線上轉檔服務？**

| 比較項目 | 線上服務 | 本工具 |
|---------|---------|--------|
| 費用 | 免費版有限制，完整版需付費 | 永久免費 |
| 浮水印 | 免費版通常加浮水印 | 從不加浮水印 |
| 次數限制 | 每天幾次 | 無限次 |
| 隱私 | 檔案上傳至第三方伺服器 | 檔案永遠留在本機 |
| 離線使用 | 需要網路 | 安裝完成後可離線 |
| 速度 | 受限於網路頻寬 | 本機 CPU 直接處理 |

---

## 功能總覽

應用視窗左側為導航列，共 7 個頁面：

| 頁面 | 功能 |
|------|------|
| 首頁 | 拖放檔案即時轉換（最多 20 檔，單檔 50MB）；轉換 Profile 一鍵套用常用「格式+輸出目錄+覆寫」組合 |
| 批次 | 整個資料夾批次轉換 |
| PDF 工具 | 合併 / 分割 / 壓縮 / 加密解密 / 點擊編輯 PDF 文字 |
| 圖片工具 | AI 自動去背（rembg）/ 背景替換 / 邊緣銳化羽化（AI 模型首次使用時自動下載） |
| 歷史 | 轉換記錄查詢 + 一鍵重新轉換 |
| 設定 | 輸出目錄、主題、並行數、通知、托盤等（即時儲存） |
| 關於 | 版本與授權資訊 |

**掃描版 PDF 自動 OCR**（v2.2 起）：PDF 轉 TXT / Markdown / HTML 時，沒有文字層的掃描頁會自動以 RapidOCR 辨識文字（支援繁中/簡中/英文，完全離線、無需安裝任何 OCR 軟體）。一般 PDF 不受影響，仍走快速精確的原生抽取。

其他特性：暗色/亮色雙主題（Nordic Design System）、系統托盤常駐、單實例鎖（重複啟動自動喚起既有視窗）、完成通知、`Ctrl+1~5` 快捷鍵切換頁面。

---

## 系統需求

- **作業系統**：Windows 10 或 Windows 11（64 位元）
- **Python**：3.10 以上版本（建議 3.12 或 3.13）
  - 下載網址：https://www.python.org/downloads/
  - 安裝時請勾選「Add Python to PATH」
- **磁碟空間**：至少 3GB 可用空間（venv + 依賴套件 + AI 去背模型）
- **Microsoft Word**（選用）：安裝後可啟用 DOCX 轉 PDF 的最高保真模式；未安裝則自動使用替代引擎

---

## 安裝與啟動

### 首次安裝（一次性，約 5-10 分鐘）

在專案資料夾開啟 cmd，依序執行：

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

（選用）若要使用圖片去背功能離線運行，預先下載 AI 模型：

```
venv\Scripts\python scripts\predownload_models.py
```

### 日常啟動

雙擊 `start.bat` —— 桌面應用視窗直接開啟，無黑色命令視窗。

---

## 支援格式矩陣

下表顯示本工具支援的所有轉換方向。「高」代表高保真（90% 以上視覺一致），「中」代表可用（70-90%，部分樣式可能不同），「低」代表僅保留基本文字結構。

| 來源格式 | 轉為 PDF | 轉為 Word | 轉為 PPT | 轉為 HTML | 轉為 Markdown | 轉為純文字 | 轉為圖片 |
|---------|---------|---------|---------|---------|------------|---------|---------|
| PDF | — | 高 | 不支援 | 中 | 中 | 高 | 高 |
| Word (DOCX) | 高 | — | 不支援 | 高 | 高 | 高 | - |
| PowerPoint (PPTX) | 中 | 不支援 | — | 中 | 不支援 | 低 | 高 |
| HTML | 高 | 中 | 不支援 | — | 高 | 高 | - |
| Markdown (MD) | 高 | 高 | 不支援 | 高 | — | 高 | - |
| 純文字 (TXT) | 中 | 中 | 不支援 | 高 | 高 | — | - |
| 圖片 (PNG/JPG) | 高 | - | - | - | - | - | 高 |

說明：
- 「不支援」為設計決策（技術複雜度與實用性權衡），非 bug
- 「-」表示語義上無意義的轉換方向
- PPTX 轉 PDF 為結構仿製，非像素級還原，動畫與過渡效果不保留

---

## PDF 輸出引擎（自動降級鏈）

HTML / Markdown / TXT 轉 PDF 採用四層引擎自動降級，**典型 Windows 11 用戶（含 Edge）零額外安裝**：

| 引擎 | 所需條件 | 輸出品質 |
|------|---------|---------|
| Chrome / Edge headless（首選） | Windows 10/11 預裝 Edge 或已安裝 Chrome | ★★★★★ 完美 |
| wkhtmltopdf | 需手動安裝 wkhtmltopdf | ★★★★ 高 |
| weasyprint | 需安裝 GTK 3 runtime（約 300MB） | ★★★ 中 |
| reportlab（純 Python 後備） | 隨本工具自動安裝 | ★★ 基礎文字排版 |

---

## 已知限制

- PDF 內嵌表格複雜時（PDF→Word）可能錯位
- 掃描版 PDF 的 OCR 輸出純文字（不還原版面）；手寫、低解析度、嚴重歪斜的掃描件辨識率有限
- PPT 動畫、嵌入影片不保留（轉換為靜態內容）
- 單檔 50MB / 批次 200MB 上限
- 圖片去背首次使用需網路下載 AI 模型（約 175MB）；離線環境請先執行 `scripts\predownload_models.py`

---

## 故障排除

| 問題 | 解決方案 |
|------|---------|
| 雙擊 start.bat 顯示「找不到虛擬環境」 | 依「首次安裝」步驟建立 venv 並安裝依賴 |
| `python -m venv venv` 失敗 | 確認 Python 3.10+ 已安裝並加入 PATH；cmd 測試 `python --version` |
| 轉換至 PDF 顯示「轉換失敗」 | 確認系統有 Chrome 或 Edge（Windows 11 預裝 Edge 通常可用）；詳見下方排查 |
| DOCX → PDF 特別慢 | 使用 MS Word COM，首次需啟動 Word 程序，約需 10-20 秒屬正常 |
| DOCX → PDF 排版差異大 | 系統未安裝 Word，已自動降級替代引擎；安裝 Word 後重啟工具即切換高保真模式 |
| 圖片去背第一次特別慢 | 首次需下載 AI 模型（~170MB）；可預先執行 `scripts\predownload_models.py` |
| 轉換後的 PDF 開啟是空白頁 | 來源檔案可能受密碼保護或損壞；先以原始軟體確認可開啟、移除密碼後再試 |
| `import weasyprint` 時 console 看到警告 | Python 3.13 deprecation warning，不影響功能，可忽略 |

### 詳細排查：PDF 輸出失敗（所有引擎均不可用）

系統會自動嘗試 Chrome/Edge headless → wkhtmltopdf → weasyprint → reportlab 四個引擎。**大多數 Windows 10/11 用戶（有 Edge）不會遇到此問題。**

若全部引擎均失敗，依序排查：

1. **確認 Edge 可用**：開始功能表搜尋「Edge」；若未安裝，前往 https://www.microsoft.com/edge
2. **（可選）安裝 wkhtmltopdf**：https://wkhtmltopdf.org/downloads.html
3. **（最後手段）安裝 GTK3**：[GTK3 Windows Installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)，安裝後 weasyprint 引擎即可使用

---

## 打包為獨立 .exe（進階，選用）

若要在沒有 Python 的電腦使用：

1. 雙擊 `build.bat`（自動清理舊產物 → PyInstaller 打包 → 驗證）
2. 產物在 `dist\文件轉檔\`，整個資料夾可複製到其他電腦
3. 雙擊 `文件轉檔.exe` 即可使用

注意：
- 產物約 600MB（含 Python runtime、所有依賴與內建 OCR 模型）
- AI 去背模型（~525MB）不內嵌：首次使用去背時自動下載；要完全離線時，先執行 `scripts\predownload_models.py` 再把 `u2net_models\` 資料夾複製到 exe 同目錄
- DOCX→PDF 高保真模式仍需該電腦安裝 MS Word
- 打包規格詳見 `desktop_build.spec`

---

## 隱私聲明

本工具採用完全本機架構設計：

- 無任何伺服器元件，不監聽任何網路埠
- 所有轉換操作在您的電腦上執行，不傳送至任何外部伺服器
- 不收集任何使用資料或統計資訊（歷史記錄僅存於本機 SQLite）
- 安裝與 AI 模型下載完成後，可在完全離線環境使用

---

## 專案文件

| 文件 | 內容 |
|------|------|
| [專案開發企劃.md](專案開發企劃.md) | 專案定位、開發歷程、維護準則、未來候選方向（backlog） |
| [CHANGELOG.md](CHANGELOG.md) | 各版本變更記錄（Keep a Changelog 格式） |
| [CLAUDE.md](CLAUDE.md) | 架構細節與開發指令（開發者 / AI 協作用） |

---

## 授權與貢獻

本專案採用 **MIT 授權**開放原始碼。您可以自由使用、修改、再發布，包含商業用途，唯須保留原始授權聲明。詳見 [LICENSE](LICENSE) 檔案。

**回報問題或建議：**

若您發現 Bug 或有功能建議，歡迎至 GitHub 回報 Issue。回報時請提供：
- 作業系統版本（例：Windows 11 22H2）
- Python 版本（執行 `python --version` 取得）
- 問題描述與重現步驟
- 錯誤訊息截圖（若有）

---

## 版本歷史

詳見 [CHANGELOG.md](CHANGELOG.md)。

| 版本 | 日期 | 說明 |
|------|------|------|
| v2.2 | 2026-06-11 | 掃描版 PDF 自動 OCR、轉換 Profile 一鍵套用、exe 瘦身（AI 模型改首次使用時下載，~1.1GB→~600MB） |
| v2.1 | 2026-06-09 | PDF 工具頁（合併/分割/壓縮/加密/文字編輯）、圖片去背工具、歷史重轉、托盤、單實例鎖 |
| v2.0 | 2026-04-25 | 從 Flask Web 全面遷移為 PySide6 桌面應用（Fluent Design、7 分頁） |
| v1.1 | 2026-04-24 | PDF 渲染四引擎降級鏈（Edge headless 零安裝輸出 PDF） |
| v1.0 | 2026-04-24 | 初始版本（Flask Web UI）。7 種格式、25+ 轉換方向、批次轉換 |
