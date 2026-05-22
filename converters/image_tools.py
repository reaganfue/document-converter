"""
converters/image_tools.py — 圖片工具函式層（純後端邏輯）

提供四大功能：
    - remove_background:  使用 rembg 移除單張圖片背景
    - batch_process:      批次處理多張圖片（去背 + 後製）
    - replace_background: 替換已去背 PNG 的背景（透明 / 純色 / 圖片）
    - sharpen_image:      Pillow UnsharpMask 銳化
    - feather_edges:      Alpha 通道 Gaussian Blur 羽化邊緣
    - get_image_info:     讀取圖片元資料（寬高 / 大小 / 格式）

所有函式為純函式，僅依賴參數，不依賴全域狀態。
無任何 Qt / PySide6 依賴，可安全地在非 GUI 執行緒中呼叫。

模型路徑解析：
    - dev 模式（未 frozen）：rembg 自動下載至 ~/.u2net/
    - frozen 模式（PyInstaller）：從 sys._MEIPASS/u2net_models/ 載入
    本模組於 import 時設定環境變數 U2NET_HOME，讓 rembg 走預打包路徑

依賴：
    - rembg >= 2.0.75（含 onnxruntime CPU 後端）
    - Pillow >= 12.0
    - numpy（rembg 已間接依賴）

上層呼叫方：desktop/controllers/image_tools_controller.py（以 QRunnable 包裝）
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import PIL.Image
    import rembg.session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 例外類別
# ---------------------------------------------------------------------------


class ImageToolError(Exception):
    """所有 image_tools 例外的基類。"""


class ImageProcessError(ImageToolError):
    """處理過程失敗（rembg 拋例外、Pillow 拋例外等）。"""


class UnsupportedImageFormatError(ImageToolError):
    """輸入格式不被支援（非 png/jpg/jpeg/webp/bmp/tiff/gif）。"""


class ModelNotFoundError(ImageToolError):
    """指定的 rembg 模型不存在於預期路徑（frozen 模式專用）。"""


class ImageCancelledError(ImageToolError):
    """使用者取消批次中當前處理（worker 檢查 cancel flag 後拋出）。"""


# ---------------------------------------------------------------------------
# 模型常數
# ---------------------------------------------------------------------------

AVAILABLE_MODELS: dict[str, str] = {
    "u2net":             "U²Net（通用，預設）",
    "u2net_human_seg":   "U²Net 人像優化",
    "isnet-general-use": "ISNet（最新最準）",
}

DEFAULT_MODEL: str = "u2net"

# 支援的輸入格式（lowercase, 無點）
SUPPORTED_INPUT_FORMATS: frozenset[str] = frozenset({
    "png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif",
})

# 模組級 session 快取：{model_name: session}（同模型重用大幅加速）
_session_cache: dict[str, object] = {}


# ---------------------------------------------------------------------------
# 模型路徑解析（模組 import 時執行）
# ---------------------------------------------------------------------------


def resolve_model_dir() -> Path:
    """回傳 rembg 模型目錄路徑。

    優先序：
        1. frozen 模式（PyInstaller）：sys._MEIPASS/u2net_models/（內嵌打包）
        2. dev 模式優先：<project_root>/u2net_models/（與 frozen 路徑一致；
           由 scripts/predownload_models.py 預下載，git-ignored）
        3. dev 模式 fallback：~/.u2net/（rembg 預設位置，需網路下載）

    呼叫此函式於模組 import 時，立即將路徑寫入環境變數 U2NET_HOME，
    讓 rembg.new_session() 走指定路徑而非預設下載路徑。

    Returns:
        模型目錄 Path（必存在；frozen 模式若不存在則拋 ModelNotFoundError）。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        candidate = meipass / "u2net_models"
        if not candidate.exists():
            raise ModelNotFoundError(
                f"打包內未找到模型目錄：{candidate}。"
                "請執行 scripts/predownload_models.py 預下載。"
            )
    else:
        # dev 模式：先看專案根 u2net_models/（與 frozen 一致），
        # 沒有則 fallback 到 rembg 預設 ~/.u2net/
        # converters/image_tools.py → 專案根 = parent.parent
        project_dir = Path(__file__).resolve().parent.parent / "u2net_models"
        if project_dir.exists() and any(project_dir.glob("*.onnx")):
            candidate = project_dir
        else:
            candidate = Path.home() / ".u2net"
            candidate.mkdir(parents=True, exist_ok=True)

    os.environ["U2NET_HOME"] = str(candidate)
    return candidate


# 模組 import 時立即執行
_MODEL_DIR = resolve_model_dir()


# ---------------------------------------------------------------------------
# DataClass
# ---------------------------------------------------------------------------


@dataclass
class BatchItemResult:
    """批次中單一檔案的處理結果。"""

    input_path: Path
    output_path: Optional[Path]  # None 表示失敗
    status: str                  # "success" | "failed" | "cancelled"
    error_message: Optional[str]
    duration_ms: int


# ---------------------------------------------------------------------------
# 內部輔助函式
# ---------------------------------------------------------------------------


def _validate_input_format(path: Path) -> None:
    """檢查副檔名是否在 SUPPORTED_INPUT_FORMATS，否則拋 UnsupportedImageFormatError。

    Args:
        path: 要驗證的圖片路徑。

    Raises:
        UnsupportedImageFormatError: 副檔名不在支援清單中。
    """
    suffix = path.suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_INPUT_FORMATS:
        raise UnsupportedImageFormatError(
            f"不支援的圖片格式：{path.suffix!r}（{path.name}）。"
            f"支援格式：{', '.join(sorted(SUPPORTED_INPUT_FORMATS))}"
        )


def _validate_model(model: str) -> None:
    """檢查 model 是否在 AVAILABLE_MODELS，否則拋 ImageProcessError。

    Args:
        model: 要驗證的模型 ID。

    Raises:
        ImageProcessError: 模型 ID 不在 AVAILABLE_MODELS 中。
    """
    if model not in AVAILABLE_MODELS:
        raise ImageProcessError(
            f"不支援的模型：{model!r}。"
            f"可用模型：{list(AVAILABLE_MODELS.keys())}"
        )


def _get_session(model: str) -> object:
    """取得 / 快取 rembg session（同模型重用 session 大幅加速）。

    使用模組級 dict 快取：{model_name: session}。

    Args:
        model: AVAILABLE_MODELS 中的 key。

    Returns:
        rembg BaseSession 物件。

    Raises:
        ImageProcessError: 建立 session 失敗（模型檔不存在或讀取錯誤）。
    """
    if model in _session_cache:
        return _session_cache[model]

    try:
        from rembg import new_session
        session = new_session(model)
        _session_cache[model] = session
        logger.info("_get_session: 模型 %r 已載入並快取", model)
        return session
    except Exception as exc:
        raise ImageProcessError(
            f"無法載入 rembg 模型 {model!r}：{exc}"
        ) from exc


def _resolve_output_filename(
    input_path: Path,
    output_dir: Path,
    suffix: str = "_nobg",
    target_ext: str = "png",
    avoid_overwrite: bool = True,
) -> Path:
    """計算 batch 模式的輸出檔名（含序號避免覆寫）。

    例：input='cat.jpg' → 'cat_nobg.png' 或 'cat_nobg_1.png'

    Args:
        input_path:     來源圖片路徑（只取 stem 用於命名）。
        output_dir:     輸出目錄。
        suffix:         附加到 stem 後面的字尾，預設 "_nobg"。
        target_ext:     輸出副檔名（不含點），預設 "png"。
        avoid_overwrite: True 時若同名存在則自動加序號。

    Returns:
        計算好的輸出 Path。
    """
    base_name = f"{input_path.stem}{suffix}.{target_ext}"
    candidate = output_dir / base_name

    if not avoid_overwrite or not candidate.exists():
        return candidate

    counter = 1
    while True:
        name = f"{input_path.stem}{suffix}_{counter}.{target_ext}"
        candidate = output_dir / name
        if not candidate.exists():
            return candidate
        counter += 1


def _fire_progress(
    callback: Optional[Callable[[float], None]],
    value: float,
) -> None:
    """安全呼叫 progress callback，靜默吞例外。

    Args:
        callback: 進度回呼，接受 0.0–1.0 的 float；None 時跳過。
        value:    進度值，自動 clamp 至 [0.0, 1.0]。
    """
    if callback is None:
        return
    try:
        callback(max(0.0, min(1.0, value)))
    except Exception:
        pass  # 進度回呼失敗不影響主流程


def _apply_post_processing(
    image: "PIL.Image.Image",
    post_process_sharpen: int,
    post_process_feather: float,
) -> "PIL.Image.Image":
    """套用去背後的後製：銳化 + 邊緣羽化。

    Args:
        image:               已去背的 RGBA PIL Image。
        post_process_sharpen: 銳化強度（0=跳過）。
        post_process_feather: 羽化半徑 px（0.0=跳過）。

    Returns:
        後製完成的 PIL Image。
    """
    result = image
    if post_process_sharpen > 0:
        result = sharpen_image(result, strength=post_process_sharpen)
    if post_process_feather > 0.0:
        result = feather_edges(result, blur_radius=post_process_feather)
    return result


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    """解析 '#RRGGBB' 格式色碼為 RGB tuple。

    Args:
        hex_color: 例如 "#FF0000" 或 "#ff0000"。

    Returns:
        (r, g, b) 各 0-255。

    Raises:
        ImageProcessError: hex 格式無效。
    """
    color = hex_color.strip().lstrip("#")
    if len(color) != 6:
        raise ImageProcessError(
            f"無效的 hex 色碼：{hex_color!r}，期望格式 '#RRGGBB'"
        )
    try:
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        return (r, g, b)
    except ValueError as exc:
        raise ImageProcessError(
            f"無效的 hex 色碼：{hex_color!r} — {exc}"
        ) from exc


def _composite_on_color(
    foreground: "PIL.Image.Image",
    bg_color_rgb: tuple[int, int, int],
    output_format: str,
) -> "PIL.Image.Image":
    """將 RGBA 前景合成於純色背景上。

    Args:
        foreground:    RGBA PIL Image（前景）。
        bg_color_rgb:  背景 RGB tuple。
        output_format: "png" 保留 alpha，其餘（如 "jpg"）轉 RGB。

    Returns:
        合成後的 PIL Image。
    """
    from PIL import Image

    fg = foreground.convert("RGBA") if foreground.mode != "RGBA" else foreground
    background = Image.new("RGBA", fg.size, bg_color_rgb + (255,))
    composite = Image.alpha_composite(background, fg)

    if output_format.lower() in ("jpg", "jpeg"):
        return composite.convert("RGB")
    return composite


def _scale_bg_image(
    bg: "PIL.Image.Image",
    target_size: tuple[int, int],
    mode: str,
) -> "PIL.Image.Image":
    """依 mode 縮放背景圖至目標尺寸。

    mode 說明：
        fit:    保持比例，letterbox（等比縮放後上下/左右留邊）。
        fill:   保持比例，填滿並裁切。
        center: 不縮放，置中（超出裁切，不足留背景色）。
        tile:   平鋪。

    Args:
        bg:          背景 PIL Image。
        target_size: (width, height) 目標尺寸。
        mode:        fit / fill / center / tile。

    Returns:
        縮放 / 合成後與 target_size 相同大小的 RGB Image。
    """
    from PIL import Image

    target_w, target_h = target_size
    canvas = Image.new("RGB", target_size, (255, 255, 255))

    if mode == "tile":
        bg_rgb = bg.convert("RGB")
        bg_w, bg_h = bg_rgb.size
        for y in range(0, target_h, bg_h):
            for x in range(0, target_w, bg_w):
                canvas.paste(bg_rgb, (x, y))
        return canvas

    if mode == "center":
        bg_rgb = bg.convert("RGB")
        offset_x = (target_w - bg_rgb.width) // 2
        offset_y = (target_h - bg_rgb.height) // 2
        canvas.paste(bg_rgb, (offset_x, offset_y))
        return canvas

    bg_ratio = bg.width / bg.height
    target_ratio = target_w / target_h

    if mode == "fit":
        # 等比縮放，保留黑邊（letterbox）
        if bg_ratio > target_ratio:
            new_w = target_w
            new_h = int(target_w / bg_ratio)
        else:
            new_h = target_h
            new_w = int(target_h * bg_ratio)
        resized = bg.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))
        return canvas

    # mode == "fill"：填滿並裁切
    if bg_ratio > target_ratio:
        new_h = target_h
        new_w = int(target_h * bg_ratio)
    else:
        new_w = target_w
        new_h = int(target_w / bg_ratio)
    resized = bg.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
    crop_x = (new_w - target_w) // 2
    crop_y = (new_h - target_h) // 2
    cropped = resized.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
    canvas.paste(cropped, (0, 0))
    return canvas


# ---------------------------------------------------------------------------
# 公開函式
# ---------------------------------------------------------------------------


def remove_background(
    input_path: Path,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 240,
    alpha_matting_background_threshold: int = 10,
    alpha_matting_erode_size: int = 10,
    post_process_sharpen: int = 0,
    post_process_feather: float = 0.0,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> None:
    """移除單張圖片背景，輸出為 PNG（含 alpha 通道）。

    流程：
        1. 讀取 input_path 為 bytes，呼叫 rembg.remove(bytes, session=...)
        2. 取得含 alpha 的 PNG bytes
        3. 若 post_process_sharpen > 0，呼叫 sharpen_image 套用銳化
        4. 若 post_process_feather > 0.0，呼叫 feather_edges 套用 alpha 羽化
        5. 寫入 output_path

    Args:
        input_path:  來源圖片路徑（必須是 SUPPORTED_INPUT_FORMATS 之一）。
        output_path: 輸出 PNG 路徑（強制 .png 副檔名；父目錄必須存在）。
        model:       AVAILABLE_MODELS 中的 key；無效時拋 ImageProcessError。
        alpha_matting: 是否啟用 alpha matting（更精細但較慢，約慢 3-5x）。
        alpha_matting_foreground_threshold: 前景閾值（0-255，預設 240）。
        alpha_matting_background_threshold: 背景閾值（0-255，預設 10）。
        alpha_matting_erode_size: 邊緣腐蝕大小（預設 10）。
        post_process_sharpen: 銳化強度（0-200，0=不套用）。
        post_process_feather: 邊緣羽化像素（0.0-10.0，0=不套用）。
        progress_callback: 進度回呼。rembg 不支援單檔內部 progress，
                          僅在開始 / 結束時回報 0.0 與 1.0。

    Raises:
        UnsupportedImageFormatError: input_path 副檔名不支援。
        ModelNotFoundError: 指定 model 不在 AVAILABLE_MODELS。
        ImageProcessError: 處理失敗（rembg 例外、Pillow 例外、寫入失敗等）。
    """
    _validate_input_format(input_path)
    _validate_model(model)

    if not input_path.exists():
        raise ImageProcessError(f"來源檔案不存在：{input_path}")

    if not output_path.parent.exists():
        raise ImageProcessError(f"輸出目錄不存在：{output_path.parent}")

    logger.info(
        "remove_background: 開始處理 %s → %s (model=%s, alpha_matting=%s)",
        input_path.name,
        output_path.name,
        model,
        alpha_matting,
    )
    _fire_progress(callback=progress_callback, value=0.0)

    try:
        from PIL import Image
        from rembg import remove

        session = _get_session(model)

        with open(input_path, "rb") as f:
            input_bytes = f.read()

        remove_kwargs: dict = {
            "data": input_bytes,
            "session": session,
            "alpha_matting": alpha_matting,
        }
        if alpha_matting:
            remove_kwargs["alpha_matting_foreground_threshold"] = (
                alpha_matting_foreground_threshold
            )
            remove_kwargs["alpha_matting_background_threshold"] = (
                alpha_matting_background_threshold
            )
            remove_kwargs["alpha_matting_erode_size"] = alpha_matting_erode_size

        output_bytes: bytes = remove(**remove_kwargs)

        result_image = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
        result_image = _apply_post_processing(
            result_image, post_process_sharpen, post_process_feather
        )

        result_image.save(str(output_path), format="PNG")
        logger.info("remove_background: 完成 → %s", output_path.name)

    except (ImageToolError, UnsupportedImageFormatError, ModelNotFoundError):
        raise
    except Exception as exc:
        raise ImageProcessError(
            f"remove_background 失敗（{input_path.name}）：{exc}"
        ) from exc

    _fire_progress(callback=progress_callback, value=1.0)


def batch_process(
    input_paths: list[Path],
    output_dir: Path,
    settings: dict,
    item_callback: Optional[Callable[[int, str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[BatchItemResult]:
    """批次處理多張圖片（去背 + 可選後製）。

    參數 settings 結構（dict）：
        {
            "model":                str,    # AVAILABLE_MODELS key
            "alpha_matting":        bool,
            "sharpen":              int,    # 0-200
            "feather":              float,  # 0.0-10.0
            "filename_suffix":      str,    # 預設 "_nobg"
            "avoid_overwrite":      bool,   # 同名時加序號
        }

    流程：
        對 input_paths 中每張：
        1. 呼叫 cancel_check()，若 True 則剩餘檔標 cancelled、提前 return
        2. 呼叫 item_callback(idx, "started") 通知開始
        3. 計算輸出路徑（_resolve_output_filename）
        4. 呼叫 remove_background(...) — 內部失敗不拋出，紀錄到 result
        5. 呼叫 item_callback(idx, "completed" | "failed") 通知結束
        6. progress_callback((idx+1) / total) 更新整體進度

    Args:
        input_paths:       要處理的圖片路徑清單（不可為空）。
        output_dir:        輸出目錄（必須存在）。
        settings:          見上方結構說明。
        item_callback:     單檔狀態回呼（idx, status_str）。
                          status_str 為 "started"|"completed"|"failed"|"cancelled"。
        progress_callback: 整體進度回呼（0.0-1.0，依完成檔數/總檔數）。
        cancel_check:      取消檢查回呼。worker 每張處理前呼叫，
                          回 True 則跳過後續所有檔案，標為 cancelled。

    Returns:
        BatchItemResult 清單，順序對應 input_paths。

    Raises:
        ImageToolError: input_paths 為空、output_dir 不存在等前置錯誤。
    """
    if not input_paths:
        raise ImageToolError("batch_process 失敗：輸入清單為空")

    if not output_dir.exists():
        raise ImageToolError(f"輸出目錄不存在：{output_dir}")

    model = settings.get("model", DEFAULT_MODEL)
    alpha_matting = bool(settings.get("alpha_matting", False))
    sharpen = int(settings.get("sharpen", 0))
    feather = float(settings.get("feather", 0.0))
    filename_suffix = str(settings.get("filename_suffix", "_nobg"))
    avoid_overwrite = bool(settings.get("avoid_overwrite", True))

    total = len(input_paths)
    results: list[BatchItemResult] = []

    logger.info(
        "batch_process: 開始批次處理 %d 張 → %s (model=%s)",
        total,
        output_dir,
        model,
    )

    for idx, input_path in enumerate(input_paths):
        # 取消檢查：若 cancel_check 回 True，剩餘檔全標 cancelled
        if cancel_check is not None and cancel_check():
            logger.info(
                "batch_process: 收到取消指令，剩餘 %d 張標為 cancelled",
                total - idx,
            )
            for remaining_path in input_paths[idx:]:
                _notify_item(item_callback, idx + (remaining_path == input_path), "cancelled")
                results.append(BatchItemResult(
                    input_path=remaining_path,
                    output_path=None,
                    status="cancelled",
                    error_message=None,
                    duration_ms=0,
                ))
            break

        _notify_item(item_callback, idx, "started")
        started_ms = int(time.monotonic() * 1000)

        try:
            output_path = _resolve_output_filename(
                input_path=input_path,
                output_dir=output_dir,
                suffix=filename_suffix,
                target_ext="png",
                avoid_overwrite=avoid_overwrite,
            )

            remove_background(
                input_path=input_path,
                output_path=output_path,
                model=model,
                alpha_matting=alpha_matting,
                post_process_sharpen=sharpen,
                post_process_feather=feather,
            )

            elapsed_ms = int(time.monotonic() * 1000) - started_ms
            results.append(BatchItemResult(
                input_path=input_path,
                output_path=output_path,
                status="success",
                error_message=None,
                duration_ms=elapsed_ms,
            ))
            _notify_item(item_callback, idx, "completed")
            logger.info(
                "batch_process: [%d/%d] %s 完成 (%dms)",
                idx + 1, total, input_path.name, elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = int(time.monotonic() * 1000) - started_ms
            error_msg = str(exc)
            results.append(BatchItemResult(
                input_path=input_path,
                output_path=None,
                status="failed",
                error_message=error_msg,
                duration_ms=elapsed_ms,
            ))
            _notify_item(item_callback, idx, "failed")
            logger.warning(
                "batch_process: [%d/%d] %s 失敗：%s",
                idx + 1, total, input_path.name, error_msg,
            )

        _fire_progress(callback=progress_callback, value=(idx + 1) / total)

    logger.info(
        "batch_process: 完成，共 %d 張（成功 %d，失敗 %d，取消 %d）",
        total,
        sum(1 for r in results if r.status == "success"),
        sum(1 for r in results if r.status == "failed"),
        sum(1 for r in results if r.status == "cancelled"),
    )
    return results


def _notify_item(
    callback: Optional[Callable[[int, str], None]],
    idx: int,
    status: str,
) -> None:
    """安全呼叫 item_callback，靜默吞例外。

    Args:
        callback: 單檔狀態回呼；None 時跳過。
        idx:      檔案在清單中的索引。
        status:   "started" | "completed" | "failed" | "cancelled"。
    """
    if callback is None:
        return
    try:
        callback(idx, status)
    except Exception:
        pass


def replace_background(
    input_path: Path,
    output_path: Path,
    bg_type: str,
    bg_color: Optional[str] = None,
    bg_image_path: Optional[Path] = None,
    bg_image_mode: str = "fit",
    progress_callback: Optional[Callable[[float], None]] = None,
) -> None:
    """替換已去背 PNG 的背景。

    bg_type 三種模式：
        - "transparent": 輸出原樣 PNG（含 alpha 通道）— 等於複製。
        - "color":       純色背景。bg_color 為 hex 字串如 "#FFFFFF"。
        - "image":       圖片背景。bg_image_path 必填，bg_image_mode 指定縮放方式。

    bg_image_mode 四種：
        - "fit":    保持比例，背景填滿不裁切（letterbox）。
        - "fill":   保持比例，背景填滿並裁切（crop）。
        - "center": 不縮放，置中。
        - "tile":   平鋪。

    Args:
        input_path:    已去背 PNG 路徑（必須有 alpha 通道；無 alpha 則視為不透明圖層）。
        output_path:   輸出路徑（.png 或 .jpg；jpg 時透明區強制為白）。
        bg_type:       "transparent" | "color" | "image"。
        bg_color:      bg_type="color" 時必填，格式 "#RRGGBB"。
        bg_image_path: bg_type="image" 時必填。
        bg_image_mode: bg_type="image" 時使用，預設 "fit"。
        progress_callback: 進度回呼（0.0 開始, 1.0 結束）。

    Raises:
        UnsupportedImageFormatError: 輸入格式不支援。
        ImageProcessError: 背景圖無法讀取、hex 色碼無效、bg_type 無效等。
    """
    _validate_input_format(input_path)

    valid_bg_types = {"transparent", "color", "image"}
    if bg_type not in valid_bg_types:
        raise ImageProcessError(
            f"不支援的 bg_type：{bg_type!r}，合法值：{valid_bg_types}"
        )

    valid_bg_modes = {"fit", "fill", "center", "tile"}
    if bg_image_mode not in valid_bg_modes:
        raise ImageProcessError(
            f"不支援的 bg_image_mode：{bg_image_mode!r}，合法值：{valid_bg_modes}"
        )

    if not input_path.exists():
        raise ImageProcessError(f"來源檔案不存在：{input_path}")

    if not output_path.parent.exists():
        raise ImageProcessError(f"輸出目錄不存在：{output_path.parent}")

    logger.info(
        "replace_background: %s → %s (bg_type=%s)",
        input_path.name, output_path.name, bg_type,
    )
    _fire_progress(callback=progress_callback, value=0.0)

    output_ext = output_path.suffix.lstrip(".").lower()

    try:
        from PIL import Image

        fg = Image.open(str(input_path)).convert("RGBA")

        if bg_type == "transparent":
            if output_ext in ("jpg", "jpeg"):
                # JPG 不支援 alpha，透明區轉白
                result = _composite_on_color(fg, (255, 255, 255), output_ext)
            else:
                result = fg
            result.save(str(output_path))

        elif bg_type == "color":
            if bg_color is None:
                raise ImageProcessError("bg_type='color' 時 bg_color 為必填")
            rgb = _parse_hex_color(bg_color)
            result = _composite_on_color(fg, rgb, output_ext)
            result.save(str(output_path))

        elif bg_type == "image":
            if bg_image_path is None:
                raise ImageProcessError("bg_type='image' 時 bg_image_path 為必填")
            if not bg_image_path.exists():
                raise ImageProcessError(
                    f"背景圖片不存在：{bg_image_path}"
                )

            bg_img = Image.open(str(bg_image_path))
            bg_scaled = _scale_bg_image(bg_img, fg.size, bg_image_mode)
            bg_rgba = bg_scaled.convert("RGBA")

            composite = Image.alpha_composite(bg_rgba, fg)
            if output_ext in ("jpg", "jpeg"):
                composite = composite.convert("RGB")
            composite.save(str(output_path))

        logger.info("replace_background: 完成 → %s", output_path.name)

    except ImageToolError:
        raise
    except Exception as exc:
        raise ImageProcessError(
            f"replace_background 失敗（{input_path.name}）：{exc}"
        ) from exc

    _fire_progress(callback=progress_callback, value=1.0)


def sharpen_image(
    image: "PIL.Image.Image",
    strength: int = 50,
    radius: float = 2.0,
) -> "PIL.Image.Image":
    """套用 UnsharpMask 銳化。

    使用 Pillow ImageFilter.UnsharpMask：
        UnsharpMask(radius=radius, percent=strength, threshold=3)

    Args:
        image:    PIL.Image，必須為 RGB 或 RGBA 模式。
        strength: 銳化強度（0-200，0=不變，預設 50）。
        radius:   高斯模糊半徑（0.5-5.0，預設 2.0）。

    Returns:
        套用銳化後的新 Image（不修改原圖）。
        若 strength=0 則直接 image.copy() 回傳。

    Raises:
        ImageProcessError: 圖片模式無法處理。
    """
    if strength == 0:
        return image.copy()

    try:
        from PIL import ImageFilter

        if image.mode not in ("RGB", "RGBA", "L"):
            raise ImageProcessError(
                f"sharpen_image 不支援模式 {image.mode!r}，"
                "請先轉換為 RGB / RGBA / L"
            )

        # RGBA：只對 RGB 通道銳化，alpha 單獨保留後合併
        if image.mode == "RGBA":
            rgb, alpha = image.convert("RGB"), image.split()[3]
            sharpened_rgb = rgb.filter(
                ImageFilter.UnsharpMask(
                    radius=radius, percent=strength, threshold=3
                )
            )
            sharpened_rgba = sharpened_rgb.convert("RGBA")
            sharpened_rgba.putalpha(alpha)
            return sharpened_rgba

        return image.filter(
            ImageFilter.UnsharpMask(
                radius=radius, percent=strength, threshold=3
            )
        )

    except ImageProcessError:
        raise
    except Exception as exc:
        raise ImageProcessError(f"sharpen_image 失敗：{exc}") from exc


def feather_edges(
    image: "PIL.Image.Image",
    blur_radius: float = 2.0,
) -> "PIL.Image.Image":
    """對 alpha 通道套用 Gaussian Blur 羽化邊緣。

    流程：
        1. 確認 image 有 alpha 通道（mode='RGBA'），否則拋例外
        2. split() 出 alpha
        3. alpha.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        4. 合併回 RGBA

    Args:
        image:       PIL.Image，必須為 RGBA 模式。
        blur_radius: Gaussian Blur 半徑（0.0-10.0，0=不變）。

    Returns:
        新 RGBA Image（不修改原圖）。
        若 blur_radius=0.0 則直接 image.copy() 回傳。

    Raises:
        ImageProcessError: image 無 alpha 通道。
    """
    if blur_radius == 0.0:
        return image.copy()

    if image.mode != "RGBA":
        raise ImageProcessError(
            f"feather_edges 需要 RGBA 模式，當前模式：{image.mode!r}"
        )

    try:
        from PIL import ImageFilter

        r, g, b, alpha = image.split()
        blurred_alpha = alpha.filter(
            ImageFilter.GaussianBlur(radius=blur_radius)
        )
        result = image.copy()
        result.putalpha(blurred_alpha)
        return result

    except ImageProcessError:
        raise
    except Exception as exc:
        raise ImageProcessError(f"feather_edges 失敗：{exc}") from exc


def get_image_info(input_path: Path) -> dict:
    """讀取圖片元資料，供 UI 預覽。

    Args:
        input_path: 圖片路徑。

    Returns:
        {
            "width":      int,        # 像素寬
            "height":     int,        # 像素高
            "format":     str,        # "PNG" | "JPEG" | "WEBP" | ...
            "mode":       str,        # "RGB" | "RGBA" | "L" | ...
            "size_bytes": int,        # 檔案位元組數
            "has_alpha":  bool,       # 是否有 alpha 通道
        }

    Raises:
        ImageToolError: 檔案不存在。
        UnsupportedImageFormatError: 副檔名不支援。
        ImageProcessError: Pillow 無法開啟。
    """
    if not input_path.exists():
        raise ImageToolError(f"檔案不存在：{input_path}")

    _validate_input_format(input_path)

    size_bytes = input_path.stat().st_size

    try:
        from PIL import Image

        with Image.open(str(input_path)) as img:
            width, height = img.size
            fmt = img.format or input_path.suffix.lstrip(".").upper()
            mode = img.mode
            has_alpha = "A" in mode or mode == "PA"

        return {
            "width": width,
            "height": height,
            "format": fmt,
            "mode": mode,
            "size_bytes": size_bytes,
            "has_alpha": has_alpha,
        }

    except ImageToolError:
        raise
    except Exception as exc:
        raise ImageProcessError(
            f"get_image_info 無法開啟圖片（{input_path.name}）：{exc}"
        ) from exc
