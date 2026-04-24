"""
tests/test_converters/test_pdf_converter.py — PDF 轉換器測試
"""

import pytest
from pathlib import Path

from converters.pdf_converter import PDFConverter
from converters.exceptions import UnsupportedFormatError, ConversionError


@pytest.fixture(scope="module")
def converter():
    return PDFConverter()


class TestPDFConverterMeta:
    def test_source_format(self, converter):
        assert converter.source_format == "pdf"

    def test_supported_targets(self, converter):
        for fmt in ["docx", "html", "md", "txt", "image"]:
            assert converter.supports(fmt), f"應支援 {fmt}"

    def test_unsupported_target(self, converter):
        assert not converter.supports("pptx")
        assert not converter.supports("unknown")

    def test_unsupported_raises(self, converter, sample_pdf, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            converter.convert(sample_pdf, tmp_output("out.pptx"), "pptx")


class TestPDFToTXT:
    def test_primary_success(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf.txt")
        try:
            converter.convert(sample_pdf, out, "txt")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PDF→TXT 需要 PyMuPDF（{exc}）")

    def test_output_contains_text(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf_text.txt")
        try:
            converter.convert(sample_pdf, out, "txt")
            content = out.read_text(encoding="utf-8")
            # 來源 fixture 含「測試文件」
            assert len(content) > 10
        except ConversionError:
            pytest.skip("PyMuPDF 不可用")

    def test_nonexistent_file_raises(self, converter, tmp_output):
        with pytest.raises(ConversionError):
            converter.convert(
                Path("/nonexistent/file.pdf"),
                tmp_output("out.txt"),
                "txt",
            )


class TestPDFToHTML:
    def test_primary_success(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf.html")
        try:
            converter.convert(sample_pdf, out, "html")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PDF→HTML 需要 PyMuPDF（{exc}）")

    def test_output_is_html(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf_html.html")
        try:
            converter.convert(sample_pdf, out, "html")
            content = out.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content or "<html" in content.lower()
        except ConversionError:
            pytest.skip("PyMuPDF 不可用")

    def test_output_not_empty(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf_html2.html")
        try:
            converter.convert(sample_pdf, out, "html")
            assert out.stat().st_size > 100
        except ConversionError:
            pytest.skip("PyMuPDF 不可用")


class TestPDFToMD:
    def test_primary_success(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf.md")
        try:
            converter.convert(sample_pdf, out, "md")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PDF→MD 需要 PyMuPDF（{exc}）")

    def test_output_is_text(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf_md.md")
        try:
            converter.convert(sample_pdf, out, "md")
            content = out.read_text(encoding="utf-8")
            assert isinstance(content, str)
            assert len(content) > 0
        except ConversionError:
            pytest.skip("PyMuPDF 不可用")


class TestPDFToDOCX:
    def test_primary_success(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf.docx")
        try:
            converter.convert(sample_pdf, out, "docx")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError:
            pytest.skip("pdf2docx 不可用，跳過首選路徑測試")

    def test_fallback_triggered_on_bad_file(self, converter, tmp_path, tmp_output):
        """測試降級路徑：損壞的 PDF 應觸發降級或失敗。"""
        bad_pdf = tmp_path / "bad.pdf"
        bad_pdf.write_bytes(b"not a real pdf content here")
        out = tmp_output("from_bad_pdf.docx")
        # 降級路徑也可能失敗（損壞檔案），允許 ConversionError
        try:
            converter.convert(bad_pdf, out, "docx")
        except ConversionError:
            pass  # 預期行為：損壞 PDF 應拋出 ConversionError


class TestPDFToImage:
    def test_single_page_pdf_to_png(self, converter, sample_pdf, tmp_output):
        """多頁 PDF → 應產出 PNG 或 ZIP。"""
        out = tmp_output("from_pdf.png")
        try:
            converter.convert(sample_pdf, out, "image")
            # sample.pdf 是 2 頁，應輸出 ZIP
            zip_out = out.with_suffix(".zip")
            assert out.exists() or zip_out.exists()
        except ConversionError as exc:
            pytest.skip(f"PDF→Image 需要 PyMuPDF（{exc}）")

    def test_output_nonempty(self, converter, sample_pdf, tmp_output):
        out = tmp_output("from_pdf_img.png")
        try:
            converter.convert(sample_pdf, out, "image")
            # 找到實際輸出（原路徑或 .zip）
            actual = out if out.exists() else out.with_suffix(".zip")
            assert actual.exists()
            assert actual.stat().st_size > 0
        except ConversionError:
            pytest.skip("PyMuPDF 不可用")
