"""
converters/pdf_ocr.py — 掃描版 PDF OCR 後端

引擎：RapidOCR（rapidocr-onnxruntime）
    - 純 pip 依賴（複用專案既有的 onnxruntime），無需安裝 Tesseract 等系統程式
    - 模型（~15MB）隨套件內建，完全離線
    - 支援繁中 / 簡中 / 英文混排

定位：PDFConverter 的「無文字層頁面」後備路徑 —
    頁面有原生文字層時永遠用 PyMuPDF 抽取（快且精確），
    僅在頁面抽不到文字（掃描圖）且本模組可用時才走 OCR。

依賴缺失時的行為：is_ocr_available() 回 False，呼叫端維持原行為
（掃描頁輸出空字串），不拋例外、不影響其他轉換功能。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# OCR 渲染倍率：掃描 PDF 內嵌圖多為 72–150 DPI，2x（144 DPI 基準)
# 對 RapidOCR 已足夠；更高倍率只會變慢、爆記憶體，辨識率無感提升。
_OCR_ZOOM = 2.0

# 引擎單例（模型載入約 1–2 秒，全程序共用一份）
_engine: Optional[object] = None
_engine_lock = threading.Lock()
_available: Optional[bool] = None


def is_ocr_available() -> bool:
    """探測 rapidocr-onnxruntime 是否可用（結果快取，重複呼叫零成本）。"""
    global _available
    if _available is None:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            _available = True
        except Exception as exc:  # ImportError 或其依賴（cv2 等）載入失敗
            logger.info("RapidOCR 不可用，掃描版 PDF 將無法抽取文字：%s", exc)
            _available = False
    return _available


def _get_engine():
    """取得 RapidOCR 引擎單例（double-checked locking，執行緒安全）。"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR()
                logger.info("RapidOCR 引擎已載入")
    return _engine


def ocr_page(page) -> str:
    """對單一 fitz.Page 執行 OCR，回傳辨識文字（按版面順序，行間以換行分隔）。

    Args:
        page: PyMuPDF（fitz）Page 物件。

    Returns:
        辨識出的文字；頁面無可辨識內容或 OCR 失敗時回傳空字串（不拋例外）。
    """
    if not is_ocr_available():
        return ""

    try:
        import fitz
        import numpy as np

        matrix = fitz.Matrix(_OCR_ZOOM, _OCR_ZOOM)
        pixmap = page.get_pixmap(matrix=matrix)
        img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )
        if pixmap.n == 4:  # RGBA → 丟棄 alpha
            img = img[:, :, :3]
        bgr = img[:, :, ::-1]  # RapidOCR 內部使用 OpenCV，預期 BGR 通道序

        # result 結構：[[box, text, score], ...]，已按版面由上而下排序
        result, _elapse = _get_engine()(bgr)
        if not result:
            return ""
        return "\n".join(str(item[1]) for item in result)
    except Exception as exc:
        logger.warning("OCR 頁面辨識失敗（將以空字串略過）：%s", exc)
        return ""
