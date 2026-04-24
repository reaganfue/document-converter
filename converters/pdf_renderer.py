"""
converters/pdf_renderer.py — 統一 PDF 渲染層

多引擎降級鏈（按可用性順序嘗試）：
  1. Chrome/Edge headless（--print-to-pdf，Windows 10/11 預裝 Edge）
  2. wkhtmltopdf CLI
  3. weasyprint（需要 GTK runtime）
  4. reportlab（純 Python 後備，品質中）

用法：
  from converters.pdf_renderer import get_renderer, diagnose_pdf_backends

  renderer = get_renderer()
  renderer.render_html_to_pdf(html_path, pdf_path)
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from .exceptions import ConversionError

logger = logging.getLogger(__name__)

# subprocess 超時（秒）— 給大型 HTML 足夠時間
_SUBPROCESS_TIMEOUT_SEC = 60

# Chrome headless 候選路徑（Windows 優先）
_CHROMIUM_CANDIDATES = [
    # Google Chrome — 64 位元
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    # Google Chrome — 32 位元相容路徑
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # Google Chrome — 用戶安裝（LOCALAPPDATA）
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    # Microsoft Edge — Windows 10/11 預裝
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # macOS Chrome
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    # macOS Chromium
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    # Linux Chrome
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


def _find_chromium_browser() -> Optional[str]:
    """偵測系統 Chrome/Edge 執行檔路徑。

    依序嘗試固定候選路徑，再 fallback 至 PATH 搜尋。

    Returns:
        有效的執行檔路徑字串，或 None（未安裝）
    """
    for candidate in _CHROMIUM_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate

    # PATH fallback — 不同作業系統的名稱
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe",
                 "google-chrome", "google-chrome-stable",
                 "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found

    return None


def _check_weasyprint() -> bool:
    """確認 weasyprint 可以正常 import（包含 GTK 動態庫）。"""
    try:
        from weasyprint import HTML  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


def _check_reportlab() -> bool:
    """確認 reportlab 可以 import。"""
    try:
        from reportlab.pdfgen import canvas  # noqa: F401
        return True
    except ImportError:
        return False


def _is_valid_pdf(pdf_path: Path) -> bool:
    """驗證 PDF 檔案有效：存在 + >0 bytes + 以 %PDF magic bytes 開頭。

    wkhtmltopdf 等工具在失敗時可能產出非空錯誤文字檔，
    此函式用來區分真正的 PDF 與偽裝成功的錯誤輸出。

    Args:
        pdf_path: 要驗證的檔案路徑

    Returns:
        True 表示是有效 PDF，False 表示不存在、空檔、或非 PDF 格式
    """
    try:
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return False
        with open(pdf_path, "rb") as f:
            header = f.read(4)
        return header == b"%PDF"
    except Exception:
        return False


def _render_via_chromium(html_path: Path, pdf_path: Path, options: dict) -> None:
    """Chrome/Edge headless --print-to-pdf 渲染引擎。

    使用臨時 user-data-dir 避免污染系統 Chrome profile。
    --headless=new 為 Chrome 112+ 新版 headless API；
    舊版 Chrome 會 ignore 此旗標並使用舊 API（仍可正常渲染）。

    Args:
        html_path: 來源 HTML 路徑（必須是本地檔案）
        pdf_path: 輸出 PDF 路徑
        options: 保留參數（目前未使用）

    Raises:
        RuntimeError: 未安裝瀏覽器、subprocess 失敗或未產出 PDF
    """
    browser = _find_chromium_browser()
    if not browser:
        raise RuntimeError("未偵測到 Chrome 或 Edge，無法使用 headless PDF 渲染")

    abs_html = html_path.resolve()
    abs_pdf = pdf_path.resolve()

    # 使用 file:// URI 處理含中文的路徑
    html_uri = abs_html.as_uri()

    # 使用臨時目錄隔離 Chrome profile，避免污染用戶設定。
    # 完整命令在 with 區塊內構建，確保 tmp_profile 生命週期正確。
    with tempfile.TemporaryDirectory(prefix="chrome_pdf_") as tmp_profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-extensions",
            "--disable-dev-shm-usage",
            "--run-all-compositor-stages-before-draw",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={abs_pdf}",
            "--virtual-time-budget=10000",  # 給 JS 10 秒執行時間
            f"--user-data-dir={tmp_profile}",
            html_uri,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_SUBPROCESS_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Chromium 渲染超時（>{_SUBPROCESS_TIMEOUT_SEC}s），HTML 可能過大或 JS 未完成"
            ) from exc

    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"Chromium headless 退出碼 {proc.returncode}: {stderr_text}"
        )

    if not _is_valid_pdf(abs_pdf):
        raise RuntimeError("Chromium 執行完成但未產出有效 PDF 檔案（缺少 %PDF magic bytes）")


def _render_via_wkhtmltopdf(html_path: Path, pdf_path: Path, options: dict) -> None:
    """wkhtmltopdf CLI 渲染引擎。

    Args:
        html_path: 來源 HTML 路徑
        pdf_path: 輸出 PDF 路徑
        options: 保留參數（目前未使用）

    Raises:
        RuntimeError: 未安裝 wkhtmltopdf 或執行失敗
    """
    wk = shutil.which("wkhtmltopdf") or shutil.which("wkhtmltopdf.exe")
    if not wk:
        raise RuntimeError("未安裝 wkhtmltopdf，跳過此引擎")

    proc = subprocess.run(
        [wk, "--enable-local-file-access", str(html_path), str(pdf_path)],
        capture_output=True,
        timeout=_SUBPROCESS_TIMEOUT_SEC,
        check=False,
    )

    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"wkhtmltopdf 失敗（退出碼 {proc.returncode}）: {stderr_text}")

    if not _is_valid_pdf(pdf_path):
        raise RuntimeError("wkhtmltopdf 執行完成但未產出有效 PDF（缺少 %PDF magic bytes）")


def _render_via_weasyprint(html_path: Path, pdf_path: Path, options: dict) -> None:
    """weasyprint HTML→PDF 渲染引擎（需要 GTK runtime）。

    Args:
        html_path: 來源 HTML 路徑
        pdf_path: 輸出 PDF 路徑
        options: 保留參數（目前未使用）

    Raises:
        RuntimeError: weasyprint 不可用（未安裝或 GTK 載入失敗）
    """
    try:
        from weasyprint import HTML as WeasyHTML
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"weasyprint 不可用（缺少 GTK？）: {exc}") from exc

    WeasyHTML(filename=str(html_path)).write_pdf(str(pdf_path))


def _render_via_reportlab(html_path: Path, pdf_path: Path, options: dict) -> None:
    """reportlab 純文字後備渲染引擎。

    從 HTML 抽取純文字，用 reportlab 產出基礎排版 PDF。
    不保留 CSS/圖片，但確保在任何環境下都能產出有效 PDF。

    中文字型：優先使用 Windows 微軟正黑（msjh.ttc），
               macOS/Linux 使用 NotoSansCJK，最後 fallback 至 Helvetica。

    Args:
        html_path: 來源 HTML 路徑
        pdf_path: 輸出 PDF 路徑
        options: 保留參數（目前未使用）

    Raises:
        RuntimeError: reportlab 未安裝
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:
        raise RuntimeError(f"reportlab 未安裝: {exc}") from exc

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError(f"beautifulsoup4 未安裝: {exc}") from exc

    # 嘗試載入 CJK 字型
    font_name = "Helvetica"
    cjk_candidates = [
        r"C:\Windows\Fonts\msjh.ttc",     # Windows 微軟正黑
        r"C:\Windows\Fonts\msyh.ttc",     # Windows 微軟雅黑
        r"C:\Windows\Fonts\mingliu.ttc",  # Windows 新細明體
        "/System/Library/Fonts/PingFang.ttc",           # macOS
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in cjk_candidates:
        if os.path.isfile(candidate):
            try:
                pdfmetrics.registerFont(TTFont("CJK", candidate))
                font_name = "CJK"
                break
            except Exception:
                continue

    html_text = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator="\n")

    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setFont(font_name, 11)
    page_width, page_height = A4
    margin = 40
    y_pos = page_height - margin
    line_height = 14
    # 已知限制：固定 80 字元折行對中文不準確（中文字寬約為英文的 2 倍），
    # 實際每行約 40 中文字。此為 reportlab 後備引擎的已知局限，
    # 主力路徑（Chromium）無此問題，CSS 排版完整支援 CJK 自動換行。
    max_chars_per_line = 80

    for raw_line in text.splitlines():
        if not raw_line.strip():
            y_pos -= line_height / 2
            continue

        # 超長行折行（簡易截斷）
        line = raw_line
        while line:
            if y_pos < margin:
                c.showPage()
                c.setFont(font_name, 11)
                y_pos = page_height - margin

            c.drawString(margin, y_pos, line[:max_chars_per_line])
            line = line[max_chars_per_line:]
            y_pos -= line_height

    c.save()


class PDFRenderer:
    """多層 PDF 渲染器。

    管理四個渲染引擎的降級鏈，依環境可用性依序嘗試。
    所有引擎失敗時拋出 ConversionError。
    """

    def __init__(self) -> None:
        # 引擎清單：(名稱, 渲染函式)
        # 順序決定優先級，不可隨意調換
        self._engines: list[tuple[str, Callable]] = [
            ("chromium", _render_via_chromium),
            ("wkhtmltopdf", _render_via_wkhtmltopdf),
            ("weasyprint", _render_via_weasyprint),
            ("reportlab", _render_via_reportlab),
        ]

    def render_html_to_pdf(
        self,
        html_path: Path,
        pdf_path: Path,
        options: Optional[dict] = None,
    ) -> None:
        """將 HTML 檔案渲染為 PDF。

        依可用性按順序嘗試渲染引擎：
          1. Chrome/Edge headless
          2. wkhtmltopdf
          3. weasyprint
          4. reportlab（純文字後備）

        Args:
            html_path: 來源 HTML 路徑（必須存在）
            pdf_path: 輸出 PDF 路徑（父目錄必須存在）
            options: 渲染選項（保留，目前未使用）

        Raises:
            ConversionError: 所有引擎都失敗
        """
        html_path = Path(html_path)
        pdf_path = Path(pdf_path)
        effective_options = options or {}
        engine_errors: dict[str, str] = {}

        for engine_name, engine_fn in self._engines:
            try:
                logger.info("PDF 渲染嘗試引擎: %s", engine_name)
                engine_fn(html_path, pdf_path, effective_options)

                # 驗證輸出：必須是有效 PDF（有 %PDF magic bytes）
                if _is_valid_pdf(pdf_path):
                    logger.info("PDF 渲染成功: %s（%d bytes）",
                                engine_name, pdf_path.stat().st_size)
                    return

                msg = f"引擎 {engine_name} 未產出有效 PDF（缺少 %PDF magic bytes 或空檔）"
                logger.warning(msg)
                engine_errors[engine_name] = msg

            except Exception as exc:
                logger.warning("引擎 %s 失敗: %s", engine_name, exc)
                engine_errors[engine_name] = str(exc)

        error_detail = "; ".join(f"{k}: {v}" for k, v in engine_errors.items())
        raise ConversionError(
            f"所有 PDF 渲染引擎失敗（html: {html_path}）— {error_detail}",
            source_error=RuntimeError(error_detail),
        )

    def get_available_engine(self) -> Optional[str]:
        """回傳第一個可用引擎的名稱（用於診斷）。

        Returns:
            引擎名稱字串，或 None（全部不可用）
        """
        if _find_chromium_browser():
            return "chromium"
        if shutil.which("wkhtmltopdf"):
            return "wkhtmltopdf"
        if _check_weasyprint():
            return "weasyprint"
        if _check_reportlab():
            return "reportlab"
        return None


# ─── 模組層級單例 ──────────────────────────────────────────────────────────────

_renderer_instance: Optional[PDFRenderer] = None
_renderer_lock = threading.Lock()


def get_renderer() -> PDFRenderer:
    """取得全域 PDFRenderer 單例（執行緒安全）。

    使用 double-checked locking + threading.Lock 保護，
    確保 Flask 多執行緒環境下不會建立多個實例。

    Returns:
        PDFRenderer 實例（懶建立，多次呼叫回傳同一物件）
    """
    global _renderer_instance
    if _renderer_instance is None:
        with _renderer_lock:
            if _renderer_instance is None:  # double-checked locking
                _renderer_instance = PDFRenderer()
    return _renderer_instance


def diagnose_pdf_backends() -> dict:
    """診斷各 PDF 渲染引擎的可用狀態。

    用於 /api/health 端點或啟動時自我診斷。

    Returns:
        各引擎狀態字典，格式：
        {
          "chromium": {"available": bool, "path": str | None},
          "wkhtmltopdf": {"available": bool, "path": str | None},
          "weasyprint": {"available": bool},
          "reportlab": {"available": bool},
        }
    """
    chromium_path = _find_chromium_browser()
    wk_path = shutil.which("wkhtmltopdf")

    return {
        "chromium": {
            "available": chromium_path is not None,
            "path": chromium_path,
        },
        "wkhtmltopdf": {
            "available": wk_path is not None,
            "path": wk_path,
        },
        "weasyprint": {
            "available": _check_weasyprint(),
        },
        "reportlab": {
            "available": _check_reportlab(),
        },
    }
