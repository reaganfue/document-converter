"""
converters/image_converter.py — 圖片來源轉換器

支援：IMG → PDF / IMG（格式互轉 PNG↔JPG）
注意：PNG→JPG 時處理透明通道（填白底）
"""

import logging
from pathlib import Path

from .base import BaseConverter
from .exceptions import ConversionError, UnsupportedFormatError
from .utils import IMAGE_EXTENSIONS, ensure_output_dir, get_image_ext

logger = logging.getLogger(__name__)

# 支援輸入的圖片副檔名（用於 dispatcher detect_format）
_SUPPORTED_INPUT_EXTS: set[str] = {"png", "jpg", "jpeg", "bmp", "gif", "tiff", "tif", "webp"}


class ImageConverter(BaseConverter):
    """圖片格式來源轉換器。

    支援目標格式：pdf / image（格式互轉）
    """

    source_format = "image"
    supported_targets = ["pdf", "image"]

    def convert(self, input_path: Path, output_path: Path, target_format: str) -> None:
        """執行圖片轉換。

        Args:
            input_path: 來源圖片路徑（PNG/JPG/BMP/GIF/TIFF/WEBP）
            output_path: 目標檔案路徑
            target_format: "pdf" | "image"

        Raises:
            UnsupportedFormatError: target_format 不在支援清單
            ConversionError: 轉換失敗
        """
        if not self.supports(target_format):
            raise UnsupportedFormatError(
                f"ImageConverter 不支援目標格式: {target_format}"
            )

        ensure_output_dir(output_path)
        self._log_primary_attempt(target_format)

        if target_format == "pdf":
            self._to_pdf(input_path, output_path)
        else:
            self._to_image(input_path, output_path)

    # ─── 各目標格式實作 ────────────────────────────────────────────

    def _to_pdf(self, input_path: Path, output_path: Path) -> None:
        """IMG → PDF：Pillow Image.save("PDF")。"""
        try:
            from PIL import Image

            img = Image.open(str(input_path))

            # PDF 不支援 RGBA / P 模式（透明）→ 轉 RGB + 填白底
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.save(str(output_path), "PDF", resolution=150)
            img.close()
            logger.info("IMG→PDF 成功")
        except Exception as exc:
            raise ConversionError("IMG→PDF 轉換失敗", source_error=exc) from exc

    def _to_image(self, input_path: Path, output_path: Path) -> None:
        """IMG → IMG（格式互轉）。

        支援：PNG↔JPG↔BMP 等 Pillow 支援格式
        JPG 不支援透明：PNG→JPG 時轉 RGB + 填白底
        """
        try:
            from PIL import Image

            img = Image.open(str(input_path))
            target_ext = output_path.suffix.lstrip(".").lower()

            if target_ext in ("jpg", "jpeg"):
                # JPG 不支援透明通道
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    if img.mode in ("RGBA", "LA"):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(str(output_path), "JPEG", quality=90)
            elif target_ext == "png":
                img.save(str(output_path), "PNG")
            elif target_ext == "bmp":
                if img.mode not in ("RGB", "RGBA", "L"):
                    img = img.convert("RGB")
                img.save(str(output_path), "BMP")
            elif target_ext in ("tiff", "tif"):
                img.save(str(output_path), "TIFF")
            elif target_ext == "webp":
                img.save(str(output_path), "WEBP", quality=90)
            else:
                # 其他格式：讓 Pillow 自行推斷
                img.save(str(output_path))

            img.close()
            logger.info("IMG→IMG 成功: %s → %s", input_path.suffix, target_ext)
        except Exception as exc:
            raise ConversionError("IMG→IMG 轉換失敗", source_error=exc) from exc
