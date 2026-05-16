# RambleBot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal institutional memory system that sweeps Claude Code and openclaw transcripts from a tailnet, distills them into a "how Frank builds" document, and serves everything as an HTTP MCP server on bespin.

**Architecture:** A Python pipeline on bespin sweeps transcripts from all tailnet hosts nightly, ingests and chunks them into ChromaDB via Voyage AI embeddings, and weekly distills patterns via OpenAI. A persistent HTTP MCP server serves the distilled doc as a passive resource and exposes semantic search as a tool.

**Tech Stack:** Python 3.11+, chromadb, voyageai, openai, mcp + starlette + uvicorn, tiktoken, pytest

---

## File Structure

```
ramblebot/
  sweep.sh                          # existing — modify for bespin
  pipeline/
    __init__.py
    models.py                       # Chunk dataclass, chunking logic
    parse_claude.py                 # Claude Code JSONL parser
    parse_openclaw.py               # openclaw trajectory.jsonl parser
    ingest.py                       # walk archive, dispatch parsers, write staging
    embed.py                        # Voyage AI → ChromaDB
    distill.py                      # OpenAI Codex → dated snapshot
    mcp_server.py                   # HTTP MCP server (resource + search tool)
    pipeline.sh                     # orchestrates sweep → ingest → embed
    requirements.txt
    launchd/
      com.ramblebot.pipeline.plist  # nightly pipeline
      com.ramblebot.distill.plist   # weekly distillation
      com.ramblebot.mcp.plist       # persistent MCP server
    tests/
      __init__.py
      conftest.py
      fixtures/
        sample_claude.jsonl
        sample_trajectory.jsonl
      test_models.py
      test_parse_claude.py
      test_parse_openclaw.py
      test_ingest.py
      test_embed.py
      test_distill.py
      test_mcp_server.py
```

**Runtime layout on bespin** (not in git, created by deploy task):
```
~/ramblebot/
  archive/            # swept transcripts
  chroma/             # ChromaDB vector store
  distilled/          # dated distillation snapshots
  ramblebot.md        # symlink → latest distilled snapshot
  .ingest_state.json  # processed file hashes
  .ingest_staging.jsonl
  .pipeline.lock
  logs/
```

**Environment variables** (set in launchd plists and shell):
- `RAMBLEBOT_HOME` — default `$HOME/ramblebot`
- `VOYAGE_API_KEY`
- `OPENAI_API_KEY`
- `RAMBLEBOT_PORT` — default `8765`

---

## Task 1: Scaffold — requirements, models, chunking

**Files:**
- Create: `ramblebot/pipeline/__init__.py`
- Create: `ramblebot/pipeline/requirements.txt`
- Create: `ramblebot/pipeline/models.py`
- Create: `ramblebot/pipeline/tests/__init__.py`
- Create: `ramblebot/pipeline/tests/conftest.py`
- Create: `ramblebot/pipeline/tests/test_models.py`

- [ ] **Step 1: Create `__init__.py` and `tests/__init__.py`**

```bash
touch ramblebot/pipeline/__init__.py ramblebot/pipeline/tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
chromadb>=0.6.0
voyageai>=0.3.0
openai>=1.30.0
mcp[cli]>=1.3.0
starlette>=0.37.0
uvicorn>=0.29.0
tiktoken>=0.7.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

- [ ] **Step 3: Write the failing tests for models**

`ramblebot/pipeline/tests/test_models.py`:
```python
import pytest
from pipeline.models import Chunk, split_into_chunks


def test_chunk_id_is_stable():
    c = Chunk(
        source="claude-code", host="bespin", project="myapp",
        session_id="s1", timestamp="2026-01-01T00:00:00Z",
        role="user", text="hello world", chunk_index=0,
    )
    assert c.chunk_id == c.chunk_id  # deterministic


def test_chunk_id_differs_on_text_change():
    base = dict(source="claude-code", host="bespin", project="myapp",
                session_id="s1", timestamp="2026-01-01T00:00:00Z",
                role="user", chunk_index=0)
    c1 = Chunk(**base, text="hello")
    c2 = Chunk(**base, text="world")
    assert c1.chunk_id != c2.chunk_id


def test_chunk_id_differs_on_index_change():
    base = dict(source="claude-code", host="bespin", project="myapp",
                session_id="s1", timestamp="2026-01-01T00:00:00Z",
                role="user", text="hello")
    c1 = Chunk(**base, chunk_index=0)
    c2 = Chunk(**base, chunk_index=1)
    assert c1.chunk_id != c2.chunk_id


def test_split_short_text_is_single_chunk():
    result = split_into_chunks("short text")
    assert result == ["short text"]


def test_split_long_text_produces_multiple_chunks():
    # Generate text well over 500 tokens
    long_text = " ".join(["word"] * 1200)
    result = split_into_chunks(long_text)
    assert len(result) > 1


def test_split_chunks_overlap():
    long_text = " ".join([str(i) for i in range(1200)])
    result = split_into_chunks(long_text, max_tokens=100, overlap=20)
    # Adjacent chunks should share some content due to overlap
    assert len(result) >= 2
    # Last token of chunk 0 should appear in chunk 1
    last_word_of_first = result[0].split()[-1]
    assert last_word_of_first in result[1]
```

- [ ] **Step 4: Run tests — verify they fail**

```bash
cd /Users/frankemanuele/Documents/GitHub/misc/misc
python -m pytest ramblebot/pipeline/tests/test_models.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 5: Install dependencies**

```bash
cd ramblebot/pipeline && pip install -r requirements.txt
```

- [ ] **Step 6: Write `models.py`**

`ramblebot/pipeline/models.py`:
```python
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import tiktoken


_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    source: str           # "claude-code" | "openclaw"
    host: str
    project: str
    session_id: str
    timestamp: str
    role: str             # "user" | "assistant"
    text: str
    chunk_index: int = 0
    provider: Optional[str] = None
    model_id: Optional[str] = None

    @property
    def chunk_id(self) -> str:
        raw = f"{self.session_id}:{self.role}:{self.chunk_index}:{self.text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def metadata(self) -> dict:
        return {
            "source": self.source,
            "host": self.host,
            "project": self.project,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "role": self.role,
            "chunk_index": self.chunk_index,
            "provider": self.provider or "",
            "model_id": self.model_id or "",
        }


def split_into_chunks(
    text: str,
    max_tokens: int = 500,
    overlap: int = 50,
) -> list[str]:
    tokens = _ENC.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunks.append(_ENC.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += max_tokens - overlap
    return chunks
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_models.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 8: Commit**

```bash
git add ramblebot/pipeline/
git commit -m "feat(ramblebot): scaffold pipeline — models and chunking"
```

---

## Task 2: Fixture files for tests

**Files:**
- Create: `ramblebot/pipeline/tests/fixtures/sample_claude.jsonl`
- Create: `ramblebot/pipeline/tests/fixtures/sample_trajectory.jsonl`
- Create: `ramblebot/pipeline/tests/conftest.py`

- [ ] **Step 1: Write Claude Code fixture**

`ramblebot/pipeline/tests/fixtures/sample_claude.jsonl`:
```jsonl
{"type":"permission-mode","permissionMode":"default","sessionId":"session-abc"}
{"type":"file-history-snapshot","messageId":"snap1","snapshot":{},"isSnapshotUpdate":false}
{"parentUuid":null,"isSidechain":false,"promptId":"p1","type":"user","message":{"role":"user","content":"how do I parse a JSON file in Python?"},"uuid":"msg1","timestamp":"2026-01-15T10:00:00.000Z","cwd":"/Users/frank/projects/myapp","sessionId":"session-abc","version":"2.1.0","gitBranch":"main"}
{"parentUuid":"msg1","isSidechain":false,"type":"assistant","message":{"role":"assistant","content":"Use Python's built-in json module:\n\n```python\nimport json\nwith open('file.json') as f:\n    data = json.load(f)\n```"},"uuid":"msg2","timestamp":"2026-01-15T10:00:05.000Z","cwd":"/Users/frank/projects/myapp","sessionId":"session-abc","version":"2.1.0"}
{"parentUuid":"msg2","isSidechain":false,"type":"user","message":{"role":"user","content":[{"type":"text","text":"what about error handling?"}]},"uuid":"msg3","timestamp":"2026-01-15T10:00:10.000Z","cwd":"/Users/frank/projects/myapp","sessionId":"session-abc","version":"2.1.0"}
{"parentUuid":"msg3","isSidechain":false,"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Wrap it in try/except json.JSONDecodeError."}]},"uuid":"msg4","timestamp":"2026-01-15T10:00:15.000Z","cwd":"/Users/frank/projects/myapp","sessionId":"session-abc","version":"2.1.0"}
```

- [ ] **Step 2: Write openclaw trajectory fixture**

`ramblebot/pipeline/tests/fixtures/sample_trajectory.jsonl`:
```jsonl
{"seq":1,"ts":"2026-01-15T11:00:00.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"session_start","cwd":"/Users/frank/projects/undercast"}}
{"seq":2,"ts":"2026-01-15T11:00:01.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"message","role":"user","content":"explain how async/await works in Python"}}
{"seq":3,"ts":"2026-01-15T11:00:05.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"message","role":"assistant","content":"async/await lets you write concurrent code without threads. An async function returns a coroutine."}}
{"seq":4,"ts":"2026-01-15T11:00:08.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"tool_use","tool":"bash","input":"echo hello"}}
{"seq":5,"ts":"2026-01-15T11:00:10.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"message","role":"user","content":"what about error handling in async code?"}}
{"seq":6,"ts":"2026-01-15T11:00:14.000Z","sessionId":"session-xyz","sessionKey":"main","runId":"run1","provider":"anthropic","modelId":"claude-sonnet-4-6","data":{"type":"message","role":"assistant","content":"Use try/except inside async functions just like sync code."}}
```

- [ ] **Step 3: Write `conftest.py`**

`ramblebot/pipeline/tests/conftest.py`:
```python
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
```

- [ ] **Step 4: Commit**

```bash
git add ramblebot/pipeline/tests/
git commit -m "test(ramblebot): add fixtures and conftest"
```

---

## Task 3: Claude Code parser

**Files:**
- Create: `ramblebot/pipeline/parse_claude.py`
- Create: `ramblebot/pipeline/tests/test_parse_claude.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_parse_claude.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest ramblebot/pipeline/tests/test_parse_claude.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'parse_claude_transcript'`

- [ ] **Step 3: Write `parse_claude.py`**

`ramblebot/pipeline/parse_claude.py`:
```python
import json
from pathlib import Path
from typing import Union

from .models import Chunk, split_into_chunks

# Entry types that carry no conversational content
_SKIP_TYPES = {
    "permission-mode",
    "file-history-snapshot",
    "deferred_tools_delta",
}


def _extract_text(content: Union[str, list]) -> str:
    if isinstance(content, str):
        return content
    # Array of content blocks — join text blocks
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _project_from_cwd(cwd: str) -> str:
    """Last path component of cwd as project name."""
    return Path(cwd).name if cwd else "unknown"


def parse_claude_transcript(path: Path, host: str) -> list[Chunk]:
    """Parse a Claude Code JSONL transcript into chunks.

    Returns [] for subagent files (path contains /subagents/).
    """
    if "subagents" in path.parts:
        return []

    chunks = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        entry_type = entry.get("type", "")
        if entry_type in _SKIP_TYPES:
            continue

        message = entry.get("message", {})
        role = message.get("role", "")
        if role not in ("user", "assistant"):
            continue

        content = message.get("content", "")
        text = _extract_text(content).strip()
        if not text:
            continue

        cwd = entry.get("cwd", "")
        session_id = entry.get("sessionId", "")
        timestamp = entry.get("timestamp", "")
        project = _project_from_cwd(cwd)

        for idx, chunk_text in enumerate(split_into_chunks(text)):
            chunks.append(Chunk(
                source="claude-code",
                host=host,
                project=project,
                session_id=session_id,
                timestamp=timestamp,
                role=role,
                text=chunk_text,
                chunk_index=idx,
            ))

    return chunks
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_parse_claude.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/parse_claude.py ramblebot/pipeline/tests/test_parse_claude.py
git commit -m "feat(ramblebot): Claude Code JSONL parser"
```

---

## Task 4: openclaw trajectory parser

**Files:**
- Create: `ramblebot/pipeline/parse_openclaw.py`
- Create: `ramblebot/pipeline/tests/test_parse_openclaw.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_parse_openclaw.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest ramblebot/pipeline/tests/test_parse_openclaw.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `parse_openclaw.py`**

`ramblebot/pipeline/parse_openclaw.py`:
```python
import json
from pathlib import Path

from .models import Chunk, split_into_chunks

_TOMBSTONE_MARKERS = (".deleted.", ".reset.")


def _is_tombstone(path: Path) -> bool:
    return any(m in path.name for m in _TOMBSTONE_MARKERS)


def _is_pointer(path: Path) -> bool:
    return path.name.endswith(".trajectory-path.json")


def parse_openclaw_trajectory(path: Path, host: str) -> list[Chunk]:
    """Parse an openclaw trajectory.jsonl file into chunks.

    Returns [] for tombstones and pointer files.
    Extracts only events where data.type == "message" and
    data.role is "user" or "assistant".
    """
    if _is_tombstone(path) or _is_pointer(path):
        return []

    chunks = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        data = event.get("data", {})
        if not isinstance(data, dict):
            continue
        if data.get("type") != "message":
            continue

        role = data.get("role", "")
        if role not in ("user", "assistant"):
            continue

        content = data.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content)
        text = text.strip()
        if not text:
            continue

        session_id = event.get("sessionId", "")
        timestamp = event.get("ts", "")
        provider = event.get("provider", "")
        model_id = event.get("modelId", "")
        project = event.get("sessionKey", "unknown")

        for idx, chunk_text in enumerate(split_into_chunks(text)):
            chunks.append(Chunk(
                source="openclaw",
                host=host,
                project=project,
                session_id=session_id,
                timestamp=timestamp,
                role=role,
                text=chunk_text,
                chunk_index=idx,
                provider=provider,
                model_id=model_id,
            ))

    return chunks
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_parse_openclaw.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/parse_openclaw.py ramblebot/pipeline/tests/test_parse_openclaw.py
git commit -m "feat(ramblebot): openclaw trajectory.jsonl parser"
```

---

## Task 5: ingest.py — archive walker and state tracking

**Files:**
- Create: `ramblebot/pipeline/ingest.py`
- Create: `ramblebot/pipeline/tests/test_ingest.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_ingest.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest ramblebot/pipeline/tests/test_ingest.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `ingest.py`**

`ramblebot/pipeline/ingest.py`:
```python
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import Chunk
from .parse_claude import parse_claude_transcript
from .parse_openclaw import parse_openclaw_trajectory


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict, state_path: Path) -> None:
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(state_path)


def classify_path(path: Path) -> Optional[str]:
    parts = path.parts
    if ".claude" in parts and path.suffix == ".jsonl":
        return "claude-code"
    if ".openclaw" in parts and "trajectory" in path.name and path.suffix == ".jsonl":
        return "openclaw"
    return None


def _host_from_archive(path: Path, archive: Path) -> str:
    rel = path.relative_to(archive)
    return rel.parts[0]


def run_ingest(archive: Path, state_path: Path, staging_path: Path) -> None:
    state = load_state(state_path)
    new_chunks: list[Chunk] = []
    updated_state = dict(state)

    for jsonl_file in sorted(archive.rglob("*.jsonl")):
        kind = classify_path(jsonl_file)
        if kind is None:
            continue

        file_key = str(jsonl_file)
        current_hash = compute_file_hash(jsonl_file)
        if state.get(file_key) == current_hash:
            continue

        host = _host_from_archive(jsonl_file, archive)
        if kind == "claude-code":
            chunks = parse_claude_transcript(jsonl_file, host=host)
        else:
            chunks = parse_openclaw_trajectory(jsonl_file, host=host)

        new_chunks.extend(chunks)
        updated_state[file_key] = current_hash

    if new_chunks:
        with staging_path.open("a", encoding="utf-8") as f:
            for chunk in new_chunks:
                record = asdict(chunk)
                record["chunk_id"] = chunk.chunk_id
                f.write(json.dumps(record) + "\n")

    save_state(updated_state, state_path)


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    run_ingest(
        archive=ramblebot_home / "archive",
        state_path=ramblebot_home / ".ingest_state.json",
        staging_path=ramblebot_home / ".ingest_staging.jsonl",
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_ingest.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/ingest.py ramblebot/pipeline/tests/test_ingest.py
git commit -m "feat(ramblebot): ingest — archive walker, state tracking, staging"
```

---

## Task 6: embed.py — Voyage AI + ChromaDB

**Files:**
- Create: `ramblebot/pipeline/embed.py`
- Create: `ramblebot/pipeline/tests/test_embed.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_embed.py`:
```python
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.embed import batch_chunks, run_embed, COLLECTION_NAME


def _make_staging(tmp_path, chunks: list[dict]) -> Path:
    p = tmp_path / ".ingest_staging.jsonl"
    p.write_text("\n".join(json.dumps(c) for c in chunks))
    return p


def test_batch_chunks_splits_correctly():
    items = list(range(250))
    batches = list(batch_chunks(items, size=100))
    assert len(batches) == 3
    assert len(batches[0]) == 100
    assert len(batches[2]) == 50


def test_batch_chunks_empty():
    assert list(batch_chunks([], size=100)) == []


def test_run_embed_skips_existing_chunks(tmp_path):
    staging = _make_staging(tmp_path, [
        {"chunk_id": "aaa", "text": "hello", "source": "claude-code",
         "host": "bespin", "project": "myapp", "session_id": "s1",
         "timestamp": "2026-01-01T00:00:00Z", "role": "user",
         "chunk_index": 0, "provider": None, "model_id": None},
    ])
    chroma_dir = tmp_path / "chroma"

    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": ["aaa"]}  # already exists

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    mock_voyage = MagicMock()

    with patch("pipeline.embed.chromadb.PersistentClient", return_value=mock_client), \
         patch("pipeline.embed.voyageai.Client", return_value=mock_voyage):
        run_embed(staging, chroma_dir, api_key="test-key")

    mock_voyage.embed.assert_not_called()


def test_run_embed_embeds_new_chunks(tmp_path):
    staging = _make_staging(tmp_path, [
        {"chunk_id": "bbb", "text": "new chunk", "source": "claude-code",
         "host": "bespin", "project": "myapp", "session_id": "s1",
         "timestamp": "2026-01-01T00:00:00Z", "role": "user",
         "chunk_index": 0, "provider": None, "model_id": None},
    ])
    chroma_dir = tmp_path / "chroma"

    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}  # not yet indexed

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    mock_voyage = MagicMock()
    mock_voyage.embed.return_value = MagicMock(embeddings=[[0.1, 0.2, 0.3]])

    with patch("pipeline.embed.chromadb.PersistentClient", return_value=mock_client), \
         patch("pipeline.embed.voyageai.Client", return_value=mock_voyage):
        run_embed(staging, chroma_dir, api_key="test-key")

    mock_voyage.embed.assert_called_once()
    mock_collection.upsert.assert_called_once()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest ramblebot/pipeline/tests/test_embed.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `embed.py`**

`ramblebot/pipeline/embed.py`:
```python
import json
import os
import time
from pathlib import Path
from typing import Iterator

import chromadb
import voyageai

COLLECTION_NAME = "ramblebot"
BATCH_SIZE = 100
MAX_RETRIES = 3


def batch_chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _embed_with_retry(client: voyageai.Client, texts: list[str]) -> list:
    delay = 1
    for attempt in range(MAX_RETRIES):
        try:
            result = client.embed(texts, model="voyage-3-lite")
            return result.embeddings
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                raise
            if "429" in str(exc) or "rate" in str(exc).lower():
                time.sleep(delay)
                delay *= 2
            else:
                raise


def run_embed(staging_path: Path, chroma_dir: Path, api_key: str) -> None:
    if not staging_path.exists():
        return

    lines = [l for l in staging_path.read_text().splitlines() if l.strip()]
    if not lines:
        return

    all_records = [json.loads(l) for l in lines]

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    voyage = voyageai.Client(api_key=api_key)

    # Filter to records not yet in ChromaDB
    all_ids = [r["chunk_id"] for r in all_records]
    existing = collection.get(ids=all_ids, include=[])["ids"]
    existing_set = set(existing)
    new_records = [r for r in all_records if r["chunk_id"] not in existing_set]

    if not new_records:
        return

    for batch in batch_chunks(new_records, BATCH_SIZE):
        texts = [r["text"] for r in batch]
        embeddings = _embed_with_retry(voyage, texts)
        collection.upsert(
            ids=[r["chunk_id"] for r in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{k: v for k, v in r.items()
                        if k not in ("chunk_id", "text") and v is not None}
                       for r in batch],
        )

    # Clear staging file after successful embed
    staging_path.write_text("")


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    run_embed(
        staging_path=ramblebot_home / ".ingest_staging.jsonl",
        chroma_dir=ramblebot_home / "chroma",
        api_key=os.environ["VOYAGE_API_KEY"],
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_embed.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/embed.py ramblebot/pipeline/tests/test_embed.py
git commit -m "feat(ramblebot): embed — Voyage AI batching + ChromaDB upsert"
```

---

## Task 7: distill.py — OpenAI Codex → dated snapshot

**Files:**
- Create: `ramblebot/pipeline/distill.py`
- Create: `ramblebot/pipeline/tests/test_distill.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_distill.py`:
```python
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
             "sessionId": f"s{i}", "timestamp": f"2026-0{i+1}-01T00:00:00Z",
             "cwd": f"/Users/frank/projects/proj{i}"},
            {"type": "assistant", "message": {"role": "assistant", "content": f"answer {i}"},
             "sessionId": f"s{i}", "timestamp": f"2026-0{i+1}-01T00:00:05Z",
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest ramblebot/pipeline/tests/test_distill.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `distill.py`**

`ramblebot/pipeline/distill.py`:
```python
import os
import random
from dataclasses import asdict
from datetime import date
from pathlib import Path

import openai

from .ingest import classify_path, _host_from_archive
from .models import Chunk
from .parse_claude import parse_claude_transcript
from .parse_openclaw import parse_openclaw_trajectory

DISTILL_MODEL = "openai-codex/gpt-5.3-codex"
MAX_SESSIONS = 200
SAMPLES_PER_SESSION = 3

SYSTEM_PROMPT = """\
You are analyzing conversation transcripts between a developer named Frank and AI coding \
assistants (Claude Code and openclaw). Create a profile document capturing Frank's \
patterns as a builder.

Identify and document:
1. **Naming conventions** — how Frank names variables, functions, files, and projects
2. **Architectural decisions** — patterns Frank prefers (languages, databases, frameworks)
3. **Recurring instructions** — what Frank repeatedly tells AI assistants; corrections he often makes
4. **Debugging approach** — how Frank frames problems; what info he always wants first
5. **Tool and workflow preferences** — CLI tools, editors, deployment targets
6. **Communication style** — how Frank phrases requests; level of detail provided
7. **Project context** — active projects and their goals

Write in third person as a markdown document. Be specific and concrete. \
Use examples from the transcripts. Do not invent patterns not present in the data.\
"""


def sample_chunks(archive: Path, max_sessions: int = MAX_SESSIONS) -> list[Chunk]:
    """Sample chunks from the archive, weighted toward recent sessions."""
    all_files = sorted(archive.rglob("*.jsonl"))
    classified = [(f, classify_path(f)) for f in all_files]
    classified = [(f, k) for f, k in classified if k is not None]

    # Group by session: parse lightly to get session_id + timestamp
    sessions: dict[str, tuple[str, list]] = {}  # session_id → (timestamp, [file])
    for f, kind in classified:
        host = _host_from_archive(f, archive)
        if kind == "claude-code":
            chunks = parse_claude_transcript(f, host=host)
        else:
            chunks = parse_openclaw_trajectory(f, host=host)
        for c in chunks:
            if c.session_id not in sessions:
                sessions[c.session_id] = (c.timestamp, [])
            sessions[c.session_id][1].append(c)

    # Sort sessions by timestamp descending (most recent first)
    sorted_sessions = sorted(sessions.values(), key=lambda x: x[0], reverse=True)
    selected = sorted_sessions[:max_sessions]

    sampled: list[Chunk] = []
    for _ts, chunks in selected:
        user_chunks = [c for c in chunks if c.role == "user"]
        asst_chunks = [c for c in chunks if c.role == "assistant"]
        sampled.extend(random.sample(user_chunks, min(SAMPLES_PER_SESSION, len(user_chunks))))
        sampled.extend(random.sample(asst_chunks, min(SAMPLES_PER_SESSION, len(asst_chunks))))

    return sampled


def write_snapshot(
    content: str,
    distilled_dir: Path,
    symlink: Path,
    today: date | None = None,
) -> None:
    today = today or date.today()
    snapshot = distilled_dir / f"ramblebot-{today.isoformat()}.md"
    snapshot.write_text(content, encoding="utf-8")
    if symlink.exists() or symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(snapshot)


def run_distill(
    archive: Path,
    distilled_dir: Path,
    symlink: Path,
    api_key: str,
) -> None:
    chunks = sample_chunks(archive)
    if not chunks:
        return

    transcript_text = "\n\n---\n\n".join(
        f"[{c.source} | {c.host} | {c.project} | {c.role}]\n{c.text}"
        for c in chunks
    )
    user_message = f"TRANSCRIPT EXCERPTS:\n\n{transcript_text}"

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=DISTILL_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    content = response.choices[0].message.content
    write_snapshot(content, distilled_dir, symlink)


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    run_distill(
        archive=ramblebot_home / "archive",
        distilled_dir=ramblebot_home / "distilled",
        symlink=ramblebot_home / "ramblebot.md",
        api_key=os.environ["OPENAI_API_KEY"],
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_distill.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/distill.py ramblebot/pipeline/tests/test_distill.py
git commit -m "feat(ramblebot): distill — sample chunks, call OpenAI, write dated snapshot"
```

---

## Task 8: pipeline.sh + sweep.sh update

**Files:**
- Modify: `ramblebot/sweep.sh`
- Create: `ramblebot/pipeline/pipeline.sh`

- [ ] **Step 1: Update `sweep.sh` for bespin**

In `ramblebot/sweep.sh`, change the HOSTS array and add openclaw to the local rsync includes:

```bash
# Change HOSTS array (around line 21):
HOSTS=(
  "frank@endor.bicolor-triceratops.ts.net"        # Ubuntu
  "frank@wis-a422.bicolor-triceratops.ts.net"     # MacBook Pro
  "local:bespin"                                   # Mac Mini (this machine)
)
```

Add openclaw to the rsync filter block for the local host. In the rsync call (around line 126), add openclaw includes **before** the `--exclude='*'` line:

```bash
    rsync -avhR --prune-empty-dirs \
      --include='*/' \
      --include='*.jsonl' \
      --include='*.trajectory.jsonl' \
      --include='*.trajectory-path.json' \
      --include='.claude.json' \
      --include='settings.json' \
      --include='settings.local.json' \
      --exclude='*' \
      "$src" "$DEST/$short/"
```

Also update the discovery script to also discover `.openclaw` dirs on the local host. After the existing `[ -d "$HOME/.claude/projects" ] && collect="$collect` block, add:

```bash
# openclaw transcripts (local bespin only — added by pipeline)
[ -d "$HOME/.openclaw/agents" ] && collect="$collect
$HOME/.openclaw"
```

- [ ] **Step 2: Test sweep.sh still runs correctly**

```bash
bash ramblebot/sweep.sh /tmp/ramblebot-test-archive 2>&1 | tail -5
```

Expected: output ends with `N transcript files collected` (no errors)

- [ ] **Step 3: Write `pipeline.sh`**

`ramblebot/pipeline/pipeline.sh`:
```bash
#!/usr/bin/env bash
# RambleBot nightly pipeline: sweep → ingest → embed
# Uses a lockfile to prevent overlapping runs.
set -euo pipefail

RAMBLEBOT_HOME="${RAMBLEBOT_HOME:-$HOME/ramblebot}"
LOCK="$RAMBLEBOT_HOME/.pipeline.lock"
LOG="$RAMBLEBOT_HOME/logs/pipeline.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$RAMBLEBOT_HOME/logs"

# Acquire lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -u +%FT%TZ) pipeline already running, skipping" >> "$LOG"
  exit 0
fi
trap 'flock -u 9; rm -f "$LOCK"' EXIT

echo "$(date -u +%FT%TZ) pipeline starting" >> "$LOG"

# Sweep
bash "$SCRIPT_DIR/../sweep.sh" "$RAMBLEBOT_HOME/archive" >> "$LOG" 2>&1

# Ingest
cd "$SCRIPT_DIR"
python -m pipeline.ingest >> "$LOG" 2>&1

# Embed
python -m pipeline.embed >> "$LOG" 2>&1

echo "$(date -u +%FT%TZ) pipeline complete" >> "$LOG"
```

```bash
chmod +x ramblebot/pipeline/pipeline.sh
```

- [ ] **Step 4: Test pipeline.sh lockfile (run two in parallel)**

```bash
RAMBLEBOT_HOME=/tmp/ramblebot-lock-test bash ramblebot/pipeline/pipeline.sh &
RAMBLEBOT_HOME=/tmp/ramblebot-lock-test bash ramblebot/pipeline/pipeline.sh
wait
cat /tmp/ramblebot-lock-test/logs/pipeline.log
```

Expected: one run logs `pipeline starting`, the other logs `pipeline already running, skipping`

- [ ] **Step 5: Commit**

```bash
git add ramblebot/sweep.sh ramblebot/pipeline/pipeline.sh
git commit -m "feat(ramblebot): update sweep for bespin + add pipeline.sh with lockfile"
```

---

## Task 9: mcp_server.py

**Files:**
- Create: `ramblebot/pipeline/mcp_server.py`
- Create: `ramblebot/pipeline/tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests**

`ramblebot/pipeline/tests/test_mcp_server.py`:
```python
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport

from pipeline.mcp_server import create_app, IDENTITY_URI


@pytest.fixture
def ramblebot_home(tmp_path):
    home = tmp_path / "ramblebot"
    distilled = home / "distilled"
    distilled.mkdir(parents=True)
    doc = distilled / "ramblebot-2026-05-16.md"
    doc.write_text("# RambleBot\nFrank prefers Python.")
    symlink = home / "ramblebot.md"
    symlink.symlink_to(doc)
    chroma = home / "chroma"
    chroma.mkdir()
    return home


def test_app_routes_exist(ramblebot_home):
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection

    with patch("pipeline.mcp_server.chromadb.PersistentClient", return_value=mock_chroma):
        app = create_app(ramblebot_home, voyage_api_key="test")

    route_paths = {r.path for r in app.routes}
    assert "/sse" in route_paths
    assert "/messages" in route_paths
```

- [ ] **Step 2: Run test — verify it fails**

```bash
python -m pytest ramblebot/pipeline/tests/test_mcp_server.py -v 2>&1 | head -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `mcp_server.py`**

`ramblebot/pipeline/mcp_server.py`:
```python
import os
from pathlib import Path

import chromadb
import uvicorn
import voyageai
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Resource, TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from .embed import COLLECTION_NAME

IDENTITY_URI = "ramblebot://identity"
SEARCH_RESULTS_K = 5


def create_app(ramblebot_home: Path, voyage_api_key: str) -> Starlette:
    ramblebot_md = ramblebot_home / "ramblebot.md"
    chroma_dir = ramblebot_home / "chroma"

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
    voyage = voyageai.Client(api_key=voyage_api_key)

    server = Server("ramblebot")

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [Resource(
            uri=IDENTITY_URI,
            name="RambleBot Identity",
            description="Frank's building patterns, preferences, and project context",
            mimeType="text/markdown",
        )]

    @server.read_resource()
    async def read_resource(uri) -> list[TextContent]:
        if str(uri) == IDENTITY_URI:
            if ramblebot_md.exists():
                text = ramblebot_md.read_text(encoding="utf-8")
            else:
                text = "# RambleBot\n\n_No distillation available yet. Run distill.py._"
            return [TextContent(type="text", text=text)]
        raise ValueError(f"Unknown resource: {uri}")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(
            name="ramblebot_search",
            description=(
                "Search Frank's historical Claude Code and openclaw conversations "
                "for relevant context, past decisions, or prior solutions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the conversation history",
                    }
                },
                "required": ["query"],
            },
        )]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "ramblebot_search":
            raise ValueError(f"Unknown tool: {name}")

        query = arguments.get("query", "").strip()
        if not query:
            return [TextContent(type="text", text="No query provided.")]

        result = voyage.embed([query], model="voyage-3-lite")
        query_embedding = result.embeddings[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=SEARCH_RESULTS_K,
            include=["documents", "metadatas"],
        )

        if not results["documents"] or not results["documents"][0]:
            return [TextContent(type="text", text="No relevant results found.")]

        parts = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            source = meta.get("source", "unknown")
            host = meta.get("host", "")
            project = meta.get("project", "")
            role = meta.get("role", "")
            ts = meta.get("timestamp", "")[:10]
            parts.append(f"**[{source} | {host} | {project} | {role} | {ts}]**\n{doc}")

        return [TextContent(type="text", text="\n\n---\n\n".join(parts))]

    sse_transport = SseServerTransport("/messages")

    async def handle_sse(request: Request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options(),
            )

    return Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse_transport.handle_post_message),
    ])


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    voyage_api_key = os.environ["VOYAGE_API_KEY"]
    port = int(os.environ.get("RAMBLEBOT_PORT", "8765"))
    app = create_app(ramblebot_home, voyage_api_key)
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest ramblebot/pipeline/tests/test_mcp_server.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ramblebot/pipeline/mcp_server.py ramblebot/pipeline/tests/test_mcp_server.py
git commit -m "feat(ramblebot): HTTP MCP server — identity resource + semantic search tool"
```

---

## Task 10: launchd plists

**Files:**
- Create: `ramblebot/pipeline/launchd/com.ramblebot.pipeline.plist`
- Create: `ramblebot/pipeline/launchd/com.ramblebot.distill.plist`
- Create: `ramblebot/pipeline/launchd/com.ramblebot.mcp.plist`

- [ ] **Step 1: Write nightly pipeline plist**

`ramblebot/pipeline/launchd/com.ramblebot.pipeline.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ramblebot.pipeline</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/admin/misc/ramblebot/pipeline/pipeline.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RAMBLEBOT_HOME</key>
    <string>/Users/admin/ramblebot</string>
    <key>VOYAGE_API_KEY</key>
    <string>REPLACE_WITH_VOYAGE_KEY</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>2</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/admin/ramblebot/logs/pipeline-launchd.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/admin/ramblebot/logs/pipeline-launchd.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

- [ ] **Step 2: Write weekly distillation plist**

`ramblebot/pipeline/launchd/com.ramblebot.distill.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ramblebot.distill</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>pipeline.distill</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/admin/misc/ramblebot/pipeline</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RAMBLEBOT_HOME</key>
    <string>/Users/admin/ramblebot</string>
    <key>OPENAI_API_KEY</key>
    <string>REPLACE_WITH_OPENAI_KEY</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>0</integer>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/admin/ramblebot/logs/distill.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/admin/ramblebot/logs/distill.log</string>
</dict>
</plist>
```

- [ ] **Step 3: Write persistent MCP server plist**

`ramblebot/pipeline/launchd/com.ramblebot.mcp.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ramblebot.mcp</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>pipeline.mcp_server</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/admin/misc/ramblebot/pipeline</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RAMBLEBOT_HOME</key>
    <string>/Users/admin/ramblebot</string>
    <key>VOYAGE_API_KEY</key>
    <string>REPLACE_WITH_VOYAGE_KEY</string>
    <key>RAMBLEBOT_PORT</key>
    <string>8765</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/admin/ramblebot/logs/mcp_server.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/admin/ramblebot/logs/mcp_server.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Commit**

```bash
git add ramblebot/pipeline/launchd/
git commit -m "feat(ramblebot): launchd plists for pipeline, distill, and MCP server"
```

---

## Task 11: Deploy to bespin

- [ ] **Step 1: Push the branch to remote**

```bash
git push -u origin claude/transcript-search-tool-6828z
```

- [ ] **Step 2: SSH to bespin and clone/pull the repo**

```bash
ssh admin@bespin.bicolor-triceratops.ts.net
```

On bespin:
```bash
cd ~ && git clone <your-misc-repo-url> misc || (cd misc && git pull)
```

- [ ] **Step 3: Create ramblebot home directory structure on bespin**

```bash
mkdir -p ~/ramblebot/{archive,chroma,distilled,logs}
```

- [ ] **Step 4: Install Python dependencies on bespin**

```bash
cd ~/misc/ramblebot/pipeline
pip3 install -r requirements.txt
```

Note the Python path used by pip3 — replace `/usr/bin/python3` in all three launchd plists with that same interpreter path (e.g. `/usr/local/bin/python3` or `/opt/homebrew/bin/python3`):
```bash
which python3   # note this path
```

- [ ] **Step 5: Set up API keys in plist files**

```bash
# Replace placeholder keys in plists before loading
sed -i '' 's/REPLACE_WITH_VOYAGE_KEY/your-actual-voyage-key/' ~/misc/ramblebot/pipeline/launchd/com.ramblebot.pipeline.plist
sed -i '' 's/REPLACE_WITH_VOYAGE_KEY/your-actual-voyage-key/' ~/misc/ramblebot/pipeline/launchd/com.ramblebot.mcp.plist
sed -i '' 's/REPLACE_WITH_OPENAI_KEY/your-actual-openai-key/' ~/misc/ramblebot/pipeline/launchd/com.ramblebot.distill.plist
```

- [ ] **Step 6: Set up passwordless SSH from bespin → wis-a422 and bespin → endor**

```bash
# On bespin — generate key if needed
ssh-keygen -t ed25519 -f ~/.ssh/id_ramblebot -N ""

# Copy to wis-a422 (run from bespin, approve password prompt once)
ssh-copy-id -i ~/.ssh/id_ramblebot.pub frank@wis-a422.bicolor-triceratops.ts.net

# Copy to endor
ssh-copy-id -i ~/.ssh/id_ramblebot.pub frank@endor.bicolor-triceratops.ts.net
```

Add to `~/.ssh/config` on bespin:
```
Host wis-a422.bicolor-triceratops.ts.net
    IdentityFile ~/.ssh/id_ramblebot
Host endor.bicolor-triceratops.ts.net
    IdentityFile ~/.ssh/id_ramblebot
```

- [ ] **Step 7: Run pipeline manually as smoke test**

```bash
RAMBLEBOT_HOME=~/ramblebot VOYAGE_API_KEY=your-key bash ~/misc/ramblebot/pipeline/pipeline.sh
```

Expected: logs show `pipeline starting` → sweep output → `pipeline complete`

- [ ] **Step 8: Run distillation manually**

```bash
cd ~/misc/ramblebot/pipeline
RAMBLEBOT_HOME=~/ramblebot OPENAI_API_KEY=your-key python3 -m pipeline.distill
```

Expected: `~/ramblebot/distilled/ramblebot-YYYY-MM-DD.md` created and `~/ramblebot/ramblebot.md` symlink updated

- [ ] **Step 9: Start MCP server manually and verify it responds**

```bash
cd ~/misc/ramblebot/pipeline
RAMBLEBOT_HOME=~/ramblebot VOYAGE_API_KEY=your-key RAMBLEBOT_PORT=8765 python3 -m pipeline.mcp_server &
curl -s http://localhost:8765/sse --max-time 2 | head -5
```

Expected: SSE stream begins (starts with `data:` or similar event prefix)

- [ ] **Step 10: Load launchd plists**

```bash
cp ~/misc/ramblebot/pipeline/launchd/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ramblebot.pipeline.plist
launchctl load ~/Library/LaunchAgents/com.ramblebot.distill.plist
launchctl load ~/Library/LaunchAgents/com.ramblebot.mcp.plist
launchctl list | grep ramblebot
```

Expected: all three services appear in list; `com.ramblebot.mcp` shows PID (running)

- [ ] **Step 11: Configure MCP in Claude Code on each machine**

On each machine (wis-a422, endor, bespin), add to `~/.claude/mcp_servers.json`:

```json
{
  "mcpServers": {
    "ramblebot": {
      "url": "http://bespin.bicolor-triceratops.ts.net:8765/sse"
    }
  }
}
```

On bespin itself, use `http://localhost:8765/sse`.

- [ ] **Step 12: Verify MCP resource loads in Claude Code**

Start a new Claude Code session on wis-a422:
```bash
claude
```

In the session, run:
```
/mcp
```

Expected: `ramblebot` appears in the MCP server list with `ramblebot://identity` resource available.

- [ ] **Step 13: Final commit with deploy notes**

Back on wis-a422:
```bash
git add -A
git commit -m "feat(ramblebot): complete pipeline — sweep, ingest, embed, distill, MCP server"
```

---

## Run All Tests

```bash
cd /Users/frankemanuele/Documents/GitHub/misc/misc
python -m pytest ramblebot/pipeline/tests/ -v
```

Expected: all tests PASS across test_models, test_parse_claude, test_parse_openclaw, test_ingest, test_embed, test_distill, test_mcp_server.
