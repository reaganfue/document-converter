"""
desktop/controllers/image_tools_controller.py — 圖片工具 Controller

透過 QThreadPool 非同步執行 converters.image_tools 的操作。
所有操作都不阻塞主執行緒，進度與結果透過 ImageToolsControllerSignals 回傳。

特殊處理：
    - 單檔操作（remove / replace_bg / filter）：rembg 不支援內部 progress，
      只 emit 0.0 / 1.0 兩端；UI 應顯示 IndeterminateProgressBar。
    - 批次操作：item_callback 推送單檔狀態，progress 為完成檔數 / 總檔數。
    - 取消：cancel() 設旗標，worker 每張開始前檢查；當前處理中的檔
      不會被中斷（rembg 為黑盒），但後續檔會跳過並標為 cancelled。

Signal 流程：
    UI 按鈕 → ImageToolsController.remove_background_async() / batch_remove_async() / ...
        → _ImageToolWorker.run()  (worker thread)
            → converters.image_tools.*  (純函式)
            → worker signals → 主執行緒 Signal 轉發
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from converters.image_tools import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    BatchItemResult,
    ImageCancelledError,
    ImageToolError,
    batch_process,
    feather_edges,
    get_image_info,
    remove_background,
    replace_background,
    sharpen_image,
)
from desktop.interfaces import ImageToolsControllerSignals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker 內部 Signals（必須是 QObject 才能跨執行緒 emit）
# ---------------------------------------------------------------------------


class _WorkerSignals(QObject):
    """_ImageToolWorker 使用的內部 Signal（在 worker thread 中 emit，Qt 自動排隊到主執行緒）。"""

    progress = Signal(float)                      # 整體進度 0.0–1.0
    item_status = Signal(int, str)                # idx, status
    item_completed_payload = Signal(int, object)  # idx, BatchItemResult
    completed = Signal(str, object)               # operation_name, result
    failed = Signal(str, str)                     # operation_name, error_message


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class _ImageToolWorker(QRunnable):
    """QRunnable worker，包裝單一 image_tools 操作呼叫。

    operation_name 決定執行路徑：
        "remove_single" → 呼叫 remove_background
        "batch"         → 呼叫 batch_process（含 cancel_check 與 item_callback 注入）
        "replace_bg"    → 呼叫 replace_background
        "filter"        → 融合 sharpen_image + feather_edges + 可選 auto_crop_alpha

    Args:
        operation_name: 操作識別字串，對應上列四種。
        func:           要執行的主函式（batch 時為 batch_process，其餘為對應函式）。
        kwargs:         傳入 func 的關鍵字參數（progress_callback / cancel_check 由 worker 注入）。
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
        self._cancel_flag = threading.Event()
        self.signals = _WorkerSignals()

    def cancel(self) -> None:
        """設定取消旗標。batch 模式下每張開始前會檢查，單檔模式無效。"""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        """回傳取消旗標狀態。"""
        return self._cancel_flag.is_set()

    def run(self) -> None:
        """在 worker thread 執行操作。捕捉所有 image_tools 例外，以 Signal 通知結果。"""
        op = self._operation_name

        progress_callback: Callable[[float], None] = (
            lambda p: self.signals.progress.emit(float(p))
        )

        try:
            if op == "batch":
                result = self._run_batch(progress_callback)
            elif op == "filter":
                result = self._run_filter(progress_callback)
            else:
                # remove_single / replace_bg — 只在兩端 emit 進度
                self.signals.progress.emit(0.0)
                result = self._func(**self._kwargs, progress_callback=progress_callback)
                self.signals.progress.emit(1.0)

            self.signals.completed.emit(op, result)

        except ImageCancelledError:
            logger.info("image_tools %s 已被取消", op)
            self.signals.failed.emit(op, "已取消")
        except ImageToolError as exc:
            logger.warning("image_tools %s 操作失敗: %s", op, exc)
            self.signals.failed.emit(op, str(exc))
        except Exception as exc:
            logger.exception("image_tools %s 未預期例外", op)
            self.signals.failed.emit(op, f"未預期錯誤：{exc}")

    # -------------------------------------------------------------------------
    # 私有：批次操作（inject cancel_check + item_callback）
    # -------------------------------------------------------------------------

    def _run_batch(
        self,
        progress_callback: Callable[[float], None],
    ) -> list[BatchItemResult]:
        """執行 batch_process，注入 cancel_check 和 item_callback。"""

        def cancel_check() -> bool:
            return self._cancel_flag.is_set()

        def item_callback(idx: int, status: str) -> None:
            self.signals.item_status.emit(idx, status)
            if status in ("completed", "failed", "cancelled"):
                # payload 將在 batch_process 回傳後由 controller 統一取出；
                # 此處先發 item_status，讓 UI 即時更新狀態列。
                pass

        results: list[BatchItemResult] = self._func(
            **self._kwargs,
            item_callback=item_callback,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

        # 批次完成後，逐一 emit item_completed_payload 讓 UI 取得完整結果物件
        for idx, item_result in enumerate(results):
            self.signals.item_completed_payload.emit(idx, item_result)

        return results

    # -------------------------------------------------------------------------
    # 私有：後製濾鏡操作（融合 sharpen + feather + auto_crop）
    # -------------------------------------------------------------------------

    def _run_filter(
        self,
        progress_callback: Callable[[float], None],
    ) -> Path:
        """融合 sharpen_image + feather_edges + auto_crop_alpha 三步驟。

        filter_options（存於 self._kwargs["filter_options"]）結構：
            {
                "sharpen_strength": int,    # 0-200
                "sharpen_radius":   float,  # 0.5-5.0
                "feather_radius":   float,  # 0.0-10.0
                "auto_crop_alpha":  bool,
            }
        """
        from PIL import Image

        input_path: Path = self._kwargs["input_path"]
        output_path: Path = self._kwargs["output_path"]
        opts: dict = self._kwargs.get("filter_options", {})

        sharpen_strength: int = int(opts.get("sharpen_strength", 0))
        sharpen_radius: float = float(opts.get("sharpen_radius", 2.0))
        feather_radius: float = float(opts.get("feather_radius", 0.0))
        is_auto_crop: bool = bool(opts.get("auto_crop_alpha", False))

        self.signals.progress.emit(0.0)

        image = Image.open(input_path).convert("RGBA")
        self.signals.progress.emit(0.2)

        # 步驟 1：銳化
        if sharpen_strength > 0:
            image = sharpen_image(image, strength=sharpen_strength, radius=sharpen_radius)
        self.signals.progress.emit(0.5)

        # 步驟 2：邊緣羽化
        if feather_radius > 0.0:
            image = feather_edges(image, blur_radius=feather_radius)
        self.signals.progress.emit(0.75)

        # 步驟 3：自動裁切透明邊界
        if is_auto_crop:
            bbox = image.getbbox()
            if bbox is not None:
                image = image.crop(bbox)
        self.signals.progress.emit(0.9)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(output_path), format="PNG")
        self.signals.progress.emit(1.0)

        return output_path


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class ImageToolsController(QObject):
    """圖片工具非同步 Controller。

    透過 QThreadPool 執行 remove_background / batch_process / replace_background /
    apply_filter，完成後透過 self.signals 通知 UI。

    使用方式（UI 層）：
        controller = ImageToolsController()
        controller.signals.operation_progress.connect(progress_bar.setValue_float)
        controller.signals.operation_completed.connect(on_completed)
        controller.signals.operation_failed.connect(on_failed)
        controller.remove_background_async(input_path, output_path, options)

    取消（批次模式）：
        controller.cancel()   # 設旗標，後續未開始的檔案標為 cancelled
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.signals = ImageToolsControllerSignals()
        self._thread_pool = QThreadPool.globalInstance()
        self._current_worker: _ImageToolWorker | None = None

    # -------------------------------------------------------------------------
    # 內部：建立並啟動 worker
    # -------------------------------------------------------------------------

    def _start_worker(
        self,
        operation_name: str,
        func: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> None:
        """建立 _ImageToolWorker，連接 signals，投入 QThreadPool。"""
        worker = _ImageToolWorker(operation_name, func, kwargs)

        worker.signals.progress.connect(self.signals.operation_progress)
        worker.signals.item_status.connect(self.signals.item_status)
        worker.signals.item_completed_payload.connect(self.signals.item_completed)
        worker.signals.completed.connect(self.signals.operation_completed)
        worker.signals.failed.connect(self.signals.operation_failed)

        self._current_worker = worker
        self.signals.operation_started.emit(operation_name)
        logger.info("image_tools: 啟動 %s worker", operation_name)
        self._thread_pool.start(worker)

    # -------------------------------------------------------------------------
    # 公開操作方法
    # -------------------------------------------------------------------------

    @Slot(Path, Path, dict)
    def remove_background_async(
        self,
        input_path: Path,
        output_path: Path,
        options: dict,
    ) -> None:
        """非同步去背單張圖片。

        Args:
            input_path:  來源圖片路徑。
            output_path: 輸出 PNG 路徑（強制 .png 副檔名）。
            options:     操作選項，結構：
                         {
                             "model":                str,   # AVAILABLE_MODELS key，預設 DEFAULT_MODEL
                             "alpha_matting":        bool,  # 是否啟用 alpha matting
                             "post_process_sharpen": int,   # 銳化強度 0-200
                             "post_process_feather": float, # 邊緣羽化 0.0-10.0
                         }
        """
        kwargs: dict[str, Any] = {
            "input_path": input_path,
            "output_path": output_path,
            "model": options.get("model", DEFAULT_MODEL),
            "alpha_matting": bool(options.get("alpha_matting", False)),
            "post_process_sharpen": int(options.get("post_process_sharpen", 0)),
            "post_process_feather": float(options.get("post_process_feather", 0.0)),
        }
        self._start_worker("remove_single", remove_background, kwargs)

    @Slot(list, Path, dict)
    def batch_remove_async(
        self,
        input_paths: list[Path],
        output_dir: Path,
        settings: dict,
    ) -> None:
        """非同步批次去背多張圖片。

        Args:
            input_paths: 要處理的圖片路徑清單（不可為空）。
            output_dir:  輸出目錄（必須存在）。
            settings:    批次設定，結構：
                         {
                             "model":           str,   # AVAILABLE_MODELS key
                             "alpha_matting":   bool,
                             "sharpen":         int,   # 0-200
                             "feather":         float, # 0.0-10.0
                             "filename_suffix": str,   # 預設 "_nobg"
                             "avoid_overwrite": bool,  # 同名時加序號
                         }
        """
        kwargs: dict[str, Any] = {
            "input_paths": input_paths,
            "output_dir": output_dir,
            "settings": settings,
        }
        self._start_worker("batch", batch_process, kwargs)

    @Slot(Path, Path, dict)
    def replace_background_async(
        self,
        input_path: Path,
        output_path: Path,
        bg_options: dict,
    ) -> None:
        """非同步替換已去背 PNG 的背景。

        Args:
            input_path:  已去背 PNG 路徑（必須有 alpha 通道）。
            output_path: 輸出路徑（.png 或 .jpg）。
            bg_options:  背景選項，結構：
                         {
                             "bg_type":       "transparent" | "color" | "image",
                             "bg_color":      "#RRGGBB"  (bg_type="color" 時必填),
                             "bg_image_path": Path       (bg_type="image" 時必填),
                             "bg_image_mode": "fit" | "fill" | "center" | "tile",
                         }
        """
        kwargs: dict[str, Any] = {
            "input_path": input_path,
            "output_path": output_path,
            "bg_type": bg_options.get("bg_type", "transparent"),
            "bg_color": bg_options.get("bg_color"),
            "bg_image_path": bg_options.get("bg_image_path"),
            "bg_image_mode": bg_options.get("bg_image_mode", "fit"),
        }
        self._start_worker("replace_bg", replace_background, kwargs)

    @Slot(Path, Path, dict)
    def apply_filter_async(
        self,
        input_path: Path,
        output_path: Path,
        filter_options: dict,
    ) -> None:
        """非同步套用後製濾鏡（銳化 + 邊緣羽化 + 可選自動裁切）。

        filter_options 融合三個步驟（見設計文件 §6.2）：
            sharpen_image → feather_edges → auto_crop_alpha（可選）

        Args:
            input_path:     來源 PNG 路徑（建議含 alpha 通道）。
            output_path:    輸出 PNG 路徑。
            filter_options: 濾鏡選項，結構：
                            {
                                "sharpen_strength": int,   # 0-200
                                "sharpen_radius":   float, # 0.5-5.0
                                "feather_radius":   float, # 0.0-10.0
                                "auto_crop_alpha":  bool,
                            }
        """
        kwargs: dict[str, Any] = {
            "input_path": input_path,
            "output_path": output_path,
            "filter_options": filter_options,
        }
        # filter 操作無對應的單一後端函式，由 worker._run_filter 融合三步驟
        self._start_worker("filter", _NOOP_FUNC, kwargs)

    def cancel(self) -> None:
        """請求取消當前批次操作。

        對單檔操作（remove_single / replace_bg / filter）無效：rembg 為黑盒不可中斷。
        對批次操作：設旗標後，worker 每張開始前檢查，後續未開始的檔案標為 cancelled。
        無 worker 時此方法安全靜默（不 raise）。
        """
        if self._current_worker is not None:
            self._current_worker.cancel()
            logger.info("image_tools: cancel() 已發送至 worker")

    def available_models(self) -> dict[str, str]:
        """回傳可用 rembg 模型對照表（id → 顯示名），供 UI 填充 ComboBox。

        Returns:
            {model_id: display_name} — 例：{"u2net": "U²Net（通用，預設）", ...}
        """
        return AVAILABLE_MODELS

    def get_info(self, input_path: Path) -> dict:
        """同步讀取圖片元資料（不啟動 worker）。

        Args:
            input_path: 圖片路徑。

        Returns:
            {width, height, format, mode, size_bytes, has_alpha}

        Raises:
            ImageToolError / UnsupportedImageFormatError / ImageProcessError — 呼叫方負責處理。
        """
        return get_image_info(input_path)


# ---------------------------------------------------------------------------
# 模組級輔助常數
# ---------------------------------------------------------------------------


def _NOOP_FUNC(**_kwargs: Any) -> None:  # noqa: N802
    """filter 操作的佔位函式。_ImageToolWorker.run() 對 'filter' op 走 _run_filter，
    不呼叫此函式；僅為滿足 _start_worker(func=...) 型別一致性而存在。
    """
