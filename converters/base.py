"""
converters/base.py — BaseConverter 抽象介面

所有格式轉換器都繼承此基底類別，保證 dispatcher 可統一呼叫。
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from .exceptions import ConversionError

logger = logging.getLogger(__name__)


class BaseConverter(ABC):
    """所有轉換器的抽象基底。

    子類須覆寫：
      - source_format: str        — 此轉換器接受的來源格式（小寫）
      - supported_targets: list[str] — 此轉換器支援的目標格式清單
      - convert()                 — 實際執行轉換

    轉換失敗規範：
      - 首選引擎失敗 → 嘗試降級引擎
      - 降級也失敗 → 拋 ConversionError
    """

    source_format: str = ""
    supported_targets: list[str] = []

    @abstractmethod
    def convert(self, input_path: Path, output_path: Path, target_format: str) -> None:
        """執行轉換。

        Args:
            input_path: 來源檔案路徑（必須存在）
            output_path: 目標輸出路徑（父目錄必須存在）
            target_format: 目標格式字串（小寫，如 "pdf"）

        Raises:
            ConversionError: 轉換失敗（首選 + 降級都失敗）
            UnsupportedFormatError: target_format 不在 supported_targets
        """
        ...

    def supports(self, target_format: str) -> bool:
        """檢查此轉換器是否支援指定目標格式。"""
        return target_format.lower() in self.supported_targets

    def _log_primary_attempt(self, target_format: str) -> None:
        """記錄首選引擎嘗試（統一日誌格式）。"""
        logger.info(
            "轉換開始: %s → %s | 引擎: 首選",
            self.source_format,
            target_format,
        )

    def _log_fallback_attempt(self, target_format: str, primary_error: Exception) -> None:
        """記錄降級引擎嘗試（統一日誌格式）。"""
        logger.warning(
            "首選引擎失敗，嘗試降級: %s → %s | 首選錯誤: %s",
            self.source_format,
            target_format,
            primary_error,
        )

    def _raise_conversion_error(
        self,
        target_format: str,
        primary_error: Exception,
        fallback_error: Exception,
    ) -> None:
        """首選 + 降級都失敗時，拋出包含完整上下文的 ConversionError。"""
        msg = (
            f"轉換失敗: {self.source_format} → {target_format}"
        )
        logger.error(
            "%s | 首選: %s | 降級: %s",
            msg,
            primary_error,
            fallback_error,
        )
        raise ConversionError(
            msg,
            source_error=primary_error,
            fallback_error=fallback_error,
        )
