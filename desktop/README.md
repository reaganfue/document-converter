# desktop/ 套件 — 文件轉檔桌面應用

> **Round 2 並行協作指南** — 請在開始實作前完整閱讀此文件。

## 架構概覽

```
desktop/
├── interfaces.py           ← Signal 契約（Single Source of Truth，禁止修改已有 Signal）
├── main.py                 ← 應用入口
├── main_window.py          ← 主視窗（Round 3 整合）
├── widgets/                ← UI 元件（widgets-1 + widgets-2 負責）
│   ├── drop_zone.py        ← widgets-1
│   ├── file_card.py        ← widgets-1
│   ├── format_selector.py  ← widgets-2
│   ├── progress_widget.py  ← widgets-2
│   └── settings_dialog.py  ← widgets-2
├── controllers/            ← 業務邏輯（controllers 代理負責）
│   ├── conversion_controller.py
│   └── job_manager.py
├── utils/                  ← 工具函式（utils 代理負責）
│   ├── theme.py
│   └── paths.py
└── resources/
    ├── icons/              ← SVG 圖示（Round 2 從 static/icons 複製）
    └── styles.qss          ← 客製 QSS 樣式
```

---

## interfaces.py — Signal 契約（關鍵）

**Round 2 代理的黃金法則：**
- 不得修改已有的 Signal 簽名
- 不得刪除已有的 Signal
- 可以新增 Signal，但需同步更新此 README

### Widget Signals 一覽

| 類別 | Signal | 參數 | 說明 |
|------|--------|------|------|
| `DropZoneSignals` | `files_dropped` | `list[Path]` | 使用者拖入/選擇的檔案 |
| `DropZoneSignals` | `open_dialog_requested` | 無 | 點擊「選擇檔案」 |
| `FileCardSignals` | `remove_requested` | `str` (job_id) | 移除任務 |
| `FileCardSignals` | `target_format_changed` | `str, str` (job_id, fmt) | 切換輸出格式 |
| `FormatSelectorSignals` | `format_selected` | `str` (fmt) | 全域格式選擇 |
| `ProgressWidgetSignals` | `cancel_requested` | `str` (job_id) | 取消任務 |
| `SettingsDialogSignals` | `settings_applied` | `dict` | 套用設定 |

### Controller Signals 一覽

| 類別 | Signal | 參數 | 說明 |
|------|--------|------|------|
| `ConversionControllerSignals` | `job_added` | `ConversionJob` | 新任務加入 |
| `ConversionControllerSignals` | `job_progress` | `str, float` (id, 0-1) | 進度更新 |
| `ConversionControllerSignals` | `job_status_changed` | `str, str` (id, status) | 狀態變更 |
| `ConversionControllerSignals` | `job_completed` | `str, Path` (id, path) | 完成 |
| `ConversionControllerSignals` | `job_failed` | `str, str` (id, msg) | 失敗 |
| `ConversionControllerSignals` | `all_completed` | 無 | 全部完成 |

---

## ConversionJob 生命週期

```
[拖入檔案]
    │
    ▼
IDLE ──→ (ConversionController.add_files) ──→ PENDING
    │
    ▼
PENDING ──→ (JobManager.pop_next + Worker 啟動) ──→ CONVERTING
    │
    ├──→ DONE    (job_completed Signal)
    └──→ ERROR   (job_failed Signal)
```

**狀態轉換規則：**
- IDLE：只在 ConversionJob 初始化時存在，立刻轉為 PENDING
- PENDING：已排隊等待執行，可被取消
- CONVERTING：Worker 正在執行，可被中斷（盡力而為）
- DONE / ERROR：終態，不可轉換

---

## Round 2 代理職責範圍

### widgets-1（DropZone + FileCard）

**職責檔案：**
- `desktop/widgets/drop_zone.py`
- `desktop/widgets/file_card.py`

**實作項目：**
1. `DropZone.dragEnterEvent` / `dragMoveEvent` / `dropEvent`
2. `DropZone` 三種視覺狀態（idle / hover / dropping）
3. `DropZone` 點擊觸發 QFileDialog
4. `FileCard.update_status(job)` — 更新進度條與狀態文字
5. `FileCard` 目標格式 ComboBox（從 `get_supported_targets` 填充）
6. 從 `resources/icons/` 載入格式圖示

**禁止（widgets-1）：**
- 不修改 `format_selector.py` / `progress_widget.py` / `settings_dialog.py`
- 不修改 `interfaces.py` 已有的 Signal 簽名

---

### widgets-2（FormatSelector + ProgressWidget + SettingsDialog）

**職責檔案：**
- `desktop/widgets/format_selector.py`
- `desktop/widgets/progress_widget.py`
- `desktop/widgets/settings_dialog.py`
- `desktop/resources/styles.qss`（可選補充）

**實作項目：**
1. `FormatSelector` 替換為 QFluentWidgets ComboBox
2. `ProgressWidget` 替換為 QFluentWidgets ProgressBar
3. `ProgressWidget.update_progress(completed, total, overall)` — 更新顯示
4. `ProgressWidget` 全部完成時顯示 StateToolTip
5. `SettingsDialog` 替換為 QFluentWidgets SettingCard 系列
6. `SettingsDialog` 資料夾選擇按鈕（QFileDialog）

**禁止（widgets-2）：**
- 不修改 `drop_zone.py` / `file_card.py`
- 不修改 `interfaces.py` 已有的 Signal 簽名

---

### controllers（ConversionController + JobManager）

**職責檔案：**
- `desktop/controllers/conversion_controller.py`
- `desktop/controllers/job_manager.py`

**實作項目：**
1. `ConversionController.add_files(paths)` — 建立 ConversionJob + 發 job_added
2. `ConversionController.start_conversion()` — 啟動 QThreadPool Workers
3. `ConversionController.cancel_job(job_id)` — 取消指定 Job
4. Worker（QRunnable）呼叫 `converters.dispatcher.convert_file`
5. Worker 完成後發出 job_completed / job_failed Signal
6. `JobManager` 已完整實作，直接使用即可

**converters.dispatcher 介面（假設）：**
```python
from converters.dispatcher import convert_file
output_path = convert_file(
    source_path=Path("input.docx"),
    target_format="pdf",
    output_dir=Path("outputs/"),
)
# 成功回傳 Path；失敗拋出 Exception
```

**禁止（controllers）：**
- 不修改 `interfaces.py` 已有的 Signal 簽名
- 不直接 import `desktop.widgets.*`（避免循環依賴）

---

### utils（theme + paths）

**職責檔案：**
- `desktop/utils/theme.py`
- `desktop/utils/paths.py`

**實作項目：**
1. `apply_theme(mode)` — 呼叫 `qfluentwidgets.setTheme` + `setThemeColor("#8B5CF6")`
2. `get_system_theme()` — 使用 `darkdetect.isDark()`
3. `paths.py` 已完整實作，可直接使用（不需修改）

**禁止（utils）：**
- 不 import 任何 `desktop.widgets.*` 或 `desktop.controllers.*`（避免循環依賴）

---

## 快捷鍵規格（Round 3 整合）

| 快捷鍵 | 動作 | 負責代理 |
|--------|------|---------|
| `Ctrl+O` | 開啟檔案對話框 | Round 3 |
| `F5` | 開始轉換 | Round 3 |
| `Delete` | 移除選中的 FileCard | Round 3 |
| `Ctrl+,` | 開啟設定對話框 | Round 3 |

---

## 依賴版本

| 套件 | 版本 |
|------|------|
| PySide6 | 6.11.0 |
| PySide6-Fluent-Widgets | 1.11.2 |
| shiboken6 | 6.11.0 |

---

## 驗證指令（Round 2 完成後執行）

```bash
# import 鏈驗證
venv/Scripts/python.exe -c "from desktop.main_window import MainWindow; print('OK')"
venv/Scripts/python.exe -c "from desktop.widgets import DropZone, FileCard, FormatSelector, ProgressWidget, SettingsDialog; print('OK')"
venv/Scripts/python.exe -c "from desktop.controllers import ConversionController, JobManager; print('OK')"
```
