"""
conftest_flask_legacy.py — 已封存的 Flask 測試 fixtures

此檔案**不會**被 pytest 自動載入（檔名非 conftest.py）。
保留供日後參考；若 Flask API 重新啟用，可將需要的 fixtures
複製回 conftest.py 並重新安裝 app.py。

原始對應檔：tests/conftest.py（封存前）
封存日期：2026-04-25
封存原因：app.py 改為 app.py.legacy，桌面版不再依賴 Flask。
"""
from __future__ import annotations

import os
import threading
from io import BytesIO
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _patch_dirs_session(tmp_path_factory):
    """
    Session 層級：為整個測試 session 建立固定的臨時目錄，
    並透過 config 模組 monkeypatch 確保 app 啟動時使用隔離路徑。
    """
    base = tmp_path_factory.mktemp("session_fs")
    uploads = base / "uploads"
    outputs = base / "outputs"
    uploads.mkdir()
    outputs.mkdir()

    os.environ["UPLOAD_DIR"] = str(uploads)
    os.environ["OUTPUT_DIR"] = str(outputs)
    yield
    os.environ.pop("UPLOAD_DIR", None)
    os.environ.pop("OUTPUT_DIR", None)


@pytest.fixture(autouse=True)
def _clean_jobs():
    """每個測試前後清空 JOBS 字典，防止測試間狀態污染。"""
    import app as flask_app_module  # noqa: PLC0415
    with flask_app_module.JOBS_LOCK:
        flask_app_module.JOBS.clear()
    yield
    with flask_app_module.JOBS_LOCK:
        flask_app_module.JOBS.clear()


@pytest.fixture(scope="session")
def flask_app():
    """回傳設定為測試模式的 Flask app（session 層級，避免重複初始化）。"""
    import app as flask_app_module  # noqa: PLC0415
    flask_app_module.app.config["TESTING"] = True
    flask_app_module.app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    return flask_app_module.app


@pytest.fixture
def app(flask_app):
    """每個測試的 Flask app（同一 session app）。"""
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client。"""
    return app.test_client()


@pytest.fixture
def fake_pdf():
    """返回一個極小的 PDF bytes（合法 PDF 標頭）。"""
    return BytesIO(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")


@pytest.fixture
def fake_docx():
    """返回偽裝成 DOCX 的 bytes（ZIP 格式起始，僅用於測試路由，不測試實際轉換）。"""
    import zipfile
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<?xml?>")
    buf.seek(0)
    return buf


@pytest.fixture
def fake_txt():
    """返回純文字 bytes。"""
    return BytesIO("Hello, World! 測試文字內容。\n第二行。".encode("utf-8"))


@pytest.fixture
def fake_html():
    """返回極小的 HTML bytes。"""
    return BytesIO(b"<html><body><p>test</p></body></html>")


@pytest.fixture
def fake_markdown():
    """返回 Markdown bytes。"""
    return BytesIO(b"# Title\n\nSome text.\n")
