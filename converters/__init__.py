"""
converters — 多格式文件轉換引擎

公開 API：
  - convert_file(input_path, output_path, source_format, target_format)
  - detect_format(file_path) -> str
  - get_supported_matrix() -> dict

例外類型（供呼叫方 import 使用）：
  - ConversionError
  - UnsupportedFormatError
  - ConversionTimeoutError
"""

__version__ = "1.0.0"

from .dispatcher import convert_file, detect_format, get_supported_matrix, is_supported_pair
from .exceptions import ConversionError, ConversionTimeoutError, UnsupportedFormatError

__all__ = [
    "convert_file",
    "detect_format",
    "get_supported_matrix",
    "is_supported_pair",
    "ConversionError",
    "UnsupportedFormatError",
    "ConversionTimeoutError",
]
