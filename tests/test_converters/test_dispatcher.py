"""
tests/test_converters/test_dispatcher.py — Dispatcher 路由測試
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from converters.dispatcher import (
    convert_file,
    detect_format,
    get_supported_matrix,
    is_supported_pair,
)
from converters.exceptions import UnsupportedFormatError, ConversionError


class TestGetSupportedMatrix:
    def test_returns_dict(self):
        matrix = get_supported_matrix()
        assert isinstance(matrix, dict)

    def test_has_all_source_formats(self):
        matrix = get_supported_matrix()
        expected = {"pdf", "docx", "pptx", "html", "md", "txt", "image"}
        assert set(matrix.keys()) == expected

    def test_pdf_targets_correct(self):
        matrix = get_supported_matrix()
        pdf_targets = set(matrix["pdf"].keys())
        assert "docx" in pdf_targets
        assert "html" in pdf_targets
        assert "txt" in pdf_targets
        assert "pptx" not in pdf_targets  # 不支援

    def test_quality_labels_valid(self):
        matrix = get_supported_matrix()
        valid_labels = {"high", "medium", "low"}
        for source, targets in matrix.items():
            for target, label in targets.items():
                assert label in valid_labels, f"{source}→{target} 的標籤 '{label}' 無效"


class TestDetectFormat:
    def test_pdf_detection(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.touch()
        assert detect_format(f) == "pdf"

    def test_docx_detection(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.touch()
        assert detect_format(f) == "docx"

    def test_pptx_detection(self, tmp_path):
        f = tmp_path / "slides.pptx"
        f.touch()
        assert detect_format(f) == "pptx"

    def test_html_detection(self, tmp_path):
        f = tmp_path / "page.html"
        f.touch()
        assert detect_format(f) == "html"

    def test_htm_detection(self, tmp_path):
        f = tmp_path / "page.htm"
        f.touch()
        assert detect_format(f) == "html"

    def test_md_detection(self, tmp_path):
        f = tmp_path / "readme.md"
        f.touch()
        assert detect_format(f) == "md"

    def test_txt_detection(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.touch()
        assert detect_format(f) == "txt"

    def test_png_detection(self, tmp_path):
        f = tmp_path / "image.png"
        f.touch()
        assert detect_format(f) == "image"

    def test_jpg_detection(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.touch()
        assert detect_format(f) == "image"

    def test_unknown_ext_raises(self, tmp_path):
        f = tmp_path / "file.xyz"
        f.touch()
        with pytest.raises(ValueError):
            detect_format(f)


class TestIsSupportedPair:
    def test_valid_pairs(self):
        valid = [
            ("pdf", "docx"), ("pdf", "txt"), ("pdf", "html"),
            ("docx", "pdf"), ("docx", "html"), ("docx", "md"),
            ("html", "pdf"), ("html", "docx"), ("html", "txt"),
            ("md", "html"), ("md", "pdf"), ("md", "docx"),
            ("txt", "pdf"), ("txt", "html"), ("txt", "md"),
            ("image", "pdf"), ("image", "image"),
        ]
        for src, tgt in valid:
            assert is_supported_pair(src, tgt), f"應支援 {src}→{tgt}"

    def test_invalid_pairs(self):
        invalid = [
            ("pdf", "pptx"),  # ✗*
            ("docx", "image"),  # ✗
            ("pptx", "docx"),  # ✗*
            ("image", "html"),  # ✗
        ]
        for src, tgt in invalid:
            assert not is_supported_pair(src, tgt), f"不應支援 {src}→{tgt}"


class TestConvertFileRouting:
    def test_routes_to_correct_converter(self, sample_txt, tmp_output):
        """convert_file 應路由到正確的 Converter 並執行。"""
        out = tmp_output("routed.html")
        convert_file(sample_txt, out, "txt", "html")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_unknown_source_raises(self, tmp_path):
        with pytest.raises(UnsupportedFormatError):
            convert_file(
                tmp_path / "file.xyz",
                tmp_path / "out.txt",
                "unknown_format",
                "txt",
            )

    def test_unsupported_target_raises(self, sample_txt, tmp_output):
        with pytest.raises(UnsupportedFormatError):
            convert_file(sample_txt, tmp_output("out.pptx"), "txt", "pptx")

    def test_md_to_html_routing(self, sample_md, tmp_output):
        out = tmp_output("md_to_html.html")
        convert_file(sample_md, out, "md", "html")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<html" in content.lower()

    def test_pdf_to_txt_routing(self, sample_pdf, tmp_output):
        out = tmp_output("pdf_to_txt.txt")
        try:
            convert_file(sample_pdf, out, "pdf", "txt")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"PDF→TXT 需要 PyMuPDF（{exc}）")

    def test_html_to_md_routing(self, sample_html, tmp_output):
        out = tmp_output("html_to_md.md")
        try:
            convert_file(sample_html, out, "html", "md")
            assert out.exists()
            assert out.stat().st_size > 0
        except ConversionError as exc:
            pytest.skip(f"HTML→MD 需要 html2text（{exc}）")

    def test_txt_to_docx_routing(self, sample_txt, tmp_output):
        out = tmp_output("txt_to_docx.docx")
        convert_file(sample_txt, out, "txt", "docx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_image_to_pdf_routing(self, sample_png, tmp_output):
        out = tmp_output("img_to_pdf.pdf")
        convert_file(sample_png, out, "image", "pdf")
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_accepts_string_paths(self, sample_txt, tmp_output):
        """convert_file 應接受字串路徑（非 Path 物件）。"""
        out = tmp_output("str_path_test.html")
        convert_file(str(sample_txt), str(out), "txt", "html")
        assert out.exists()
