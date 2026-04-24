"""widgets 子套件 — 所有 UI 元件的入口。"""
from desktop.widgets.drop_zone import DropZone
from desktop.widgets.file_card import FileCard
from desktop.widgets.format_selector import FormatSelector
from desktop.widgets.progress_widget import ProgressWidget
from desktop.widgets.settings_dialog import SettingsDialog

__all__ = [
    "DropZone",
    "FileCard",
    "FormatSelector",
    "ProgressWidget",
    "SettingsDialog",
]
