"""SettingsManager 轉換 Profile 存儲層測試。

隔離策略：注入 IniFormat QSettings（寫到 pytest tmp_path），
不觸碰 Windows Registry 中的正式 DocConverter 設定。
"""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from desktop.controllers.settings_manager import SettingsManager


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    """確保 QObject 建構時有 QCoreApplication 存在。"""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture()
def manager(tmp_path):
    """回傳以 tmp INI 檔為後端的 SettingsManager（每測試獨立）。"""
    ini = tmp_path / "settings_test.ini"
    qs = QSettings(str(ini), QSettings.Format.IniFormat)
    return SettingsManager(qsettings=qs)


def _profile(name="日常PDF", fmt="pdf", output_dir="", overwrite=False):
    return {
        "name": name,
        "target_format": fmt,
        "output_dir": output_dir,
        "overwrite": overwrite,
    }


class TestProfileCRUD:
    def test_empty_by_default(self, manager):
        assert manager.get_profiles() == []

    def test_save_and_get_roundtrip(self, manager):
        manager.save_profile(_profile(output_dir="D:/out", overwrite=True))
        profiles = manager.get_profiles()
        assert len(profiles) == 1
        p = profiles[0]
        assert p["name"] == "日常PDF"
        assert p["target_format"] == "pdf"
        assert p["output_dir"] == "D:/out"
        assert p["overwrite"] is True

    def test_same_name_overwrites(self, manager):
        manager.save_profile(_profile(fmt="pdf"))
        manager.save_profile(_profile(fmt="docx"))
        profiles = manager.get_profiles()
        assert len(profiles) == 1
        assert profiles[0]["target_format"] == "docx"

    def test_multiple_profiles_sorted_by_name(self, manager):
        manager.save_profile(_profile(name="乙組", fmt="txt"))
        manager.save_profile(_profile(name="甲組", fmt="pdf"))
        names = [p["name"] for p in manager.get_profiles()]
        assert names == sorted(names)

    def test_delete_existing(self, manager):
        manager.save_profile(_profile())
        assert manager.delete_profile("日常PDF") is True
        assert manager.get_profiles() == []

    def test_delete_missing_returns_false(self, manager):
        assert manager.delete_profile("不存在") is False


class TestProfileValidation:
    def test_reject_empty_name(self, manager):
        with pytest.raises(ValueError):
            manager.save_profile(_profile(name="   "))

    def test_reject_unsupported_format(self, manager):
        with pytest.raises(ValueError):
            manager.save_profile(_profile(fmt="exe"))

    def test_corrupt_json_returns_empty(self, manager):
        manager.set("profiles", "{not json!!")
        assert manager.get_profiles() == []

    def test_non_list_json_returns_empty(self, manager):
        manager.set("profiles", json.dumps({"name": "x"}))
        assert manager.get_profiles() == []

    def test_invalid_entries_filtered_out(self, manager):
        mixed = [
            {"name": "好的", "target_format": "pdf", "output_dir": "", "overwrite": False},
            {"name": "", "target_format": "pdf"},          # 空名 → 過濾
            {"name": "壞格式", "target_format": "exe"},     # 不支援格式 → 過濾
            "not-a-dict",                                   # 非 dict → 過濾
        ]
        manager.set("profiles", json.dumps(mixed, ensure_ascii=False))
        profiles = manager.get_profiles()
        assert [p["name"] for p in profiles] == ["好的"]


class TestProfilePersistence:
    def test_survives_manager_reload(self, tmp_path):
        ini = tmp_path / "persist.ini"
        m1 = SettingsManager(qsettings=QSettings(str(ini), QSettings.Format.IniFormat))
        m1.save_profile(_profile(name="跨重啟", fmt="md"))

        m2 = SettingsManager(qsettings=QSettings(str(ini), QSettings.Format.IniFormat))
        profiles = m2.get_profiles()
        assert len(profiles) == 1
        assert profiles[0]["name"] == "跨重啟"
        assert profiles[0]["target_format"] == "md"
