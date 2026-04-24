"""Desktop 資料庫模組 — SQLite 歷史記錄層。

匯出入口：
    HistoryDB   核心資料存取物件（Thread-safe SQLite wrapper）
"""
from desktop.database.history_db import HistoryDB

__all__ = ["HistoryDB"]
