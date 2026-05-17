import pytest
from pathlib import Path
from pipeline.parse_openclaw import parse_openclaw_trajectory
from pipeline.models import Chunk


def test_extracts_user_and_assistant_messages(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    roles = {c.role for c in chunks}
    assert roles == {"user", "assistant"}


def test_skips_non_message_events(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    # tool_use and session_start events should not produce chunks
    texts = [c.text for c in chunks]
    assert not any("echo hello" in t for t in texts)


def test_sets_source_to_openclaw(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    assert all(c.source == "openclaw" for c in chunks)


def test_extracts_provider_and_model(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    assert all(c.provider == "anthropic" for c in chunks)
    assert all(c.model_id == "claude-sonnet-4-6" for c in chunks)


def test_extracts_session_id(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    assert all(c.session_id == "session-xyz" for c in chunks)


def test_skips_tombstone_file(tombstone_fixture):
    chunks = parse_openclaw_trajectory(tombstone_fixture, host="bespin")
    assert chunks == []


def test_skips_pointer_file(tmp_path):
    pointer = tmp_path / "session-abc.trajectory-path.json"
    pointer.write_text('{"traceSchema":"openclaw-trajectory-pointer","sessionId":"s1","path":"/some/path"}')
    chunks = parse_openclaw_trajectory(pointer, host="bespin")
    assert chunks == []


def test_extracts_project_from_session_key(trajectory_fixture):
    chunks = parse_openclaw_trajectory(trajectory_fixture, host="bespin")
    # agent path is "main" from sessionKey
    assert all(c.project == "main" for c in chunks)
