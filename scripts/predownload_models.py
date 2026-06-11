"""預下載 rembg 模型到專案根 u2net_models/ 目錄（選用）。

執行方式：
    venv/Scripts/python.exe scripts/predownload_models.py

預設情況下「不需要」執行本腳本 — 應用會在首次使用去背功能時
自動下載所需模型（~175MB/個）至 ~/.u2net/。本腳本適用於：
    - dev 環境想一次抓齊 3 個模型、之後完全離線
    - 離線部署 portable exe：下載後把 u2net_models/ 資料夾
      複製到 exe 同目錄，應用會優先讀取（不需網路）

3 個模型總計約 ~525MB：
    - u2net               約 175MB（通用）
    - u2net_human_seg     約 175MB（人像優化）
    - isnet-general-use   約 175MB（最新最準）

路徑解析優先序詳見 converters/image_tools.py 的 resolve_model_dir()。
注意：desktop_build.spec 已「不再」內嵌模型（瘦身 ~1.1GB → ~550MB）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / "u2net_models"

MODELS = [
    "u2net",
    "u2net_human_seg",
    "isnet-general-use",
]


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(TARGET_DIR)

    print(f"目標目錄：{TARGET_DIR}")
    print(f"待下載模型：{', '.join(MODELS)}")
    print()

    try:
        from rembg import new_session
    except ImportError as exc:
        print(f"[ERROR] 無法 import rembg：{exc}")
        print("請先安裝：pip install -r requirements.txt")
        return 1

    for idx, model in enumerate(MODELS, 1):
        print(f"[{idx}/{len(MODELS)}] {model} 下載中...")
        try:
            new_session(model)
            print(f"  [OK] {model} 已就緒")
        except Exception as exc:
            print(f"  [FAIL] {model} 下載失敗：{exc}")
            return 1

    # 列出實際下載的檔案大小
    print()
    print(f"模型已下載至 {TARGET_DIR}")
    total_size = 0
    for f in sorted(TARGET_DIR.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        total_size += size_mb
        print(f"  {f.name}  {size_mb:.1f} MB")
    print(f"\n總計 {total_size:.1f} MB")
    print("\n打包時 desktop_build.spec 會自動將此目錄複製進 dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
