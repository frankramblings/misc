import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import date

from pipeline.distill import sample_chunks, write_snapshot, run_distill


def _make_archive(tmp_path, n_sessions=5) -> Path:
    """Create a minimal archive with n_sessions Claude Code sessions."""
    archive = tmp_path / "archive"
    for i in range(n_sessions):
        session_dir = archive / "bespin" / "Users" / "frank" / ".claude" / "projects" / f"proj{i}"
        session_dir.mkdir(parents=True)
        session_file = session_dir / f"session{i}.jsonl"
        entries = [
            {"type": "user", "message": {"role": "user", "content": f"question {i}"},
             "sessionId": f"s{i}", "timestamp": f"2026-{i+1:02d}-01T00:00:00Z",
             "cwd": f"/Users/frank/projects/proj{i}"},
            {"type": "assistant", "message": {"role": "assistant", "content": f"answer {i}"},
             "sessionId": f"s{i}", "timestamp": f"2026-{i+1:02d}-01T00:00:05Z",
             "cwd": f"/Users/frank/projects/proj{i}"},
        ]
        session_file.write_text("\n".join(json.dumps(e) for e in entries))
    return archive


def test_sample_chunks_returns_list(tmp_path):
    archive = _make_archive(tmp_path)
    chunks = sample_chunks(archive, max_sessions=3)
    assert isinstance(chunks, list)
    assert len(chunks) > 0


def test_sample_chunks_respects_max_sessions(tmp_path):
    archive = _make_archive(tmp_path, n_sessions=5)
    chunks = sample_chunks(archive, max_sessions=2)
    session_ids = {c.session_id for c in chunks}
    assert len(session_ids) <= 2


def test_write_snapshot_creates_dated_file(tmp_path):
    distilled_dir = tmp_path / "distilled"
    distilled_dir.mkdir()
    symlink = tmp_path / "ramblebot.md"
    today = date(2026, 5, 16)

    write_snapshot("# RambleBot\nPatterns here.", distilled_dir, symlink, today=today)

    expected = distilled_dir / "ramblebot-2026-05-16.md"
    assert expected.exists()
    assert expected.read_text() == "# RambleBot\nPatterns here."


def test_write_snapshot_updates_symlink(tmp_path):
    distilled_dir = tmp_path / "distilled"
    distilled_dir.mkdir()
    symlink = tmp_path / "ramblebot.md"
    today = date(2026, 5, 16)

    write_snapshot("content", distilled_dir, symlink, today=today)

    assert symlink.is_symlink()
    assert symlink.read_text() == "content"


def test_run_distill_calls_openai(tmp_path):
    archive = _make_archive(tmp_path)
    distilled_dir = tmp_path / "distilled"
    distilled_dir.mkdir()
    symlink = tmp_path / "ramblebot.md"

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "# RambleBot\nFrank prefers Python."
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("pipeline.distill.openai.OpenAI", return_value=mock_client):
        run_distill(archive, distilled_dir, symlink, api_key="test-key")

    mock_client.chat.completions.create.assert_called_once()
    assert symlink.exists()
    assert symlink.read_text() == "# RambleBot\nFrank prefers Python."
