import pytest
from pathlib import Path
from pipeline.parse_claude import parse_claude_transcript
from pipeline.models import Chunk


def test_extracts_user_and_assistant_messages(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    roles = [c.role for c in chunks]
    assert "user" in roles
    assert "assistant" in roles


def test_skips_permission_mode_and_snapshot_entries(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    # All chunks should have real message text, not metadata
    for c in chunks:
        assert c.text.strip() != ""
        assert "permissionMode" not in c.text


def test_extracts_project_from_cwd(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    assert all(c.project == "myapp" for c in chunks)


def test_extracts_session_id(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    assert all(c.session_id == "session-abc" for c in chunks)


def test_handles_array_content(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    texts = [c.text for c in chunks]
    assert any("what about error handling?" in t for t in texts)


def test_returns_chunks_with_correct_source(claude_fixture):
    chunks = parse_claude_transcript(claude_fixture, host="bespin")
    assert all(c.source == "claude-code" for c in chunks)


def test_skips_subagent_file(tmp_path):
    subagent = tmp_path / "subagents" / "agent-abc.jsonl"
    subagent.parent.mkdir()
    subagent.write_text('{"type":"user","message":{"role":"user","content":"hi"},"sessionId":"s1","timestamp":"2026-01-01T00:00:00Z","cwd":"/foo/bar"}\n')
    chunks = parse_claude_transcript(subagent, host="bespin")
    assert chunks == []
