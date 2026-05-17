import json
import pytest
from pathlib import Path
from unittest.mock import patch

from pipeline.ingest import (
    compute_file_hash,
    load_state,
    save_state,
    classify_path,
    run_ingest,
)


def test_compute_file_hash_is_stable(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text("hello world")
    h1 = compute_file_hash(f)
    h2 = compute_file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_file_hash_differs_on_content(tmp_path):
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    f1.write_text("hello")
    f2.write_text("world")
    assert compute_file_hash(f1) != compute_file_hash(f2)


def test_load_state_returns_empty_dict_when_missing(tmp_path):
    state = load_state(tmp_path / ".ingest_state.json")
    assert state == {}


def test_save_and_load_state(tmp_path):
    state_path = tmp_path / ".ingest_state.json"
    save_state({"file.jsonl": "abc123"}, state_path)
    loaded = load_state(state_path)
    assert loaded == {"file.jsonl": "abc123"}


def test_classify_path_claude(tmp_path):
    p = tmp_path / "bespin" / "Users" / "frank" / ".claude" / "projects" / "myapp" / "session.jsonl"
    p.parent.mkdir(parents=True)
    p.touch()
    assert classify_path(p) == "claude-code"


def test_classify_path_openclaw_trajectory(tmp_path):
    p = tmp_path / "bespin" / "Users" / "frank" / ".openclaw" / "agents" / "main" / "sessions" / "uuid.trajectory.jsonl"
    p.parent.mkdir(parents=True)
    p.touch()
    assert classify_path(p) == "openclaw"


def test_classify_path_unknown_returns_none(tmp_path):
    p = tmp_path / "bespin" / "random" / "file.jsonl"
    p.parent.mkdir(parents=True)
    p.touch()
    assert classify_path(p) is None


def test_run_ingest_skips_already_processed(tmp_path, claude_fixture):
    archive = tmp_path / "archive"
    archive.mkdir()
    dest = archive / "bespin" / "Users" / "frank" / ".claude" / "projects" / "myapp"
    dest.mkdir(parents=True)
    import shutil
    transcript = dest / "session.jsonl"
    shutil.copy(claude_fixture, transcript)

    state_path = tmp_path / ".ingest_state.json"
    staging_path = tmp_path / ".ingest_staging.jsonl"
    state = {str(transcript): compute_file_hash(transcript)}
    save_state(state, state_path)

    run_ingest(archive, state_path, staging_path)
    # Nothing new was written — file was already in state
    assert not staging_path.exists() or staging_path.read_text().strip() == ""


def test_run_ingest_writes_chunks_for_new_files(tmp_path, claude_fixture):
    archive = tmp_path / "archive"
    archive.mkdir()
    dest = archive / "bespin" / "Users" / "frank" / ".claude" / "projects" / "myapp"
    dest.mkdir(parents=True)
    import shutil
    transcript = dest / "session.jsonl"
    shutil.copy(claude_fixture, transcript)

    state_path = tmp_path / ".ingest_state.json"
    staging_path = tmp_path / ".ingest_staging.jsonl"

    run_ingest(archive, state_path, staging_path)

    lines = staging_path.read_text().splitlines()
    chunks = [json.loads(l) for l in lines if l.strip()]
    assert len(chunks) > 0
    assert all("chunk_id" in c for c in chunks)
