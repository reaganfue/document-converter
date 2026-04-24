# 文件轉檔工具

**本機運行 | 永久免費 | 無浮水印 | 無次數限制 | 離線可用**

---

## 簡介

一個完全在您電腦本機運行的多格式文件轉換工具。不需要上傳檔案到任何雲端伺服器，不需要付費，沒有浮水印，沒有次數限制，網路中斷後仍可正常使用（首次安裝除外）。

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

## 系統需求

在安裝前，請確認您的電腦符合以下需求：

- **作業系統**：Windows 10 或 Windows 11（64 位元）
- **Python**：3.10 以上版本（建議 3.12 或 3.13）
  - 下載網址：https://www.python.org/downloads/
  - 安裝時請勾選「Add Python to PATH」
- **瀏覽器**：Chrome 90+、Edge 90+、Firefox 88+、Safari 14+（不支援 Internet Explorer）
- **磁碟空間**：至少 2GB 可用空間（venv + 依賴套件約佔 500MB）
- **Microsoft Word**（選用）：安裝後可啟用 DOCX 轉 PDF 的最高保真模式；未安裝則自動使用替代引擎

---

## 快速開始

### 前置需求

- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/)（安裝時**勾選 "Add Python to PATH"**）

### 三步驟啟動

1. 下載本專案到任意資料夾
2. 雙擊 `start.bat`
   - 首次啟動會自動建立虛擬環境並安裝依賴（約 2-5 分鐘）
   - 日常啟動只需 5-10 秒
3. 瀏覽器自動開啟 http://localhost:5000，開始使用

---

## 介面預覽

暗色模式（預設）：
![首頁暗色](docs/screenshots/01_home_dark.png)

亮色模式：
![首頁亮色](docs/screenshots/02_home_light.png)

轉換完成：
![轉換完成](docs/screenshots/03_conversion_done.png)

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
- 「不支援」的轉換方向在 v1.0 版本中未實作（技術複雜度較高，規劃於 v2.0 版本加入）
- 「-」表示語義上無意義的轉換方向
- PPTX 轉 PDF 為結構仿製，非像素級還原，動畫與過渡效果不保留

---

## 實測轉換品質

### PDF 輸出開箱即用（v1.1.0 起）

v1.1.0 新增多層 PDF 渲染降級鏈，**在含 Chrome 或 Edge 的環境下無需手動安裝任何額外 runtime**：

| 引擎 | 所需條件 | 輸出品質 |
|------|---------|---------|
| Chrome / Edge headless（首選） | Windows 10/11 預裝 Edge 或已安裝 Chrome | ★★★★★ 完美 |
| wkhtmltopdf | 需手動安裝 wkhtmltopdf | ★★★★ 高 |
| weasyprint | 需安裝 GTK 3 runtime（約 300MB） | ★★★ 中 |
| reportlab（純 Python 後備） | 隨本工具自動安裝 | ★★ 基礎文字排版 |

**典型 Windows 11 用戶（含 Edge）：自動使用 Edge headless，零額外安裝。**

### 完全可用（所有依賴已安裝、無需 GTK）

- PDF → Word / HTML / Markdown / TXT / 圖片
- Word → HTML / Markdown / TXT
- PPT → HTML / TXT / 圖片
- **HTML → PDF**（自動使用 Chrome/Edge headless）
- **Markdown → PDF**（自動使用 Chrome/Edge headless）
- **TXT → PDF**（自動使用 Chrome/Edge headless）
- HTML → Markdown / TXT / Word
- Markdown → HTML / Word / TXT
- TXT → 各格式
- 圖片 → PDF / 其他圖片格式

### 需要額外依賴的轉換

- **Word → PDF**：需安裝 MS Word（已自動偵測）；未安裝時降級至替代引擎
- **任何 → PDF（若 Chrome/Edge 均未安裝）**：需安裝 GTK 3 runtime 或 wkhtmltopdf（見故障排除）

### 已知限制

- PDF 內嵌表格複雜時（PDF→Word）可能錯位
- 掃描版 PDF 目前不支援 OCR（計畫 v2.0）
- PPT 動畫、嵌入影片不保留（轉換為靜態內容）
- 單檔 50MB / 批次 200MB 上限

---

## 使用方式

**基本操作流程：**

1. 雙擊 `start.bat` 啟動工具，瀏覽器自動開啟至 http://localhost:5000
2. 將檔案拖放到網頁中央的拖放區域（或點選區域手動選擇檔案）
3. 從下拉選單選擇目標格式（例如：PDF 轉 Word）
4. 點選「開始轉換」按鈕
5. 等待進度條完成後，點選「下載」按鈕取得轉換結果

**批次轉換：**

可同時拖放最多 20 個檔案一次轉換，所有檔案轉換完成後以 ZIP 壓縮包下載。

**轉換限制：**

- 單一檔案最大 50MB
- 單次轉換總大小最大 200MB
- 建議單次不超過 20 個檔案

---

## 故障排除

| 問題 | 解決方案 |
|------|---------|
| 雙擊 start.bat 沒反應 | 確認 Python 3.10+ 已安裝並加入 PATH；cmd 測試 `python --version` |
| 首次安裝依賴超過 5 分鐘 | 網路慢，耐心等；或查看 cmd 視窗錯誤訊息 |
| `pip install weasyprint` 失敗 | v1.1.0 起已不依賴 weasyprint（有 Chrome/Edge 即可）。若仍需安裝，參考 [weasyprint Windows 文件](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) |
| 轉換至 PDF 顯示「轉換失敗」 | 確認系統有安裝 Chrome 或 Edge（Windows 11 預裝 Edge 通常可用）。詳見「PDF 輸出失敗」排查節 |
| DOCX → PDF 特別慢 | 使用 MS Word COM，首次需啟動 Word 程序，約需 10-20 秒屬正常 |
| 瀏覽器沒自動打開 | 手動輸入 http://localhost:5000；或檢查是否 port 被佔用 |
| Port 5000 被佔用 | cmd 執行 `netstat -ano \| findstr :5000` 找佔用的 PID，再 `taskkill /PID <pid> /F` |
| 中文檔名亂碼 | start.bat 已用 chcp 65001；若仍亂碼請先將檔案改為英文檔名再轉換 |
| 關閉 cmd 視窗後轉檔失效 | 伺服器已停止；重新雙擊 start.bat 啟動 |
| 已完成轉檔的檔案消失 | 正常行為：完成 60 秒後自動清理；建議立即下載 |
| `import weasyprint` 時 console 看到警告 | 這是 Python 3.13 deprecation warning，不影響功能，可忽略 |
| 雙擊 start.bat 顯示「未偵測到 Python」 | Python 未安裝，或安裝時未勾選「Add Python to PATH」。前往 https://www.python.org/downloads/ 重新安裝並勾選 PATH 選項 |

### 詳細問題：PDF 輸出失敗（所有引擎均不可用）

v1.1.0 起，系統會自動嘗試 Chrome/Edge headless → wkhtmltopdf → weasyprint → reportlab 四個引擎降級。**大多數 Windows 10/11 用戶（有 Edge）不會遇到此問題。**

若全部引擎均失敗（錯誤訊息：「所有 PDF 渲染引擎失敗」），請依序排查：

**排查 A：確認 Chrome 或 Edge 可用**
- 開啟「開始功能表」，搜尋「Edge」確認已安裝
- 若未安裝，前往 https://www.microsoft.com/edge 下載

**排查 B（可選）：安裝 wkhtmltopdf**
1. 前往 https://wkhtmltopdf.org/downloads.html
2. 下載 Windows 安裝檔並執行
3. 重新啟動本工具

**排查 C（最後手段）：安裝 GTK3 for Windows**
1. 前往 [GTK3 Windows Installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
2. 下載最新版 `.exe` 安裝檔並執行
3. 重新啟動本工具後 weasyprint 引擎即可使用

### 詳細問題：DOCX 轉 PDF 結果與原始格式差異大

原因：系統未安裝 Microsoft Word，本工具使用替代引擎（weasyprint）進行轉換，複雜排版無法完全還原。

解決方式：
1. 安裝 Microsoft Word 後，重新啟動工具，系統會自動偵測並切換至高保真模式
2. 若無法安裝 Word，目前的替代引擎結果已是最佳品質

### 詳細問題：轉換後的 PDF 開啟後是空白頁面

原因：來源檔案可能受密碼保護，或檔案內容損壞。

解決方式：
1. 確認來源檔案可以正常開啟
2. 若是密碼保護的檔案，需先移除密碼保護後再轉換
3. 若檔案損壞，請嘗試以原始軟體（如 Word、Acrobat）重新儲存後再上傳

---

## 離線運行說明

本工具設計為安裝完成後**完全離線可用**：

- 所有前端資源（Tailwind CSS、Alpine.js）均已下載至 `static/` 本機目錄
- 無任何 CDN 引用（驗證：`grep -r "cdn." templates/` 無結果）
- Flask 僅監聽 `localhost:5000`，不建立任何對外連線
- 轉換引擎（PyMuPDF、pdf2docx、python-docx 等）均為本機套件

**首次安裝**需要網路（pip 下載依賴）。安裝完成後可完全離線使用。

### 離線安裝（無網路環境）

若您的環境無法連接網路，可以事先在有網路的機器下載所有依賴的 wheel 套件，再複製到目標機器進行離線安裝。

**在有網路的機器上執行：**

```
mkdir wheels
pip download -r requirements.txt -d wheels
```

執行完成後，將整個 `wheels\` 資料夾複製到「文件轉檔」目錄中。

**後續操作：**

將 `wheels\` 資料夾放入「文件轉檔」目錄後，`start.bat` 啟動時會自動偵測並切換為離線安裝模式，無需額外設定。

---

## 打包為獨立 .exe（進階，選用）

若要分發給沒有 Python 的用戶：

1. `pip install pyinstaller`
2. `pyinstaller build.spec`
3. 產物在 `dist/文件轉檔/`，整個資料夾可壓縮發給他人
4. 對方雙擊 `文件轉檔工具.exe` 即可使用
5. 首次啟動約 5 秒（需解壓資源）

注意：
- 產物約 300-500MB（含所有依賴）
- 仍需 MS Word（若要 DOCX→PDF）或 GTK runtime（若要輸出 PDF）
- 詳見專案根目錄的 `build.spec` 規格檔

---

## 技術架構

本工具由以下主要元件組成：

**Web 框架**：Flask 3.0（輕量 Python Web 框架），監聽 localhost:5000，不對外暴露。

**轉換引擎鏈**：不同格式對使用不同的轉換函式庫。PDF 相關操作使用 PyMuPDF（高效能 PDF 渲染）和 pdf2docx（PDF 轉 Word）；Office 格式使用 python-docx、python-pptx 讀取結構後重組輸出；HTML 轉 PDF 使用 weasyprint（支援 CSS3）；Markdown 使用 markdown 函式庫解析後轉換；圖片處理使用 Pillow。每對轉換都設計了首選路徑與降級備援路徑，確保即使首選引擎失敗仍能產出結果。

**非同步處理**：使用 Python 的 ThreadPoolExecutor（最多 4 個執行緒），多個檔案可同時轉換，前端透過輪詢 API 即時更新進度。

**臨時檔案管理**：所有上傳和輸出檔案存放在本機 uploads/ 和 outputs/ 目錄，轉換完成後自動清理（成功後 60 秒、失敗後 300 秒），啟動時亦會清理 6 小時前的遺留檔案。

---

## 隱私聲明

本工具採用完全本機架構設計：

- 所有上傳的檔案僅存放在您的電腦本機（uploads/ 目錄）
- 所有轉換操作在您的電腦上執行，不傳送至任何外部伺服器
- 轉換完成的檔案下載後，本工具會自動清理本機暫存
- 本工具不收集任何使用資料或統計資訊
- 啟動後如需離線使用，可關閉網路連線（首次安裝已完成的情況下）

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
| v1.0 | 2026-04-24 | 初始版本。支援 7 種格式、25+ 轉換方向、拖放介面、批次轉換、非同步進度顯示 |
