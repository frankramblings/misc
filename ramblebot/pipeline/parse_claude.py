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
