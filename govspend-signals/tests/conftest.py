import os
import pytest
from pathlib import Path
import tempfile

# Set required env var for all tests
os.environ.setdefault("EDGAR_USER_AGENT", "Test User test@example.com")


@pytest.fixture
def tmp_db(tmp_path):
    from govspend_signals.storage import Storage
    db = Storage(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def tmp_config_file(tmp_path):
    """Write a minimal config.toml for testing."""
    import shutil
    src = Path(__file__).parent.parent / "config.example.toml"
    dst = tmp_path / "config.toml"
    shutil.copy(src, dst)
    return dst
