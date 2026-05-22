"""轉換控制器 — 橋接 UI 事件到 converters.dispatcher。

Round 2 職責（controllers 代理）：
    - 接收 DropZone.signals.files_dropped → 建立 ConversionJob → 發出 job_added
    - 使用 QThreadPool 呼叫 converters.dispatcher.convert_file（非同步）
    - 追蹤所有 Job 狀態，發出 job_progress / job_status_changed / job_completed / job_failed
    - 支援取消（Cancel）：標記 Job 為 ERROR 並停止對應 Worker
    - 設定 concurrent 上限（從 SettingsDialog.settings_applied 接收）
    - 全部完成後發出 all_completed Signal

重要：converters.dispatcher.convert_file 的實際簽名：
    convert_file(input_path, output_path, source_format, target_format) -> None
    （不回傳路徑；呼叫端需自行計算 output_path；dispatcher 圖片格式 key 為 "image"）

注意：desktop/utils/__init__.py 在其他代理完成前可能有 ImportError（get_system_theme）。
本模組使用延遲 import（函式內部）來隔離此依賴，確保 controller 可獨立 import。
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QThreadPool,
    Slot,
)

from desktop.interfaces import (
    ConversionControllerSignals,
    ConversionJob,
    JobStatus,
    get_supported_targets,
)
from desktop.controllers.job_manager import JobManager

logger = logging.getLogger(__name__)

# 副檔名 → dispatcher 格式 key 映射（圖片統一對應 "image"）
_IMAGE_EXTS: frozenset[str] = frozenset(
    {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}
)


# ---------------------------------------------------------------------------
# paths 工具（內聯 fallback，避免在 utils/__init__.py 有 import 問題時阻塞）
# ---------------------------------------------------------------------------

def _get_default_output_dir() -> Path:
    """取得預設輸出目錄，優先使用 desktop.utils.paths；失敗時退回內聯實作。"""
    try:
        import importlib.util as _ilu
        import sys as _sys
        _mod_name = "desktop.utils.paths"
        if _mod_name in _sys.modules:
            return _sys.modules[_mod_name].get_default_output_dir()
        # 直接從 .py 檔案載入，完全繞開 __init__.py
        _here = Path(__file__).parent.parent  # desktop/
        _spec = _ilu.spec_from_file_location(_mod_name, _here / "utils" / "paths.py")
        if _spec and _spec.loader:
            _mod = _ilu.module_from_spec(_spec)
            _sys.modules[_mod_name] = _mod
            _spec.loader.exec_module(_mod)
            return _mod.get_default_output_dir()
    except Exception as exc:
        logger.debug("paths 模組載入失敗，使用 fallback：%s", exc)

    # Fallback：自行計算輸出目錄
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".config"
    output_dir = base / "DocConverter" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_output_path(
    source_path: Path,
    target_format: str,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """計算輸出路徑，優先使用 desktop.utils.paths；失敗時退回內聯實作。"""
    try:
        import sys as _sys
        _mod_name = "desktop.utils.paths"
        if _mod_name in _sys.modules:
            return _sys.modules[_mod_name].resolve_output_path(
                source_path, target_format, output_dir, overwrite
            )
    except Exception as exc:
        logger.debug("paths.resolve_output_path 呼叫失敗，使用 fallback：%s", exc)

    # Fallback：簡單計算輸出路徑（不做序號防衝突）
    stem = source_path.stem
    candidate = output_dir / f"{stem}.{target_format}"
    if overwrite or not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = output_dir / f"{stem}_{counter}.{target_format}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# 格式工具函式
# ---------------------------------------------------------------------------

def _to_dispatcher_format(ext: str) -> str:
    """將副檔名（小寫無點）轉換為 dispatcher 使用的格式 key。

    dispatcher 的圖片來源統一使用 "image" 而非個別副檔名。

    Args:
        ext: 副檔名，小寫無點，例如 "png" / "docx"。

    Returns:
        dispatcher 格式 key，例如 "image" / "docx"。
    """
    return "image" if ext in _IMAGE_EXTS else ext


def _get_ui_targets(source_ext: str) -> list[str]:
    """取得指定來源格式可轉換的目標格式清單（UI 層使用）。

    優先透過 dispatcher 的支援矩陣查詢；
    圖片格式退回靜態清單；未知格式退回 interfaces._FORMAT_MATRIX。

    Args:
        source_ext: 來源副檔名，小寫無點。

    Returns:
        目標格式清單（小寫無點），順序決定 UI 預設選項。
    """
    try:
        from converters.dispatcher import get_supported_matrix
        matrix = get_supported_matrix()
        dispatcher_key = _to_dispatcher_format(source_ext)
        if dispatcher_key in matrix:
            return list(matrix[dispatcher_key].keys())
    except Exception as exc:
        logger.debug("get_supported_matrix 失敗，退回靜態清單：%s", exc)

    return get_supported_targets(source_ext)


# ---------------------------------------------------------------------------
# Worker（QRunnable）
# ---------------------------------------------------------------------------

class _ConversionWorker(QRunnable):
    """在 QThreadPool 中執行單一轉換任務的 Worker。

    設計原則：
    - 使用內嵌 _Signals（QObject 子類）傳遞結果回主執行緒
    - 捕捉所有已知例外，失敗路徑一律以 failed signal 回傳而非 raise
    - cancelled 旗標為軟性取消：Worker 在轉換開始前檢查；
      一旦 convert_file 進入執行，無法強制中斷（依賴 dispatcher 完成或拋出例外）
    """

    class _Signals(QObject):
        """Worker 內部 Signal 容器（必須是 QObject 子類才能發出 Signal）。"""
        from PySide6.QtCore import Signal
        progress = Signal(str, float)    # job_id, 0.0–1.0
        completed = Signal(str, object)  # job_id, output_path (Path)
        failed = Signal(str, str)        # job_id, error_message

    def __init__(
        self,
        job: ConversionJob,
        output_path: Path,
        settings: dict,
    ) -> None:
        super().__init__()
        self._job = job
        self._output_path = output_path
        self._settings = settings
        self.signals = _ConversionWorker._Signals()
        self._cancelled = False

    def cancel(self) -> None:
        """設定取消旗標（軟性取消，僅在轉換開始前生效）。"""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        """執行轉換任務。所有例外均被捕捉並以 failed signal 回傳。"""
        job_id = self._job.job_id

        if self._cancelled:
            self.signals.failed.emit(job_id, "任務已取消")
            return

        self.signals.progress.emit(job_id, 0.05)

        try:
            from converters.dispatcher import convert_file
            from converters.exceptions import (
                ConversionError,
                ConversionTimeoutError,
                UnsupportedFormatError,
            )

            self.signals.progress.emit(job_id, 0.15)

            # 確保輸出目錄存在
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

            dispatcher_source = _to_dispatcher_format(self._job.source_format)

            convert_file(
                input_path=self._job.source_path,
                output_path=self._output_path,
                source_format=dispatcher_source,
                target_format=self._job.target_format,
            )

            self.signals.progress.emit(job_id, 1.0)
            self.signals.completed.emit(job_id, self._output_path)

        except UnsupportedFormatError as exc:
            logger.warning(
                "不支援的格式對 [job=%s]: %s → %s | %s",
                job_id,
                self._job.source_format,
                self._job.target_format,
                exc,
            )
            self.signals.failed.emit(job_id, f"不支援此格式轉換：{exc}")

        except ConversionTimeoutError as exc:
            logger.error("轉換超時 [job=%s]: %s", job_id, exc)
            self.signals.failed.emit(job_id, f"轉換超時：{exc}")

        except ConversionError as exc:
            logger.error("轉換失敗 [job=%s]: %s", job_id, exc)
            self.signals.failed.emit(job_id, f"轉換失敗：{exc}")

        except Exception as exc:
            logger.exception("未預期錯誤 [job=%s]: %r", job_id, exc)
            self.signals.failed.emit(job_id, f"未預期錯誤：{exc!r}")


# ---------------------------------------------------------------------------
# ConversionController
# ---------------------------------------------------------------------------

class ConversionController(QObject):
    """管理 ConversionJob 生命週期 + 非同步調用 converters.dispatcher。

    使用範例（Round 3 整合）：
        controller = ConversionController()
        drop_zone.signals.files_dropped.connect(controller.add_files)
        controller.signals.job_added.connect(file_list_widget.add_card)
        controller.signals.job_completed.connect(lambda jid, path: ...)

    converters.dispatcher.convert_file 的實際簽名：
        convert_file(input_path, output_path, source_format, target_format) -> None
    ConversionController 負責計算 output_path（透過 _resolve_output_path）。

    Args:
        parent: 父 QObject（通常為 MainWindow）。
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.signals = ConversionControllerSignals()
        self._jobs: dict[str, ConversionJob] = {}
        self._workers: dict[str, _ConversionWorker] = {}  # job_id → Worker（進行中）

        self._threadpool = QThreadPool.globalInstance()

        # 從 QSettings 載入持久化設定（_get_default_output_dir 帶 fallback）
        qt_settings = QSettings("DocConverter", "DocConverter")
        self._settings: dict = {
            "output_dir": qt_settings.value(
                "output_dir",
                str(_get_default_output_dir()),
            ),
            "overwrite": qt_settings.value("overwrite", False, type=bool),
            "concurrent": qt_settings.value("concurrent", 3, type=int),
            "theme": qt_settings.value("theme", "system"),
        }

        self._job_manager = JobManager(
            max_concurrent=self._settings["concurrent"]
        )
        self._threadpool.setMaxThreadCount(self._settings["concurrent"])

        logger.debug(
            "ConversionController 初始化完成 | output_dir=%s | concurrent=%d",
            self._settings["output_dir"],
            self._settings["concurrent"],
        )

    # ------------------------------------------------------------------
    # 公開 Slot / 方法（Round 3 連接至 UI 事件）
    # ------------------------------------------------------------------

    @Slot(list)
    def add_files(
        self,
        file_paths: list[Path],
        target_format: str | None = None,
    ) -> None:
        """處理 DropZone 送入的檔案清單，建立並排隊 ConversionJob。

        每個有效檔案建立一個 ConversionJob，並以 PENDING 狀態發出 job_added Signal。
        若來源格式不支援任何輸出格式，跳過該檔案並 log。

        Args:
            file_paths: 使用者拖入或選擇的檔案路徑清單（list[Path]）。
            target_format: 可選的目標格式覆寫（小寫無點）。若提供且該來源格式支援
                此目標,則所有檔案的 target_format 統一設為此值;否則退回 targets[0]。
                主要由「歷史 → 一鍵再轉」流程使用。
        """
        for raw_path in file_paths:
            file_path = Path(raw_path) if not isinstance(raw_path, Path) else raw_path

            source_ext = file_path.suffix.lstrip(".").lower()
            if not source_ext:
                logger.warning("無法識別副檔名，跳過：%s", file_path)
                continue

            targets = _get_ui_targets(source_ext)
            if not targets:
                logger.warning(
                    "格式 '%s' 無支援的轉換目標，跳過：%s",
                    source_ext,
                    file_path,
                )
                continue

            # 決定最終 target_format:優先使用覆寫值,否則用 targets[0]
            preferred = target_format.lower() if target_format else None
            if preferred and preferred in targets:
                chosen_target = preferred
            else:
                chosen_target = targets[0]
                if preferred:
                    logger.debug(
                        "add_files: 目標格式覆寫 '%s' 不在支援清單 %s,退回 %s",
                        preferred, targets, chosen_target,
                    )

            job_id = uuid.uuid4().hex[:8]
            job = ConversionJob(
                job_id=job_id,
                source_path=file_path,
                source_format=source_ext,
                target_format=chosen_target,
                status=JobStatus.PENDING,
            )

            self._jobs[job_id] = job
            self._job_manager.enqueue(job)

            logger.debug("Job 建立 [job=%s]: %s → %s", job_id, source_ext, chosen_target)

            self.signals.job_added.emit(job)
            self.signals.job_status_changed.emit(job_id, JobStatus.PENDING.value)

    @Slot(str, str)
    def set_target_format(self, job_id: str, target_format: str) -> None:
        """更新指定 Job 的目標格式（來自 FileCard.target_format_changed）。

        只允許更新 IDLE / PENDING 狀態的 Job（CONVERTING / DONE / ERROR 不可更改）。

        Args:
            job_id: 任務 ID。
            target_format: 新的目標格式，小寫無點。
        """
        job = self._jobs.get(job_id)
        if job is None:
            logger.warning("set_target_format: 找不到 job_id=%s", job_id)
            return

        if job.status not in (JobStatus.IDLE, JobStatus.PENDING):
            logger.debug(
                "set_target_format: job=%s 狀態 %s 不允許更改格式",
                job_id,
                job.status.value,
            )
            return

        job.target_format = target_format
        logger.debug("set_target_format: job=%s → %s", job_id, target_format)

    @Slot(str)
    def remove_job(self, job_id: str) -> None:
        """從佇列移除指定 Job（FileCard.remove_requested 連接至此）。

        若 Job 在 PENDING 狀態，從 JobManager 佇列移除；
        若在 CONVERTING 狀態，先設定 Worker 取消旗標再移除；
        DONE / ERROR 直接從 _jobs 清除。

        Args:
            job_id: 要移除的任務 ID。
        """
        if job_id not in self._jobs:
            return

        job = self._jobs[job_id]

        if job.status == JobStatus.PENDING:
            self._job_manager.remove_pending(job_id)
        elif job.status == JobStatus.CONVERTING:
            self._soft_cancel_worker(job_id)

        del self._jobs[job_id]
        logger.debug("remove_job: job=%s 已移除", job_id)

    @Slot()
    def start_all(self) -> None:
        """開始轉換佇列中所有 PENDING 狀態的 Job（F5 觸發）。

        透過 JobManager 控制並行數，依序啟動 Worker 直到達到並行上限。
        """
        self._dispatch_pending_jobs()

    def start_conversion(self) -> None:
        """start_all 的別名，保持與骨架的相容性。"""
        self.start_all()

    @Slot(str)
    def cancel_job(self, job_id: str) -> None:
        """取消指定 Job（ProgressWidget.cancel_requested 或 FileCard 取消按鈕）。

        若 Job 在 PENDING 狀態，從 JobManager 佇列移除並標記 ERROR；
        若在 CONVERTING 狀態，設定 Worker 取消旗標（軟性取消）並標記 ERROR。

        Args:
            job_id: 要取消的任務 ID。
        """
        job = self._jobs.get(job_id)
        if job is None:
            return

        if job.status in (JobStatus.DONE, JobStatus.ERROR):
            return

        if job.status == JobStatus.PENDING:
            self._job_manager.remove_pending(job_id)

        self._soft_cancel_worker(job_id)

        job.status = JobStatus.ERROR
        job.error_message = "使用者取消"

        self.signals.job_status_changed.emit(job_id, JobStatus.ERROR.value)
        self.signals.job_failed.emit(job_id, "使用者取消")

        logger.info("cancel_job: job=%s 已取消", job_id)
        self._check_all_completed()

    @Slot()
    def cancel_all(self) -> None:
        """取消所有尚未完成的 Job（ProgressWidget 全部取消按鈕）。"""
        active_ids = [
            jid
            for jid, job in self._jobs.items()
            if job.status in (JobStatus.PENDING, JobStatus.CONVERTING)
        ]
        for job_id in active_ids:
            self.cancel_job(job_id)

    @Slot(dict)
    def update_settings(self, settings: dict) -> None:
        """套用來自 SettingsDialog 的設定並持久化至 QSettings。

        Args:
            settings: 設定 dict，結構：
                {
                    "output_dir": str,
                    "overwrite": bool,
                    "concurrent": int,
                    "theme": str,
                }
        """
        self._settings.update(settings)

        concurrent = max(1, min(8, int(settings.get("concurrent", self._settings["concurrent"]))))
        self._job_manager.max_concurrent = concurrent
        self._threadpool.setMaxThreadCount(concurrent)

        qt_settings = QSettings("DocConverter", "DocConverter")
        qt_settings.setValue("output_dir", self._settings.get("output_dir", ""))
        qt_settings.setValue("overwrite", bool(self._settings.get("overwrite", False)))
        qt_settings.setValue("concurrent", concurrent)
        qt_settings.setValue("theme", self._settings.get("theme", "system"))
        qt_settings.sync()

        logger.debug(
            "update_settings: output_dir=%s overwrite=%s concurrent=%d theme=%s",
            self._settings.get("output_dir"),
            self._settings.get("overwrite"),
            concurrent,
            self._settings.get("theme"),
        )

    def apply_settings(self, settings: dict) -> None:
        """update_settings 的別名，保持與骨架的相容性。

        Args:
            settings: 設定 dict（格式同 update_settings）。
        """
        self.update_settings(settings)

    def get_job(self, job_id: str) -> ConversionJob | None:
        """取得指定 Job 的當前快照。

        Args:
            job_id: 任務 ID。

        Returns:
            ConversionJob 或 None（若不存在）。
        """
        return self._jobs.get(job_id)

    @property
    def all_jobs(self) -> list[ConversionJob]:
        """回傳所有 Job 的清單（快照，非引用）。"""
        return list(self._jobs.values())

    # ------------------------------------------------------------------
    # 內部方法
    # ------------------------------------------------------------------

    def _dispatch_pending_jobs(self) -> None:
        """從 JobManager 佇列取出 Job 並啟動 Worker（持續直到並行數滿）。"""
        while self._job_manager.can_start_next():
            job = self._job_manager.pop_next()
            if job is None:
                break
            self._start_worker(job)

    def _start_worker(self, job: ConversionJob) -> None:
        """為指定 Job 建立並提交 _ConversionWorker 至 QThreadPool。

        Args:
            job: 待執行的 ConversionJob（應已從 JobManager.pop_next() 取出）。
        """
        output_dir_str = self._settings.get("output_dir", "")
        output_dir = Path(output_dir_str) if output_dir_str else _get_default_output_dir()
        overwrite = bool(self._settings.get("overwrite", False))

        output_path = _resolve_output_path(
            source_path=job.source_path,
            target_format=job.target_format,
            output_dir=output_dir,
            overwrite=overwrite,
        )

        worker = _ConversionWorker(
            job=job,
            output_path=output_path,
            settings=self._settings,
        )
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.completed.connect(self._on_worker_completed)
        worker.signals.failed.connect(self._on_worker_failed)

        self._workers[job.job_id] = worker

        self._job_manager.mark_started(job.job_id)
        job.status = JobStatus.CONVERTING

        self.signals.job_status_changed.emit(job.job_id, JobStatus.CONVERTING.value)
        self.signals.job_progress.emit(job.job_id, 0.0)

        self._threadpool.start(worker)

        logger.info(
            "Worker 啟動 [job=%s]: %s → %s | output=%s",
            job.job_id,
            job.source_format,
            job.target_format,
            output_path,
        )

    def _soft_cancel_worker(self, job_id: str) -> None:
        """設定對應 Worker 的取消旗標（如果存在）。

        Args:
            job_id: 目標 Worker 的任務 ID。
        """
        worker = self._workers.get(job_id)
        if worker is not None:
            worker.cancel()

    def _check_all_completed(self) -> None:
        """檢查是否所有 Job 均已達到終態，若是則發出 all_completed Signal。"""
        if not self._jobs:
            return
        all_done = all(
            job.status in (JobStatus.DONE, JobStatus.ERROR)
            for job in self._jobs.values()
        )
        if all_done:
            logger.info("all_completed: 所有 %d 個 Job 已完成", len(self._jobs))
            self.signals.all_completed.emit()

    # ------------------------------------------------------------------
    # Worker Signal 回調
    # ------------------------------------------------------------------

    @Slot(str, float)
    def _on_worker_progress(self, job_id: str, progress: float) -> None:
        """Worker 進度更新回調。

        Args:
            job_id: 任務 ID。
            progress: 進度值 0.0–1.0。
        """
        job = self._jobs.get(job_id)
        if job is None:
            return

        self._job_manager.update_progress(job_id, progress)
        job.progress = progress
        self.signals.job_progress.emit(job_id, progress)

    @Slot(str, object)
    def _on_worker_completed(self, job_id: str, output_path: object) -> None:
        """Worker 成功完成回調。

        Args:
            job_id: 任務 ID。
            output_path: 輸出路徑（Path 物件或可轉 Path 的值）。
        """
        output = Path(output_path) if not isinstance(output_path, Path) else output_path

        job = self._jobs.get(job_id)
        if job is not None:
            job.output_path = output
            job.progress = 1.0
            job.status = JobStatus.DONE

        self._job_manager.mark_completed(job_id, output)
        self._workers.pop(job_id, None)

        self.signals.job_progress.emit(job_id, 1.0)
        self.signals.job_status_changed.emit(job_id, JobStatus.DONE.value)
        self.signals.job_completed.emit(job_id, output)

        logger.info("Job 完成 [job=%s]: 輸出 %s", job_id, output)

        # 嘗試啟動下一個等待中的 Job
        self._dispatch_pending_jobs()
        self._check_all_completed()

    @Slot(str, str)
    def _on_worker_failed(self, job_id: str, error_message: str) -> None:
        """Worker 失敗回調。

        Args:
            job_id: 任務 ID。
            error_message: 錯誤描述字串。
        """
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.ERROR
            job.error_message = error_message

        self._job_manager.mark_failed(job_id, error_message)
        self._workers.pop(job_id, None)

        self.signals.job_status_changed.emit(job_id, JobStatus.ERROR.value)
        self.signals.job_failed.emit(job_id, error_message)

        logger.warning("Job 失敗 [job=%s]: %s", job_id, error_message)

        # 嘗試啟動下一個等待中的 Job
        self._dispatch_pending_jobs()
        self._check_all_completed()
