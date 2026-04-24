"""Job Manager — 並發控制與任務佇列管理。

Round 2 職責（controllers 代理）：
    - 維護 PENDING 任務佇列（FIFO）
    - 控制最大並行數（max_concurrent），防止超載
    - 在 Worker 完成後自動從佇列拉取下一個任務
    - 提供整體進度計算（供 ProgressWidget 使用）

設計原則：
    - JobManager 是純邏輯層（不直接與 Qt Signals 互動）
    - ConversionController 持有 JobManager，並透過 JobManager 決定何時啟動 Worker
    - JobManager 不直接 import converters.dispatcher

信任假設（Round 2 可依賴）：
    - interfaces.ConversionJob 的欄位不變
    - interfaces.JobStatus 枚舉值不變
"""
from __future__ import annotations

from collections import deque

from desktop.interfaces import ConversionJob, JobStatus


class JobManager:
    """並發任務佇列管理器（純邏輯，無 Qt 依賴）。

    使用範例（在 ConversionController 中）：
        mgr = JobManager(max_concurrent=2)
        mgr.enqueue(job)
        next_job = mgr.pop_next()   # 若並行數未滿，回傳下一個 Job
        mgr.mark_started(job_id)
        mgr.mark_completed(job_id)
        progress = mgr.overall_progress  # 0.0 – 1.0
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._max_concurrent = max_concurrent
        self._queue: deque[ConversionJob] = deque()
        self._active: dict[str, ConversionJob] = {}     # job_id → Job（進行中）
        self._completed: dict[str, ConversionJob] = {}  # job_id → Job（已完成/失敗）

    # ------------------------------------------------------------------
    # 佇列操作
    # ------------------------------------------------------------------

    def enqueue(self, job: ConversionJob) -> None:
        """將新 Job 加入等待佇列（FIFO）。

        Args:
            job: 狀態應為 IDLE 的新 ConversionJob。
        """
        self._queue.append(job)

    def can_start_next(self) -> bool:
        """判斷是否可以啟動下一個 Job（並行數未滿且佇列非空）。"""
        return len(self._active) < self._max_concurrent and len(self._queue) > 0

    def pop_next(self) -> ConversionJob | None:
        """從佇列取出下一個 Job 並移入 active（若條件滿足）。

        Returns:
            待啟動的 ConversionJob；若無法啟動則回傳 None。
        """
        if not self.can_start_next():
            return None
        job = self._queue.popleft()
        self._active[job.job_id] = job
        return job

    def mark_started(self, job_id: str) -> None:
        """標記 Job 為 CONVERTING 狀態。

        Args:
            job_id: 任務 ID（必須已在 active 中）。
        """
        if job_id in self._active:
            self._active[job_id].status = JobStatus.CONVERTING

    def mark_completed(self, job_id: str, output_path=None) -> None:
        """標記 Job 為 DONE 並移出 active。

        Args:
            job_id: 任務 ID。
            output_path: 成功時的輸出路徑（Path 物件）。
        """
        if job_id in self._active:
            job = self._active.pop(job_id)
            job.status = JobStatus.DONE
            job.progress = 1.0
            if output_path is not None:
                job.output_path = output_path
            self._completed[job_id] = job

    def mark_failed(self, job_id: str, error_message: str) -> None:
        """標記 Job 為 ERROR 並移出 active。

        Args:
            job_id: 任務 ID。
            error_message: 錯誤描述字串。
        """
        if job_id in self._active:
            job = self._active.pop(job_id)
            job.status = JobStatus.ERROR
            job.error_message = error_message
            self._completed[job_id] = job

    def update_progress(self, job_id: str, progress: float) -> None:
        """更新進行中 Job 的進度。

        Args:
            job_id: 任務 ID。
            progress: 進度值（0.0–1.0）。
        """
        if job_id in self._active:
            self._active[job_id].progress = max(0.0, min(1.0, progress))

    def remove_pending(self, job_id: str) -> bool:
        """從等待佇列移除指定 Job（若已進入 active 則無法移除）。

        Args:
            job_id: 要移除的任務 ID。

        Returns:
            True 若成功移除；False 若 Job 不在佇列中。
        """
        for i, job in enumerate(self._queue):
            if job.job_id == job_id:
                del self._queue[i]
                return True
        return False

    # ------------------------------------------------------------------
    # 狀態查詢
    # ------------------------------------------------------------------

    @property
    def overall_progress(self) -> float:
        """計算所有已知 Job 的加權平均進度（0.0–1.0）。"""
        all_jobs = list(self._queue) + list(self._active.values()) + list(self._completed.values())
        if not all_jobs:
            return 0.0
        return sum(j.progress for j in all_jobs) / len(all_jobs)

    @property
    def completed_count(self) -> int:
        """已完成（DONE 或 ERROR）的任務數。"""
        return len(self._completed)

    @property
    def total_count(self) -> int:
        """全部任務總數。"""
        return len(self._queue) + len(self._active) + len(self._completed)

    @property
    def is_all_done(self) -> bool:
        """是否所有任務均已完成（佇列空 + 無進行中）。"""
        return len(self._queue) == 0 and len(self._active) == 0

    @property
    def max_concurrent(self) -> int:
        """最大並行任務數。"""
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        """設定最大並行任務數（1–8）。"""
        self._max_concurrent = max(1, min(8, value))
