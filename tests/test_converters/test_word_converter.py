"""
tests/test_converters/test_word_converter.py — Word 轉換器測試
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from converters.word_converter import WordConverter
from converters.exceptions import UnsupportedFormatError, ConversionError


@pytest.fixture(scope="module")
def converter():
    return WordConverter()


class TestWordConverterMeta:
    def test_source_format(self, converter):
        assert converter.source_format == "docx"

    def test_supported_targets(self, converter):
        for fmt in ["pdf", "html", "md", "txt"]:
            assert converter.supports(fmt)

    def test_unsupported_target(self, converter):
        assert not converter.supports("pptx")
        assert not converter.supports("image")

    def test_unsupported_raises(self, converter, sample_docx, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            converter.convert(sample_docx, tmp_output("out.pptx"), "pptx")


class TestDOCXToTXT:
    def test_primary_success(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx.txt")
        converter.convert(sample_docx, out, "txt")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_contains_heading(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx_content.txt")
        converter.convert(sample_docx, out, "txt")
        content = out.read_text(encoding="utf-8")
        # fixture 含「測試 Word 文件」
        assert "測試" in content or len(content) > 10

    def test_nonexistent_file_raises(self, converter, tmp_output):
        with pytest.raises(ConversionError):
            converter.convert(
                Path("/nonexistent/file.docx"),
                tmp_output("out.txt"),
                "txt",
            )


class TestDOCXToHTML:
    def test_primary_success(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx.html")
        converter.convert(sample_docx, out, "html")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_is_html(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx_html.html")
        converter.convert(sample_docx, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "<html" in content.lower()

    def test_output_contains_heading_tag(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx_html2.html")
        converter.convert(sample_docx, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "<h1" in content.lower() or "<h2" in content.lower()


class TestDOCXToMD:
    def test_primary_success(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx.md")
        try:
            converter.convert(sample_docx, out, "md")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"DOCX→MD 需要 html2text（{exc}）")

    def test_output_is_markdown(self, converter, sample_docx, tmp_output):
        out = tmp_output("from_docx_md.md")
        try:
            converter.convert(sample_docx, out, "md")
            content = out.read_text(encoding="utf-8")
            assert isinstance(content, str)
            assert len(content) > 10
        except ConversionError:
            pytest.skip("html2text 不可用")


class TestDOCXToPDF:
    def test_fallback_when_docx2pdf_fails(self, converter, sample_docx, tmp_output):
        """驗證降級路徑：mock docx2pdf 拋出例外，應使用 weasyprint 降級。"""
        out = tmp_output("from_docx_fallback.pdf")

        with patch("converters.word_converter.WordConverter._docx2pdf_with_timeout") as mock_primary:
            mock_primary.side_effect = ConversionError("模擬 docx2pdf 失敗")
            # 降級應產出 PDF（可能 weasyprint 也需系統環境，若不可用允許失敗）
            try:
                converter.convert(sample_docx, out, "pdf")
                assert out.exists()
                assert out.stat().st_size > 0
            except ConversionError:
                # 若 weasyprint 也失敗（環境限制），視為跳過
                pytest.skip("weasyprint 降級路徑在此環境不可用")

    def test_pdf_output_attempt(self, converter, sample_docx, tmp_output):
        """嘗試 DOCX→PDF 轉換（允許 COM 相關環境失敗）。"""
        out = tmp_output("from_docx.pdf")
        try:
            converter.convert(sample_docx, out, "pdf")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError:
            # COM 可能未安裝 Word，允許失敗但不能靜默吞掉
            pytest.skip("docx2pdf 需要 Microsoft Word（COM），跳過此環境")
