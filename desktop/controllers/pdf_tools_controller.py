"""
desktop/controllers/pdf_tools_controller.py — PDF 工具 Controller

透過 QThreadPool 非同步執行 converters.pdf_tools 的五項操作。
所有操作都不阻塞主執行緒，進度與結果透過 PdfToolsControllerSignals 回傳。

Signal 流程：
    UI 按鈕 → PdfToolsController.merge() / split() / ...
        → _PdfToolWorker.run()  (worker thread)
            → converters.pdf_tools.*  (純函式)
            → worker signals → 主執行緒 Signal 轉發
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from converters.pdf_tools import (
    PdfCorruptedError,
    PdfPasswordError,
    PdfToolError,
    apply_text_edits,
    check_edit_warnings,
    compress_pdf,
    decrypt_pdf,
    encrypt_pdf,
    extract_text_spans,
    get_pdf_info,
    measure_overflow,
    merge_pdfs,
    render_page_png,
    split_pdf,
)
from desktop.interfaces import PdfToolsControllerSignals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker 內部 Signals（必須是 QObject 才能跨執行緒 emit）
# ---------------------------------------------------------------------------

class _WorkerSignals(QObject):
    """_PdfToolWorker 使用的內部 Signal（在 worker thread 中 emit，Qt 自動排隊到主執行緒）。"""

    progress = Signal(float)            # 0.0–1.0
    completed = Signal(str, object)     # operation_name, result
    failed = Signal(str, str)           # operation_name, error_message


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class _PdfToolWorker(QRunnable):
    """QRunnable worker，包裝單一 pdf_tools 函式呼叫。

    Args:
        operation_name: 操作名稱（"merge" / "split" / "compress" / "encrypt" / "decrypt"），
                        用於 Signal 識別。
        func:           要執行的 pdf_tools 函式（無 progress_callback 參數）。
        kwargs:         傳入 func 的關鍵字參數（progress_callback 由 worker 自動注入）。
    """

    def __init__(
        self,
        operation_name: str,
        func: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._operation_name = operation_name
        self._func = func
        self._kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self) -> None:
        """在 worker thread 執行操作。捕捉所有例外，以 Signal 通知結果。"""
        progress_callback: Callable[[float], None] = lambda p: self.signals.progress.emit(p)

        try:
            result = self._func(**self._kwargs, progress_callback=progress_callback)
            self.signals.completed.emit(self._operation_name, result)
        except PdfPasswordError as exc:
            logger.warning("pdf_tools %s 密碼錯誤: %s", self._operation_name, exc)
            self.signals.failed.emit(self._operation_name, f"密碼錯誤：{exc}")
        except PdfCorruptedError as exc:
            logger.warning("pdf_tools %s PDF 損壞: %s", self._operation_name, exc)
            self.signals.failed.emit(self._operation_name, f"PDF 檔案損壞或無法開啟：{exc}")
        except PdfToolError as exc:
            logger.warning("pdf_tools %s 操作失敗: %s", self._operation_name, exc)
            self.signals.failed.emit(self._operation_name, str(exc))
        except Exception as exc:
            logger.exception("pdf_tools %s 未預期例外", self._operation_name)
            self.signals.failed.emit(self._operation_name, f"未預期錯誤：{exc}")


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class PdfToolsController(QObject):
    """PDF 工具非同步 Controller。

    透過 QThreadPool 執行 merge / split / compress / encrypt / decrypt，
    完成後透過 self.signals 通知 UI。

    使用方式（UI 層）：
        controller = PdfToolsController()
        controller.signals.operation_progress.connect(progress_bar.setValue_float)
        controller.signals.operation_completed.connect(on_completed)
        controller.signals.operation_failed.connect(on_failed)
        controller.merge(input_paths=[...], output_path=Path(...))
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.signals = PdfToolsControllerSignals()
        self._thread_pool = QThreadPool.globalInstance()

    # -------------------------------------------------------------------------
    # 內部：建立並啟動 worker
    # -------------------------------------------------------------------------

    def _start_worker(
        self,
        operation_name: str,
        func: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> None:
        """建立 _PdfToolWorker，連接 signals，投入 QThreadPool。"""
        worker = _PdfToolWorker(operation_name, func, kwargs)
        worker.signals.progress.connect(self.signals.operation_progress)
        worker.signals.completed.connect(self.signals.operation_completed)
        worker.signals.failed.connect(self.signals.operation_failed)

        self.signals.operation_started.emit(operation_name)
        logger.info("pdf_tools: 啟動 %s worker", operation_name)
        self._thread_pool.start(worker)

    # -------------------------------------------------------------------------
    # 公開操作方法
    # -------------------------------------------------------------------------

    @Slot(list, Path)
    def merge(self, input_paths: list[Path], output_path: Path) -> None:
        """非同步合併多個 PDF 為單一輸出檔。

        Args:
            input_paths: 要合併的 PDF 路徑清單（至少 1 個）。
            output_path: 合併結果輸出路徑（父目錄必須存在）。
        """
        self._start_worker(
            "merge",
            merge_pdfs,
            {"input_paths": input_paths, "output_path": output_path},
        )

    @Slot(Path, Path, str, object)
    def split(
        self,
        input_path: Path,
        output_dir: Path,
        mode: str,
        ranges: list[tuple[int, int]] | None = None,
    ) -> None:
        """非同步拆分 PDF。

        Args:
            input_path: 來源 PDF 路徑。
            output_dir: 拆分結果輸出目錄（必須存在）。
            mode:       "per_page" | "ranges" | "bookmarks"。
            ranges:     頁面範圍清單（mode="ranges" 時必填）。
        """
        kwargs: dict[str, Any] = {
            "input_path": input_path,
            "output_dir": output_dir,
            "mode": mode,
        }
        if ranges is not None:
            kwargs["ranges"] = ranges
        self._start_worker("split", split_pdf, kwargs)

    @Slot(Path, Path, str)
    def compress(self, input_path: Path, output_path: Path, quality: str) -> None:
        """非同步壓縮 PDF。

        Args:
            input_path:  來源 PDF 路徑。
            output_path: 壓縮結果輸出路徑。
            quality:     壓縮等級 "low" | "balanced" | "high"。
        """
        self._start_worker(
            "compress",
            compress_pdf,
            {"input_path": input_path, "output_path": output_path, "quality": quality},
        )

    @Slot(Path, Path, str, str)
    def encrypt(
        self,
        input_path: Path,
        output_path: Path,
        user_password: str,
        owner_password: str | None = None,
    ) -> None:
        """非同步加密 PDF（AES-256）。

        Args:
            input_path:     來源 PDF 路徑。
            output_path:    加密結果輸出路徑。
            user_password:  開啟文件所需密碼（不可空）。
            owner_password: 擁有者密碼；None 時與 user_password 相同。
        """
        kwargs: dict[str, Any] = {
            "input_path": input_path,
            "output_path": output_path,
            "user_password": user_password,
        }
        if owner_password is not None:
            kwargs["owner_password"] = owner_password
        self._start_worker("encrypt", encrypt_pdf, kwargs)

    @Slot(Path, Path, str)
    def decrypt(self, input_path: Path, output_path: Path, password: str) -> None:
        """非同步解密（移除密碼保護）PDF。

        Args:
            input_path:  來源（加密）PDF 路徑。
            output_path: 解密結果輸出路徑（父目錄必須存在）。
            password:    解鎖密碼（user 或 owner password 均可）。
        """
        self._start_worker(
            "decrypt",
            decrypt_pdf,
            {"input_path": input_path, "output_path": output_path, "password": password},
        )

    def get_info(self, input_path: Path) -> dict:
        """同步讀取 PDF 元資訊（不啟動 worker）。

        Args:
            input_path: 來源 PDF 路徑。

        Returns:
            {page_count, size_bytes, is_encrypted, has_bookmarks, title, author}

        Raises:
            PdfToolError / PdfCorruptedError — 呼叫方負責處理。
        """
        return get_pdf_info(input_path)

    # -------------------------------------------------------------------------
    # 文字小修（box-level 編輯）
    # -------------------------------------------------------------------------

    def extract_spans(self, input_path: Path, page_num: int) -> list[dict]:
        """同步讀取指定頁的可編輯文字段落（不啟動 worker）。

        Args:
            input_path: 來源 PDF 路徑。
            page_num:   頁碼（0-indexed）。

        Returns:
            list[dict] — 每段含 index/text/font/size/color/edit_font_exact/bbox。
            詳見 converters.pdf_tools.extract_text_spans。

        Raises:
            PdfToolError / PdfPasswordError / PdfCorruptedError — 呼叫方負責處理。
        """
        return extract_text_spans(input_path, page_num)

    def render_page(self, input_path: Path, page_num: int, scale: float = 2.0) -> bytes:
        """同步渲染指定頁為 PNG bytes（不啟動 worker），供 UI 預覽。

        Args:
            input_path: 來源 PDF 路徑。
            page_num:   頁碼（0-indexed）。
            scale:      渲染倍率（2.0 ≈ 144 dpi）。

        Returns:
            PNG 影像 bytes。

        Raises:
            PdfToolError / PdfPasswordError / PdfCorruptedError — 呼叫方負責處理。
        """
        return render_page_png(input_path, page_num, scale)

    @Slot(Path, Path, list)
    def apply_text_edits_async(
        self,
        input_path: Path,
        output_path: Path,
        edits: list[dict],
    ) -> None:
        """非同步套用一批文字替換並另存。

        operation_name="edit_text"；完成後 operation_completed 回傳
        {"edited_count": int, "overflow_count": int}。

        Args:
            input_path:  來源 PDF 路徑。
            output_path: 輸出 PDF 路徑。
            edits:       [{"page": int, "index": int, "new_text": str}, ...]。
        """
        self._start_worker(
            "edit_text",
            apply_text_edits,
            {"input_path": input_path, "output_path": output_path, "edits": edits},
        )

    def measure_overflow(
        self,
        new_text: str,
        pdf_font_name: str,
        fontsize: float,
        max_width: float,
    ) -> bool:
        """同步估算新文字是否爆框（供 UI 即時標紅，不啟動 worker）。

        Args:
            new_text:      要填入的新文字。
            pdf_font_name: 原 span 字型名。
            fontsize:      字級（pt）。
            max_width:     原 span 框寬（pt）。

        Returns:
            True 表示會爆框。
        """
        return measure_overflow(new_text, pdf_font_name, fontsize, max_width)

    def check_edit_warnings(self, input_path: Path) -> dict:
        """同步檢查編輯前風險（禁修改權限 / 數位簽章），供 UI 揭露。

        Args:
            input_path: 來源 PDF 路徑。

        Returns:
            {"can_modify": bool, "has_signature": bool}
        """
        return check_edit_warnings(input_path)
