"""
conftest.py — pytest fixtures（桌面版，無 Flask 依賴）

職責：
- 提供 converter 測試需要的通用 fixtures
- 不再包含 Flask / app.py 相關 fixtures（已移至 conftest_flask_legacy.py）

Flask fixtures 封存原因：
  app.py 已改為 app.py.legacy，桌面版應用不再依賴 Flask。
  若日後重新啟用 Flask API，從 conftest_flask_legacy.py 複製所需 fixtures。
"""

from __future__ import annotations

import pytest
