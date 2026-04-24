# 錯誤知識庫 — 文件轉檔工具專案（W-CONV）

> debugger 即時錯誤記錄 | 供所有 agent 在執行前掃描參考

---

## ERR-20260425-001

- **日期**: 2026-04-25
- **task_id**: W-CONV-P-debug-A（post-onboarder session）
- **錯誤類型**: env (Windows CMD encoding)
- **錯誤訊息**:

```
隢銝?蝬脣?銝?銝血?鋆?Python 3.10 隞乩??嚗?
    echo   https://www.python.org/downloads/
'砌???3.10嚗?????3.10' 不是內部或外部命令、可執行的程式或批次檔。
'?憭橘?雿輻?Ｙ?璅∪?摰?...' 不是內部或外部命令、可執行的程式或批次檔。
'b' 不是內部或外部命令、可執行的程式或批次檔。
'ut' 不是內部或外部命令、可執行的程式或批次檔。
'cho' 不是內部或外部命令、可執行的程式或批次檔。
```

- **影響檔案**: `start.bat`
- **根因分析**: `start.bat` 原本雖然在第 2 行有 `chcp 65001 > nul`（切換 CMD 代碼頁至 UTF-8），但檔案本身是 **UTF-8 無 BOM + LF 換行符（Unix 樣式）**。CMD 開始解析批次檔時，尚未執行 `chcp` 之前以系統預設代碼頁（繁中 Windows 為 CP950/Big5）解讀整個檔案結構，加上 LF 換行（而非 Windows 標準 CRLF）導致 CMD 對中文字在位元組層級的邊界判定錯誤，把中文字的 UTF-8 多字節序列切開後殘餘字節被誤判為命令名稱（如 `'b'`、`'ut'`、`'cho'`）。
- **解決方案**:
  1. 保留 `chcp 65001 > nul` 在第 2 行（運行時期切換 CP）
  2. **檔案編碼改為 UTF-8 with BOM**（開頭 3 byte `EF BB BF`）— 讓 CMD 識別 UTF-8 編碼的提示信號
  3. **換行符改為 CRLF**（`0D 0A`）— Windows 批次檔標準，避免 CMD 在 LF 下誤判行邊界
  4. 使用 Python 重新寫入檔案確保精確位元組格式：

     ```python
     text = open('start.bat', 'rb').read().decode('utf-8')
     text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
     with open('start.bat', 'wb') as f:
         f.write(b'\xef\xbb\xbf')  # UTF-8 BOM
         f.write(text.encode('utf-8'))
     ```

- **預防措施**:
  1. 所有含中文的 Windows 批次檔（`.bat` / `.cmd`）必須遵守三條件：
     - 檔案編碼 = **UTF-8 with BOM**（避免 CP950 默認解讀）
     - 換行符 = **CRLF**（Windows 標準）
     - 首行切換 = `@echo off` 後立即 `chcp 65001 > nul`
  2. 產生或修改 `.bat` 檔時使用 `file <path>` 或 `hexdump -C <path> | head` 驗證 BOM 與 CRLF
  3. CI/pre-commit 可加入 `.bat` 檔靜態檢查：開頭必須為 `EF BB BF`，所有換行必須為 `0D 0A`
  4. 若跨平台編輯器（VS Code / Sublime / 非 Windows）存檔，需在設定中固定 `.bat` 存檔格式為 UTF-8 BOM + CRLF
- **是否為已知問題**: 否（首次在本專案出現）
- **標籤**: #env #windows #batch #encoding #utf-8 #cp950 #bom #crlf #lf

---

## ERR-20260425-002

- **日期**: 2026-04-25
- **task_id**: W-DESKTOP-P4.5B（code-reviewer C-DESK-001 → implementer 修復）
- **錯誤類型**: runtime (Windows subprocess)
- **錯誤訊息**:

```
# 症狀：呼叫 explorer /select, 後只開啟父資料夾，未選取檔案
subprocess.run(['explorer', '/select,', str(output_path)], check=False)
# 部分 Windows 版本靜默失敗（開啟父目錄而非選取目標檔案）
```

- **影響檔案**: `desktop/widgets/file_card.py`
- **根因分析**: `subprocess.run(['explorer', '/select,', path])` 將 `/select,` 與路徑分成兩個獨立引數。Windows explorer 的 `/select,` switch 要求逗號與路徑緊接在同一個引數字串中（`/select,C:\path\to\file`）。當逗號與路徑分離時，部分 Windows 10/11 版本會靜默忽略 path 引數，只開啟父目錄。此外，使用 `str(path)` 而非 `path.resolve()` 可能產生相對路徑，在某些情況下 explorer 無法正確解析。
- **解決方案**:
  1. 將 `/select,` 與路徑合併為單一 f-string 引數：
     ```python
     target = self._output_path.resolve()
     if target.exists():
         subprocess.run(['explorer', f'/select,{target}'], check=False, shell=False)
     else:
         # fallback：開啟父目錄
         subprocess.run(['explorer', str(target.parent)], check=False, shell=False)
     ```
  2. 使用 `.resolve()` 確保絕對路徑
  3. 保持 `shell=False`（防止路徑含特殊字元的 shell injection）
  4. 加入 `exists()` 檢查，檔案不存在時 fallback 開父目錄
- **預防措施**:
  1. Windows 上呼叫 explorer 的特殊 switch（如 `/select,`）時，逗號/斜線語法必須在**同一個引數字串**內，不可分割為多個 list 元素
  2. subprocess 引數含路徑時，優先使用 `.resolve()` 產生絕對路徑
  3. 靜態審查時重點關注 `subprocess.run([..., '/select,', path, ...])` 的引數分割模式
- **是否為已知問題**: 否（首次在本專案出現）
- **標籤**: #runtime #windows #subprocess #explorer #path #shell

---

## ERR-20260425-003

- **日期**: 2026-04-25
- **task_id**: W-DESKTOP-P2 系列（PySide6 import 邊界）
- **錯誤類型**: runtime (PySide6 import)
- **錯誤訊息**:

```python
from PySide6.QtWidgets import QShortcut
# ImportError: cannot import name 'QShortcut' from 'PySide6.QtWidgets'
```

- **影響檔案**: 任何使用 `QShortcut` 的 PySide6 檔案
- **根因分析**: PySide6 與 PyQt5 的 Widget/Gui 模組分工不同。在 PyQt5 中 `QShortcut` 位於 `QtWidgets`；在 PySide6 中 `QShortcut` 已移至 `QtGui`。直接從 PyQt5 文件或示例複製的 import 語句在 PySide6 中會失敗。同樣的 import 差異還存在於 `QAction`（PyQt5 在 QtWidgets，PySide6 在 QtGui）等類別。
- **解決方案**:
  ```python
  # 錯誤（PyQt5 寫法，在 PySide6 中失敗）
  from PySide6.QtWidgets import QShortcut
  
  # 正確（PySide6）
  from PySide6.QtGui import QShortcut
  
  # 同樣的差異：QAction
  from PySide6.QtGui import QAction  # 而非 QtWidgets
  ```
- **預防措施**:
  1. 從 PyQt5 遷移到 PySide6 時，驗證所有 `QtWidgets` import 中的類別，確認哪些已移至 `QtGui`
  2. 受影響的主要類別清單：`QShortcut`、`QAction`、`QRegularExpressionValidator`（部分版本）
  3. 遷移計畫中加入「PySide6 import 對照驗證」步驟，可使用 `python -c "from PySide6.QtWidgets import X"` 快速驗證
  4. 若需要同時支援 PyQt5 和 PySide6，可使用 qtpy 或 Qt.py 作為抽象層
- **是否為已知問題**: 否（首次在本專案出現）
- **標籤**: #runtime #pyside6 #pyqt5 #import #migration #qshortcut #qaction

---

## ERR-20260425-004

- **日期**: 2026-04-25
- **task_id**: W-DESKTOP-P4B（code-reviewer C-DESK-004 → P4.5A 修復）
- **錯誤類型**: runtime (UI state management)
- **錯誤訊息**:

```
# 症狀：第二批檔案拖入後，進度條從已完成 K/N 跳回 0/N
# 根因：_on_job_added 中有 self._completed_count = 0
```

- **影響檔案**: `desktop/main_window.py`
- **根因分析**: `_completed_count` 是一個手動維護的累計計數器，在每次 `_on_job_added`（新任務加入）時被重置為 0。這在單批次使用時表現正常，但在多批次拖入（第一批完成後再拖入第二批）時導致進度計數倒退（已完成的 K 個任務被忘記，顯示 0/N）。同時 `_refresh_global_progress` 內已有從 `controller._jobs` 即時計算 completed 的邏輯（正確），造成雙重狀態，且累計計數器是「錯的那個」。
- **解決方案**:
  1. 完全移除 `_completed_count` 成員變數及所有賦值（`= 0`、`+= 1`）
  2. 在 `_refresh_global_progress` 中使用一個 for 迴圈即時計算所有需要的計數：
     ```python
     def _refresh_global_progress(self):
         completed = 0
         in_progress_sum = 0.0
         has_active = False
         for card in self._file_cards.values():
             snap = card.snapshot()
             if snap.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                 completed += 1
             elif snap.status == JobStatus.RUNNING:
                 has_active = True
                 in_progress_sum += snap.progress
         # 使用 completed 更新 UI
     ```
  3. `_on_remove_job` 改為直接呼叫 `_refresh_global_progress()` 而非手動調整計數器
- **預防措施**:
  1. UI 進度狀態只設置一個 Source of Truth（controller 的 jobs dict），進度 widget 永遠從此即時計算，不做二次快取計數器
  2. 若有多個地方維護同一份「完成數量」的計數，務必審查：哪個是 source，哪個是 cache？Cache 更新時機是否覆蓋了所有狀態變化路徑（new / complete / fail / remove）？
  3. 靜態審查時關注「在事件 handler 中重置計數器」的 pattern（`self._count = 0` 在 on_item_added 中）
- **是否為已知問題**: 否（首次在本專案出現）
- **標籤**: #runtime #ui #state-management #pyside6 #progress #counter #single-source-of-truth

---

## ERR-20260425-005

- **日期**: 2026-04-25
- **task_id**: W-DESKTOP-P-regression-A（雙擊 start.bat 啟動失敗）
- **錯誤類型**: env (Windows CMD Unix 語法污染 + BOM 顯示)
- **錯誤訊息**:

```
C:\...文件轉檔>嚜濃echo off
'嚜濃echo' 不是內部或外部命令、可執行的程式或批次檔。

C:\...文件轉檔>chcp 65001  1>/dev/null
系統找不到指定的路徑。

C:\...文件轉檔>where python  1>/dev/null 2>/dev/null
系統找不到指定的路徑。

C:\...文件轉檔>if errorlevel 1 (
 [錯誤] 未偵測 Python 3.10 以上版本
)
```

- **影響檔案**: `start.bat`, `build.bat`
- **根因分析**: 兩個互相獨立但同時發生的回歸缺陷：
  1. **Unix 重定向語法污染**：implementer 在 Round 3.B 重寫 `start.bat` 時，誤將 Windows 重定向寫成 Unix 風格 `>/dev/null`。Windows CMD 將 `/dev/null` 當成不存在的路徑（`系統找不到指定的路徑`），`chcp` / `where python` 等指令全數失敗，errorlevel 被錯誤設為 1，誤觸發「未偵測 Python」分支。
  2. **BOM 顯示為亂碼**：檔案雖為 UTF-8 with BOM（符合 ERR-20260425-001 的策略），但用戶實測時 CMD 在執行 `chcp 65001` 之前（此時仍為 CP950/Big5 代碼頁）直接 echo 出 `@echo off`，BOM 的 `EF BB BF` 三 byte 被 CP950 解讀為 `嚜濃`，加上 `@` 未被靜音，完整顯示為 `嚜濃echo off`。這推翻了 ERR-20260425-001「UTF-8 with BOM 是萬靈丹」的結論——**在某些 Windows 環境 / Terminal 組合下，BOM 反而造成亂碼**。
- **解決方案**:
  1. **移除 BOM**：檔案改為純 UTF-8 無 BOM（不再寫入 `EF BB BF`）
  2. **首兩行保持純 ASCII**：
     - Line 1: `@echo off`（`@` 會抑制該行 echo）
     - Line 2: `chcp 65001 >nul`（Windows 原生重定向）
     - 中文內容放在 Line 3 之後，此時代碼頁已切換為 UTF-8
  3. **所有重定向改為 Windows 原生語法**：
     - `>/dev/null` → `>nul`
     - `2>/dev/null` → `2>&1`
     - `where python >/dev/null 2>/dev/null` → `where python >nul 2>&1`
  4. **保留 CRLF 換行**（Windows 標準）
- **預防措施**:
  1. **CEO 派發 implementer 寫 .bat 檔案時，prompt 必須明示**：
     - 「使用 Windows CMD 原生重定向：`>nul` / `2>nul` / `2>&1`」
     - 「禁用 Unix 語法：`/dev/null` / `$VAR` / `&&` / `||`」
  2. **產出 .bat 後自動驗證**（integrate into Phase 4 verification）：
     - `grep -c /dev/null *.bat` 必須為 0
     - 首行必須為 `@echo off`，第二行必須為 `chcp 65001 >nul`（純 ASCII）
  3. **BOM 策略修正（覆蓋 ERR-20260425-001）**：
     - 舊策略：UTF-8 with BOM + CRLF
     - **新策略：UTF-8 無 BOM + CRLF + 首兩行純 ASCII + `chcp 65001 >nul` 在第二行**
     - 原因：有 BOM 時，某些 CMD 環境會在 `chcp` 執行前以 CP950 解讀 BOM，顯示為 `嚜濃`
  4. **sandbox 踩坑警示**：若使用 Python 透過 shell 寫入 .bat 檔，注意 sandbox 可能自動將 `>nul` 字串轉換為 `>/dev/null`（Unix 化），應使用 `chr(62) + "nul"` 等字串拼接繞過
- **是否為已知問題**: 部分（ERR-20260425-001 涉及編碼，但 BOM 結論被本事件覆蓋；Unix 語法污染為首次）
- **標籤**: #env #windows #batch #cmd #unix-syntax-pollution #bom #regression #cp950

---
