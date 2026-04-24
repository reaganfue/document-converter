"""
converters/markdown_converter.py — Markdown 來源轉換器

支援：MD → HTML / PDF / DOCX / TXT
"""

import logging
from pathlib import Path

from .base import BaseConverter
from .exceptions import ConversionError, UnsupportedFormatError
from .utils import build_minimal_html, ensure_output_dir, strip_markdown_syntax, temp_file

logger = logging.getLogger(__name__)

# Markdown 解析擴充清單
_MD_EXTENSIONS = ["tables", "fenced_code", "nl2br", "sane_lists"]


class MarkdownConverter(BaseConverter):
    """Markdown 格式來源轉換器。

    支援目標格式：html / pdf / docx / txt
    """

    source_format = "md"
    supported_targets = ["html", "pdf", "docx", "txt"]

    def convert(self, input_path: Path, output_path: Path, target_format: str) -> None:
        """執行 MD 轉換。

        Args:
            input_path: 來源 MD 路徑
            output_path: 目標檔案路徑
            target_format: "html" | "pdf" | "docx" | "txt"

        Raises:
            UnsupportedFormatError: target_format 不在支援清單
            ConversionError: 轉換失敗
        """
        if not self.supports(target_format):
            raise UnsupportedFormatError(
                f"MarkdownConverter 不支援目標格式: {target_format}"
            )

        ensure_output_dir(output_path)
        self._log_primary_attempt(target_format)

        dispatch_map = {
            "html": self._to_html,
            "pdf": self._to_pdf,
            "docx": self._to_docx,
            "txt": self._to_txt,
        }
        dispatch_map[target_format](input_path, output_path)

    # ─── 各目標格式實作 ────────────────────────────────────────────

    def _to_html(self, input_path: Path, output_path: Path) -> None:
        """MD → HTML：markdown lib + 完整 HTML 包裝。"""
        try:
            html_body = self._md_to_html_body(input_path)
            full_html = build_minimal_html(html_body, title=input_path.stem)
            output_path.write_text(full_html, encoding="utf-8")
            logger.info("MD→HTML 成功")
        except Exception as exc:
            raise ConversionError("MD→HTML 轉換失敗", source_error=exc) from exc

    def _to_pdf(self, input_path: Path, output_path: Path) -> None:
        """MD → PDF：MD→HTML→多層渲染降級鏈。"""
        try:
            from .pdf_renderer import get_renderer

            html_body = self._md_to_html_body(input_path)
            full_html = build_minimal_html(html_body, title=input_path.stem)

            with temp_file(suffix=".html") as html_path:
                html_path.write_text(full_html, encoding="utf-8")
                get_renderer().render_html_to_pdf(html_path, output_path)

            logger.info("MD→PDF 成功")
        except Exception as exc:
            raise ConversionError("MD→PDF 轉換失敗", source_error=exc) from exc

    def _to_docx(self, input_path: Path, output_path: Path) -> None:
        """MD → DOCX：MD→HTML→HTMLConverter 的 HTML→DOCX 邏輯。"""
        try:
            from .html_converter import HTMLConverter

            html_body = self._md_to_html_body(input_path)
            full_html = build_minimal_html(html_body, title=input_path.stem)

            html_conv = HTMLConverter()
            html_conv._html_to_docx(full_html, output_path)
            logger.info("MD→DOCX 成功")
        except Exception as exc:
            raise ConversionError("MD→DOCX 轉換失敗", source_error=exc) from exc

    def _to_txt(self, input_path: Path, output_path: Path) -> None:
        """MD → TXT：移除 Markdown 語法，保留純文字。"""
        try:
            raw_text = input_path.read_text(encoding="utf-8", errors="replace")
            clean_text = strip_markdown_syntax(raw_text)
            output_path.write_text(clean_text, encoding="utf-8")
            logger.info("MD→TXT 成功")
        except Exception as exc:
            raise ConversionError("MD→TXT 轉換失敗", source_error=exc) from exc

    # ─── 共用輔助 ──────────────────────────────────────────────────

    def _md_to_html_body(self, input_path: Path) -> str:
        """讀取 MD 檔，轉換為 HTML body 內容（不含 <html>/<head>）。"""
        import markdown as md_lib

        raw_text = input_path.read_text(encoding="utf-8", errors="replace")
        return md_lib.markdown(raw_text, extensions=_MD_EXTENSIONS)
