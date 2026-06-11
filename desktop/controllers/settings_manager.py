"""應用設定管理器 — QSettings 的業務層包裝。

職責：
    - 統一管理所有應用設定（輸出路徑、主題、保留策略、托盤行為等）
    - 提供型別安全的 get/set 方法，避免散落的 QSettings 存取
    - 在設定變更時觸發 SettingsManagerSignals 通知訂閱方
    - 支援匯入 / 匯出 / 重置為預設值

依賴：
    - PySide6.QtCore.QSettings（Windows: Registry；macOS: plist）
    - desktop.interfaces.SettingsManagerSignals（Signal 契約）
    - desktop.utils.paths.get_default_output_dir（預設輸出路徑）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QSettings

from desktop.interfaces import SUPPORTED_OUTPUT_FORMATS, SettingsManagerSignals
from desktop.utils.paths import get_default_output_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 所有設定鍵的預設值（CEO Q2/Q3/Q4/Q5 決策已固化）
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # === 檔案與轉換 ===
    "output_dir": "",                     # "" → 執行期 fallback 到 get_default_output_dir()
    "overwrite": False,
    "auto_open_folder_on_done": False,
    "concurrent": 3,
    "default_target_format": "pdf",
    "timeout_seconds": 60,

    # === 外觀 ===
    "theme": "system",                    # "system" | "light" | "dark"
    "theme_color": "#8B5CF6",             # 品牌紫
    "font_scale": "normal",               # "normal" | "large" | "xlarge"
    "enable_animations": True,

    # === 歷史 ===
    "record_history": True,
    "history_retention_days": 90,         # CEO Q3：0 = 永久保留
    "history_max_records": 1000,          # CEO Q3

    # === 通知 ===
    "notify_on_complete": True,
    "notify_on_error": True,
    "play_sound": False,

    # === 系統整合 ===
    "minimize_to_tray": True,             # CEO Q5
    "close_action": "ask",                # "ask" | "tray" | "quit"

    # === 進階 ===
    "enable_com_fallback": True,          # CEO Q4：COM 降級 (docx2pdf)
    "temp_dir": "",
    "log_level": "INFO",

    # === 轉換 Profile（具名的「目標格式+輸出目錄+覆寫」組合，JSON 字串存儲） ===
    "profiles": "[]",
}

# QSettings 後端使用的 org / app 名稱（與 theme.py 保持一致）
_QSETTINGS_ORG = "DocConverter"
_QSETTINGS_APP = "DocConverter"

# 已知的 bool 型別鍵集合（用於 QSettings 讀取時的型別還原）
_BOOL_KEYS: frozenset[str] = frozenset(
    k for k, v in DEFAULTS.items() if isinstance(v, bool)
)

# 已知的 int 型別鍵集合
_INT_KEYS: frozenset[str] = frozenset(
    k for k, v in DEFAULTS.items() if isinstance(v, int) and not isinstance(v, bool)
)


class SettingsManager(QObject):
    """應用設定管理器。

    使用方式（由 MainWindowV2 建立）：
        manager = SettingsManager(parent=window)
        output_dir = manager.output_dir        # Path
        manager.set("theme", "dark")           # 即時儲存 + 發 Signal

    Signals（透過 self.signals）：
        setting_changed(str, object)    key + 新值（每次 set 觸發）
        reset_completed()               重置為預設值完成
        imported(int)                   匯入的鍵數量
        exported(str)                   匯出的檔案路徑字串
    """

    def __init__(
        self,
        parent: Optional[QObject] = None,
        qsettings: Optional[QSettings] = None,
    ) -> None:
        """初始化 SettingsManager，載入所有 QSettings 到記憶體快取。

        Args:
            parent:    Qt 父物件（通常是 MainWindowV2）。
            qsettings: 自訂 QSettings 後端（測試隔離用；None 時使用
                       Registry 中的 DocConverter 正式儲存區）。
        """
        super().__init__(parent)
        self.signals = SettingsManagerSignals()
        self._qs = qsettings if qsettings is not None else QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        self._cache: dict[str, Any] = {}
        self._load_all()
        logger.debug(
            "SettingsManager 初始化完成，儲存位置：%s，載入 %d 個設定",
            self._qs.fileName(),
            len(self._cache),
        )

    # =========================================================================
    # 內部載入
    # =========================================================================

    def _load_all(self) -> None:
        """從 QSettings 讀取所有已知鍵到 self._cache。

        QSettings 在 Windows Registry 中儲存為字串化值，
        此方法依 DEFAULTS 型別推斷做型別還原，確保 bool/int 不被字串污染。
        """
        for key, default in DEFAULTS.items():
            raw = self._qs.value(key, default)
            self._cache[key] = self._coerce(key, raw, default)

    def _coerce(self, key: str, raw: Any, default: Any) -> Any:
        """將 QSettings 原始值強制轉換為 DEFAULTS 所期望的型別。

        Args:
            key:     設定鍵名稱。
            raw:     從 QSettings 讀到的原始值。
            default: DEFAULTS 中對應的預設值（用於型別推斷）。

        Returns:
            型別正確的設定值；轉換失敗時回傳 default 並記錄 warning。
        """
        if raw is None:
            return default

        # bool 必須先判斷（因為 bool 是 int 的子類）
        if key in _BOOL_KEYS:
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("true", "1", "yes")

        if key in _INT_KEYS:
            try:
                return int(raw)
            except (ValueError, TypeError):
                logger.warning("設定 %r 型別轉換失敗（raw=%r），使用預設值 %r", key, raw, default)
                return default

        return raw

    # =========================================================================
    # 核心 get / set
    # =========================================================================

    def get(self, key: str, default: Any = None) -> Any:
        """取得設定值。

        優先序：記憶體快取 → 傳入 default → DEFAULTS[key]。

        Args:
            key:     設定鍵（見 DEFAULTS）。
            default: 找不到時的備援值；None 時改用 DEFAULTS.get(key)。

        Returns:
            型別正確的設定值。
        """
        if key in self._cache:
            return self._cache[key]
        if default is not None:
            return default
        return DEFAULTS.get(key)

    def set(self, key: str, value: Any) -> None:
        """寫入設定值並觸發 signals.setting_changed。

        若新值與快取中舊值相同（== 比較），不寫入也不發 Signal（避免不必要更新）。

        Args:
            key:   設定鍵（不必須在 DEFAULTS 中，但建議只用已知鍵）。
            value: 新值（必須可被 QSettings 序列化）。
        """
        old = self._cache.get(key)
        if old == value:
            return

        self._cache[key] = value
        self._qs.setValue(key, value)
        self._qs.sync()
        logger.debug("設定更新：%r = %r（舊值 %r）", key, value, old)
        self.signals.setting_changed.emit(key, value)

    # =========================================================================
    # 重置 / 匯入 / 匯出
    # =========================================================================

    def reset_all(self) -> None:
        """將所有設定重置為 DEFAULTS 並觸發 signals.reset_completed。

        同時清除 QSettings 後端（避免殘留鍵干擾），再依序寫入 DEFAULTS。
        """
        self._qs.clear()
        self._cache = dict(DEFAULTS)
        for key, value in DEFAULTS.items():
            self._qs.setValue(key, value)
        self._qs.sync()
        logger.info("SettingsManager：所有設定已重置為預設值")
        self.signals.reset_completed.emit()

    def export_json(self, path: Path) -> int:
        """將當前設定匯出至 JSON 檔案。

        Args:
            path: 目標 JSON 檔案路徑。

        Returns:
            匯出的設定鍵數量。

        Raises:
            IOError: 若寫入檔案失敗。
        """
        data = dict(self._cache)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("設定已匯出至 %s（%d 個鍵）", path, len(data))
        self.signals.exported.emit(str(path))
        return len(data)

    def import_json(self, path: Path) -> int:
        """從 JSON 檔案匯入設定（只接受 DEFAULTS 中的已知鍵）。

        邊界防護：只匯入已知鍵，忽略未知鍵，防止注入惡意設定。

        Args:
            path: 來源 JSON 檔案路徑。

        Returns:
            成功匯入的鍵數量。

        Raises:
            json.JSONDecodeError: 若 JSON 格式錯誤。
            IOError: 若讀取檔案失敗。
        """
        raw_data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for key, value in raw_data.items():
            if key in DEFAULTS:
                self.set(key, value)
                count += 1
            else:
                logger.debug("匯入設定：忽略未知鍵 %r", key)
        logger.info("設定已從 %s 匯入（%d/%d 個鍵）", path, count, len(raw_data))
        self.signals.imported.emit(count)
        return count

    # =========================================================================
    # 轉換 Profile（具名的「目標格式 + 輸出目錄 + 覆寫」組合）
    # =========================================================================

    def get_profiles(self) -> list[dict[str, Any]]:
        """取得所有轉換 Profile（依名稱排序）。

        儲存格式為 "profiles" 鍵下的 JSON 字串；解析失敗（壞資料）
        或結構非 list 時回傳空清單，不拋例外。

        Returns:
            list[dict]，每個 dict 含 name / target_format / output_dir / overwrite。
        """
        raw = self.get("profiles", "[]")
        try:
            data = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            logger.warning("profiles 設定值非合法 JSON，回傳空清單（raw=%r）", raw)
            return []
        if not isinstance(data, list):
            return []
        valid = [p for p in data if self._is_valid_profile(p)]
        return sorted(valid, key=lambda p: str(p["name"]))

    def save_profile(self, profile: dict[str, Any]) -> None:
        """儲存一個 Profile（同名覆蓋）。

        Args:
            profile: 必含 name(非空 str) / target_format(SUPPORTED_OUTPUT_FORMATS 之一)，
                     可選 output_dir(str，空 = 用全域) / overwrite(bool)。

        Raises:
            ValueError: profile 結構不合法。
        """
        normalized = {
            "name": str(profile.get("name", "")).strip(),
            "target_format": str(profile.get("target_format", "")).lower(),
            "output_dir": str(profile.get("output_dir", "")),
            "overwrite": bool(profile.get("overwrite", False)),
        }
        if not self._is_valid_profile(normalized):
            raise ValueError(f"Profile 結構不合法：{profile!r}")

        profiles = [p for p in self.get_profiles() if p["name"] != normalized["name"]]
        profiles.append(normalized)
        self.set("profiles", json.dumps(profiles, ensure_ascii=False))
        logger.info("Profile 已儲存：%r（共 %d 個）", normalized["name"], len(profiles))

    def delete_profile(self, name: str) -> bool:
        """刪除指定名稱的 Profile。

        Args:
            name: Profile 名稱。

        Returns:
            True 表示有刪除；False 表示找不到該名稱。
        """
        profiles = self.get_profiles()
        remaining = [p for p in profiles if p["name"] != name]
        if len(remaining) == len(profiles):
            return False
        self.set("profiles", json.dumps(remaining, ensure_ascii=False))
        logger.info("Profile 已刪除：%r（剩 %d 個）", name, len(remaining))
        return True

    @staticmethod
    def _is_valid_profile(p: Any) -> bool:
        """檢查 profile dict 結構合法性（name 非空 + 格式在支援清單中）。"""
        return (
            isinstance(p, dict)
            and isinstance(p.get("name"), str)
            and bool(p["name"].strip())
            and p.get("target_format") in SUPPORTED_OUTPUT_FORMATS
        )

    # =========================================================================
    # 便利屬性（型別安全存取）
    # =========================================================================

    @property
    def output_dir(self) -> Path:
        """輸出資料夾（空字串時 fallback 到 get_default_output_dir()）。

        Returns:
            輸出目錄 Path，保證存在（get_default_output_dir 會自動建立）。
        """
        raw = self.get("output_dir", "")
        if not raw:
            return get_default_output_dir()
        return Path(raw)

    @property
    def theme(self) -> str:
        """主題模式："system" | "light" | "dark"。"""
        return str(self.get("theme", "system"))

    @property
    def minimize_to_tray(self) -> bool:
        """最小化至托盤（CEO Q5 預設 True）。"""
        return bool(self.get("minimize_to_tray", True))

    @property
    def concurrent(self) -> int:
        """最大並行轉換數（1–8）。"""
        return int(self.get("concurrent", 3))

    @property
    def overwrite(self) -> bool:
        """是否自動覆寫同名輸出檔案。"""
        return bool(self.get("overwrite", False))

    @property
    def notify_on_complete(self) -> bool:
        """轉換完成時是否發送通知。"""
        return bool(self.get("notify_on_complete", True))

    @property
    def enable_com_fallback(self) -> bool:
        """是否啟用 COM 降級（docx2pdf）。CEO Q4 決策。"""
        return bool(self.get("enable_com_fallback", True))
