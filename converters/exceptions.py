"""
converters/exceptions.py — 轉換引擎例外類型

定義所有轉換相關例外，供 dispatcher 和呼叫方 catch。
"""


class ConversionError(Exception):
    """轉換失敗（首選 + 降級都失敗）"""

    def __init__(self, message: str, source_error: Exception | None = None,
                 fallback_error: Exception | None = None):
        super().__init__(message)
        self.source_error = source_error
        self.fallback_error = fallback_error

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.source_error:
            parts.append(f"首選引擎錯誤: {self.source_error}")
        if self.fallback_error:
            parts.append(f"降級引擎錯誤: {self.fallback_error}")
        return " | ".join(parts)


class UnsupportedFormatError(ConversionError):
    """不支援的格式對（source_format → target_format）"""


class ConversionTimeoutError(ConversionError):
    """轉換超時（超過設定的上限秒數）"""
