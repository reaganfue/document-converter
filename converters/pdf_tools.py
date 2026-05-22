"""
converters/pdf_tools.py — PDF 工具函式層（純後端邏輯）

提供 PDF 合併、拆分、壓縮、加密、解密、元資訊讀取六項功能。
所有函式為純函式，僅依賴參數，不依賴全域狀態。
無任何 Qt / PySide6 依賴，可安全地在非 GUI 執行緒中呼叫。

上層呼叫方：desktop/controllers/pdf_tools_controller.py（以 QRunnable 包裝）

依賴：
    - PyMuPDF (fitz) 1.24.14
    - Pillow（compress_pdf 圖片降級壓縮時使用）
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 例外類別
# ---------------------------------------------------------------------------


class PdfToolError(Exception):
    """PDF 工具操作的基礎例外。

    所有 pdf_tools 函式拋出的例外均為此類或其子類，
    呼叫方只需 catch PdfToolError 即可統一處理。
    """


class PdfPasswordError(PdfToolError):
    """密碼錯誤或加密相關問題。

    例：decrypt_pdf 時密碼錯誤、encrypt_pdf 時密碼為空。
    """


class PdfCorruptedError(PdfToolError):
    """PDF 檔案損壞或無法以 PyMuPDF 開啟。

    例：fitz.open() 拋出例外、認證失敗導致無法讀取頁面。
    """


# ---------------------------------------------------------------------------
# 內部輔助
# ---------------------------------------------------------------------------

# Windows / macOS / Linux 的檔名非法字元（取聯集）
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
# 連續空白收縮為底線
_WHITESPACE_NORMALIZE = re.compile(r'\s+')


def _sanitize_filename(name: str, max_length: int = 100) -> str:
    """將字串轉換為合法的檔名片段。

    Args:
        name: 原始字串（可能含書籤標題、特殊字元）。
        max_length: 最大長度（字元數），超過則截斷。

    Returns:
        合法的檔名片段字串，不含路徑分隔符及系統保留字元。
    """
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name)
    cleaned = _WHITESPACE_NORMALIZE.sub("_", cleaned).strip("_. ")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_length]


def _open_pdf(path: Path) -> "fitz.Document":
    """以 PyMuPDF 開啟 PDF，失敗時拋 PdfCorruptedError。

    Args:
        path: PDF 檔案路徑。

    Returns:
        已開啟的 fitz.Document 物件（呼叫方負責 close）。

    Raises:
        PdfToolError: 檔案不存在。
        PdfCorruptedError: PyMuPDF 無法開啟該檔案。
    """
    if not path.exists():
        raise PdfToolError(f"檔案不存在: {path}")
    try:
        import fitz
        return fitz.open(str(path))
    except Exception as exc:
        raise PdfCorruptedError(f"無法開啟 PDF: {path} — {exc}") from exc


def _fire_progress(
    callback: Callable[[float], None] | None,
    value: float,
) -> None:
    """安全地呼叫 progress_callback，靜默忽略回呼自身的例外。

    Args:
        callback: 進度回呼，接受 0.0–1.0 的 float；None 時跳過。
        value: 進度值，範圍 [0.0, 1.0]。
    """
    if callback is None:
        return
    try:
        callback(max(0.0, min(1.0, value)))
    except Exception:
        pass  # 進度回呼失敗不影響主流程


# ---------------------------------------------------------------------------
# 公開函式
# ---------------------------------------------------------------------------


def merge_pdfs(
    input_paths: list[Path],
    output_path: Path,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    """合併多個 PDF 為一個輸出檔案。

    用 fitz.open() 建立空白文件，逐一以 doc.insert_pdf(src) 串接各來源 PDF。
    每處理完一個來源檔案即呼叫 progress_callback，最終呼叫 progress_callback(1.0)。

    Args:
        input_paths: 要合併的 PDF 路徑清單，至少需包含 1 個路徑。
        output_path: 合併結果的輸出路徑（父目錄必須存在）。
        progress_callback: 進度回呼，接受 0.0–1.0 的 float；None 時略過。

    Raises:
        PdfToolError: 輸入清單為空、某個來源檔案不存在、父目錄不存在、
                      磁碟寫入失敗等。
        PdfCorruptedError: 某個來源 PDF 損壞或無法以 PyMuPDF 開啟。
    """
    if not input_paths:
        raise PdfToolError("合併 PDF 失敗：輸入清單為空")

    if not output_path.parent.exists():
        raise PdfToolError(f"輸出目錄不存在: {output_path.parent}")

    import fitz

    total = len(input_paths)
    logger.info("merge_pdfs: 開始合併 %d 個 PDF → %s", total, output_path)

    merged_doc = fitz.open()
    try:
        for index, src_path in enumerate(input_paths):
            src_doc = _open_pdf(src_path)
            try:
                merged_doc.insert_pdf(src_doc)
                logger.debug(
                    "merge_pdfs: 已插入 %s (%d 頁)",
                    src_path.name,
                    len(src_doc),
                )
            finally:
                src_doc.close()

            _fire_progress(callback=progress_callback, value=(index + 1) / total)

        merged_doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        logger.info("merge_pdfs: 完成，輸出 %s", output_path)
    except PdfToolError:
        raise
    except PdfCorruptedError:
        raise
    except Exception as exc:
        raise PdfToolError(
            f"merge_pdfs 失敗（合併至 {output_path}）: {exc}"
        ) from exc
    finally:
        merged_doc.close()

    _fire_progress(callback=progress_callback, value=1.0)


def split_pdf(
    input_path: Path,
    output_dir: Path,
    mode: str = "per_page",
    ranges: list[tuple[int, int]] | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> list[Path]:
    """拆分 PDF，回傳所有輸出檔案路徑清單。

    支援三種拆分模式：

    - ``"per_page"``：每頁獨立為一個 PDF，
      命名規則 ``{stem}_page_{N:04d}.pdf``（N 從 1 起）。

    - ``"ranges"``：依使用者指定的頁面範圍切割，
      命名規則 ``{stem}_part_{i}_{start}-{end}.pdf``（i 從 1 起），
      頁碼為 1-indexed inclusive；需傳入 ``ranges`` 參數。

    - ``"bookmarks"``：依頂層書籤（level=1）切割，
      命名規則 ``{stem}_{safe_title}.pdf``；
      若 PDF 無書籤則拋 ``PdfToolError("此 PDF 無書籤")``。

    每處理完一個輸出檔即呼叫 progress_callback，最終呼叫 progress_callback(1.0)。

    Args:
        input_path: 來源 PDF 路徑。
        output_dir: 輸出目錄（必須存在）。
        mode: 拆分模式，``"per_page"`` | ``"ranges"`` | ``"bookmarks"``。
        ranges: 頁面範圍清單，僅 ``mode="ranges"`` 時使用。
                每個 tuple 格式為 ``(start_page, end_page)``，1-indexed inclusive。
                例：``[(1, 3), (5, 7)]``。
        progress_callback: 進度回呼，接受 0.0–1.0 的 float；None 時略過。

    Returns:
        所有產生的輸出檔案路徑清單，順序對應拆分順序。

    Raises:
        PdfToolError: 輸出目錄不存在、mode 無效、ranges 為空、
                      頁碼超出範圍、PDF 無書籤等。
        PdfCorruptedError: 來源 PDF 損壞或無法開啟。
    """
    if not output_dir.exists():
        raise PdfToolError(f"輸出目錄不存在: {output_dir}")

    valid_modes = {"per_page", "ranges", "bookmarks"}
    if mode not in valid_modes:
        raise PdfToolError(f"split_pdf 不支援的 mode: {mode!r}，合法值: {valid_modes}")

    src_doc = _open_pdf(input_path)
    stem = input_path.stem
    output_paths: list[Path] = []

    try:
        page_count = len(src_doc)
        logger.info(
            "split_pdf: 開始拆分 %s (%d 頁) mode=%s",
            input_path.name,
            page_count,
            mode,
        )

        if mode == "per_page":
            output_paths = _split_per_page(
                src_doc=src_doc,
                output_dir=output_dir,
                stem=stem,
                page_count=page_count,
                progress_callback=progress_callback,
            )

        elif mode == "ranges":
            if not ranges:
                raise PdfToolError("mode='ranges' 時 ranges 參數不可為空")
            output_paths = _split_ranges(
                src_doc=src_doc,
                output_dir=output_dir,
                stem=stem,
                page_count=page_count,
                ranges=ranges,
                progress_callback=progress_callback,
            )

        elif mode == "bookmarks":
            output_paths = _split_bookmarks(
                src_doc=src_doc,
                output_dir=output_dir,
                stem=stem,
                page_count=page_count,
                progress_callback=progress_callback,
            )

    except PdfToolError:
        raise
    except Exception as exc:
        raise PdfToolError(f"split_pdf 失敗（{input_path.name}）: {exc}") from exc
    finally:
        src_doc.close()

    _fire_progress(callback=progress_callback, value=1.0)
    logger.info("split_pdf: 完成，產生 %d 個檔案", len(output_paths))
    return output_paths


def _split_per_page(
    src_doc: "fitz.Document",
    output_dir: Path,
    stem: str,
    page_count: int,
    progress_callback: Callable[[float], None] | None,
) -> list[Path]:
    """split_pdf 的 per_page 實作：每頁產生一個 PDF。"""
    import fitz

    output_paths: list[Path] = []
    for page_num in range(page_count):
        out_path = output_dir / f"{stem}_page_{page_num + 1:04d}.pdf"
        single_doc = fitz.open()
        try:
            single_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
            single_doc.save(str(out_path), garbage=4, deflate=True, clean=True)
            output_paths.append(out_path)
            logger.debug("split_pdf per_page: 頁 %d → %s", page_num + 1, out_path.name)
        finally:
            single_doc.close()

        _fire_progress(
            callback=progress_callback,
            value=(page_num + 1) / page_count,
        )

    return output_paths


def _split_ranges(
    src_doc: "fitz.Document",
    output_dir: Path,
    stem: str,
    page_count: int,
    ranges: list[tuple[int, int]],
    progress_callback: Callable[[float], None] | None,
) -> list[Path]:
    """split_pdf 的 ranges 實作：依頁面範圍產生 PDF。"""
    import fitz

    output_paths: list[Path] = []
    total_ranges = len(ranges)

    for i, (start_page, end_page) in enumerate(ranges):
        # 驗證頁碼（1-indexed）
        if start_page < 1 or end_page < start_page or end_page > page_count:
            raise PdfToolError(
                f"頁面範圍無效: ({start_page}, {end_page})，"
                f"PDF 共 {page_count} 頁（1-indexed）"
            )

        out_path = output_dir / f"{stem}_part_{i + 1}_{start_page}-{end_page}.pdf"
        range_doc = fitz.open()
        try:
            # insert_pdf 使用 0-indexed
            range_doc.insert_pdf(
                src_doc,
                from_page=start_page - 1,
                to_page=end_page - 1,
            )
            range_doc.save(str(out_path), garbage=4, deflate=True, clean=True)
            output_paths.append(out_path)
            logger.debug(
                "split_pdf ranges: 頁 %d-%d → %s",
                start_page,
                end_page,
                out_path.name,
            )
        finally:
            range_doc.close()

        _fire_progress(
            callback=progress_callback,
            value=(i + 1) / total_ranges,
        )

    return output_paths


def _split_bookmarks(
    src_doc: "fitz.Document",
    output_dir: Path,
    stem: str,
    page_count: int,
    progress_callback: Callable[[float], None] | None,
) -> list[Path]:
    """split_pdf 的 bookmarks 實作：依頂層書籤產生 PDF。

    get_toc(simple=True) 回傳 [level, title, page, dest] 的清單，
    只取 level=1 的頂層書籤，計算每段的結束頁後切割。
    """
    import fitz

    toc = src_doc.get_toc(simple=True)
    top_level_bookmarks = [entry for entry in toc if entry[0] == 1]

    if not top_level_bookmarks:
        raise PdfToolError("此 PDF 無書籤，無法使用 mode='bookmarks' 拆分")

    # 計算每個書籤的頁面範圍（0-indexed）
    bookmark_ranges: list[tuple[str, int, int]] = []
    for idx, entry in enumerate(top_level_bookmarks):
        title = entry[1]
        start_page = entry[2] - 1  # get_toc 回傳 1-indexed，轉為 0-indexed

        # 此書籤的結束頁 = 下一個書籤的起始頁 - 1，最後一個用文件末頁
        if idx + 1 < len(top_level_bookmarks):
            end_page = top_level_bookmarks[idx + 1][2] - 2  # 0-indexed
        else:
            end_page = page_count - 1

        # 邊界保護：若頁碼異常則跳過
        if start_page < 0 or start_page > end_page or end_page >= page_count:
            logger.warning(
                "split_pdf bookmarks: 書籤 %r 頁碼異常 (%d–%d)，已跳過",
                title,
                start_page + 1,
                end_page + 1,
            )
            continue

        bookmark_ranges.append((title, start_page, end_page))

    if not bookmark_ranges:
        raise PdfToolError("所有頂層書籤的頁碼均無效，無法拆分")

    output_paths: list[Path] = []
    total = len(bookmark_ranges)
    used_names: set[str] = set()

    for i, (title, start_page, end_page) in enumerate(bookmark_ranges):
        safe_title = _sanitize_filename(title)

        # 避免同名衝突（書籤名稱清理後可能重複）
        unique_title = safe_title
        counter = 2
        while unique_title in used_names:
            unique_title = f"{safe_title}_{counter}"
            counter += 1
        used_names.add(unique_title)

        out_path = output_dir / f"{stem}_{unique_title}.pdf"
        bm_doc = fitz.open()
        try:
            bm_doc.insert_pdf(src_doc, from_page=start_page, to_page=end_page)
            bm_doc.save(str(out_path), garbage=4, deflate=True, clean=True)
            output_paths.append(out_path)
            logger.debug(
                "split_pdf bookmarks: 書籤 %r (頁 %d–%d) → %s",
                title,
                start_page + 1,
                end_page + 1,
                out_path.name,
            )
        finally:
            bm_doc.close()

        _fire_progress(callback=progress_callback, value=(i + 1) / total)

    return output_paths


def compress_pdf(
    input_path: Path,
    output_path: Path,
    quality: str = "balanced",
    progress_callback: Callable[[float], None] | None = None,
) -> dict:
    """壓縮 PDF，回傳壓縮前後大小資訊。

    壓縮策略：
    1. 先啟用 PyMuPDF 的 ``garbage=4, deflate=True, deflate_images=True,
       deflate_fonts=True, clean=True`` 整理並重壓縮 streams。
    2. 依 quality 等級額外處理圖片 streams：
       用 Pillow 讀取各圖片 xref，重新編碼為 JPEG，再以 ``update_stream()`` 寫回。
       - ``"low"``：JPEG quality=40
       - ``"balanced"``：JPEG quality=70
       - ``"high"``：JPEG quality=90

    若壓縮後檔案反而變大，仍正常寫出（ratio 可能 > 1.0，不視為錯誤）。

    Args:
        input_path: 來源 PDF 路徑。
        output_path: 壓縮結果的輸出路徑（父目錄必須存在）。
        quality: 壓縮等級，``"low"`` | ``"balanced"`` | ``"high"``。
        progress_callback: 進度回呼，接受 0.0–1.0 的 float；None 時略過。

    Returns:
        ::

            {
                "original_size": int,    # 原始檔案位元組數
                "compressed_size": int,  # 壓縮後位元組數
                "ratio": float,          # compressed_size / original_size
            }

    Raises:
        PdfToolError: 輸入檔不存在、quality 無效、父目錄不存在、磁碟寫入失敗等。
        PdfCorruptedError: 來源 PDF 損壞或無法開啟。
    """
    valid_quality = {"low", "balanced", "high"}
    if quality not in valid_quality:
        raise PdfToolError(
            f"compress_pdf 不支援的 quality: {quality!r}，合法值: {valid_quality}"
        )

    if not output_path.parent.exists():
        raise PdfToolError(f"輸出目錄不存在: {output_path.parent}")

    jpeg_quality_map = {"low": 40, "balanced": 70, "high": 90}
    jpeg_quality = jpeg_quality_map[quality]

    original_size = input_path.stat().st_size
    logger.info(
        "compress_pdf: 開始壓縮 %s (%.1f KB) quality=%s",
        input_path.name,
        original_size / 1024,
        quality,
    )

    _fire_progress(callback=progress_callback, value=0.0)

    doc = _open_pdf(input_path)
    try:
        _compress_images_in_place(doc, jpeg_quality, progress_callback)

        _fire_progress(callback=progress_callback, value=0.9)

        doc.save(
            str(output_path),
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    except PdfToolError:
        raise
    except PdfCorruptedError:
        raise
    except Exception as exc:
        raise PdfToolError(f"compress_pdf 失敗（{input_path.name}）: {exc}") from exc
    finally:
        doc.close()

    compressed_size = output_path.stat().st_size
    ratio = compressed_size / original_size if original_size > 0 else 1.0

    logger.info(
        "compress_pdf: 完成 %.1f KB → %.1f KB (ratio=%.2f)",
        original_size / 1024,
        compressed_size / 1024,
        ratio,
    )

    _fire_progress(callback=progress_callback, value=1.0)

    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "ratio": ratio,
    }


def _compress_images_in_place(
    doc: "fitz.Document",
    jpeg_quality: int,
    progress_callback: Callable[[float], None] | None,
) -> None:
    """遍歷文件中所有圖片 xref，以 Pillow 重壓縮後寫回。

    只處理可被 Pillow 重新解碼的格式（PNG / JPEG / BMP 等）；
    CMYK / 遮罩 / 不可識別格式的圖片靜默跳過，不中斷流程。

    Args:
        doc: 已開啟的 fitz.Document（直接修改，呼叫方負責 save 和 close）。
        jpeg_quality: JPEG 壓縮品質（1–95）。
        progress_callback: 進度回呼；圖片處理占整體進度 0.0–0.85。
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("compress_pdf: Pillow 未安裝，跳過圖片重壓縮")
        return

    xref_total = doc.xref_length()
    if xref_total <= 0:
        return

    processed_xrefs: set[int] = set()

    for page in doc:
        image_list = page.get_images(full=True)
        for img_info in image_list:
            xref = img_info[0]
            if xref in processed_xrefs:
                continue
            processed_xrefs.add(xref)

            if not doc.xref_is_image(xref):
                continue

            try:
                img_dict = doc.extract_image(xref)
                if img_dict is None:
                    continue

                image_bytes = img_dict.get("image")
                colorspace = img_dict.get("colorspace", 3)

                if not image_bytes:
                    continue

                # CMYK (colorspace=4) 轉 RGB 後再壓縮；單色 (1) 跳過（品質損失不划算）
                pil_img = Image.open(io.BytesIO(image_bytes))
                if pil_img.mode == "CMYK":
                    pil_img = pil_img.convert("RGB")
                elif pil_img.mode in ("1", "P"):
                    continue

                # 確保可用 JPEG 編碼
                if pil_img.mode not in ("RGB", "L", "RGBA"):
                    pil_img = pil_img.convert("RGB")

                # RGBA 轉 RGB（JPEG 不支援 alpha）
                if pil_img.mode == "RGBA":
                    background = Image.new("RGB", pil_img.size, (255, 255, 255))
                    background.paste(pil_img, mask=pil_img.split()[3])
                    pil_img = background

                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
                new_bytes = buf.getvalue()

                # 只在實際更小時才寫回，避免無謂放大
                if len(new_bytes) < len(image_bytes):
                    doc.update_stream(xref, new_bytes)
                    logger.debug(
                        "compress_pdf: xref %d 圖片 %d → %d bytes",
                        xref,
                        len(image_bytes),
                        len(new_bytes),
                    )

            except Exception as img_exc:
                logger.debug("compress_pdf: xref %d 圖片跳過（%s）", xref, img_exc)
                continue

        # 以頁數為粒度回報進度（占 0.0–0.85 區間）
        _fire_progress(
            callback=progress_callback,
            value=(page.number + 1) / len(doc) * 0.85,
        )


def encrypt_pdf(
    input_path: Path,
    output_path: Path,
    user_password: str,
    owner_password: str | None = None,
    permissions: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    """為 PDF 加密（AES-256）。

    以 AES-256 演算法加密，設定使用者密碼（開啟文件所需）與
    擁有者密碼（完整權限），並套用權限遮罩。

    Args:
        input_path: 來源 PDF 路徑。
        output_path: 加密結果的輸出路徑（父目錄必須存在）。
        user_password: 開啟文件所需密碼，不可為空字串。
        owner_password: 擁有者密碼（可修改權限）；None 時與 user_password 相同。
        permissions: fitz 權限遮罩整數；None 時預設為
                     ``fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT``。
        progress_callback: 進度回呼，接受 0.0–1.0 的 float；None 時略過。

    Raises:
        PdfPasswordError: user_password 為空字串。
        PdfToolError: 父目錄不存在、磁碟寫入失敗等。
        PdfCorruptedError: 來源 PDF 損壞或無法開啟。
    """
    if not user_password:
        raise PdfPasswordError("密碼不可為空")

    if not output_path.parent.exists():
        raise PdfToolError(f"輸出目錄不存在: {output_path.parent}")

    import fitz

    effective_owner_password = owner_password if owner_password is not None else user_password
    effective_permissions = (
        permissions
        if permissions is not None
        else fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT
    )

    logger.info("encrypt_pdf: 加密 %s → %s", input_path.name, output_path.name)
    _fire_progress(callback=progress_callback, value=0.0)

    doc = _open_pdf(input_path)
    try:
        doc.save(
            str(output_path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=effective_owner_password,
            user_pw=user_password,
            permissions=effective_permissions,
            garbage=4,
            deflate=True,
        )
    except PdfCorruptedError:
        raise
    except Exception as exc:
        raise PdfToolError(f"encrypt_pdf 失敗（{input_path.name}）: {exc}") from exc
    finally:
        doc.close()

    logger.info("encrypt_pdf: 完成 → %s", output_path.name)
    _fire_progress(callback=progress_callback, value=1.0)


def decrypt_pdf(
    input_path: Path,
    output_path: Path,
    password: str,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    """移除 PDF 密碼保護，輸出明文 PDF。

    以 ``fitz.open()`` 嘗試開啟，再以 ``doc.authenticate(password)`` 解鎖；
    驗證成功後以 ``fitz.PDF_ENCRYPT_NONE`` 重新存檔。

    Args:
        input_path: 來源（加密）PDF 路徑。
        output_path: 解密結果的輸出路徑（父目錄必須存在）。
        password: 解鎖密碼（user password 或 owner password 均可）。
        progress_callback: 進度回呼，接受 0.0–1.0 的 float；None 時略過。

    Raises:
        PdfPasswordError: 密碼錯誤（authenticate 回傳 0）。
        PdfToolError: 輸入檔不存在、父目錄不存在、磁碟寫入失敗等。
        PdfCorruptedError: PDF 損壞或無法開啟。
    """
    if not output_path.parent.exists():
        raise PdfToolError(f"輸出目錄不存在: {output_path.parent}")

    import fitz

    logger.info("decrypt_pdf: 解密 %s", input_path.name)
    _fire_progress(callback=progress_callback, value=0.0)

    doc = _open_pdf(input_path)
    try:
        if doc.needs_pass:
            auth_result = doc.authenticate(password)
            if auth_result == 0:
                raise PdfPasswordError(
                    f"密碼錯誤，無法解密: {input_path.name}"
                )
            logger.debug("decrypt_pdf: 認證成功（auth_result=%d）", auth_result)

        _fire_progress(callback=progress_callback, value=0.5)

        doc.save(
            str(output_path),
            encryption=fitz.PDF_ENCRYPT_NONE,
            garbage=4,
            deflate=True,
        )
    except (PdfPasswordError, PdfToolError, PdfCorruptedError):
        raise
    except Exception as exc:
        raise PdfToolError(f"decrypt_pdf 失敗（{input_path.name}）: {exc}") from exc
    finally:
        doc.close()

    logger.info("decrypt_pdf: 完成 → %s", output_path.name)
    _fire_progress(callback=progress_callback, value=1.0)


def get_pdf_info(input_path: Path) -> dict:
    """讀取 PDF 元資訊，供 UI 預覽用。

    嘗試開啟時若遇到加密 PDF，以 ``needs_pass`` 旗標判斷；
    無法認證時仍回傳部分資訊（page_count=0、is_encrypted=True）。

    Args:
        input_path: 來源 PDF 路徑。

    Returns:
        ::

            {
                "page_count": int,       # 頁面數（加密且無法認證時為 0）
                "size_bytes": int,       # 檔案大小（位元組）
                "is_encrypted": bool,    # 是否有密碼保護
                "has_bookmarks": bool,   # 是否有書籤（目錄）
                "title": str | None,     # PDF 元資料中的標題
                "author": str | None,    # PDF 元資料中的作者
            }

    Raises:
        PdfToolError: 輸入檔不存在。
        PdfCorruptedError: PDF 損壞或 PyMuPDF 無法開啟。
    """
    if not input_path.exists():
        raise PdfToolError(f"檔案不存在: {input_path}")

    size_bytes = input_path.stat().st_size
    doc = _open_pdf(input_path)

    try:
        is_encrypted = doc.needs_pass

        if is_encrypted:
            # 加密且未解鎖，只回傳有限資訊
            return {
                "page_count": 0,
                "size_bytes": size_bytes,
                "is_encrypted": True,
                "has_bookmarks": False,
                "title": None,
                "author": None,
            }

        page_count = len(doc)
        toc = doc.get_toc(simple=True)
        has_bookmarks = len(toc) > 0

        metadata = doc.metadata or {}
        title = metadata.get("title") or None
        author = metadata.get("author") or None

        # 空字串視同 None（PyMuPDF 有時回傳 ""）
        if title == "":
            title = None
        if author == "":
            author = None

        return {
            "page_count": page_count,
            "size_bytes": size_bytes,
            "is_encrypted": is_encrypted,
            "has_bookmarks": has_bookmarks,
            "title": title,
            "author": author,
        }

    except PdfToolError:
        raise
    except Exception as exc:
        raise PdfCorruptedError(
            f"get_pdf_info 讀取元資訊失敗（{input_path.name}）: {exc}"
        ) from exc
    finally:
        doc.close()
