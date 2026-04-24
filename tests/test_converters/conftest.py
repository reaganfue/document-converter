"""
tests/test_converters/conftest.py — 轉換器測試 fixtures 配置

自動在 pytest 收集前生成測試 fixtures（若尚未存在）。
"""

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def pytest_configure(config):
    """pytest 啟動時自動生成 fixtures（一次性）。"""
    from tests.fixtures.generate_fixtures import generate_all
    generate_all(force=False)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """回傳 fixtures 目錄路徑。"""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def sample_pdf(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.pdf"


@pytest.fixture(scope="session")
def sample_docx(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.docx"


@pytest.fixture(scope="session")
def sample_pptx(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.pptx"


@pytest.fixture(scope="session")
def sample_html(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.html"


@pytest.fixture(scope="session")
def sample_md(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.md"


@pytest.fixture(scope="session")
def sample_txt(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.txt"


@pytest.fixture(scope="session")
def sample_png(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.png"


@pytest.fixture
def tmp_output(tmp_path: Path):
    """回傳一個用於測試輸出的 factory，提供臨時目錄。"""
    def _factory(filename: str) -> Path:
        return tmp_path / filename
    return _factory
