import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def claude_fixture():
    return FIXTURES / "sample_claude.jsonl"


@pytest.fixture
def trajectory_fixture():
    return FIXTURES / "sample_trajectory.jsonl"


@pytest.fixture
def tombstone_fixture(tmp_path):
    """A trajectory file renamed as a tombstone."""
    f = tmp_path / "session-dead.jsonl.deleted.2026-01-01T00:00:00Z"
    f.write_text('{"seq":1,"data":{"type":"message","role":"user","content":"deleted"}}\n')
    return f
