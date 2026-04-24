"""SQLite 歷史記錄資料庫層 — 連線管理 + schema 初始化 + DAO 實作。

架構（per architect W-COMMERCIAL_plan.md 附錄 A）：
    - 單一資料庫檔案：%LOCALAPPDATA%/DocConverter/history.db
    - 3 個主要資料表：
        jobs            歷史轉換記錄
        preferences     未來偏好設定擴展保留
        schema_version  版本號追蹤（支援 migration）
    - Thread-safe：sqlite3 + check_same_thread=False + threading.Lock
    - isolation_level=None（autocommit 模式，簡化 transaction 管理）
"""
from __future__ import annotations

import csv
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from desktop.interfaces import HistoryRecord

# CSV 公式注入防護（CVE-2017-15005）：以下字元開頭的欄位值會被 Excel / LibreOffice
# 視為公式，加上單引號前綴可強制視為文字。
_DANGEROUS_CSV_PREFIXES = ("=", "@", "+", "-", "\t", "\r")

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid            TEXT    NOT NULL UNIQUE,
    created_at          TEXT    NOT NULL,
    completed_at        TEXT,
    source_path         TEXT    NOT NULL,
    source_format       TEXT    NOT NULL,
    source_size_bytes   INTEGER NOT NULL,
    target_format       TEXT    NOT NULL,
    output_path         TEXT,
    status              TEXT    NOT NULL,
    error_message       TEXT,
    duration_ms         INTEGER,
    app_version         TEXT    NOT NULL,
    settings_snapshot   TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at
    ON jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);

CREATE INDEX IF NOT EXISTS idx_jobs_source_format
    ON jobs(source_format);

CREATE INDEX IF NOT EXISTS idx_jobs_target_format
    ON jobs(target_format);

CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
"""

# 所有 HistoryRecord 欄位（不含 id，用於 SELECT 順序對齊）
_JOB_COLUMNS = (
    "id", "job_uuid", "created_at", "completed_at",
    "source_path", "source_format", "source_size_bytes",
    "target_format", "output_path", "status", "error_message",
    "duration_ms", "app_version",
)


def _sanitize_csv_cell(value: Any) -> str:
    """防止 CSV formula injection（CVE-2017-15005）。

    若值以危險字元開頭，前綴單引號（Excel / LibreOffice 視為文字而非公式）。
    None 回傳空字串；非字串值先轉為字串再判斷。
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _DANGEROUS_CSV_PREFIXES:
        return "'" + text
    return text


def _row_to_record(row: sqlite3.Row) -> HistoryRecord:
    """將 sqlite3.Row 轉換為 HistoryRecord dataclass。"""
    return HistoryRecord(
        id=row["id"],
        job_uuid=row["job_uuid"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        source_path=row["source_path"],
        source_format=row["source_format"],
        source_size_bytes=row["source_size_bytes"],
        target_format=row["target_format"],
        output_path=row["output_path"],
        status=row["status"],
        error_message=row["error_message"],
        duration_ms=row["duration_ms"],
        app_version=row["app_version"],
    )


class HistoryDB:
    """Thread-safe SQLite 歷史記錄資料庫。

    使用方式：
        db = HistoryDB()               # 使用預設路徑
        db = HistoryDB(db_path=Path("custom.db"))  # 指定路徑（測試用）

    生命週期：
        __init__ 即自動初始化 schema。
        close()  在應用關閉時呼叫（MainWindowV2.closeEvent 負責）。

    所有公開方法皆 Thread-safe（內部使用 threading.Lock）。
    """

    def __init__(self, db_path: Optional[Path] = None):
        """初始化資料庫連線並執行 schema 初始化。

        Args:
            db_path: 資料庫檔案路徑。None 時使用預設路徑
                     (%LOCALAPPDATA%/DocConverter/history.db)。
        """
        self._db_path = db_path or self._default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.debug("HistoryDB 初始化完成：%s", self._db_path)

    @staticmethod
    def _default_db_path() -> Path:
        """回傳預設資料庫路徑（%LOCALAPPDATA%/DocConverter/history.db）。"""
        from desktop.utils.paths import get_app_data_dir
        return get_app_data_dir() / "history.db"

    def _init_db(self) -> None:
        """建立 SQLite 連線、執行 DDL、寫入 schema 版本號。"""
        with self._lock:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,   # autocommit
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA_DDL)

            cur = self._conn.execute(
                "SELECT version FROM schema_version WHERE version = ?",
                (SCHEMA_VERSION,),
            )
            if cur.fetchone() is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
                logger.info("schema_version %d 已寫入", SCHEMA_VERSION)

    # =========================================================================
    # DAO 實作
    # =========================================================================

    def add_record(self, **kwargs: Any) -> int:
        """插入一筆 job 記錄，回傳資料庫 auto-increment id。

        Args:
            **kwargs: 對應 jobs 表欄位（job_uuid, created_at, source_path, ...）。
                      settings_snapshot 可選，預設 NULL。

        Returns:
            新插入記錄的 lastrowid。

        Raises:
            sqlite3.IntegrityError: job_uuid 重複時。
            sqlite3.Error: 其他 SQL 錯誤。
        """
        cols = [
            "job_uuid", "created_at", "completed_at",
            "source_path", "source_format", "source_size_bytes",
            "target_format", "output_path", "status", "error_message",
            "duration_ms", "app_version", "settings_snapshot",
        ]
        values = [kwargs.get(col) for col in cols]
        placeholders = ", ".join("?" * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO jobs ({col_names}) VALUES ({placeholders})"

        with self._lock:
            cur = self._conn.execute(sql, values)
            row_id = cur.lastrowid
            logger.debug("add_record: inserted id=%d uuid=%s", row_id, kwargs.get("job_uuid"))
            return row_id

    def update_record(self, record_id: int, **kwargs: Any) -> bool:
        """更新指定 id 的 job 記錄（僅更新傳入的欄位）。

        Args:
            record_id: 要更新的記錄主鍵 id。
            **kwargs:  欲更新的欄位與值。

        Returns:
            True 表示成功更新（rowcount > 0），False 表示找不到 id。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        if not kwargs:
            return False

        set_clauses = ", ".join(f"{col} = ?" for col in kwargs)
        values = list(kwargs.values()) + [record_id]
        sql = f"UPDATE jobs SET {set_clauses} WHERE id = ?"

        with self._lock:
            cur = self._conn.execute(sql, values)
            updated = cur.rowcount > 0
            logger.debug("update_record: id=%d updated=%s", record_id, updated)
            return updated

    def list_records(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        source_format: Optional[str] = None,
        target_format: Optional[str] = None,
        search_term: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[HistoryRecord]:
        """查詢記錄清單，支援篩選與分頁。

        Args:
            offset:        分頁偏移量（預設 0）。
            limit:         每頁筆數（預設 100）。
            status:        狀態篩選（"done"/"error"/"cancelled"，None 表示全部）。
            source_format: 來源格式篩選（None 表示全部）。
            target_format: 目標格式篩選（None 表示全部）。
            search_term:   搜尋詞（對 source_path 做 LIKE 匹配）。
            date_from:     起始日期 ISO-8601 字串（含）。
            date_to:       結束日期 ISO-8601 字串（含）。

        Returns:
            HistoryRecord list，按 created_at DESC 排序。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        conditions: list[str] = []
        params: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if source_format is not None:
            conditions.append("source_format = ?")
            params.append(source_format)
        if target_format is not None:
            conditions.append("target_format = ?")
            params.append(target_format)
        if search_term is not None and search_term.strip():
            conditions.append("source_path LIKE ?")
            params.append(f"%{search_term.strip()}%")
        if date_from is not None:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to is not None:
            conditions.append("created_at <= ?")
            params.append(date_to)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        col_list = ", ".join(_JOB_COLUMNS)
        sql = (
            f"SELECT {col_list} FROM jobs {where_clause} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_record(row) for row in rows]

    def get_record(self, record_id: int) -> Optional[HistoryRecord]:
        """查詢單筆記錄。

        Args:
            record_id: 記錄主鍵 id。

        Returns:
            HistoryRecord 或 None（找不到時）。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        col_list = ", ".join(_JOB_COLUMNS)
        sql = f"SELECT {col_list} FROM jobs WHERE id = ?"

        with self._lock:
            cur = self._conn.execute(sql, (record_id,))
            row = cur.fetchone()
            return _row_to_record(row) if row else None

    def find_by_uuid(self, job_uuid: str) -> Optional[HistoryRecord]:
        """依 job_uuid 查詢最新一筆記錄。

        Args:
            job_uuid: 任務 UUID 字串。

        Returns:
            HistoryRecord（取 created_at 最新的那筆），找不到時回傳 None。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        col_list = ", ".join(_JOB_COLUMNS)
        sql = (
            f"SELECT {col_list} FROM jobs "
            "WHERE job_uuid = ? ORDER BY created_at DESC LIMIT 1"
        )
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.execute(sql, (job_uuid,))
            row = cur.fetchone()
            return _row_to_record(row) if row else None

    def delete_record(self, record_id: int) -> bool:
        """刪除單筆記錄。

        Args:
            record_id: 記錄主鍵 id。

        Returns:
            True 表示成功刪除，False 表示找不到該 id。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        with self._lock:
            cur = self._conn.execute("DELETE FROM jobs WHERE id = ?", (record_id,))
            deleted = cur.rowcount > 0
            logger.debug("delete_record: id=%d deleted=%s", record_id, deleted)
            return deleted

    def delete_records(self, ids: list[int]) -> int:
        """批量刪除多筆記錄。

        Args:
            ids: 要刪除的記錄 id 清單。

        Returns:
            實際刪除的筆數。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        if not ids:
            return 0

        placeholders = ", ".join("?" * len(ids))
        sql = f"DELETE FROM jobs WHERE id IN ({placeholders})"

        with self._lock:
            cur = self._conn.execute(sql, ids)
            deleted = cur.rowcount
            logger.debug("delete_records: deleted=%d from ids=%s", deleted, ids)
            return deleted

    def clear_all(self) -> int:
        """清除所有歷史記錄。

        Returns:
            刪除的總筆數。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        with self._lock:
            count_cur = self._conn.execute("SELECT COUNT(*) FROM jobs")
            total = count_cur.fetchone()[0]
            self._conn.execute("DELETE FROM jobs")
            logger.info("clear_all: deleted %d records", total)
            return total

    def count(
        self,
        *,
        status: Optional[str] = None,
        source_format: Optional[str] = None,
        target_format: Optional[str] = None,
        search_term: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> int:
        """計算符合篩選條件的記錄數。

        Args:
            status:        狀態篩選。
            source_format: 來源格式篩選。
            target_format: 目標格式篩選。
            search_term:   搜尋詞。
            date_from:     起始日期。
            date_to:       結束日期。

        Returns:
            符合條件的記錄筆數。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        conditions: list[str] = []
        params: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if source_format is not None:
            conditions.append("source_format = ?")
            params.append(source_format)
        if target_format is not None:
            conditions.append("target_format = ?")
            params.append(target_format)
        if search_term is not None and search_term.strip():
            conditions.append("source_path LIKE ?")
            params.append(f"%{search_term.strip()}%")
        if date_from is not None:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to is not None:
            conditions.append("created_at <= ?")
            params.append(date_to)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT COUNT(*) FROM jobs {where_clause}"

        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchone()[0]

    def export_csv(self, path: Path, **filters: Any) -> int:
        """將記錄匯出為 CSV 檔案。

        Args:
            path:     目標 CSV 路徑（父目錄必須存在）。
            **filters: 傳遞至 list_records 的篩選參數。

        Returns:
            匯出的記錄筆數。

        Raises:
            sqlite3.Error: 查詢失敗時向上傳播。
            OSError:       檔案寫入失敗時向上傳播。
        """
        records = self.list_records(limit=100_000, **filters)

        fieldnames = list(_JOB_COLUMNS)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for rec in records:
                # 數值欄位（id、source_size_bytes、duration_ms）不需 sanitize；
                # 路徑 / 字串欄位套用 _sanitize_csv_cell 防止 formula injection。
                writer.writerow({
                    "id":                 rec.id,
                    "job_uuid":           _sanitize_csv_cell(rec.job_uuid),
                    "created_at":         _sanitize_csv_cell(rec.created_at),
                    "completed_at":       _sanitize_csv_cell(rec.completed_at),
                    "source_path":        _sanitize_csv_cell(rec.source_path),
                    "source_format":      _sanitize_csv_cell(rec.source_format),
                    "source_size_bytes":  rec.source_size_bytes,
                    "target_format":      _sanitize_csv_cell(rec.target_format),
                    "output_path":        _sanitize_csv_cell(rec.output_path),
                    "status":             _sanitize_csv_cell(rec.status),
                    "error_message":      _sanitize_csv_cell(rec.error_message),
                    "duration_ms":        rec.duration_ms,
                    "app_version":        _sanitize_csv_cell(rec.app_version),
                })

        logger.info("export_csv: wrote %d records to %s", len(records), path)
        return len(records)

    def apply_retention(
        self,
        *,
        max_records: int = 1000,
        max_age_days: Optional[int] = 90,
    ) -> int:
        """清除超出保留策略的記錄。

        策略：
            1. 先刪除 created_at 超過 max_age_days 天前的記錄（若 max_age_days 不為 None）
            2. 若總數仍超過 max_records，從最舊的開始刪除至 max_records 上限

        Args:
            max_records:  最大保留筆數（預設 1000）。
            max_age_days: 最大保留天數（None 表示不限天數）。

        Returns:
            實際刪除的總筆數。

        Raises:
            sqlite3.Error: SQL 錯誤時向上傳播。
        """
        total_deleted = 0

        with self._lock:
            # Step 1：刪除超齡記錄
            if max_age_days is not None:
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=max_age_days)
                ).isoformat()
                cur = self._conn.execute(
                    "DELETE FROM jobs WHERE created_at < ?",
                    (cutoff,),
                )
                age_deleted = cur.rowcount
                total_deleted += age_deleted
                if age_deleted:
                    logger.info(
                        "apply_retention: deleted %d records older than %d days",
                        age_deleted, max_age_days,
                    )

            # Step 2：若總筆數仍超過上限，刪除最舊的
            count_cur = self._conn.execute("SELECT COUNT(*) FROM jobs")
            current_count = count_cur.fetchone()[0]
            if current_count > max_records:
                excess = current_count - max_records
                cur = self._conn.execute(
                    "DELETE FROM jobs WHERE id IN ("
                    "  SELECT id FROM jobs ORDER BY created_at ASC LIMIT ?"
                    ")",
                    (excess,),
                )
                count_deleted = cur.rowcount
                total_deleted += count_deleted
                logger.info(
                    "apply_retention: deleted %d excess records (limit=%d)",
                    count_deleted, max_records,
                )

        return total_deleted

    def close(self) -> None:
        """關閉資料庫連線。應在應用程式退出時呼叫。"""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                logger.debug("HistoryDB 連線已關閉")
