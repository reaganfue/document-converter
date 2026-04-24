"""config.py — 全域設定常數"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# 允許透過環境變數覆蓋目錄路徑（供測試隔離使用）
_upload_env = os.environ.get("UPLOAD_DIR")
_output_env = os.environ.get("OUTPUT_DIR")

UPLOAD_DIR = Path(_upload_env) if _upload_env else BASE_DIR / "uploads"
OUTPUT_DIR = Path(_output_env) if _output_env else BASE_DIR / "outputs"

# ---------- 大小限制 ----------
MAX_FILE_SIZE = 50 * 1024 * 1024        # 50 MB per file
MAX_TOTAL_SIZE = 200 * 1024 * 1024      # 200 MB per job
MAX_FILES_PER_JOB = 20
MAX_CONCURRENT_JOBS = 10
CONVERSION_TIMEOUT_SEC = 120

# ---------- 清理策略 ----------
CLEANUP_AFTER_SUCCESS_SEC = 60
CLEANUP_AFTER_FAILURE_SEC = 300
CLEANUP_SCAN_INTERVAL_SEC = 600         # 10 minutes
CLEANUP_STALE_AGE_SEC = 6 * 3600       # 6 hours

# ---------- 支援格式定義 ----------
SUPPORTED_FORMATS = {
    "pdf": {
        "label": "PDF",
        "ext": "pdf",
        "mime": "application/pdf",
    },
    "docx": {
        "label": "Word",
        "ext": "docx",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "pptx": {
        "label": "PowerPoint",
        "ext": "pptx",
        "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    "html": {
        "label": "HTML",
        "ext": "html",
        "mime": "text/html",
    },
    "md": {
        "label": "Markdown",
        "ext": "md",
        "mime": "text/markdown",
    },
    "txt": {
        "label": "純文字",
        "ext": "txt",
        "mime": "text/plain",
    },
    "image": {
        "label": "圖片",
        "ext": "png",
        "mime": "image/png",
    },
}

# 可接受上傳的副檔名白名單（對應上方 key）
UPLOAD_EXTENSIONS = {
    "pdf", "docx", "doc",
    "pptx", "ppt",
    "html", "htm",
    "md", "markdown",
    "txt",
    "png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff",
}

# ---------- 轉換矩陣 ----------
# source_format → { target_format: quality_label }
# quality_label: "high" | "medium" | "low"
CONVERSION_MATRIX = {
    "pdf": {
        "docx": "high",
        "html": "medium",
        "md": "medium",
        "txt": "high",
        "image": "high",
    },
    "docx": {
        "pdf": "high",
        "html": "high",
        "md": "high",
        "txt": "high",
    },
    "pptx": {
        "pdf": "medium",
        "html": "medium",
        "txt": "low",
        "image": "high",
    },
    "html": {
        "pdf": "high",
        "docx": "medium",
        "md": "high",
        "txt": "high",
    },
    "md": {
        "pdf": "high",
        "docx": "high",
        "html": "high",
        "txt": "high",
    },
    "txt": {
        "pdf": "medium",
        "docx": "medium",
        "html": "high",
        "md": "high",
    },
    "image": {
        "pdf": "high",
        "image": "high",
    },
}

# ---------- 副檔名到格式 key 的映射 ----------
EXT_TO_FORMAT = {
    "pdf": "pdf",
    "docx": "docx",
    "doc": "docx",
    "pptx": "pptx",
    "ppt": "pptx",
    "html": "html",
    "htm": "html",
    "md": "md",
    "markdown": "md",
    "txt": "txt",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "bmp": "image",
    "webp": "image",
    "tiff": "image",
}

# ---------- 本地化錯誤訊息（繁中） ----------
ERROR_MESSAGES = {
    "file_too_large": "檔案 {name} 超過 50MB 上限",
    "total_too_large": "總大小超過 200MB 上限",
    "unsupported_format": "不支援從 {src} 轉換至 {tgt}",
    "conversion_failed": "轉換 {name} 時發生錯誤：{reason}",
    "no_word_installed": "您的系統未安裝 Microsoft Word，將使用替代引擎",
    "timeout": "轉換 {name} 超過 120 秒已中止",
    "invalid_file": "檔案 {name} 格式不正確或已損壞",
    "password_protected": "檔案 {name} 受密碼保護，無法轉換",
    "too_many_jobs": "目前處理中任務過多，請稍後再試",
    "no_files": "未提供任何檔案",
    "missing_target_format": "未指定目標格式",
    "unknown_job": "找不到任務 {job_id}",
    "symlink_rejected": "檔案 {name} 為符號連結，已拒絕",
    "too_many_files": "單次最多上傳 {max} 個檔案",
}
