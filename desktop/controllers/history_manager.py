"""歷史記錄管理器 — HistoryDB DAO 的業務邏輯包裝層。

職責：
    - 包裝 HistoryDB DAO 操作，提供業務層語義方法
    - 接收 ConversionController 的 job_completed / job_failed 訊號，自動寫入記錄
    - 觸發 HistoryManagerSignals 通知 HistoryPage 更新顯示
    - 執行保留策略（apply_retention）

依賴：
    - desktop.database.HistoryDB（SQLite DAO）
    - desktop.interfaces.HistoryManagerSignals（Signal 契約）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject

from desktop.database.history_db import HistoryDB
from desktop.interfaces import ConversionJob, HistoryManagerSignals, HistoryRecord

logger = logging.getLogger(__name__)

_APP_VERSION = "v2.0"
_PAGE_SIZE_DEFAULT = 50


class HistoryManager(QObject):
    """歷史記錄管理器。

    使用方式（由 MainWindowV2 建立並注入）：
        manager = HistoryManager(parent=window)
        manager.signals.record_added.connect(history_page.on_record_added)

    Signals（透過 self.signals）：
        record_added(int)       新記錄寫入後，帶 id
        record_updated(int)     記錄狀態更新後，帶 id
        record_deleted(int)     單筆刪除後，帶 id
        records_changed()       批量變更（清除 / 匯入）
        error_occurred(str)     資料庫操作失敗，帶錯誤說明
    """

    def __init__(
        self,
        parent: Optional[QObject] = None,
        db: Optional[HistoryDB] = None,
        db_path: Optional[Path] = None,
    ):
        """初始化 HistoryManager。

        Args:
            parent:  Qt 父物件（通常是 MainWindowV2）。
            db:      注入的 HistoryDB 實例（測試用）；None 時自動建立。
            db_path: 資料庫路徑（None 時用預設路徑）；db 已指定時忽略。
        """
        super().__init__(parent)
        self.signals = HistoryManagerSignals()
        self._db = db or HistoryDB(db_path=db_path)
        self._app_version = _APP_VERSION
        logger.debug("HistoryManager 初始化完成")

    # =========================================================================
    # 核心寫入 API（由 ConversionController signal 觸發）
    # =========================================================================

    def record_completion(
        self,
        job: ConversionJob,
        output_path: Path,
        duration_ms: int = 0,
    ) -> int:
        """從 ConversionJob 建立 completion 記錄（status="done"）。

        Args:
            job:         已完成的 ConversionJob 物件。
            output_path: 輸出檔案路徑。
            duration_ms: 轉換耗時毫秒（0 表示未記錄）。

        Returns:
            新記錄的資料庫 id，失敗時回傳 -1。
        """
        try:
            source_size = self._get_file_size(job.source_path)
            now = datetime.now(timezone.utc).isoformat()
            record_id = self._db.add_record(
                job_uuid=job.job_id,
                created_at=now,
                completed_at=now,
                source_path=str(job.source_path),
                source_format=job.source_format,
                source_size_bytes=source_size,
                target_format=job.target_format,
                output_path=str(output_path),
                status="done",
                error_message=None,
                duration_ms=duration_ms,
                app_version=self._app_version,
                settings_snapshot=None,
            )
            self.signals.record_added.emit(record_id)
            logger.info(
                "record_completion: job=%s id=%d output=%s",
                job.job_id, record_id, output_path,
            )
            return record_id
        except Exception as exc:
            error_msg = f"記錄完成狀態失敗（job={job.job_id}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return -1

    def record_failure(
        self,
        job: ConversionJob,
        error_message: str,
        duration_ms: int = 0,
    ) -> int:
        """記錄轉換失敗（status="error"）。

        Args:
            job:           失敗的 ConversionJob 物件。
            error_message: 錯誤說明字串。
            duration_ms:   已耗費毫秒（0 表示未記錄）。

        Returns:
            新記錄的資料庫 id，失敗時回傳 -1。
        """
        try:
            source_size = self._get_file_size(job.source_path)
            now = datetime.now(timezone.utc).isoformat()
            record_id = self._db.add_record(
                job_uuid=job.job_id,
                created_at=now,
                completed_at=now,
                source_path=str(job.source_path),
                source_format=job.source_format,
                source_size_bytes=source_size,
                target_format=job.target_format,
                output_path=None,
                status="error",
                error_message=error_message,
                duration_ms=duration_ms,
                app_version=self._app_version,
                settings_snapshot=None,
            )
            self.signals.record_added.emit(record_id)
            logger.info(
                "record_failure: job=%s id=%d error=%s",
                job.job_id, record_id, error_message,
            )
            return record_id
        except Exception as exc:
            error_msg = f"記錄失敗狀態失敗（job={job.job_id}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return -1

    # =========================================================================
    # 舊 API 相容（Record job started / completed / failed / cancelled）
    # =========================================================================

    def record_job_started(
        self,
        job_uuid: str,
        source_path: str,
        source_format: str,
        source_size_bytes: int,
        target_format: str,
        app_version: str,
    ) -> int:
        """記錄任務開始（status="pending"）。

        Args:
            job_uuid:          任務 UUID。
            source_path:       來源檔案路徑字串。
            source_format:     來源格式代碼。
            source_size_bytes: 來源檔案大小（bytes）。
            target_format:     目標格式代碼。
            app_version:       應用版本字串。

        Returns:
            新記錄的資料庫 id，失敗時回傳 -1。
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            record_id = self._db.add_record(
                job_uuid=job_uuid,
                created_at=now,
                completed_at=None,
                source_path=source_path,
                source_format=source_format,
                source_size_bytes=source_size_bytes,
                target_format=target_format,
                output_path=None,
                status="pending",
                error_message=None,
                duration_ms=None,
                app_version=app_version,
                settings_snapshot=None,
            )
            self.signals.record_added.emit(record_id)
            return record_id
        except Exception as exc:
            error_msg = f"record_job_started 失敗（uuid={job_uuid}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return -1

    def record_job_completed(
        self,
        job_uuid: str,
        output_path: str,
        duration_ms: int,
    ) -> bool:
        """更新已存在任務為完成狀態（status="done"）。

        Args:
            job_uuid:    任務 UUID。
            output_path: 輸出路徑字串。
            duration_ms: 轉換耗時毫秒。

        Returns:
            True 表示成功更新，False 表示找不到或更新失敗。
        """
        try:
            record = self._find_by_uuid(job_uuid)
            if record is None:
                logger.warning("record_job_completed: uuid=%s 找不到記錄", job_uuid)
                return False
            now = datetime.now(timezone.utc).isoformat()
            updated = self._db.update_record(
                record.id,
                status="done",
                output_path=output_path,
                completed_at=now,
                duration_ms=duration_ms,
            )
            if updated:
                self.signals.record_updated.emit(record.id)
            return updated
        except Exception as exc:
            error_msg = f"record_job_completed 失敗（uuid={job_uuid}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return False

    def record_job_failed(self, job_uuid: str, error_message: str) -> bool:
        """更新已存在任務為失敗狀態（status="error"）。

        Args:
            job_uuid:      任務 UUID。
            error_message: 錯誤說明字串。

        Returns:
            True 表示成功更新，False 表示找不到或更新失敗。
        """
        try:
            record = self._find_by_uuid(job_uuid)
            if record is None:
                logger.warning("record_job_failed: uuid=%s 找不到記錄", job_uuid)
                return False
            now = datetime.now(timezone.utc).isoformat()
            updated = self._db.update_record(
                record.id,
                status="error",
                completed_at=now,
                error_message=error_message,
            )
            if updated:
                self.signals.record_updated.emit(record.id)
            return updated
        except Exception as exc:
            error_msg = f"record_job_failed 失敗（uuid={job_uuid}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return False

    def record_job_cancelled(self, job_uuid: str) -> bool:
        """更新已存在任務為取消狀態（status="cancelled"）。

        Args:
            job_uuid: 任務 UUID。

        Returns:
            True 表示成功更新，False 表示找不到或更新失敗。
        """
        try:
            record = self._find_by_uuid(job_uuid)
            if record is None:
                logger.warning("record_job_cancelled: uuid=%s 找不到記錄", job_uuid)
                return False
            now = datetime.now(timezone.utc).isoformat()
            updated = self._db.update_record(
                record.id,
                status="cancelled",
                completed_at=now,
            )
            if updated:
                self.signals.record_updated.emit(record.id)
            return updated
        except Exception as exc:
            error_msg = f"record_job_cancelled 失敗（uuid={job_uuid}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return False

    # =========================================================================
    # 查詢 API
    # =========================================================================

    def list_records(
        self,
        *,
        offset: int = 0,
        limit: int = _PAGE_SIZE_DEFAULT,
        status: Optional[str] = None,
        source_format: Optional[str] = None,
        target_format: Optional[str] = None,
        search_term: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[HistoryRecord]:
        """取得歷史記錄清單。

        Args:
            offset:        分頁偏移量。
            limit:         每頁筆數（預設 50）。
            status:        狀態篩選。
            source_format: 來源格式篩選。
            target_format: 目標格式篩選。
            search_term:   搜尋詞（對 source_path 做模糊匹配）。
            date_from:     起始日期 ISO-8601 字串。
            date_to:       結束日期 ISO-8601 字串。

        Returns:
            HistoryRecord list。
        """
        try:
            return self._db.list_records(
                offset=offset,
                limit=limit,
                status=status,
                source_format=source_format,
                target_format=target_format,
                search_term=search_term,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as exc:
            error_msg = f"list_records 查詢失敗：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return []

    # 舊 API 別名
    def get_records(self, **kwargs) -> list[HistoryRecord]:
        """list_records 的舊 API 別名。"""
        return self.list_records(**kwargs)

    def delete_record(self, record_id: int) -> bool:
        """刪除單筆記錄並通知 UI。

        Args:
            record_id: 記錄主鍵 id。

        Returns:
            True 表示成功刪除。
        """
        try:
            deleted = self._db.delete_record(record_id)
            if deleted:
                self.signals.record_deleted.emit(record_id)
            return deleted
        except Exception as exc:
            error_msg = f"delete_record 失敗（id={record_id}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return False

    def delete_records(self, ids: list[int]) -> int:
        """批量刪除記錄並通知 UI。

        只在 DB 確實刪除了記錄時才 emit records_changed；
        不對不存在的 id emit 假 signal，避免 UI 進行無效刷新。

        Args:
            ids: 要刪除的記錄 id 清單。

        Returns:
            實際刪除筆數。
        """
        if not ids:
            return 0
        try:
            deleted = self._db.delete_records(ids)
            if deleted > 0:
                self.signals.records_changed.emit()
            return deleted
        except Exception as exc:
            error_msg = f"delete_records 失敗（ids={ids}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return 0

    def clear_all(self) -> int:
        """清除全部歷史並通知 UI。

        Returns:
            刪除筆數。
        """
        try:
            count = self._db.clear_all()
            self.signals.records_changed.emit()
            return count
        except Exception as exc:
            error_msg = f"clear_all 失敗：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return 0

    # 舊 API 別名
    def clear_all_records(self) -> int:
        """clear_all 的舊 API 別名。"""
        return self.clear_all()

    def count(self, **filters) -> int:
        """取得符合條件的記錄總數。

        Args:
            **filters: 傳遞至 HistoryDB.count 的篩選參數。

        Returns:
            記錄筆數。
        """
        try:
            return self._db.count(**filters)
        except Exception as exc:
            error_msg = f"count 查詢失敗：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return 0

    # 舊 API 別名
    def get_count(self, **filters) -> int:
        """count 的舊 API 別名。"""
        return self.count(**filters)

    def export_csv(self, path: Path, **filters) -> int:
        """匯出歷史記錄至 CSV 並通知 UI。

        Args:
            path:     目標 CSV 路徑。
            **filters: 篩選參數。

        Returns:
            匯出筆數。
        """
        try:
            count = self._db.export_csv(path, **filters)
            logger.info("export_csv: %d 筆匯出至 %s", count, path)
            return count
        except Exception as exc:
            error_msg = f"匯出 CSV 失敗（path={path}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return 0

    def apply_retention_policy(
        self,
        max_records: int = 1000,
        max_age_days: Optional[int] = 90,
    ) -> int:
        """執行保留策略清理（90 天 / 1000 筆）。

        Args:
            max_records:  最大保留筆數。
            max_age_days: 最大保留天數（None 表示不限天數）。

        Returns:
            實際刪除筆數。
        """
        try:
            deleted = self._db.apply_retention(
                max_records=max_records,
                max_age_days=max_age_days,
            )
            if deleted > 0:
                self.signals.records_changed.emit()
                logger.info("apply_retention_policy: 清除 %d 筆過期記錄", deleted)
            return deleted
        except Exception as exc:
            error_msg = f"apply_retention_policy 失敗：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return 0

    def close(self) -> None:
        """釋放資料庫資源（MainWindowV2.closeEvent 呼叫）。"""
        self._db.close()

    # =========================================================================
    # 私有工具
    # =========================================================================

    def _find_by_uuid(self, job_uuid: str) -> Optional[HistoryRecord]:
        """依 job_uuid 查找最近一筆記錄（UUID 可能重複，取最新）。

        透過 HistoryDB.find_by_uuid() public API 查詢，不直接存取 DB 內部狀態。
        """
        try:
            return self._db.find_by_uuid(job_uuid)
        except Exception as exc:
            error_msg = f"_find_by_uuid 查詢失敗（uuid={job_uuid}）：{exc}"
            logger.error(error_msg, exc_info=True)
            self.signals.error_occurred.emit(error_msg)
            return None

    @staticmethod
    def _get_file_size(source_path) -> int:
        """安全取得檔案大小，找不到時回傳 0。"""
        try:
            from pathlib import Path as _Path
            return _Path(source_path).stat().st_size
        except OSError:
            return 0
