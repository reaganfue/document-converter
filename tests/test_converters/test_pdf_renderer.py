"""
tests/test_converters/test_pdf_renderer.py — PDF 渲染引擎降級鏈測試

測試範圍：
  - Chrome/Edge 偵測邏輯
  - 各引擎 mock 成功 / 失敗行為
  - 降級鏈（首選失敗→次選）
  - 全引擎失敗拋出 ConversionError
  - reportlab 實際產出 PDF
  - diagnose_pdf_backends API
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import converters.pdf_renderer as pdf_renderer_module
from converters.exceptions import ConversionError
from converters.pdf_renderer import (
    PDFRenderer,
    _find_chromium_browser,
    _is_valid_pdf,
    _render_via_chromium,
    _render_via_reportlab,
    _render_via_wkhtmltopdf,
    diagnose_pdf_backends,
    get_renderer,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def simple_html_file(tmp_path: Path) -> Path:
    """產出含中文的最簡 HTML 測試檔。"""
    html_path = tmp_path / "test.html"
    html_path.write_text(
        "<html><body><h1>測試標題</h1><p>你好世界</p></body></html>",
        encoding="utf-8",
    )
    return html_path


@pytest.fixture
def pdf_output(tmp_path: Path) -> Path:
    """PDF 輸出路徑（尚未存在）。"""
    return tmp_path / "output.pdf"


# ─── Test 1: Chrome 偵測 — 找到 Chrome ───────────────────────────────────────


class TestChromiumDetection:
    def test_chromium_detection_windows_chrome(self):
        """mock os.path.isfile 讓 Chrome 路徑存在，應回傳該路徑。"""
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        def fake_isfile(path):
            return path == chrome_path

        with patch("converters.pdf_renderer.os.path.isfile", side_effect=fake_isfile):
            result = _find_chromium_browser()

        assert result == chrome_path

    def test_chromium_detection_windows_edge(self):
        """mock os.path.isfile 讓 Edge 路徑存在（Chrome 不存在），應回傳 Edge。"""
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

        def fake_isfile(path):
            return path == edge_path

        with patch("converters.pdf_renderer.os.path.isfile", side_effect=fake_isfile):
            result = _find_chromium_browser()

        assert result == edge_path

    def test_chromium_detection_not_found(self):
        """所有路徑不存在且 PATH 也找不到，應回傳 None。"""
        with (
            patch("converters.pdf_renderer.os.path.isfile", return_value=False),
            patch("converters.pdf_renderer.shutil.which", return_value=None),
        ):
            result = _find_chromium_browser()

        assert result is None

    def test_chromium_detection_path_fallback(self):
        """所有固定路徑不存在，但 PATH 找到 chrome，應回傳 PATH 結果。"""
        with (
            patch("converters.pdf_renderer.os.path.isfile", return_value=False),
            patch("converters.pdf_renderer.shutil.which", return_value="/usr/bin/chrome"),
        ):
            result = _find_chromium_browser()

        assert result == "/usr/bin/chrome"


# ─── Test 4: Chromium 引擎成功 ────────────────────────────────────────────────


class TestRenderViaChromium:
    def test_render_via_chromium_success(self, simple_html_file: Path, pdf_output: Path):
        """mock subprocess.run 成功 + 模擬 PDF 寫入，應完成不拋例外。"""
        def fake_run(cmd, **kwargs):
            # 模擬 Chrome 寫出 PDF 檔案
            for arg in cmd:
                if isinstance(arg, str) and arg.startswith("--print-to-pdf="):
                    out_path = Path(arg.split("=", 1)[1])
                    out_path.write_bytes(b"%PDF-1.4 fake pdf content")
                    break
            return MagicMock(returncode=0, stderr=b"")

        with (
            patch("converters.pdf_renderer._find_chromium_browser",
                  return_value=r"C:\chrome.exe"),
            patch("converters.pdf_renderer.subprocess.run", side_effect=fake_run),
        ):
            _render_via_chromium(simple_html_file, pdf_output, {})

        assert pdf_output.exists()
        assert pdf_output.stat().st_size > 0

    def test_render_via_chromium_nonzero_exit_raises(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """Chromium 回傳非零退出碼，應拋出 RuntimeError。"""
        mock_proc = MagicMock(returncode=1, stderr=b"some error")

        with (
            patch("converters.pdf_renderer._find_chromium_browser",
                  return_value=r"C:\chrome.exe"),
            patch("converters.pdf_renderer.subprocess.run", return_value=mock_proc),
        ):
            with pytest.raises(RuntimeError, match="退出碼"):
                _render_via_chromium(simple_html_file, pdf_output, {})

    def test_render_via_chromium_no_browser_raises(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """未偵測到瀏覽器，應拋出 RuntimeError。"""
        with patch("converters.pdf_renderer._find_chromium_browser", return_value=None):
            with pytest.raises(RuntimeError, match="未偵測到 Chrome"):
                _render_via_chromium(simple_html_file, pdf_output, {})


# ─── Test 5: 降級鏈（首選失敗→次選成功）────────────────────────────────────────


class TestFallbackChain:
    def test_chromium_fails_falls_back_to_wkhtmltopdf(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """Chromium 失敗，應降級到 wkhtmltopdf 並成功。"""
        def wk_success(html_path, pdf_path, options):
            pdf_path.write_bytes(b"%PDF-1.4 wkhtmltopdf")

        with (
            patch("converters.pdf_renderer._render_via_chromium",
                  side_effect=RuntimeError("chrome not found")),
            patch("converters.pdf_renderer._render_via_wkhtmltopdf",
                  side_effect=wk_success),
        ):
            renderer = PDFRenderer()
            renderer.render_html_to_pdf(simple_html_file, pdf_output)

        assert pdf_output.exists()
        assert pdf_output.read_bytes().startswith(b"%PDF")

    def test_chromium_and_wkhtmltopdf_fail_weasyprint_succeeds(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """前兩個引擎失敗，weasyprint 成功。"""
        def weasy_success(html_path, pdf_path, options):
            pdf_path.write_bytes(b"%PDF-1.4 weasyprint")

        with (
            patch("converters.pdf_renderer._render_via_chromium",
                  side_effect=RuntimeError("no chrome")),
            patch("converters.pdf_renderer._render_via_wkhtmltopdf",
                  side_effect=RuntimeError("no wkhtmltopdf")),
            patch("converters.pdf_renderer._render_via_weasyprint",
                  side_effect=weasy_success),
        ):
            renderer = PDFRenderer()
            renderer.render_html_to_pdf(simple_html_file, pdf_output)

        assert pdf_output.exists()


# ─── Test 6: 全引擎失敗 → ConversionError ───────────────────────────────────


class TestAllEnginesFail:
    def test_all_engines_fail_raises_conversion_error(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """所有引擎都失敗時，應拋出 ConversionError。"""
        with (
            patch("converters.pdf_renderer._render_via_chromium",
                  side_effect=RuntimeError("no chrome")),
            patch("converters.pdf_renderer._render_via_wkhtmltopdf",
                  side_effect=RuntimeError("no wkhtmltopdf")),
            patch("converters.pdf_renderer._render_via_weasyprint",
                  side_effect=RuntimeError("no weasyprint")),
            patch("converters.pdf_renderer._render_via_reportlab",
                  side_effect=RuntimeError("no reportlab")),
        ):
            renderer = PDFRenderer()
            with pytest.raises(ConversionError):
                renderer.render_html_to_pdf(simple_html_file, pdf_output)


# ─── Test 7: reportlab 實際產出有效 PDF ─────────────────────────────────────


class TestReportlabFallback:
    def test_reportlab_fallback_produces_valid_pdf(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """reportlab 在不呼叫任何外部程式的情況下產出有效 PDF。"""
        pytest.importorskip("reportlab", reason="reportlab 未安裝，跳過")
        pytest.importorskip("bs4", reason="beautifulsoup4 未安裝，跳過")

        _render_via_reportlab(simple_html_file, pdf_output, {})

        assert pdf_output.exists(), "PDF 檔案應已存在"
        content = pdf_output.read_bytes()
        assert content[:4] == b"%PDF", f"PDF 應以 %PDF 開頭，實際為 {content[:8]}"
        assert pdf_output.stat().st_size > 100, "PDF 不應是空檔案"

    def test_reportlab_cjk_content(self, tmp_path: Path):
        """reportlab 應能處理含中文字的 HTML 而不崩潰。"""
        pytest.importorskip("reportlab", reason="reportlab 未安裝，跳過")
        pytest.importorskip("bs4", reason="beautifulsoup4 未安裝，跳過")

        html_path = tmp_path / "cjk.html"
        html_path.write_text(
            "<html><body>"
            "<h1>繁體中文測試</h1>"
            "<p>這是一段很長的中文段落，用來測試 reportlab 的基礎渲染能力。</p>"
            "<p>Hello World 混合 English 內容。</p>"
            "</body></html>",
            encoding="utf-8",
        )
        pdf_path = tmp_path / "cjk_output.pdf"

        _render_via_reportlab(html_path, pdf_path, {})

        assert pdf_path.exists()
        assert pdf_path.read_bytes()[:4] == b"%PDF"


# ─── Test 8: diagnose_pdf_backends API ──────────────────────────────────────


class TestDiagnosePdfBackends:
    def test_diagnose_returns_dict_with_required_keys(self):
        """diagnose_pdf_backends 應回傳含四個引擎狀態的字典。"""
        result = diagnose_pdf_backends()

        assert isinstance(result, dict)
        assert "chromium" in result
        assert "wkhtmltopdf" in result
        assert "weasyprint" in result
        assert "reportlab" in result

    def test_diagnose_chromium_structure(self):
        """chromium 欄位應含 available (bool) 和 path (str|None)。"""
        result = diagnose_pdf_backends()

        chrom = result["chromium"]
        assert isinstance(chrom["available"], bool)
        assert "path" in chrom
        # path 必須是字串或 None
        assert chrom["path"] is None or isinstance(chrom["path"], str)

    def test_diagnose_weasyprint_structure(self):
        """weasyprint 欄位應含 available (bool)。"""
        result = diagnose_pdf_backends()

        weasy = result["weasyprint"]
        assert isinstance(weasy["available"], bool)

    def test_diagnose_reportlab_available_when_installed(self):
        """如果 reportlab 已安裝，available 應為 True。"""
        try:
            import reportlab  # noqa: F401
            result = diagnose_pdf_backends()
            assert result["reportlab"]["available"] is True
        except ImportError:
            pytest.skip("reportlab 未安裝")

    def test_diagnose_when_nothing_available(self):
        """模擬全不可用環境，所有 available 應為 False。"""
        with (
            patch("converters.pdf_renderer._find_chromium_browser", return_value=None),
            patch("converters.pdf_renderer.shutil.which", return_value=None),
            patch("converters.pdf_renderer._check_weasyprint", return_value=False),
            patch("converters.pdf_renderer._check_reportlab", return_value=False),
        ):
            result = diagnose_pdf_backends()

        assert result["chromium"]["available"] is False
        assert result["wkhtmltopdf"]["available"] is False
        assert result["weasyprint"]["available"] is False
        assert result["reportlab"]["available"] is False


# ─── Test 9: get_renderer 單例 ───────────────────────────────────────────────


class TestGetRenderer:
    def test_get_renderer_returns_pdf_renderer_instance(self):
        """get_renderer 應回傳 PDFRenderer 實例。"""
        renderer = get_renderer()
        assert isinstance(renderer, PDFRenderer)

    def test_get_renderer_returns_same_instance(self):
        """get_renderer 應每次回傳同一個單例。"""
        r1 = get_renderer()
        r2 = get_renderer()
        assert r1 is r2

    def test_renderer_has_render_html_to_pdf_method(self):
        """PDFRenderer 應提供 render_html_to_pdf 公開方法。"""
        renderer = get_renderer()
        assert hasattr(renderer, "render_html_to_pdf")
        assert callable(renderer.render_html_to_pdf)


# ─── Test 10: Chromium Timeout → RuntimeError ────────────────────────────────


class TestChromiumTimeout:
    def test_chromium_timeout_raises_runtime_error(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """Chrome 渲染超時應拋出 RuntimeError 而非 UnboundLocalError。"""
        with (
            patch("converters.pdf_renderer._find_chromium_browser",
                  return_value=r"C:\fake_chrome.exe"),
            patch(
                "converters.pdf_renderer.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="chrome", timeout=60),
            ),
        ):
            with pytest.raises(RuntimeError, match="超時"):
                _render_via_chromium(simple_html_file, pdf_output, {})

    def test_chromium_timeout_does_not_raise_unbound_local_error(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """TimeoutExpired 不應導致 UnboundLocalError（proc 未定義）。"""
        with (
            patch("converters.pdf_renderer._find_chromium_browser",
                  return_value=r"C:\fake_chrome.exe"),
            patch(
                "converters.pdf_renderer.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="chrome", timeout=60),
            ),
        ):
            try:
                _render_via_chromium(simple_html_file, pdf_output, {})
            except RuntimeError:
                pass  # 預期的例外
            except UnboundLocalError as exc:
                pytest.fail(f"不應拋出 UnboundLocalError，修復未生效: {exc}")


# ─── Test 11: _is_valid_pdf helper ──────────────────────────────────────────


class TestIsValidPdf:
    def test_valid_pdf_returns_true(self, tmp_path: Path):
        """有效 PDF（%PDF magic bytes）應回傳 True。"""
        pdf = tmp_path / "valid.pdf"
        pdf.write_bytes(b"%PDF-1.4 minimal pdf content")
        assert _is_valid_pdf(pdf) is True

    def test_nonexistent_file_returns_false(self, tmp_path: Path):
        """不存在的檔案應回傳 False。"""
        assert _is_valid_pdf(tmp_path / "nonexistent.pdf") is False

    def test_empty_file_returns_false(self, tmp_path: Path):
        """空檔案應回傳 False。"""
        pdf = tmp_path / "empty.pdf"
        pdf.write_bytes(b"")
        assert _is_valid_pdf(pdf) is False

    def test_text_error_file_returns_false(self, tmp_path: Path):
        """wkhtmltopdf 失敗時產出的錯誤文字檔應回傳 False。"""
        pdf = tmp_path / "error.pdf"
        pdf.write_text("Error: wkhtmltopdf failed with code 1", encoding="utf-8")
        assert _is_valid_pdf(pdf) is False


# ─── Test 12: wkhtmltopdf 引擎獨立測試 ───────────────────────────────────────


class TestRenderViaWkhtmltopdf:
    def test_missing_wkhtmltopdf_raises_runtime_error(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """未安裝 wkhtmltopdf 應拋出 RuntimeError。"""
        with patch("converters.pdf_renderer.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="wkhtmltopdf"):
                _render_via_wkhtmltopdf(simple_html_file, pdf_output, {})

    def test_wkhtmltopdf_success(self, simple_html_file: Path, pdf_output: Path):
        """wkhtmltopdf 成功執行且產出有效 PDF 時，不應拋例外。"""
        def fake_run(cmd, **kwargs):
            # 找到 pdf 輸出路徑參數並寫入有效 PDF
            out_path = Path(cmd[-1])  # wkhtmltopdf 最後一個參數為 output
            out_path.write_bytes(b"%PDF-1.4 fake wkhtmltopdf pdf")
            return MagicMock(returncode=0, stderr=b"")

        with (
            patch("converters.pdf_renderer.shutil.which", return_value=r"C:\wkhtmltopdf.exe"),
            patch("converters.pdf_renderer.subprocess.run", side_effect=fake_run),
        ):
            _render_via_wkhtmltopdf(simple_html_file, pdf_output, {})

        assert pdf_output.exists()
        assert pdf_output.read_bytes()[:4] == b"%PDF"

    def test_wkhtmltopdf_nonzero_exit_raises(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """wkhtmltopdf 回傳非零退出碼應拋出 RuntimeError。"""
        mock_proc = MagicMock(returncode=1, stderr=b"fatal error")

        with (
            patch("converters.pdf_renderer.shutil.which", return_value=r"C:\wkhtmltopdf.exe"),
            patch("converters.pdf_renderer.subprocess.run", return_value=mock_proc),
        ):
            with pytest.raises(RuntimeError, match="退出碼"):
                _render_via_wkhtmltopdf(simple_html_file, pdf_output, {})

    def test_wkhtmltopdf_error_output_file_fails_validation(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """wkhtmltopdf 產出非 PDF 的錯誤文字時，應被 magic bytes 驗證攔截。"""
        def fake_run_with_text_output(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.write_text("Error: rendering failed", encoding="utf-8")
            return MagicMock(returncode=0, stderr=b"")

        with (
            patch("converters.pdf_renderer.shutil.which", return_value=r"C:\wkhtmltopdf.exe"),
            patch("converters.pdf_renderer.subprocess.run",
                  side_effect=fake_run_with_text_output),
        ):
            with pytest.raises(RuntimeError, match="magic bytes"):
                _render_via_wkhtmltopdf(simple_html_file, pdf_output, {})


# ─── Test 13: URL 特殊字元防衛性檢查（F05）──────────────────────────────────


class TestChromiumUrlHandling:
    def test_chromium_uuid_path_renders_safely(
        self, simple_html_file: Path, pdf_output: Path
    ):
        """UUID 路徑（本專案標準）不含 #/? 特殊字元，應安全渲染。"""
        def fake_run(cmd, **kwargs):
            # 確認 cmd 中有 file:// URI
            html_uri_args = [a for a in cmd if a.startswith("file://")]
            assert len(html_uri_args) == 1, "應含有 file:// URI 參數"
            # UUID 路徑不含 # 或 ?
            assert "#" not in html_uri_args[0], "UUID 路徑不應含 #"
            assert "?" not in html_uri_args[0], "UUID 路徑不應含 ?"

            for arg in cmd:
                if isinstance(arg, str) and arg.startswith("--print-to-pdf="):
                    Path(arg.split("=", 1)[1]).write_bytes(b"%PDF-1.4 test")
                    break
            return MagicMock(returncode=0, stderr=b"")

        with (
            patch("converters.pdf_renderer._find_chromium_browser",
                  return_value=r"C:\chrome.exe"),
            patch("converters.pdf_renderer.subprocess.run", side_effect=fake_run),
        ):
            _render_via_chromium(simple_html_file, pdf_output, {})
