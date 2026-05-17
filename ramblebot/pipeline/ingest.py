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
