"""
tests/test_converters/test_markdown_converter.py — Markdown 轉換器測試
"""

import pytest
from pathlib import Path

from converters.markdown_converter import MarkdownConverter
from converters.exceptions import UnsupportedFormatError, ConversionError


@pytest.fixture(scope="module")
def converter():
    return MarkdownConverter()


class TestMarkdownConverterMeta:
    def test_source_format(self, converter):
        assert converter.source_format == "md"

    def test_supported_targets(self, converter):
        for fmt in ["html", "pdf", "docx", "txt"]:
            assert converter.supports(fmt)

    def test_unsupported_target(self, converter):
        assert not converter.supports("pptx")
        assert not converter.supports("image")

    def test_unsupported_raises(self, converter, sample_md, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            converter.convert(sample_md, tmp_output("out.pptx"), "pptx")


class TestMDToHTML:
    def test_primary_success(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md.html")
        converter.convert(sample_md, out, "html")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_is_html(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_html.html")
        converter.convert(sample_md, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_headings_converted(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_html2.html")
        converter.convert(sample_md, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "<h1" in content.lower()

    def test_nonexistent_file_raises(self, converter, tmp_output):
        with pytest.raises(ConversionError):
            converter.convert(
                Path("/nonexistent/file.md"),
                tmp_output("out.html"),
                "html",
            )


class TestMDToTXT:
    def test_primary_success(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md.txt")
        converter.convert(sample_md, out, "txt")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_markdown_syntax_removed(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_txt.txt")
        converter.convert(sample_md, out, "txt")
        content = out.read_text(encoding="utf-8")
        # 標題的 # 應被移除
        assert "# 測試" not in content
        # 粗體標記 ** 應被移除
        assert "**" not in content

    def test_text_content_preserved(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_txt2.txt")
        converter.convert(sample_md, out, "txt")
        content = out.read_text(encoding="utf-8")
        assert len(content) > 50


class TestMDToDOCX:
    def test_primary_success(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md.docx")
        converter.convert(sample_md, out, "docx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_is_valid_docx(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_docx.docx")
        converter.convert(sample_md, out, "docx")
        from docx import Document
        doc = Document(str(out))
        assert len(doc.paragraphs) > 0


class TestMDToPDF:
    def test_primary_success(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md.pdf")
        try:
            converter.convert(sample_md, out, "pdf")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"MD→PDF 需要 weasyprint（{exc}）")

    def test_pdf_valid_header(self, converter, sample_md, tmp_output):
        out = tmp_output("from_md_pdf.pdf")
        try:
            converter.convert(sample_md, out, "pdf")
            assert out.read_bytes()[:4] == b"%PDF"
        except ConversionError:
            pytest.skip("weasyprint 不可用")
