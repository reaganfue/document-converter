"""
desktop/pages/image_tools_page.py — 圖片工具頁面

提供 4 個 Tab：單張去背 / 批次去背 / 背景替換 / 後製濾鏡。
每個 Tab 各自持有 UI 元件，共用頁面底部的進度條與 InfoBar 通知。

商用級 UX：
    - 拖入即用（單張直接去背，批次加入清單）
    - 並列雙圖預覽（原圖 + 處理結果，透明區顯示棋盤格）
    - 即時參數 debounce 300ms re-process
    - IndeterminateProgressBar（單張）/ QProgressBar（批次）
    - 空態 SVG icon + 引導文字
    - InfoBar 錯誤 / 成功提示
    - QSettings 記憶上次設定
    - Ctrl+O / Ctrl+S / Esc 快捷鍵
    - Nordic palette 動態取色 + theme_bus 訂閱

依賴注入（由 MainWindowV2 呼叫）：
    set_controller(image_tools_controller)  — ImageToolsController 實例
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QMimeData,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import (
        CheckBox,
        ComboBox,
        FluentIcon,
        IndeterminateProgressBar,
        InfoBar,
        InfoBarPosition,
        PrimaryPushButton,
        PushButton,
        RadioButton,
        SubtitleLabel,
        CaptionLabel,
        BodyLabel,
    )
    _HAS_FLUENT = True
except ImportError:
    from PySide6.QtWidgets import (  # type: ignore[assignment]
        QCheckBox as CheckBox,
        QComboBox as ComboBox,
        QLabel as SubtitleLabel,
        QLabel as CaptionLabel,
        QLabel as BodyLabel,
        QProgressBar as IndeterminateProgressBar,
        QPushButton as PrimaryPushButton,
        QPushButton as PushButton,
        QRadioButton as RadioButton,
    )
    InfoBar = None  # type: ignore[assignment]
    InfoBarPosition = None  # type: ignore[assignment]
    FluentIcon = None  # type: ignore[assignment]
    _HAS_FLUENT = False

try:
    from PySide6.QtSvgWidgets import QSvgWidget
    _HAS_SVG = True
except ImportError:
    _HAS_SVG = False

from PySide6.QtGui import QKeySequence

from desktop.interfaces import PageID
from desktop.pages.base_page import BasePage
from desktop.utils.theme import FONT_FAMILY, get_palette, theme_bus
from desktop.widgets.drop_zone import DropZone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 支援的圖片格式
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
})

_IMAGE_FILTER = "圖片 (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif)"


# ---------------------------------------------------------------------------
# 主頁面
# ---------------------------------------------------------------------------

class ImageToolsPage(BasePage):
    """圖片工具頁面 — 單張去背 / 批次去背 / 背景替換 / 後製濾鏡。"""

    PAGE_ID = PageID.IMAGE_TOOLS
    PAGE_TITLE = "圖片工具"
    PAGE_ICON = getattr(FluentIcon, "PHOTO", None) if _HAS_FLUENT else None

    def _setup_ui(self) -> None:
        """建立頁面 UI：標題 + 四 Tab + 底部進度區。"""
        # 頁面標題
        title_label = SubtitleLabel("圖片工具") if _HAS_FLUENT else QLabel("圖片工具")
        self._content_layout.addWidget(title_label)

        # Tab 容器
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._content_layout.addWidget(self._tab_widget, stretch=1)

        # 建立四個 Tab
        self._single_tab = _SingleRemoveTab(self)
        self._batch_tab = _BatchTab(self)
        self._replace_tab = _ReplaceBgTab(self)
        self._filter_tab = _FilterTab(self)

        self._tab_widget.addTab(self._single_tab, "單張去背")
        self._tab_widget.addTab(self._batch_tab, "批次去背")
        self._tab_widget.addTab(self._replace_tab, "背景替換")
        self._tab_widget.addTab(self._filter_tab, "後製濾鏡")

        # 底部進度區（單檔 indeterminate + 批次 determinate）
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)

        self._batch_progress_label = QLabel("0 / 0")
        self._batch_progress_label.setVisible(False)
        progress_row.addWidget(self._batch_progress_label)

        self._batch_progress_bar = QProgressBar()
        self._batch_progress_bar.setRange(0, 100)
        self._batch_progress_bar.setValue(0)
        self._batch_progress_bar.setFixedHeight(6)
        self._batch_progress_bar.setTextVisible(False)
        self._batch_progress_bar.setVisible(False)

        self._indet_progress_bar = _make_indeterminate_bar()
        self._indet_progress_bar.setVisible(False)

        progress_row.addWidget(self._batch_progress_bar, stretch=1)
        progress_row.addWidget(self._indet_progress_bar, stretch=1)
        self._content_layout.addLayout(progress_row)

        # 快捷鍵
        self._setup_shortcuts()

        # QSettings 載入
        self._load_persisted_settings()

        # 動態主題訂閱
        theme_bus.theme_changed.connect(self._refresh_palette)
        self._refresh_palette()

    def set_controller(self, controller) -> None:
        """注入 ImageToolsController，連接 6 個 Signals。

        Args:
            controller: ImageToolsController 實例。
        """
        super().set_controller(controller)
        if controller is None:
            return

        sig = controller.signals
        sig.operation_started.connect(self._on_operation_started)
        sig.operation_progress.connect(self._on_operation_progress)
        sig.item_status.connect(self._on_item_status)
        sig.item_completed.connect(self._on_item_completed)
        sig.operation_completed.connect(self._on_operation_completed)
        sig.operation_failed.connect(self._on_operation_failed)

        # 把 controller 傳給各 Tab
        for tab in (self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab):
            tab.set_controller(controller)

    def on_enter(self) -> None:
        """頁面成為活動頁時呼叫。"""
        super().on_enter()

    def on_leave(self) -> None:
        """離開頁面時呼叫，取消當前批次任務。"""
        super().on_leave()
        if self._controller is not None:
            self._controller.cancel()

    def on_close(self) -> None:
        """應用程式關閉前呼叫，寫回 QSettings。"""
        self._persist_settings()

    # -------------------------------------------------------------------------
    # Signal 處理
    # -------------------------------------------------------------------------

    def _on_operation_started(self, operation_name: str) -> None:
        """操作開始：顯示適當進度條，鎖定所有 Tab 主按鈕。"""
        is_batch = operation_name == "batch"
        self._batch_progress_bar.setVisible(is_batch)
        self._batch_progress_label.setVisible(is_batch)
        self._indet_progress_bar.setVisible(not is_batch)
        if is_batch:
            self._batch_progress_bar.setValue(0)
        for tab in (self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab):
            tab.set_running(True)

    def _on_operation_progress(self, value: float) -> None:
        """更新進度條（0.0–1.0）。"""
        if self._batch_progress_bar.isVisible():
            self._batch_progress_bar.setValue(int(value * 100))
        self._single_tab.set_progress(value)

    def _on_item_status(self, idx: int, status: str) -> None:
        """批次單檔狀態更新，委派給批次 Tab。"""
        self._batch_tab.on_item_status(idx, status)

    def _on_item_completed(self, idx: int, result: object) -> None:
        """批次單檔完成，委派給批次 Tab 更新計數。"""
        self._batch_tab.on_item_completed(idx, result)
        completed = self._batch_tab.completed_count()
        total = self._batch_tab.total_count()
        if total > 0:
            self._batch_progress_label.setText(f"{completed} / {total}")

    def _on_operation_completed(self, operation_name: str, result: object) -> None:
        """操作完成：隱藏進度條，顯示成功通知，通知各 Tab。"""
        self._batch_progress_bar.setVisible(False)
        self._batch_progress_label.setVisible(False)
        self._indet_progress_bar.setVisible(False)
        for tab in (self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab):
            tab.set_running(False)

        if operation_name == "remove_single":
            self._single_tab.on_processing_done(result)
        elif operation_name == "batch":
            self._batch_tab.on_batch_done(result)
            content = _build_batch_summary(result)
            _show_info_bar(self, "success", "批次完成", content)
        elif operation_name == "replace_bg":
            self._replace_tab.on_processing_done(result)
            _show_info_bar(self, "success", "完成", "背景替換完成。")
        elif operation_name == "filter":
            self._filter_tab.on_processing_done(result)
            _show_info_bar(self, "success", "完成", "後製濾鏡套用完成。")
        logger.info("image_tools 操作完成: %s", operation_name)

    def _on_operation_failed(self, operation_name: str, error_message: str) -> None:
        """操作失敗：隱藏進度條，顯示錯誤通知。"""
        self._batch_progress_bar.setVisible(False)
        self._batch_progress_label.setVisible(False)
        self._indet_progress_bar.setVisible(False)
        for tab in (self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab):
            tab.set_running(False)

        if error_message != "已取消":
            _show_info_bar(self, "error", "操作失敗", error_message)
        logger.warning("image_tools 操作失敗: %s — %s", operation_name, error_message)

    # -------------------------------------------------------------------------
    # 快捷鍵
    # -------------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        """安裝 page-scope 快捷鍵（Ctrl+O / Ctrl+S / Esc）。"""
        open_sc = QShortcut(QKeySequence.StandardKey.Open, self)
        open_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        open_sc.activated.connect(self._on_shortcut_open)

        save_sc = QShortcut(QKeySequence.StandardKey.Save, self)
        save_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save_sc.activated.connect(self._on_shortcut_save)

        esc_sc = QShortcut(QKeySequence("Esc"), self)
        esc_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc_sc.activated.connect(self._on_shortcut_cancel)

    def _on_shortcut_open(self) -> None:
        """Ctrl+O：依當前 Tab 呼叫開啟動作。"""
        idx = self._tab_widget.currentIndex()
        tabs = [self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab]
        if 0 <= idx < len(tabs):
            tabs[idx].on_open_shortcut()

    def _on_shortcut_save(self) -> None:
        """Ctrl+S：依當前 Tab 呼叫匯出動作。"""
        idx = self._tab_widget.currentIndex()
        tabs = [self._single_tab, self._batch_tab, self._replace_tab, self._filter_tab]
        if 0 <= idx < len(tabs):
            tabs[idx].on_save_shortcut()

    def _on_shortcut_cancel(self) -> None:
        """Esc：取消當前操作。"""
        if self._controller is not None:
            self._controller.cancel()

    # -------------------------------------------------------------------------
    # QSettings
    # -------------------------------------------------------------------------

    def _load_persisted_settings(self) -> None:
        """從 QSettings 載入上次設定，分發給各 Tab。"""
        settings = QSettings("DocConverter", "DocConverter")
        last_model = settings.value("image_tools/last_model", "u2net")
        alpha_matting = settings.value("image_tools/alpha_matting", False, type=bool)
        sharpen = settings.value("image_tools/sharpen", 0, type=int)
        feather = settings.value("image_tools/feather", 0.0, type=float)
        output_dir = settings.value("image_tools/output_dir", "")
        last_bg_color = settings.value("image_tools/last_bg_color", "#FFFFFF")
        auto_suffix = settings.value("image_tools/auto_suffix", True, type=bool)
        avoid_overwrite = settings.value("image_tools/avoid_overwrite", True, type=bool)

        self._single_tab.restore_settings(last_model, alpha_matting, sharpen, feather)
        self._batch_tab.restore_settings(
            last_model, alpha_matting, sharpen, feather,
            output_dir, auto_suffix, avoid_overwrite,
        )
        self._replace_tab.restore_settings(last_bg_color)

    def _persist_settings(self) -> None:
        """將當前設定寫回 QSettings。"""
        settings = QSettings("DocConverter", "DocConverter")
        model, alpha = self._single_tab.get_model_settings()
        sharpen, feather = self._single_tab.get_post_settings()
        settings.setValue("image_tools/last_model", model)
        settings.setValue("image_tools/alpha_matting", alpha)
        settings.setValue("image_tools/sharpen", sharpen)
        settings.setValue("image_tools/feather", feather)
        output_dir = self._batch_tab.get_output_dir()
        if output_dir:
            settings.setValue("image_tools/output_dir", output_dir)
        auto_suffix, avoid_overwrite = self._batch_tab.get_suffix_settings()
        settings.setValue("image_tools/auto_suffix", auto_suffix)
        settings.setValue("image_tools/avoid_overwrite", avoid_overwrite)
        bg_color = self._replace_tab.get_current_bg_color()
        if bg_color:
            settings.setValue("image_tools/last_bg_color", bg_color)

    # -------------------------------------------------------------------------
    # 主題
    # -------------------------------------------------------------------------

    def _refresh_palette(self) -> None:
        """主題切換時重新套色（委派給各需要的子元件）。"""
        self._single_tab.refresh_palette()
        self._batch_tab.refresh_palette()
        self._replace_tab.refresh_palette()
        self._filter_tab.refresh_palette()


# ---------------------------------------------------------------------------
# Tab 基類
# ---------------------------------------------------------------------------

class _BaseImageTab(QWidget):
    """各 Tab 的共同基類，提供 set_controller / set_running / 快捷鍵介面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller = None
        self._setup_tab_ui()

    def _setup_tab_ui(self) -> None:
        """子類實作：建立 Tab 內容 UI。"""
        raise NotImplementedError

    def set_controller(self, controller) -> None:
        """注入 ImageToolsController。"""
        self._controller = controller
        self._on_controller_set()

    def _on_controller_set(self) -> None:
        """controller 注入後的鉤子，子類可覆寫（例如填充 ComboBox）。"""

    def set_running(self, is_running: bool) -> None:
        """鎖定 / 解鎖主按鈕，防止操作中重複觸發。"""
        btn = getattr(self, "_primary_btn", None)
        if btn is not None:
            btn.setEnabled(not is_running)

    def on_open_shortcut(self) -> None:
        """Ctrl+O 快捷鍵觸發，子類可覆寫。"""

    def on_save_shortcut(self) -> None:
        """Ctrl+S 快捷鍵觸發，子類可覆寫。"""

    def refresh_palette(self) -> None:
        """主題切換時重新套色，子類可覆寫。"""


# ---------------------------------------------------------------------------
# Tab 0：單張去背
# ---------------------------------------------------------------------------

class _SingleRemoveTab(_BaseImageTab):
    """單張去背 Tab — 拖入即用 + 並列預覽 + 模型設定 + 後製。"""

    def _setup_tab_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 左側：預覽區（60%）
        self._preview = _ImagePreviewArea("拖入圖片開始去背")
        self._preview.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(self._preview, stretch=6)

        # 右側面板（40%）
        right_panel = QWidget()
        right_panel.setMinimumWidth(260)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 模型面板
        self._model_panel = _ModelPanel()
        self._model_panel.model_changed.connect(self._on_settings_changed)
        self._model_panel.alpha_matting_toggled.connect(self._on_settings_changed)
        right_layout.addWidget(self._model_panel)

        # 後製面板
        self._post_panel = _PostProcessPanel()
        self._post_panel.values_changed.connect(self._on_settings_changed)
        right_layout.addWidget(self._post_panel)

        # 操作按鈕
        btn_group = QGroupBox("操作")
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setSpacing(6)

        self._open_btn = PushButton("開啟（Ctrl+O）")
        self._open_btn.clicked.connect(self._on_open_file)
        btn_layout.addWidget(self._open_btn)

        self._primary_btn = PrimaryPushButton("匯出 PNG（Ctrl+S）")
        self._primary_btn.clicked.connect(self._on_export)
        self._primary_btn.setEnabled(False)
        btn_layout.addWidget(self._primary_btn)
        right_layout.addWidget(btn_group)

        # 訊息區
        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        pal = get_palette()
        self._info_label.setStyleSheet(
            f"color: {pal.get('text_secondary', '#4C566A')};"
            f" font-size: 12px;"
        )
        right_layout.addWidget(self._info_label)
        right_layout.addStretch()

        layout.addWidget(right_panel, stretch=4)

        # 當前已去背的暫存路徑
        self._current_input: Path | None = None
        self._current_preview_path: Path | None = None
        self._is_processing = False

    def _on_controller_set(self) -> None:
        """填充模型 ComboBox。"""
        if self._controller is not None:
            self._model_panel.populate_models(self._controller.available_models())

    def _on_file_dropped(self, path: Path) -> None:
        """使用者拖入檔案。"""
        self._load_file(path)

    def _on_open_file(self) -> None:
        """按下開啟按鈕或 Ctrl+O。"""
        path, _ = QFileDialog.getOpenFileName(self, "開啟圖片", "", _IMAGE_FILTER)
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path) -> None:
        """載入圖片檔案，顯示原圖並觸發去背。"""
        if not path.exists():
            _show_info_bar(self, "error", "檔案不存在", str(path))
            return

        self._current_input = path
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            _show_info_bar(self, "error", "無法讀取圖片", f"無法載入：{path.name}")
            return

        self._preview.set_original(pixmap)
        self._preview.set_processed(None)

        # 更新訊息區
        if self._controller is not None:
            try:
                info = self._controller.get_info(path)
                size_mb = info.get("size_bytes", 0) / (1024 * 1024)
                w = info.get("width", "?")
                h = info.get("height", "?")
                self._info_label.setText(f"影像 {w}×{h} · {size_mb:.1f} MB")
            except Exception:
                self._info_label.setText(path.name)

        self._trigger_process()

    def _trigger_process(self) -> None:
        """觸發去背（由設定變更 debounce 後呼叫）。"""
        if self._current_input is None or self._controller is None:
            return

        # 產生暫存輸出路徑
        tmp_dir = Path(tempfile.gettempdir())
        tmp_name = f"imgtools_preview_{uuid.uuid4().hex[:8]}.png"
        self._current_preview_path = tmp_dir / tmp_name

        model, alpha_matting = self._model_panel.get_values()
        sharpen, feather = self._post_panel.get_values()

        options = {
            "model": model,
            "alpha_matting": alpha_matting,
            "post_process_sharpen": sharpen,
            "post_process_feather": feather,
        }
        self._preview.set_processing(True)
        self._controller.remove_background_async(
            self._current_input,
            self._current_preview_path,
            options,
        )

    def _on_settings_changed(self, *_args) -> None:
        """設定變更時，若已有輸入圖則 debounce 重新去背。"""
        if self._current_input is not None:
            self._trigger_process()

    def on_processing_done(self, result: object) -> None:
        """controller 通知單張去背完成，更新右側預覽。"""
        self._preview.set_processing(False)
        path = result if isinstance(result, Path) else self._current_preview_path
        if path is not None and Path(str(path)).exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._preview.set_processed(pixmap)
                self._primary_btn.setEnabled(True)
                return
        _show_info_bar(self, "warning", "預覽失敗", "無法載入處理結果。")

    def set_progress(self, value: float) -> None:
        """進度更新，傳遞給預覽區顯示。"""
        self._preview.set_progress(value)

    def _on_export(self) -> None:
        """匯出去背結果 PNG（Ctrl+S）。"""
        if self._current_preview_path is None or not self._current_preview_path.exists():
            _show_info_bar(self, "warning", "尚無處理結果", "請先拖入圖片執行去背。")
            return

        default_name = ""
        if self._current_input:
            default_name = self._current_input.stem + "_nobg.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "儲存去背 PNG", default_name, "PNG 圖片 (*.png)"
        )
        if path:
            shutil.copy2(str(self._current_preview_path), path)
            _show_info_bar(self, "success", "匯出完成", Path(path).name)

    def on_open_shortcut(self) -> None:
        self._on_open_file()

    def on_save_shortcut(self) -> None:
        self._on_export()

    def restore_settings(
        self,
        model: str,
        alpha_matting: bool,
        sharpen: int,
        feather: float,
    ) -> None:
        """從 QSettings 恢復上次設定。"""
        self._model_panel.restore(model, alpha_matting)
        self._post_panel.restore(sharpen, feather)

    def get_model_settings(self) -> tuple[str, bool]:
        """回傳當前模型設定，供 QSettings 儲存。"""
        return self._model_panel.get_values()

    def get_post_settings(self) -> tuple[int, float]:
        """回傳當前後製設定，供 QSettings 儲存。"""
        return self._post_panel.get_values()

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""
        self._preview.refresh_palette()
        pal = get_palette()
        self._info_label.setStyleSheet(
            f"color: {pal.get('text_secondary', '#4C566A')};"
            f" font-size: 12px;"
        )


# ---------------------------------------------------------------------------
# Tab 1：批次去背
# ---------------------------------------------------------------------------

class _BatchTab(_BaseImageTab):
    """批次去背 Tab — DropZone + 檔案清單 + 設定 + 按鈕。"""

    def _setup_tab_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # DropZone（沿用既有 widget）
        self._drop_zone = DropZone(self)
        self._drop_zone.setFixedHeight(100)
        self._drop_zone.signals.files_dropped.connect(self._on_files_added)
        layout.addWidget(self._drop_zone)

        # 清單標題列
        list_header = QHBoxLayout()
        self._list_count_label = QLabel("檔案清單（0 個）")
        list_header.addWidget(self._list_count_label)
        list_header.addStretch()
        layout.addLayout(list_header)

        # 檔案清單表格（4 欄：縮圖 / 檔名 / 大小 / 狀態）
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["縮圖", "檔名", "大小", "狀態"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            1, self._table.horizontalHeader().ResizeMode.Stretch
        )
        self._table.setColumnWidth(0, 48)
        self._table.setColumnWidth(2, 72)
        self._table.setColumnWidth(3, 80)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setDefaultSectionSize(48)
        layout.addWidget(self._table, stretch=1)

        # 設定群組
        settings_group = QGroupBox("設定")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(6)

        # 模型 + alpha matting
        self._model_panel = _ModelPanel()
        settings_layout.addWidget(self._model_panel)

        # 後製
        self._post_panel = _PostProcessPanel()
        settings_layout.addWidget(self._post_panel)

        # 輸出資料夾
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("輸出資料夾："))
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("選擇輸出資料夾…")
        self._browse_out_btn = PushButton("瀏覽")
        self._browse_out_btn.clicked.connect(self._on_browse_output)
        out_row.addWidget(self._out_dir_edit, stretch=1)
        out_row.addWidget(self._browse_out_btn)
        settings_layout.addLayout(out_row)

        # 後綴 / 避免覆寫
        suffix_row = QHBoxLayout()
        self._auto_suffix_cb = CheckBox("自動加 _nobg 後綴")
        self._auto_suffix_cb.setChecked(True)
        self._avoid_overwrite_cb = CheckBox("同名時加序號")
        self._avoid_overwrite_cb.setChecked(True)
        suffix_row.addWidget(self._auto_suffix_cb)
        suffix_row.addWidget(self._avoid_overwrite_cb)
        suffix_row.addStretch()
        settings_layout.addLayout(suffix_row)
        layout.addWidget(settings_group)

        # 按鈕列
        btn_row = QHBoxLayout()
        self._clear_btn = PushButton("全部清空")
        self._remove_selected_btn = PushButton("移除選取")
        self._primary_btn = PrimaryPushButton("開始批次")
        self._open_output_btn = PushButton("開啟輸出資料夾")
        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(self._remove_selected_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._open_output_btn)
        btn_row.addWidget(self._primary_btn)
        layout.addLayout(btn_row)

        # 連線
        self._clear_btn.clicked.connect(self._on_clear_list)
        self._remove_selected_btn.clicked.connect(self._on_remove_selected)
        self._primary_btn.clicked.connect(self._on_start_batch)
        self._open_output_btn.clicked.connect(self._on_open_output_dir)

        # 內部狀態
        self._file_paths: list[Path] = []
        self._completed_count = 0

    def _on_controller_set(self) -> None:
        """填充模型 ComboBox。"""
        if self._controller is not None:
            self._model_panel.populate_models(self._controller.available_models())

    def _on_files_added(self, paths: list[Path]) -> None:
        """DropZone 或按鈕新增檔案。"""
        added = 0
        for path in paths:
            if path.suffix.lower() in _IMAGE_EXTENSIONS:
                if path not in self._file_paths:
                    self._file_paths.append(path)
                    self._add_table_row(path)
                    added += 1

        if added == 0 and paths:
            _show_info_bar(self, "warning", "不支援的格式", "請加入 PNG / JPG / WEBP 等圖片格式。")
        self._update_list_label()

    def _add_table_row(self, path: Path) -> None:
        """在清單表格末尾插入一列。"""
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 縮圖（小尺寸 pixmap）
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            thumb_label.setPixmap(
                pixmap.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            )
        self._table.setCellWidget(row, 0, thumb_label)

        # 檔名
        self._table.setItem(row, 1, QTableWidgetItem(path.name))

        # 大小
        try:
            size_kb = path.stat().st_size / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        except OSError:
            size_str = "—"
        self._table.setItem(row, 2, QTableWidgetItem(size_str))

        # 狀態
        self._table.setItem(row, 3, QTableWidgetItem("等待"))

    def _update_list_label(self) -> None:
        """更新清單標題計數。"""
        count = len(self._file_paths)
        self._list_count_label.setText(f"檔案清單（{count} 個）")

    def _on_clear_list(self) -> None:
        """清空所有檔案。"""
        self._table.setRowCount(0)
        self._file_paths.clear()
        self._completed_count = 0
        self._update_list_label()

    def _on_remove_selected(self) -> None:
        """移除已選中的列。"""
        selected_rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in selected_rows:
            self._table.removeRow(row)
            if row < len(self._file_paths):
                self._file_paths.pop(row)
        self._update_list_label()

    def _on_browse_output(self) -> None:
        """瀏覽選擇輸出資料夾。"""
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self._out_dir_edit.setText(path)

    def _on_start_batch(self) -> None:
        """開始批次去背。"""
        if self._controller is None:
            return

        # 只取狀態為「等待」的檔案
        pending: list[Path] = []
        for i, path in enumerate(self._file_paths):
            item = self._table.item(i, 3)
            if item is not None and item.text() in ("等待", "失敗"):
                pending.append(path)

        if not pending:
            _show_info_bar(self, "warning", "無待處理檔案", "清單中沒有「等待」狀態的圖片。")
            return

        out_dir_text = self._out_dir_edit.text().strip()
        if not out_dir_text:
            _show_info_bar(self, "warning", "請選擇輸出資料夾", "尚未指定批次輸出目錄。")
            return

        out_dir = Path(out_dir_text)
        if not out_dir.exists():
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _show_info_bar(self, "error", "無法建立輸出目錄", str(exc))
                return

        model, alpha_matting = self._model_panel.get_values()
        sharpen, feather = self._post_panel.get_values()

        settings = {
            "model": model,
            "alpha_matting": alpha_matting,
            "sharpen": sharpen,
            "feather": feather,
            "filename_suffix": "_nobg" if self._auto_suffix_cb.isChecked() else "",
            "avoid_overwrite": self._avoid_overwrite_cb.isChecked(),
        }
        self._completed_count = 0
        self._controller.batch_remove_async(pending, out_dir, settings)

    def _on_open_output_dir(self) -> None:
        """開啟輸出資料夾。"""
        out_dir_text = self._out_dir_edit.text().strip()
        if out_dir_text and Path(out_dir_text).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir_text))
        else:
            _show_info_bar(self, "warning", "無輸出資料夾", "請先設定輸出資料夾。")

    def on_item_status(self, idx: int, status: str) -> None:
        """更新清單中指定列的狀態文字。"""
        status_map = {
            "started": "處理中…",
            "completed": "✓ 完成",
            "failed": "✗ 失敗",
            "cancelled": "已取消",
        }
        if idx < self._table.rowCount():
            item = self._table.item(idx, 3)
            if item is not None:
                item.setText(status_map.get(status, status))

    def on_item_completed(self, idx: int, result: object) -> None:
        """單檔完成時更新計數。"""
        from converters.image_tools import BatchItemResult
        if isinstance(result, BatchItemResult):
            if result.status == "success":
                self._completed_count += 1

    def on_batch_done(self, result: object) -> None:
        """批次全部完成。"""
        self._completed_count = 0

    def completed_count(self) -> int:
        """回傳已完成的檔案數。"""
        return self._completed_count

    def total_count(self) -> int:
        """回傳清單中的總檔案數。"""
        return self._table.rowCount()

    def restore_settings(
        self,
        model: str,
        alpha_matting: bool,
        sharpen: int,
        feather: float,
        output_dir: str,
        auto_suffix: bool,
        avoid_overwrite: bool,
    ) -> None:
        """從 QSettings 恢復上次設定。"""
        self._model_panel.restore(model, alpha_matting)
        self._post_panel.restore(sharpen, feather)
        if output_dir:
            self._out_dir_edit.setText(output_dir)
        self._auto_suffix_cb.setChecked(auto_suffix)
        self._avoid_overwrite_cb.setChecked(avoid_overwrite)

    def get_output_dir(self) -> str:
        """回傳當前輸出資料夾，供 QSettings 儲存。"""
        return self._out_dir_edit.text().strip()

    def get_suffix_settings(self) -> tuple[bool, bool]:
        """回傳後綴設定，供 QSettings 儲存。"""
        return self._auto_suffix_cb.isChecked(), self._avoid_overwrite_cb.isChecked()

    def on_open_shortcut(self) -> None:
        """Ctrl+O：觸發 DropZone 的開啟對話框。"""
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇圖片", "", _IMAGE_FILTER)
        if paths:
            self._on_files_added([Path(p) for p in paths])

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""


# ---------------------------------------------------------------------------
# Tab 2：背景替換
# ---------------------------------------------------------------------------

class _ReplaceBgTab(_BaseImageTab):
    """背景替換 Tab — 選去背 PNG + 背景類型選擇 + 並列預覽。"""

    def _setup_tab_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 左側預覽（60%）
        self._preview = _ImagePreviewArea("拖入去背 PNG")
        self._preview.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(self._preview, stretch=6)

        # 右側面板（40%）
        right_panel = QWidget()
        right_panel.setMinimumWidth(260)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 來源 PNG
        src_group = QGroupBox("來源（已去背 PNG）")
        src_layout = QHBoxLayout(src_group)
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("選擇去背 PNG…")
        self._src_browse_btn = PushButton("瀏覽")
        self._src_browse_btn.clicked.connect(self._on_browse_source)
        src_layout.addWidget(self._src_edit, stretch=1)
        src_layout.addWidget(self._src_browse_btn)
        right_layout.addWidget(src_group)

        # 背景選擇器
        self._bg_chooser = _BackgroundChooser()
        self._bg_chooser.bg_changed.connect(self._on_bg_changed)
        right_layout.addWidget(self._bg_chooser)

        # 匯出按鈕
        self._primary_btn = PrimaryPushButton("匯出 PNG（Ctrl+S）")
        self._primary_btn.clicked.connect(self._on_export)
        self._primary_btn.setEnabled(False)
        right_layout.addWidget(self._primary_btn)

        right_layout.addStretch()
        layout.addWidget(right_panel, stretch=4)

        # 內部狀態
        self._current_input: Path | None = None
        self._current_preview_path: Path | None = None
        self._pending_bg_options: dict = {}

    def _on_file_dropped(self, path: Path) -> None:
        self._load_source(path)

    def _on_browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇去背 PNG", "", "PNG 圖片 (*.png)"
        )
        if path:
            self._src_edit.setText(path)
            self._load_source(Path(path))

    def _load_source(self, path: Path) -> None:
        """載入來源 PNG，顯示原圖，準備替換背景。"""
        if not path.exists():
            _show_info_bar(self, "error", "檔案不存在", str(path))
            return
        self._current_input = path
        self._src_edit.setText(str(path))
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._preview.set_original(pixmap)
        self._trigger_replace()

    def _on_bg_changed(self, bg_options: dict) -> None:
        """背景設定變更，若有來源圖則觸發替換。"""
        self._pending_bg_options = bg_options
        if self._current_input is not None:
            self._trigger_replace()

    def _trigger_replace(self) -> None:
        """呼叫 controller 替換背景（輸出到暫存路徑）。"""
        if self._current_input is None or self._controller is None:
            return
        if not self._pending_bg_options:
            self._pending_bg_options = self._bg_chooser.get_options()

        tmp_dir = Path(tempfile.gettempdir())
        tmp_name = f"imgtools_bg_{uuid.uuid4().hex[:8]}.png"
        self._current_preview_path = tmp_dir / tmp_name

        self._preview.set_processing(True)
        self._controller.replace_background_async(
            self._current_input,
            self._current_preview_path,
            self._pending_bg_options,
        )

    def on_processing_done(self, result: object) -> None:
        """背景替換完成，更新右側預覽。"""
        self._preview.set_processing(False)
        path = result if isinstance(result, Path) else self._current_preview_path
        if path is not None and Path(str(path)).exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._preview.set_processed(pixmap)
                self._primary_btn.setEnabled(True)
                return
        _show_info_bar(self, "warning", "預覽失敗", "無法載入背景替換結果。")

    def _on_export(self) -> None:
        """匯出背景替換結果（Ctrl+S）。"""
        if self._current_preview_path is None or not self._current_preview_path.exists():
            _show_info_bar(self, "warning", "尚無處理結果", "請先選擇圖片並設定背景。")
            return

        default_name = ""
        if self._current_input:
            default_name = self._current_input.stem + "_bg.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "儲存背景替換結果", default_name,
            "PNG 圖片 (*.png);;JPEG 圖片 (*.jpg)"
        )
        if path:
            shutil.copy2(str(self._current_preview_path), path)
            _show_info_bar(self, "success", "匯出完成", Path(path).name)

    def on_open_shortcut(self) -> None:
        self._on_browse_source()

    def on_save_shortcut(self) -> None:
        self._on_export()

    def restore_settings(self, last_bg_color: str) -> None:
        """恢復上次的背景色。"""
        self._bg_chooser.set_color(last_bg_color)

    def get_current_bg_color(self) -> str | None:
        """回傳當前純色背景色，供 QSettings 儲存。"""
        opts = self._bg_chooser.get_options()
        return opts.get("bg_color")

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""
        self._preview.refresh_palette()
        self._bg_chooser.refresh_palette()


# ---------------------------------------------------------------------------
# Tab 3：後製濾鏡
# ---------------------------------------------------------------------------

class _FilterTab(_BaseImageTab):
    """後製濾鏡 Tab — 銳化 + 邊緣羽化 + 自動裁切。"""

    def _setup_tab_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 左側預覽（60%）
        self._preview = _ImagePreviewArea("拖入 PNG 套用濾鏡")
        self._preview.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(self._preview, stretch=6)

        # 右側面板（40%）
        right_panel = QWidget()
        right_panel.setMinimumWidth(260)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 來源 PNG
        src_group = QGroupBox("來源 PNG")
        src_layout = QHBoxLayout(src_group)
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("選擇 PNG 圖片…")
        self._src_browse_btn = PushButton("瀏覽")
        self._src_browse_btn.clicked.connect(self._on_browse_source)
        src_layout.addWidget(self._src_edit, stretch=1)
        src_layout.addWidget(self._src_browse_btn)
        right_layout.addWidget(src_group)

        # 濾鏡控制
        self._filter_controls = _FilterControls()
        self._filter_controls.values_changed.connect(self._on_settings_changed)
        right_layout.addWidget(self._filter_controls)

        # 匯出按鈕
        self._primary_btn = PrimaryPushButton("套用 + 匯出（Ctrl+S）")
        self._primary_btn.clicked.connect(self._on_export)
        self._primary_btn.setEnabled(False)
        right_layout.addWidget(self._primary_btn)

        right_layout.addStretch()
        layout.addWidget(right_panel, stretch=4)

        # 內部狀態
        self._current_input: Path | None = None
        self._current_preview_path: Path | None = None

    def _on_file_dropped(self, path: Path) -> None:
        self._load_source(path)

    def _on_browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇 PNG 圖片", "", "PNG 圖片 (*.png)")
        if path:
            self._load_source(Path(path))

    def _load_source(self, path: Path) -> None:
        if not path.exists():
            _show_info_bar(self, "error", "檔案不存在", str(path))
            return
        self._current_input = path
        self._src_edit.setText(str(path))
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._preview.set_original(pixmap)
        self._trigger_filter()

    def _on_settings_changed(self) -> None:
        """濾鏡設定變更，若已有輸入圖則觸發 re-process。"""
        if self._current_input is not None:
            self._trigger_filter()

    def _trigger_filter(self) -> None:
        """呼叫 controller 套用後製濾鏡（輸出到暫存路徑）。"""
        if self._current_input is None or self._controller is None:
            return

        tmp_dir = Path(tempfile.gettempdir())
        tmp_name = f"imgtools_filter_{uuid.uuid4().hex[:8]}.png"
        self._current_preview_path = tmp_dir / tmp_name

        filter_options = self._filter_controls.get_options()
        self._preview.set_processing(True)
        self._controller.apply_filter_async(
            self._current_input,
            self._current_preview_path,
            filter_options,
        )

    def on_processing_done(self, result: object) -> None:
        """濾鏡套用完成，更新右側預覽。"""
        self._preview.set_processing(False)
        path = result if isinstance(result, Path) else self._current_preview_path
        if path is not None and Path(str(path)).exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._preview.set_processed(pixmap)
                self._primary_btn.setEnabled(True)
                return
        _show_info_bar(self, "warning", "預覽失敗", "無法載入濾鏡結果。")

    def _on_export(self) -> None:
        """匯出濾鏡結果（Ctrl+S）。先觸發一次處理，完成後由 on_processing_done 跳至儲存。"""
        if self._current_input is None:
            _show_info_bar(self, "warning", "尚無來源圖片", "請先選擇 PNG 圖片。")
            return

        if self._current_preview_path is not None and self._current_preview_path.exists():
            self._do_save_export()
        else:
            self._trigger_filter()

    def _do_save_export(self) -> None:
        """執行實際的檔案儲存。"""
        default_name = ""
        if self._current_input:
            default_name = self._current_input.stem + "_filtered.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "儲存濾鏡結果", default_name, "PNG 圖片 (*.png)"
        )
        if path:
            shutil.copy2(str(self._current_preview_path), path)
            _show_info_bar(self, "success", "匯出完成", Path(path).name)

    def on_open_shortcut(self) -> None:
        self._on_browse_source()

    def on_save_shortcut(self) -> None:
        self._on_export()

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""
        self._preview.refresh_palette()


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_ImagePreviewArea
# ---------------------------------------------------------------------------

class _ImagePreviewArea(QWidget):
    """並列雙圖預覽（原圖 + 處理結果），透明區顯示棋盤格背景，空態顯示引導文字。

    對外 Signals:
        file_dropped(Path): 使用者拖入有效圖片檔案。

    對外 Methods:
        set_original(QPixmap)
        set_processed(QPixmap | None)
        clear()
        set_processing(bool)
        set_progress(float)
        refresh_palette()
    """

    file_dropped = Signal(Path)

    def __init__(self, empty_hint: str = "拖入圖片", parent=None):
        super().__init__(parent)
        self._empty_hint = empty_hint
        self._original_pixmap: QPixmap | None = None
        self._processed_pixmap: QPixmap | None = None
        self._is_processing = False

        self.setAcceptDrops(True)
        self.setMinimumHeight(280)
        self._setup_ui()
        self.refresh_palette()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 原圖預覽
        self._left_frame = _CheckerLabel()
        self._left_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._left_frame, stretch=1)

        # 處理結果預覽
        self._right_frame = _CheckerLabel()
        self._right_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._right_frame, stretch=1)

        # 空態覆蓋層
        self._empty_overlay = QWidget(self)
        empty_layout = QVBoxLayout(self._empty_overlay)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_label = QLabel(self._empty_hint)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_label)

        self._processing_label = QLabel("處理中…")
        self._processing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._processing_label.setVisible(False)
        empty_layout.addWidget(self._processing_label)

        # 空態時顯示覆蓋層
        self._update_empty_state()

    def resizeEvent(self, event) -> None:
        """調整空態覆蓋層大小。"""
        super().resizeEvent(event)
        self._empty_overlay.setGeometry(self.rect())

    def set_original(self, pixmap: QPixmap) -> None:
        """設定左側原圖。"""
        self._original_pixmap = pixmap
        self._update_labels()
        self._update_empty_state()

    def set_processed(self, pixmap: QPixmap | None) -> None:
        """設定右側處理結果（None 表示清除）。"""
        self._processed_pixmap = pixmap
        self._update_labels()

    def clear(self) -> None:
        """清除所有預覽，回到空態。"""
        self._original_pixmap = None
        self._processed_pixmap = None
        self._left_frame.clear()
        self._right_frame.clear()
        self._update_empty_state()

    def set_processing(self, is_processing: bool) -> None:
        """顯示 / 隱藏「處理中」文字。"""
        self._is_processing = is_processing
        self._processing_label.setVisible(is_processing)
        if is_processing:
            self._right_frame.setText("處理中…")
        elif self._processed_pixmap is None:
            self._right_frame.clear()

    def set_progress(self, value: float) -> None:
        """接收進度更新（保留接口，目前使用 indeterminate 進度條）。"""

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""
        pal = get_palette()
        bg = pal.get("bg_subtle", "#F7F6F4")
        border = pal.get("border_default", "rgba(46,52,64,0.12)")
        text_tertiary = pal.get("text_tertiary", "#8E8E93")

        frame_style = (
            f"background-color: {bg};"
            f" border: 1px solid {border};"
            f" border-radius: 6px;"
        )
        self._left_frame.setStyleSheet(frame_style)
        self._right_frame.setStyleSheet(frame_style)

        self._empty_label.setStyleSheet(
            f"color: {text_tertiary}; font-size: 14px;"
        )
        self._processing_label.setStyleSheet(
            f"color: {pal.get('state_info', '#5E81AC')}; font-size: 13px;"
        )
        self._empty_overlay.setStyleSheet("background: transparent;")
        self._left_frame.set_palette(pal)
        self._right_frame.set_palette(pal)

    def _update_labels(self) -> None:
        """更新兩側 QLabel 的 pixmap。"""
        if self._original_pixmap is not None:
            self._left_frame.setPixmap(
                self._original_pixmap.scaled(
                    self._left_frame.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        if self._processed_pixmap is not None:
            self._right_frame.setPixmap(
                self._processed_pixmap.scaled(
                    self._right_frame.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _update_empty_state(self) -> None:
        """依是否有原圖決定空態覆蓋層的可見性。"""
        is_empty = self._original_pixmap is None
        self._empty_overlay.setVisible(is_empty)

    # -------------------------------------------------------------------------
    # 拖放支援
    # -------------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(
                Path(u.toLocalFile()).suffix.lower() in _IMAGE_EXTENSIONS
                for u in urls
            ):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in _IMAGE_EXTENSIONS and path.exists():
                self.file_dropped.emit(path)
                break
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_CheckerLabel（帶棋盤格透明背景的 QLabel）
# ---------------------------------------------------------------------------

class _CheckerLabel(QLabel):
    """在透明區域顯示棋盤格的 QLabel。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checker_color_a = QColor("#CCCCCC")
        self._checker_color_b = QColor("#FFFFFF")
        self.setMinimumSize(120, 120)

    def set_palette(self, pal: dict) -> None:
        """依 Nordic palette 更新棋盤格色彩。"""
        self._checker_color_a = QColor(pal.get("bg_secondary", "#F2F1EE"))
        self._checker_color_b = QColor(pal.get("bg_subtle", "#F7F6F4"))
        self.update()

    def paintEvent(self, event) -> None:
        """繪製棋盤格背景，再繪製 pixmap。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 棋盤格
        cell = 12
        cols = self.width() // cell + 1
        rows = self.height() // cell + 1
        for row in range(rows):
            for col in range(cols):
                color = self._checker_color_a if (row + col) % 2 == 0 else self._checker_color_b
                painter.fillRect(col * cell, row * cell, cell, cell, color)

        painter.end()
        # 委派給 QLabel 繪製 pixmap / text
        super().paintEvent(event)


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_ModelPanel
# ---------------------------------------------------------------------------

class _ModelPanel(QWidget):
    """模型選擇 + Alpha Matting 開關。

    Signals:
        model_changed(str)         模型 ID 變更
        alpha_matting_toggled(bool) Alpha Matting 開關變更
    """

    model_changed = Signal(str)
    alpha_matting_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        group = QGroupBox("模型")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)

        self._model_combo = ComboBox() if _HAS_FLUENT else ComboBox()
        # 預設填入，待 controller 注入後以 populate_models 覆蓋
        self._model_combo.addItem("U²Net（通用，預設）", "u2net")
        group_layout.addWidget(self._model_combo)

        self._alpha_matting_cb = CheckBox("Alpha Matting（更精細，慢約 3 倍）")
        group_layout.addWidget(self._alpha_matting_cb)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._alpha_matting_cb.stateChanged.connect(
            lambda _: self.alpha_matting_toggled.emit(self._alpha_matting_cb.isChecked())
        )

    def populate_models(self, models: dict[str, str]) -> None:
        """以 controller.available_models() 回傳值填充 ComboBox。"""
        self._model_combo.blockSignals(True)
        current_data = self._model_combo.currentData()
        self._model_combo.clear()
        for model_id, display_name in models.items():
            self._model_combo.addItem(display_name, model_id)
        # 恢復之前選取的項目
        if current_data:
            for i in range(self._model_combo.count()):
                if self._model_combo.itemData(i) == current_data:
                    self._model_combo.setCurrentIndex(i)
                    break
        self._model_combo.blockSignals(False)

    def _on_model_changed(self, index: int) -> None:
        model_id = self._model_combo.itemData(index)
        if model_id:
            self.model_changed.emit(model_id)

    def get_values(self) -> tuple[str, bool]:
        """回傳 (model_id, alpha_matting)。"""
        model_id = self._model_combo.currentData() or "u2net"
        return model_id, self._alpha_matting_cb.isChecked()

    def restore(self, model: str, alpha_matting: bool) -> None:
        """恢復上次設定。"""
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == model:
                self._model_combo.setCurrentIndex(i)
                break
        self._alpha_matting_cb.setChecked(alpha_matting)


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_PostProcessPanel
# ---------------------------------------------------------------------------

class _PostProcessPanel(QWidget):
    """銳化 + 羽化兩個滑桿，含 300ms debounce。

    Signals:
        values_changed(int, float)  (sharpen 0-200, feather 0.0-10.0)
    """

    values_changed = Signal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._emit_values)
        self._setup_ui()

    def _setup_ui(self) -> None:
        group = QGroupBox("後製")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)

        # 銳化強度 0-200
        sharpen_row = QHBoxLayout()
        sharpen_row.addWidget(QLabel("銳化強度"))
        self._sharpen_slider = QSlider(Qt.Orientation.Horizontal)
        self._sharpen_slider.setRange(0, 200)
        self._sharpen_slider.setValue(0)
        self._sharpen_label = QLabel("0")
        self._sharpen_label.setFixedWidth(32)
        sharpen_row.addWidget(self._sharpen_slider, stretch=1)
        sharpen_row.addWidget(self._sharpen_label)
        group_layout.addLayout(sharpen_row)

        # 邊緣羽化 0-100（對應 0.0-10.0px）
        feather_row = QHBoxLayout()
        feather_row.addWidget(QLabel("邊緣羽化"))
        self._feather_slider = QSlider(Qt.Orientation.Horizontal)
        self._feather_slider.setRange(0, 100)
        self._feather_slider.setValue(0)
        self._feather_label = QLabel("0")
        self._feather_label.setFixedWidth(36)
        feather_row.addWidget(self._feather_slider, stretch=1)
        feather_row.addWidget(self._feather_label)
        group_layout.addLayout(feather_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

        self._sharpen_slider.valueChanged.connect(self._on_slider_changed)
        self._feather_slider.valueChanged.connect(self._on_slider_changed)

    def _on_slider_changed(self) -> None:
        """滑桿變更時更新標籤並重置 debounce 計時器。"""
        sharpen = self._sharpen_slider.value()
        feather_raw = self._feather_slider.value()
        self._sharpen_label.setText(str(sharpen))
        self._feather_label.setText(f"{feather_raw / 10:.1f}")
        self._debounce_timer.start()

    def _emit_values(self) -> None:
        """debounce 到期後發出 values_changed。"""
        sharpen = self._sharpen_slider.value()
        feather = self._feather_slider.value() / 10.0
        self.values_changed.emit(sharpen, feather)

    def get_values(self) -> tuple[int, float]:
        """回傳 (sharpen, feather_px)。"""
        return self._sharpen_slider.value(), self._feather_slider.value() / 10.0

    def restore(self, sharpen: int, feather: float) -> None:
        """恢復上次設定（feather 以 px 為單位）。"""
        self._sharpen_slider.setValue(max(0, min(200, sharpen)))
        self._feather_slider.setValue(max(0, min(100, int(feather * 10))))


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_BackgroundChooser
# ---------------------------------------------------------------------------

class _BackgroundChooser(QWidget):
    """背景類型選擇器：透明 / 純色 / 圖片 + 預設色塊 + ColorDialog。

    Signals:
        bg_changed(dict)  {bg_type, bg_color, bg_image_path, bg_image_mode}
    """

    bg_changed = Signal(dict)

    _PRESET_COLORS = ["#FFFFFF", "#000000", "#3B82F6", "#22C55E", "#EF4444", "#A855F7"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_color = "#FFFFFF"
        self._setup_ui()

    def _setup_ui(self) -> None:
        group = QGroupBox("背景類型")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        # 三個 RadioButton
        self._btn_group = QButtonGroup(self)
        self._radio_transparent = RadioButton("透明（PNG 原樣）")
        self._radio_color = RadioButton("純色")
        self._radio_image = RadioButton("圖片")
        self._radio_color.setChecked(True)
        for rb in (self._radio_transparent, self._radio_color, self._radio_image):
            self._btn_group.addButton(rb)
            group_layout.addWidget(rb)

        # 純色控制列
        color_row = QHBoxLayout()
        self._color_preview = _ColorChipButton(self._current_color, parent=self)
        self._color_preview.color_picked.connect(self._on_chip_color_picked)
        self._custom_color_btn = PushButton("自訂")
        self._custom_color_btn.setFixedWidth(52)
        self._custom_color_btn.clicked.connect(self._on_pick_custom_color)
        color_row.addWidget(self._color_preview)

        # 預設色塊
        for hex_color in self._PRESET_COLORS:
            chip = _ColorChipButton(hex_color, parent=self)
            chip.color_picked.connect(self._on_chip_color_picked)
            color_row.addWidget(chip)
        color_row.addWidget(self._custom_color_btn)
        color_row.addStretch()
        group_layout.addLayout(color_row)

        # 圖片背景控制
        img_row = QHBoxLayout()
        self._bg_image_edit = QLineEdit()
        self._bg_image_edit.setPlaceholderText("選擇背景圖片…")
        self._bg_image_browse_btn = PushButton("瀏覽")
        self._bg_image_browse_btn.clicked.connect(self._on_browse_bg_image)
        img_row.addWidget(self._bg_image_edit, stretch=1)
        img_row.addWidget(self._bg_image_browse_btn)
        group_layout.addLayout(img_row)

        # 圖片縮放模式
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("縮放模式："))
        self._bg_mode_combo = ComboBox() if _HAS_FLUENT else ComboBox()
        for label, data in [("置中縮放", "fit"), ("填滿裁切", "fill"),
                             ("置中不縮放", "center"), ("平鋪", "tile")]:
            self._bg_mode_combo.addItem(label, data)
        mode_row.addWidget(self._bg_mode_combo)
        mode_row.addStretch()
        group_layout.addLayout(mode_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

        # Signal 連線
        self._radio_transparent.toggled.connect(self._on_type_changed)
        self._radio_color.toggled.connect(self._on_type_changed)
        self._radio_image.toggled.connect(self._on_type_changed)
        self._bg_image_edit.textChanged.connect(self._on_type_changed)
        self._bg_mode_combo.currentIndexChanged.connect(self._on_type_changed)

    def _on_type_changed(self, *_args) -> None:
        """任何背景設定變更後 emit bg_changed。"""
        self.bg_changed.emit(self.get_options())

    def _on_chip_color_picked(self, hex_color: str) -> None:
        """預設色塊點擊：更新 current_color 並 emit。"""
        self._current_color = hex_color
        self._color_preview.set_color(hex_color)
        if not self._radio_color.isChecked():
            self._radio_color.setChecked(True)
        else:
            self.bg_changed.emit(self.get_options())

    def _on_pick_custom_color(self) -> None:
        """開啟顏色選擇對話框。"""
        try:
            if _HAS_FLUENT:
                from qfluentwidgets import ColorDialog
                dialog = ColorDialog(QColor(self._current_color), "選擇背景顏色", self)
                dialog.colorChanged.connect(lambda c: self._apply_color(c.name()))
                dialog.exec()
                return
        except Exception:
            pass
        # 降級至 PySide6 原生
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor(self._current_color), self, "選擇背景顏色")
        if color.isValid():
            self._apply_color(color.name())

    def _apply_color(self, hex_color: str) -> None:
        self._current_color = hex_color
        self._color_preview.set_color(hex_color)
        if not self._radio_color.isChecked():
            self._radio_color.setChecked(True)
        else:
            self.bg_changed.emit(self.get_options())

    def _on_browse_bg_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇背景圖片", "", _IMAGE_FILTER)
        if path:
            self._bg_image_edit.setText(path)
            if not self._radio_image.isChecked():
                self._radio_image.setChecked(True)

    def get_options(self) -> dict:
        """回傳當前背景設定 dict。"""
        if self._radio_transparent.isChecked():
            return {"bg_type": "transparent", "bg_color": None,
                    "bg_image_path": None, "bg_image_mode": "fit"}
        elif self._radio_color.isChecked():
            return {"bg_type": "color", "bg_color": self._current_color,
                    "bg_image_path": None, "bg_image_mode": "fit"}
        else:
            img_path_str = self._bg_image_edit.text().strip()
            img_path = Path(img_path_str) if img_path_str else None
            mode = self._bg_mode_combo.currentData() or "fit"
            return {"bg_type": "image", "bg_color": None,
                    "bg_image_path": img_path, "bg_image_mode": mode}

    def set_color(self, hex_color: str) -> None:
        """從外部設定顏色（QSettings 恢復用）。"""
        self._current_color = hex_color
        self._color_preview.set_color(hex_color)

    def refresh_palette(self) -> None:
        """主題切換時重新套色。"""
        self._color_preview.refresh_palette()


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_ColorChipButton
# ---------------------------------------------------------------------------

class _ColorChipButton(QPushButton):
    """24×24 圓角色塊按鈕，點擊後 emit color_picked(hex)。

    Signals:
        color_picked(str)  hex 色碼（如 "#FFFFFF"）
    """

    color_picked = Signal(str)

    def __init__(self, hex_color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._hex_color = hex_color
        self._border_color = "rgba(46,52,64,0.20)"
        self.setFixedSize(24, 24)
        self.setToolTip(hex_color)
        self.clicked.connect(lambda: self.color_picked.emit(self._hex_color))
        self._update_style()

    def set_color(self, hex_color: str) -> None:
        """更新顯示色彩。"""
        self._hex_color = hex_color
        self.setToolTip(hex_color)
        self._update_style()

    def refresh_palette(self) -> None:
        """主題切換時更新邊框色。"""
        pal = get_palette()
        self._border_color = pal.get("border_strong", "rgba(46,52,64,0.20)")
        self._update_style()

    def _update_style(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {self._hex_color};"
            f"  border: 1.5px solid {self._border_color};"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border: 2.5px solid {self._border_color};"
            f"}}"
        )


# ---------------------------------------------------------------------------
# 自製輔助 Widget：_FilterControls
# ---------------------------------------------------------------------------

class _FilterControls(QWidget):
    """後製濾鏡控制：銳化強度 / 半徑 / 邊緣羽化 / 自動裁切，含 300ms debounce。

    Signals:
        values_changed()  任意設定變更後（debounce）
    """

    values_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self.values_changed)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 銳化群組
        sharpen_group = QGroupBox("銳化（UnsharpMask）")
        sg_layout = QVBoxLayout(sharpen_group)
        sg_layout.setSpacing(4)

        # 強度 0-200
        strength_row = QHBoxLayout()
        strength_row.addWidget(QLabel("強度"))
        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(0, 200)
        self._strength_slider.setValue(50)
        self._strength_label = QLabel("50")
        self._strength_label.setFixedWidth(32)
        strength_row.addWidget(self._strength_slider, stretch=1)
        strength_row.addWidget(self._strength_label)
        sg_layout.addLayout(strength_row)

        # 半徑 0-50（對應 0.0-5.0px）
        radius_row = QHBoxLayout()
        radius_row.addWidget(QLabel("半徑"))
        self._radius_slider = QSlider(Qt.Orientation.Horizontal)
        self._radius_slider.setRange(0, 50)
        self._radius_slider.setValue(20)
        self._radius_label = QLabel("2.0")
        self._radius_label.setFixedWidth(36)
        radius_row.addWidget(self._radius_slider, stretch=1)
        radius_row.addWidget(self._radius_label)
        sg_layout.addLayout(radius_row)
        outer.addWidget(sharpen_group)

        # 邊緣羽化群組
        feather_group = QGroupBox("邊緣羽化（Alpha Blur）")
        fg_layout = QVBoxLayout(feather_group)
        feather_row = QHBoxLayout()
        feather_row.addWidget(QLabel("強度"))
        self._feather_slider = QSlider(Qt.Orientation.Horizontal)
        self._feather_slider.setRange(0, 100)
        self._feather_slider.setValue(0)
        self._feather_label = QLabel("0")
        self._feather_label.setFixedWidth(36)
        feather_row.addWidget(self._feather_slider, stretch=1)
        feather_row.addWidget(self._feather_label)
        fg_layout.addLayout(feather_row)
        outer.addWidget(feather_group)

        # 進階
        adv_group = QGroupBox("進階")
        adv_layout = QVBoxLayout(adv_group)
        self._auto_crop_cb = CheckBox("自動裁切透明邊界")
        adv_layout.addWidget(self._auto_crop_cb)
        outer.addWidget(adv_group)

        # 連線
        self._strength_slider.valueChanged.connect(self._on_changed)
        self._radius_slider.valueChanged.connect(self._on_changed)
        self._feather_slider.valueChanged.connect(self._on_changed)
        self._auto_crop_cb.stateChanged.connect(self._on_changed)

    def _on_changed(self, *_args) -> None:
        """滑桿或勾選框變更時更新標籤並重置 debounce 計時器。"""
        self._strength_label.setText(str(self._strength_slider.value()))
        self._radius_label.setText(f"{self._radius_slider.value() / 10:.1f}")
        self._feather_label.setText(f"{self._feather_slider.value() / 10:.1f}")
        self._debounce_timer.start()

    def get_options(self) -> dict:
        """回傳當前濾鏡設定 dict。"""
        return {
            "sharpen_strength": self._strength_slider.value(),
            "sharpen_radius": self._radius_slider.value() / 10.0,
            "feather_radius": self._feather_slider.value() / 10.0,
            "auto_crop_alpha": self._auto_crop_cb.isChecked(),
        }


# ---------------------------------------------------------------------------
# 工具函式
# ---------------------------------------------------------------------------

def _make_indeterminate_bar() -> QWidget:
    """建立不確定進度條 widget（qfluentwidgets 或 QProgressBar 模擬）。"""
    if _HAS_FLUENT:
        try:
            bar = IndeterminateProgressBar()
            bar.setFixedHeight(6)
            return bar
        except Exception:
            pass
    bar = QProgressBar()
    bar.setRange(0, 0)  # 不確定模式
    bar.setFixedHeight(6)
    bar.setTextVisible(False)
    return bar


def _show_info_bar(parent: QWidget, level: str, title: str, content: str) -> None:
    """顯示 InfoBar 通知（qfluentwidgets），降級為 logger。

    Args:
        parent:  顯示父 widget。
        level:   "info" | "success" | "warning" | "error"。
        title:   通知標題。
        content: 通知內容。
    """
    if not _HAS_FLUENT or InfoBar is None:
        logger.info("[%s] %s — %s", level.upper(), title, content)
        return

    position = InfoBarPosition.TOP if InfoBarPosition else None
    duration = 4000

    try:
        if level == "success":
            InfoBar.success(title=title, content=content, parent=parent,
                            position=position, duration=duration)
        elif level == "warning":
            InfoBar.warning(title=title, content=content, parent=parent,
                            position=position, duration=duration)
        elif level == "error":
            InfoBar.error(title=title, content=content, parent=parent,
                          position=position, duration=duration)
        else:
            InfoBar.info(title=title, content=content, parent=parent,
                         position=position, duration=duration)
    except Exception as exc:
        logger.warning("InfoBar 顯示失敗（%s）: %s — %s", exc, title, content)


def _build_batch_summary(result: object) -> str:
    """依批次結果建立完成通知內文。

    Args:
        result: list[BatchItemResult] 或任意物件。

    Returns:
        人類可讀的批次完成說明字串。
    """
    if not isinstance(result, list):
        return "批次處理完成。"

    success = sum(1 for r in result if getattr(r, "status", "") == "success")
    failed = sum(1 for r in result if getattr(r, "status", "") == "failed")
    cancelled = sum(1 for r in result if getattr(r, "status", "") == "cancelled")
    parts = [f"{success} 張完成"]
    if failed:
        parts.append(f"{failed} 張失敗")
    if cancelled:
        parts.append(f"{cancelled} 張已取消")
    return "，".join(parts) + "。"
