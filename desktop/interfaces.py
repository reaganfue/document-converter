"""
Signal/Slot 契約定義 — Round 2 並行代理必須嚴格遵守此介面。

此檔案是唯一的跨模組合約來源（Single Source of Truth），
所有 widget 和 controller 的 Signal 定義都集中於此。

Round 2 代理禁止修改已有的 Signal 簽名，只可新增。
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# 枚舉與資料類型
# ---------------------------------------------------------------------------

class JobStatus(Enum):
    """ConversionJob 生命週期狀態。"""
    IDLE = "idle"
    PENDING = "pending"
    CONVERTING = "converting"
    DONE = "done"
    ERROR = "error"


@dataclass
class ConversionJob:
    """一個轉換任務的完整狀態快照。

    job_id 唯一識別此任務，由 ConversionController 在建立時指派（UUID4 前 8 碼）。
    source_path 是使用者拖入的原始檔案絕對路徑。
    output_path 在任務完成後由 ConversionController 填入。
    """

    job_id: str
    source_path: Path
    source_format: str          # 小寫無點，例如 "pdf" / "docx" / "png"
    target_format: str          # 小寫無點
    output_path: Optional[Path] = None
    status: JobStatus = JobStatus.IDLE
    progress: float = 0.0       # 0.0 – 1.0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Widget Signal 契約
# ---------------------------------------------------------------------------

class DropZoneSignals(QObject):
    """DropZone Widget 對外發出的 Signal。

    files_dropped: 使用者拖入或透過檔案對話框選擇的檔案路徑清單。
    open_dialog_requested: 使用者點擊「選擇檔案」按鈕或按 Ctrl+O。
    """

    files_dropped = Signal(list)          # list[Path]
    open_dialog_requested = Signal()


class FileCardSignals(QObject):
    """FileCard Widget 對外發出的 Signal。

    remove_requested: 使用者按刪除或 Delete 鍵，需從佇列移除指定 job。
    target_format_changed: 使用者在卡片上直接切換目標格式。
    """

    remove_requested = Signal(str)            # job_id
    target_format_changed = Signal(str, str)  # job_id, target_format


class FormatSelectorSignals(QObject):
    """FormatSelector Widget 對外發出的 Signal。

    format_selected: 使用者選擇了新的輸出格式（套用至當前全部未開始任務）。
    """

    format_selected = Signal(str)    # target_format（小寫無點）


class ProgressWidgetSignals(QObject):
    """ProgressWidget 對外發出的 Signal。

    cancel_requested: 使用者取消某個正在進行的任務。
    """

    cancel_requested = Signal(str)   # job_id


# ---------------------------------------------------------------------------
# Controller Signal 契約
# ---------------------------------------------------------------------------

class ConversionControllerSignals(QObject):
    """ConversionController 對外發出的 Signal。

    job_added:          新任務建立後發送（含完整 ConversionJob 物件）。
    job_progress:       任務進度更新（0.0 – 1.0）。
    job_status_changed: 任務狀態轉換（IDLE→PENDING→CONVERTING→DONE/ERROR）。
    job_completed:      任務成功完成，附帶輸出路徑。
    job_failed:         任務失敗，附帶錯誤訊息字串。
    all_completed:      佇列中所有任務均完成（DONE 或 ERROR）。
    """

    job_added = Signal(object)              # ConversionJob（避免 Qt 型別不符）
    job_progress = Signal(str, float)       # job_id, progress (0.0–1.0)
    job_status_changed = Signal(str, str)   # job_id, JobStatus.value
    job_completed = Signal(str, object)     # job_id, output_path (Path)
    job_failed = Signal(str, str)           # job_id, error_message
    all_completed = Signal()


# ---------------------------------------------------------------------------
# 支援的格式宣告
# ---------------------------------------------------------------------------

SUPPORTED_INPUT_FORMATS: list[str] = [
    "pdf", "docx", "pptx", "html", "md", "txt",
    "png", "jpg", "jpeg", "gif", "webp",
]

SUPPORTED_OUTPUT_FORMATS: list[str] = [
    "pdf", "docx", "pptx", "html", "md", "txt", "png",
]

# 格式相容性矩陣（Round 2 ConversionController 會從 converters.dispatcher 動態補充）
_FORMAT_MATRIX: dict[str, list[str]] = {
    "pdf":  ["docx", "txt", "md", "html", "png"],
    "docx": ["pdf", "txt", "md", "html"],
    "pptx": ["pdf", "png"],
    "html": ["pdf", "docx", "md", "txt"],
    "md":   ["pdf", "docx", "html", "txt"],
    "txt":  ["pdf", "docx", "md", "html"],
    "png":  ["pdf"],
    "jpg":  ["pdf"],
    "jpeg": ["pdf"],
    "gif":  ["pdf"],
    "webp": ["pdf"],
}


def get_supported_targets(source_format: str) -> list[str]:
    """給定來源格式，回傳可轉換的目標格式清單。

    Round 1 使用靜態矩陣；Round 2 ConversionController
    應改為從 converters.dispatcher.get_supported_conversions() 動態取得。

    Args:
        source_format: 來源格式，小寫無點（例如 "pdf"）。

    Returns:
        目標格式字串清單；若來源不支援則回傳空清單。
    """
    return _FORMAT_MATRIX.get(source_format.lower(), [])


# ============================================================================
# W-COMMERCIAL 擴充（Round 2 append-only — 不影響 Round 1/2 既有契約）
# ============================================================================

from enum import Enum as _EnumCommercial


class NotificationLevel(_EnumCommercial):
    """通知嚴重程度等級。"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class PageID(_EnumCommercial):
    """分頁 ID — MainWindowV2 導航路由鍵。"""
    HOME = "home"
    BATCH = "batch"
    HISTORY = "history"
    SETTINGS = "settings"
    ABOUT = "about"
    PDF_TOOLS = "pdf_tools"
    IMAGE_TOOLS = "image_tools"


@dataclass
class HistoryRecord:
    """SQLite 歷史記錄 DTO（對應 jobs 資料表一列）。

    欄位說明：
        id              資料庫 auto-increment 主鍵
        job_uuid        對應 ConversionJob.job_id（UUID 前 8 碼）
        created_at      ISO-8601 UTC 字串（任務建立時間）
        completed_at    ISO-8601 UTC 字串，完成時填入（None 表示未完成）
        source_path     來源檔案絕對路徑字串
        source_format   小寫無點格式碼，例如 "pdf"
        source_size_bytes 來源檔案大小（bytes）
        target_format   目標格式碼
        output_path     輸出路徑字串（None 表示失敗或取消）
        status          "done" | "error" | "cancelled"
        error_message   失敗時的錯誤說明（None 表示成功）
        duration_ms     轉換耗時毫秒（None 表示未記錄）
        app_version     轉換當時的應用版本字串
    """
    id: int
    job_uuid: str
    created_at: str
    completed_at: Optional[str]
    source_path: str
    source_format: str
    source_size_bytes: int
    target_format: str
    output_path: Optional[str]
    status: str
    error_message: Optional[str]
    duration_ms: Optional[int]
    app_version: str


class HistoryManagerSignals(QObject):
    """HistoryManager 對外 Signal 契約。"""

    record_added = Signal(int)       # record id（新增後）
    record_updated = Signal(int)     # record id（狀態更新後）
    record_deleted = Signal(int)     # record id（單筆刪除）
    records_changed = Signal()       # 批量變更（清除 / 匯入）觸發
    error_occurred = Signal(str)     # 錯誤說明字串


class SettingsManagerSignals(QObject):
    """SettingsManager 對外 Signal 契約。"""

    setting_changed = Signal(str, object)  # key, new_value
    reset_completed = Signal()             # 重置為預設值完成
    imported = Signal(int)                 # 匯入的鍵數量
    exported = Signal(str)                 # 匯出的檔案路徑


class NotificationSignals(QObject):
    """NotificationManager 對外 Signal 契約。

    notify_requested 參數：
        level (str)       "info" | "success" | "warning" | "error"
        title (str)       通知標題
        content (str)     通知內容
        duration_ms (int) 顯示毫秒（0 = 持續直到使用者關閉）
    """

    notify_requested = Signal(str, str, str, int)


class TraySignals(QObject):
    """TrayManager 對外 Signal 契約。"""

    show_window_requested = Signal()   # 使用者點選「顯示視窗」
    quit_requested = Signal()          # 使用者點選「結束」
    activated = Signal()               # 托盤圖示雙擊或單擊


class PageNavigationSignals(QObject):
    """頁面導航 Signal 契約（由 MainWindowV2 管理）。

    navigate_to_page: 請求切換至指定頁面（page_id = PageID.value）
    page_changed:     頁面切換完成通知（from_id, to_id）
    """

    navigate_to_page = Signal(str)    # page_id（PageID.value）
    page_changed = Signal(str, str)   # from_id, to_id


def get_format_display_name(fmt: str) -> str:
    """格式代碼轉人類可讀顯示名稱。

    Args:
        fmt: 小寫格式代碼，例如 "pdf"、"image"。

    Returns:
        大寫顯示名，例如 "PDF"；image 特例回傳 "圖片"。
    """
    return "圖片" if fmt == "image" else fmt.upper()


# ============================================================================
# PDF Tools 擴充（W-PDF-TOOLS append-only — 不影響既有契約）
# ============================================================================

class PdfToolsControllerSignals(QObject):
    """PdfToolsController 對外 Signal 契約。"""

    operation_started = Signal(str)             # operation_name: "merge"|"split"|"compress"|"encrypt"|"decrypt"
    operation_progress = Signal(float)          # 0.0–1.0
    operation_completed = Signal(str, object)   # operation_name, result (Path | list[Path] | dict | None)
    operation_failed = Signal(str, str)         # operation_name, error_message


# ============================================================================
# Image Tools 擴充（W-IMAGE-TOOLS append-only — 不影響既有契約）
# ============================================================================

class ImageToolsControllerSignals(QObject):
    """ImageToolsController 對外 Signal 契約。

    生命週期：
        operation_started → operation_progress×N →
        (item_status / item_completed)×N →
        operation_completed | operation_failed

    payload 說明：
        operation_name (str): "remove_single" | "batch" | "replace_bg" | "filter"
        result (object):
            - remove_single / replace_bg / filter: Path（輸出檔路徑）
            - batch: list[BatchItemResult]
        item_status (idx, status):
            status ∈ "started" | "completed" | "failed" | "cancelled"
    """

    operation_started = Signal(str)             # operation_name
    operation_progress = Signal(float)          # 0.0–1.0
    item_status = Signal(int, str)              # idx, status
    item_completed = Signal(int, object)        # idx, BatchItemResult
    operation_completed = Signal(str, object)   # operation_name, result
    operation_failed = Signal(str, str)         # operation_name, error_message
