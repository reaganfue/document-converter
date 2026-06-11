"""
converters/dispatcher.py — 轉換路由引擎

根據 (source_format, target_format) 選擇正確的 Converter 實例，
並提供 convert_file 作為桌面控制層（ConversionController）呼叫的唯一公開入口。
"""

import logging
from pathlib import Path

from .exceptions import UnsupportedFormatError
from .html_converter import HTMLConverter
from .image_converter import ImageConverter
from .markdown_converter import MarkdownConverter
from .pdf_converter import PDFConverter
from .ppt_converter import PPTConverter
from .txt_converter import TXTConverter
from .word_converter import WordConverter
from .utils import detect_format_from_path, FORMAT_TO_EXT, IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

# 格式 → Converter 實例（單例，執行緒安全讀取）
_CONVERTERS: dict[str, object] = {
    "pdf": PDFConverter(),
    "docx": WordConverter(),
    "pptx": PPTConverter(),
    "html": HTMLConverter(),
    "md": MarkdownConverter(),
    "txt": TXTConverter(),
    "image": ImageConverter(),
}

# 完整支援矩陣（格式品質標籤）
_SUPPORT_MATRIX: dict[str, dict[str, str]] = {
    "pdf":   {"docx": "high", "html": "medium", "md": "medium", "txt": "high", "image": "high"},
    "docx":  {"pdf": "high", "html": "high", "md": "high", "txt": "high"},
    "pptx":  {"pdf": "medium", "html": "medium", "txt": "low", "image": "high"},
    "html":  {"pdf": "high", "docx": "medium", "md": "high", "txt": "high"},
    "md":    {"pdf": "high", "docx": "high", "html": "high", "txt": "high"},
    "txt":   {"pdf": "medium", "docx": "medium", "html": "high", "md": "high"},
    "image": {"pdf": "high", "image": "high"},
}


def convert_file(
    input_path: str | Path,
    output_path: str | Path,
    source_format: str,
    target_format: str,
) -> None:
    """執行單一檔案轉換（桌面應用的主呼叫入口）。

    Args:
        input_path: 來源檔案路徑
        output_path: 目標輸出路徑
        source_format: 來源格式名稱（小寫，如 "pdf"、"docx"）
        target_format: 目標格式名稱（小寫，如 "html"、"txt"）

    Raises:
        UnsupportedFormatError: 格式不支援
        ConversionError: 轉換過程中失敗
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    source_format = source_format.lower()
    target_format = target_format.lower()

    logger.info(
        "convert_file 呼叫: %s → %s | 來源: %s | 目標: %s",
        input_path.name,
        output_path.name,
        source_format,
        target_format,
    )

    if source_format not in _CONVERTERS:
        raise UnsupportedFormatError(
            f"不支援來源格式: {source_format}（支援: {list(_CONVERTERS.keys())}）"
        )

    conv = _CONVERTERS[source_format]
    if not conv.supports(target_format):
        raise UnsupportedFormatError(
            f"不支援從 {source_format} 轉換至 {target_format}"
        )

    conv.convert(input_path, output_path, target_format)


def detect_format(file_path: Path) -> str:
    """從副檔名推斷格式名稱。

    Args:
        file_path: 檔案路徑

    Returns:
        格式名稱（小寫），如 "pdf"、"docx"、"image"

    Raises:
        ValueError: 無法辨識副檔名
    """
    return detect_format_from_path(file_path)


def get_supported_matrix() -> dict[str, dict[str, str]]:
    """回傳完整支援矩陣，格式與 config.CONVERSION_MATRIX 一致。

    Returns:
        dict: { source_format: { target_format: quality_label } }
              quality_label: "high" | "medium" | "low"
    """
    return dict(_SUPPORT_MATRIX)


def is_supported_pair(source_format: str, target_format: str) -> bool:
    """快速判斷某轉換對是否支援。"""
    return target_format in _SUPPORT_MATRIX.get(source_format, {})
