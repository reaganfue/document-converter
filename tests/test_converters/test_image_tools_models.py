"""image_tools 模型路徑解析與可用性檢查測試（不觸發實際下載）。"""
from __future__ import annotations

import os
from pathlib import Path

from converters.image_tools import _MODEL_DIR, is_model_available, resolve_model_dir


class TestModelDirResolution:
    def test_model_dir_exists(self):
        """解析出的模型目錄必定存在（缺失時自動建立，等待下載）。"""
        assert _MODEL_DIR.exists()
        assert _MODEL_DIR.is_dir()

    def test_u2net_home_env_is_set(self):
        """U2NET_HOME 必須在 import 時設定，rembg 才會走指定目錄。"""
        assert os.environ.get("U2NET_HOME") == str(_MODEL_DIR)

    def test_resolve_returns_same_dir(self):
        """重複呼叫 resolve_model_dir 結果穩定。"""
        assert resolve_model_dir() == _MODEL_DIR


class TestModelAvailability:
    def test_nonexistent_model_not_available(self):
        """從未下載過的模型名稱必回 False（驅動 UI 的下載提示）。"""
        assert is_model_available("no_such_model_xyz") is False

    def test_available_matches_filesystem(self):
        """is_model_available 與實際 .onnx 檔存在性一致。"""
        for model in ("u2net", "u2net_human_seg", "isnet-general-use"):
            expected = (Path(_MODEL_DIR) / f"{model}.onnx").exists()
            assert is_model_available(model) is expected
