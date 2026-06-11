"""
converters/pdf_converter.py — PDF 來源轉換器

支援：PDF → DOCX / HTML / MD / TXT / IMG
首選引擎：PyMuPDF (fitz) + pdf2docx
掃描版後備：頁面無文字層時自動 OCR（converters/pdf_ocr.py，RapidOCR）
"""

import io
import logging
import zipfile
from pathlib import Path

from .base import BaseConverter
from .exceptions import ConversionError, UnsupportedFormatError
from .pdf_ocr import is_ocr_available, ocr_page
from .utils import build_minimal_html, ensure_output_dir

logger = logging.getLogger(__name__)

# 渲染 DPI（150 dpi 提供足夠品質且不爆記憶體）
_RENDER_DPI = 150
_RENDER_MATRIX_SCALE = _RENDER_DPI / 72  # fitz Matrix 縮放係數


class PDFConverter(BaseConverter):
    """PDF 格式來源轉換器。

    支援目標格式：docx / html / md / txt / image
    """

    source_format = "pdf"
    supported_targets = ["docx", "html", "md", "txt", "image"]

    def convert(self, input_path: Path, output_path: Path, target_format: str) -> None:
        """執行 PDF 轉換。

        Args:
            input_path: 來源 PDF 路徑
            output_path: 目標檔案路徑
            target_format: "docx" | "html" | "md" | "txt" | "image"

        Raises:
            UnsupportedFormatError: target_format 不在支援清單
            ConversionError: 轉換失敗
        """
        if not self.supports(target_format):
            raise UnsupportedFormatError(
                f"PDFConverter 不支援目標格式: {target_format}"
            )

        ensure_output_dir(output_path)
        self._log_primary_attempt(target_format)

        dispatch_map = {
            "docx": self._to_docx,
            "html": self._to_html,
            "md": self._to_md,
            "txt": self._to_txt,
            "image": self._to_image,
        }
        dispatch_map[target_format](input_path, output_path)

    # ─── 各目標格式實作 ────────────────────────────────────────────

    def _to_docx(self, input_path: Path, output_path: Path) -> None:
        """PDF → DOCX：首選 pdf2docx；降級 PyMuPDF 抽文 + python-docx。"""
        primary_error: Exception | None = None

        # 首選：pdf2docx
        try:
            from pdf2docx import Converter as Pdf2DocxConverter

            cv = Pdf2DocxConverter(str(input_path))
            cv.convert(str(output_path), start=0, end=None)
            cv.close()
            logger.info("PDF→DOCX 首選成功: pdf2docx")
            return
        except Exception as exc:
            primary_error = exc
            self._log_fallback_attempt("docx", exc)

        # 降級：PyMuPDF 抽文字 + python-docx 重組
        try:
            self._pdf_to_docx_fallback(input_path, output_path)
            logger.info("PDF→DOCX 降級成功: PyMuPDF+python-docx")
        except Exception as fallback_error:
            self._raise_conversion_error("docx", primary_error, fallback_error)

    def _pdf_to_docx_fallback(self, input_path: Path, output_path: Path) -> None:
        """降級：PyMuPDF 抽文字 → python-docx 重組。"""
        import fitz  # PyMuPDF
        from docx import Document
        from docx.shared import Pt

        doc = Document()
        pdf_doc = fitz.open(str(input_path))
        try:
            for page_num, page in enumerate(pdf_doc, start=1):
                if page_num > 1:
                    doc.add_page_break()
                text = page.get_text()
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped:
                        para = doc.add_paragraph(stripped)
                        para.style.font.size = Pt(11)
        finally:
            pdf_doc.close()
        doc.save(str(output_path))

    def _to_html(self, input_path: Path, output_path: Path) -> None:
        """PDF → HTML：PyMuPDF get_text("html")。"""
        primary_error: Exception | None = None
        try:
            import fitz

            pdf_doc = fitz.open(str(input_path))
            html_parts: list[str] = []
            try:
                for page_num, page in enumerate(pdf_doc, start=1):
                    text, used_ocr = self._page_text_or_ocr(page)
                    if used_ocr:
                        # 掃描圖頁：OCR 純文字以 <pre> 呈現
                        import html as html_module
                        logger.info("PDF→HTML 第 %d 頁無文字層，已使用 OCR 辨識", page_num)
                        page_body = f"<pre>{html_module.escape(text)}</pre>"
                    else:
                        page_body = page.get_text("html")
                    html_parts.append(f'<div class="pdf-page">{page_body}</div>')
            finally:
                pdf_doc.close()

            body = "\n".join(html_parts)
            full_html = build_minimal_html(body, title="PDF 轉換結果")
            output_path.write_text(full_html, encoding="utf-8")
            logger.info("PDF→HTML 成功")
            return
        except Exception as exc:
            primary_error = exc
            self._log_fallback_attempt("html", exc)

        # 降級：純文字包 <pre>
        try:
            text = self._extract_text(input_path)
            import html as html_module
            body = f"<pre>{html_module.escape(text)}</pre>"
            full_html = build_minimal_html(body, title="PDF 轉換結果（降級）")
            output_path.write_text(full_html, encoding="utf-8")
            logger.info("PDF→HTML 降級成功（純文字模式）")
        except Exception as fallback_error:
            self._raise_conversion_error("html", primary_error, fallback_error)

    def _to_md(self, input_path: Path, output_path: Path) -> None:
        """PDF → MD：PyMuPDF HTML → html2text。"""
        primary_error: Exception | None = None
        try:
            import fitz
            import html2text

            pdf_doc = fitz.open(str(input_path))
            md_parts: list[str] = []
            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.body_width = 0  # 不自動換行
            try:
                for page_num, page in enumerate(pdf_doc, start=1):
                    text, used_ocr = self._page_text_or_ocr(page)
                    if used_ocr:
                        # 掃描圖頁：OCR 純文字直接作為該頁內容
                        logger.info("PDF→MD 第 %d 頁無文字層，已使用 OCR 辨識", page_num)
                        page_md = text
                    else:
                        page_html = page.get_text("html")
                        page_md = converter.handle(page_html)
                    md_parts.append(f"---\n\n<!-- 第 {page_num} 頁 -->\n\n{page_md}")
            finally:
                pdf_doc.close()

            output_path.write_text("\n\n".join(md_parts), encoding="utf-8")
            logger.info("PDF→MD 首選成功")
            return
        except Exception as exc:
            primary_error = exc
            self._log_fallback_attempt("md", exc)

        # 降級：純文字抽取
        try:
            text = self._extract_text(input_path)
            output_path.write_text(text, encoding="utf-8")
            logger.info("PDF→MD 降級成功（純文字模式）")
        except Exception as fallback_error:
            self._raise_conversion_error("md", primary_error, fallback_error)

    def _to_txt(self, input_path: Path, output_path: Path) -> None:
        """PDF → TXT：PyMuPDF get_text()。"""
        try:
            text = self._extract_text(input_path)
            output_path.write_text(text, encoding="utf-8")
            logger.info("PDF→TXT 成功")
        except Exception as exc:
            raise ConversionError(
                f"PDF→TXT 轉換失敗",
                source_error=exc,
            ) from exc

    def _to_image(self, input_path: Path, output_path: Path) -> None:
        """PDF → IMG：PyMuPDF 頁面渲染。

        單頁輸出：PNG 檔案
        多頁輸出：ZIP 檔案（含多頁 PNG），output_path 副檔名改為 .zip
        """
        try:
            import fitz

            matrix = fitz.Matrix(_RENDER_MATRIX_SCALE, _RENDER_MATRIX_SCALE)
            pdf_doc = fitz.open(str(input_path))
            page_count = len(pdf_doc)

            try:
                if page_count == 1:
                    page = pdf_doc[0]
                    pixmap = page.get_pixmap(matrix=matrix)
                    pixmap.save(str(output_path))
                else:
                    # 多頁：輸出 ZIP
                    zip_path = output_path.with_suffix(".zip")
                    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                        for page_num, page in enumerate(pdf_doc, start=1):
                            pixmap = page.get_pixmap(matrix=matrix)
                            png_bytes = pixmap.tobytes("png")
                            zf.writestr(f"page_{page_num:04d}.png", png_bytes)
                    # 若原本 output_path 不是 .zip，用 zip_path 覆蓋
                    if output_path != zip_path:
                        if output_path.exists():
                            output_path.unlink()
                        zip_path.rename(output_path)
            finally:
                pdf_doc.close()

            logger.info("PDF→IMG 成功（%d 頁）", page_count)
        except Exception as exc:
            raise ConversionError(
                f"PDF→IMG 轉換失敗",
                source_error=exc,
            ) from exc

    # ─── 共用輔助 ──────────────────────────────────────────────────

    def _extract_text(self, input_path: Path) -> str:
        """用 PyMuPDF 抽取所有頁面純文字（無文字層頁面自動 OCR）。"""
        import fitz

        pdf_doc = fitz.open(str(input_path))
        texts: list[str] = []
        try:
            for page_num, page in enumerate(pdf_doc, start=1):
                text, used_ocr = self._page_text_or_ocr(page)
                if used_ocr:
                    logger.info("PDF 第 %d 頁無文字層，已使用 OCR 辨識", page_num)
                texts.append(text)
        finally:
            pdf_doc.close()
        return "\n".join(texts)

    @staticmethod
    def _page_text_or_ocr(page) -> tuple[str, bool]:
        """回傳 (頁面文字, 是否來自 OCR)。

        原生文字層優先（快且精確）；頁面抽不到文字（掃描圖頁）
        且 OCR 引擎可用時，降級為 RapidOCR 辨識。
        """
        text = page.get_text()
        if text.strip():
            return text, False
        if is_ocr_available():
            return ocr_page(page), True
        return text, False
