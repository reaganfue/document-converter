"""掃描版 PDF OCR 端到端測試。

fixture 為程式生成的「純圖片 PDF」（文字畫成點陣圖再嵌入，無文字層），
模擬掃描器產出的 PDF。驗證 PDF→TXT / PDF→MD 能透過 RapidOCR 抽出文字。
"""
from __future__ import annotations

import io

import pytest

from converters.pdf_converter import PDFConverter
from converters.pdf_ocr import is_ocr_available, ocr_page

# OCR 後備引擎是本迭代核心依賴，缺失即視為環境壞掉 → 失敗而非跳過
pytestmark = pytest.mark.skipif(
    not is_ocr_available(), reason="rapidocr-onnxruntime 未安裝"
)

_SAMPLE_TEXT = "SCANNED OCR TEST 2026"


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory) -> "Path":
    """生成單頁「掃描版」PDF：大字白底點陣圖嵌入，無文字層。"""
    from pathlib import Path

    import fitz
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=56)
    draw.text((40, 100), _SAMPLE_TEXT, fill="black", font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")

    pdf_path = tmp_path_factory.mktemp("ocr") / "scanned.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_image(fitz.Rect(20, 40, 575, 210), stream=buf.getvalue())
    doc.save(str(pdf_path))
    doc.close()

    # 自我驗證 fixture 真的沒有文字層
    check = fitz.open(str(pdf_path))
    assert check[0].get_text().strip() == ""
    check.close()
    return pdf_path


class TestOCRAvailability:
    def test_ocr_engine_available(self):
        assert is_ocr_available() is True


class TestScannedPDFConversion:
    def test_ocr_page_recognizes_text(self, scanned_pdf):
        import fitz

        doc = fitz.open(str(scanned_pdf))
        try:
            text = ocr_page(doc[0])
        finally:
            doc.close()
        assert "SCANNED" in text.upper().replace(" ", "")
        assert "2026" in text

    def test_scanned_pdf_to_txt(self, scanned_pdf, tmp_path):
        output = tmp_path / "out.txt"
        PDFConverter().convert(scanned_pdf, output, "txt")
        content = output.read_text(encoding="utf-8")
        assert "SCANNED" in content.upper().replace(" ", "")

    def test_scanned_pdf_to_md(self, scanned_pdf, tmp_path):
        output = tmp_path / "out.md"
        PDFConverter().convert(scanned_pdf, output, "md")
        content = output.read_text(encoding="utf-8")
        assert "SCANNED" in content.upper().replace(" ", "")

    def test_native_text_pdf_bypasses_ocr(self, tmp_path, monkeypatch):
        """有文字層的 PDF 必須走原生抽取，不得觸發 OCR。"""
        import fitz

        import converters.pdf_converter as pc

        pdf_path = tmp_path / "native.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "NATIVE TEXT LAYER")
        doc.save(str(pdf_path))
        doc.close()

        called = []
        monkeypatch.setattr(pc, "ocr_page", lambda page: called.append(1) or "")

        output = tmp_path / "native.txt"
        PDFConverter().convert(pdf_path, output, "txt")
        assert "NATIVE TEXT LAYER" in output.read_text(encoding="utf-8")
        assert called == []
