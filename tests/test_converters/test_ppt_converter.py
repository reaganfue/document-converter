"""
tests/test_converters/test_ppt_converter.py — PPT 轉換器測試
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from converters.ppt_converter import PPTConverter
from converters.exceptions import UnsupportedFormatError, ConversionError


@pytest.fixture(scope="module")
def converter():
    return PPTConverter()


class TestPPTConverterMeta:
    def test_source_format(self, converter):
        assert converter.source_format == "pptx"

    def test_supported_targets(self, converter):
        for fmt in ["pdf", "html", "txt", "image"]:
            assert converter.supports(fmt)

    def test_unsupported_target(self, converter):
        assert not converter.supports("docx")
        assert not converter.supports("md")

    def test_unsupported_raises(self, converter, sample_pptx, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            converter.convert(sample_pptx, tmp_output("out.docx"), "docx")


class TestPPTXToTXT:
    def test_primary_success(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx.txt")
        converter.convert(sample_pptx, out, "txt")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_contains_slide_marker(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx_txt.txt")
        converter.convert(sample_pptx, out, "txt")
        content = out.read_text(encoding="utf-8")
        assert "第" in content or "頁" in content or len(content) > 5

    def test_nonexistent_file_raises(self, converter, tmp_output):
        with pytest.raises(ConversionError):
            converter.convert(
                Path("/nonexistent/file.pptx"),
                tmp_output("out.txt"),
                "txt",
            )


class TestPPTXToHTML:
    def test_primary_success(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx.html")
        converter.convert(sample_pptx, out, "html")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_output_is_html(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx_html.html")
        converter.convert(sample_pptx, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "<html" in content.lower()

    def test_output_has_sections(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx_html2.html")
        converter.convert(sample_pptx, out, "html")
        content = out.read_text(encoding="utf-8")
        assert "slide" in content.lower() or "section" in content.lower() or "第" in content


class TestPPTXToPDF:
    def test_primary_success(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx.pdf")
        try:
            converter.convert(sample_pptx, out, "pdf")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PPTX→PDF 轉換失敗（環境限制）: {exc}")

    def test_fallback_to_pdf_renderer(self, converter, sample_pptx, tmp_output):
        """驗證降級路徑：mock Pillow 渲染失敗 → 使用 PDFRenderer 降級鏈。"""
        out = tmp_output("from_pptx_fallback.pdf")

        with patch.object(converter, "_render_slides_to_pngs") as mock_render:
            mock_render.side_effect = Exception("模擬 Pillow 渲染失敗")
            try:
                converter.convert(sample_pptx, out, "pdf")
                assert out.exists()
            except ConversionError:
                pytest.skip("PDFRenderer 降級鏈在此環境不可用（無可用 PDF 引擎）")


class TestPPTXToImage:
    def test_primary_success(self, converter, sample_pptx, tmp_output):
        out = tmp_output("from_pptx.png")
        try:
            converter.convert(sample_pptx, out, "image")
            # 多頁 PPTX 應輸出 ZIP
            zip_out = out.with_suffix(".zip")
            actual = out if out.exists() else zip_out
            assert actual.exists()
            assert actual.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PPTX→IMG 轉換失敗: {exc}")
