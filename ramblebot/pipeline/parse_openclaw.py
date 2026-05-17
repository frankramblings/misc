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
