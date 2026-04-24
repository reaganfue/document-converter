"""
tests/test_converters/test_image_converter.py — 圖片轉換器測試
"""

import pytest
from pathlib import Path

from converters.image_converter import ImageConverter
from converters.exceptions import UnsupportedFormatError, ConversionError


@pytest.fixture(scope="module")
def converter():
    return ImageConverter()


class TestImageConverterMeta:
    def test_source_format(self, converter):
        assert converter.source_format == "image"

    def test_supported_targets(self, converter):
        for fmt in ["pdf", "image"]:
            assert converter.supports(fmt)

    def test_unsupported_target(self, converter):
        assert not converter.supports("docx")
        assert not converter.supports("html")

    def test_unsupported_raises(self, converter, sample_png, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            converter.convert(sample_png, tmp_output("out.docx"), "docx")


class TestIMGToPDF:
    def test_png_to_pdf_success(self, converter, sample_png, tmp_output):
        out = tmp_output("from_png.pdf")
        converter.convert(sample_png, out, "pdf")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_pdf_valid_header(self, converter, sample_png, tmp_output):
        out = tmp_output("from_png_pdf.pdf")
        converter.convert(sample_png, out, "pdf")
        assert out.read_bytes()[:4] == b"%PDF"

    def test_nonexistent_file_raises(self, converter, tmp_output):
        with pytest.raises(ConversionError):
            converter.convert(
                Path("/nonexistent/file.png"),
                tmp_output("out.pdf"),
                "pdf",
            )


class TestIMGToIMG:
    def test_png_to_jpg(self, converter, sample_png, tmp_output):
        out = tmp_output("from_png.jpg")
        converter.convert(sample_png, out, "image")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_jpg_output_no_alpha(self, converter, sample_png, tmp_output):
        """PNG→JPG 不應有 Alpha 通道。"""
        out = tmp_output("from_png_jpg.jpg")
        converter.convert(sample_png, out, "image")
        from PIL import Image
        img = Image.open(str(out))
        assert img.mode in ("RGB", "L"), "JPG 不應含 Alpha 通道"
        img.close()

    def test_png_to_png_identity(self, converter, sample_png, tmp_output):
        """PNG → PNG（格式互轉）應正常產出。"""
        out = tmp_output("from_png_copy.png")
        converter.convert(sample_png, out, "image")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_rgba_png_to_jpg_fills_white(self, tmp_path, converter):
        """RGBA 圖像轉 JPG 時應填白底，不拋例外。"""
        from PIL import Image
        import numpy as np

        # 建立 RGBA 測試圖
        rgba_img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))  # 半透明紅
        rgba_path = tmp_path / "rgba_test.png"
        rgba_img.save(str(rgba_path))
        rgba_img.close()

        out = tmp_path / "converted.jpg"
        converter.convert(rgba_path, out, "image")
        assert out.exists()

        result = Image.open(str(out))
        assert result.mode == "RGB"
        result.close()
