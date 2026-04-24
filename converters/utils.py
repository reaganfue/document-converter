"""
converters/utils.py — 共用工具函式

提供格式偵測、臨時檔管理、HTML 輔助等共用功能。
"""

import logging
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# 副檔名 → 正規化格式名稱映射
_EXT_TO_FORMAT: dict[str, str] = {
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
    "text": "txt",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "bmp": "image",
    "gif": "image",
    "tiff": "image",
    "tif": "image",
    "webp": "image",
}

# 格式 → 預設輸出副檔名
FORMAT_TO_EXT: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "pptx": "pptx",
    "html": "html",
    "md": "md",
    "txt": "txt",
    "image": "png",
}

# 圖片副檔名集合（dispatcher 用於判斷原始圖片格式）
IMAGE_EXTENSIONS: set[str] = {"png", "jpg", "jpeg", "bmp", "gif", "tiff", "tif", "webp"}


def detect_format_from_path(file_path: Path) -> str:
    """從副檔名推斷格式名稱。

    Args:
        file_path: 檔案路徑

    Returns:
        格式名稱（小寫），如 "pdf"、"docx"、"image"

    Raises:
        ValueError: 無法辨識副檔名
    """
    ext = file_path.suffix.lstrip(".").lower()
    if ext not in _EXT_TO_FORMAT:
        raise ValueError(f"無法辨識副檔名: .{ext}")
    return _EXT_TO_FORMAT[ext]


def get_image_ext(file_path: Path) -> str:
    """取得圖片檔案的實際副檔名（小寫）。"""
    return file_path.suffix.lstrip(".").lower()


@contextmanager
def temp_file(suffix: str = "", prefix: str = "conv_"):
    """建立臨時檔案的 context manager，退出時自動刪除。

    Args:
        suffix: 臨時檔副檔名，如 ".html"
        prefix: 臨時檔前綴

    Yields:
        Path: 臨時檔案路徑
    """
    tmp = tempfile.NamedTemporaryFile(
        suffix=suffix, prefix=prefix, delete=False
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        yield tmp_path
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as exc:
            logger.warning("無法刪除臨時檔案 %s: %s", tmp_path, exc)


def ensure_output_dir(output_path: Path) -> None:
    """確保輸出路徑的父目錄存在。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)


def build_minimal_html(
    body_content: str,
    title: str = "文件",
    charset: str = "utf-8",
    extra_style: str = "",
) -> str:
    """包裝 body 內容成完整 HTML 文件。

    Args:
        body_content: HTML body 內的內容（不含 <body> 標籤）
        title: HTML 標題
        charset: 字元編碼
        extra_style: 額外 CSS 樣式

    Returns:
        完整 HTML 字串
    """
    base_style = """
        body { font-family: "Microsoft JhengHei", "Noto Sans CJK TC", Arial, sans-serif;
               line-height: 1.6; margin: 2em auto; max-width: 900px; color: #333; }
        h1, h2, h3, h4, h5, h6 { color: #111; margin-top: 1.2em; }
        table { border-collapse: collapse; width: 100%; margin: 1em 0; }
        th, td { border: 1px solid #ccc; padding: 6px 10px; }
        th { background: #f0f0f0; }
        pre, code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px;
                    font-family: monospace; }
        pre { padding: 1em; overflow-x: auto; }
        a { color: #0066cc; }
    """ + extra_style
    return (
        f"<!DOCTYPE html>\n"
        f'<html lang="zh-TW">\n'
        f"<head>\n"
        f'  <meta charset="{charset}">\n'
        f"  <title>{_escape_html(title)}</title>\n"
        f"  <style>{base_style}</style>\n"
        f"</head>\n"
        f"<body>\n{body_content}\n</body>\n"
        f"</html>\n"
    )


def _escape_html(text: str) -> str:
    """基本 HTML 字元跳脫。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def strip_markdown_syntax(text: str) -> str:
    """用正則移除常見 Markdown 語法，留下純文字。

    處理：標題(#)、粗體/斜體(**/_)、連結([text](url))、
          行內代碼(`)、代碼塊(```)、清單(- / *)、水平線(---)
    """
    # 代碼塊（多行）
    text = re.sub(r"```[\w]*\n?", "", text)
    # 標題
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 粗體 + 斜體（順序重要：先處理三個再處理兩個）
    text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text)
    text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_{3}(.+?)_{3}", r"\1", text)
    text = re.sub(r"_{2}(.+?)_{2}", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    # 行內代碼
    text = re.sub(r"`(.+?)`", r"\1", text)
    # 連結 [text](url) → text
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    # 圖片 ![alt](url) → alt
    text = re.sub(r"!\[(.+?)\]\(.+?\)", r"\1", text)
    # 清單標記
    text = re.sub(r"^[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # 水平線
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\*{3,}$", "", text, flags=re.MULTILINE)
    # 引用區塊
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    # 清理多餘空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
