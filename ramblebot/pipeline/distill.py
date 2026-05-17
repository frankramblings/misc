import os
import random
from datetime import date
from pathlib import Path

import openai

from .ingest import classify_path, _host_from_archive
from .models import Chunk
from .parse_claude import parse_claude_transcript
from .parse_openclaw import parse_openclaw_trajectory

DISTILL_MODEL = "gpt-5.2"
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
    sessions: dict[str, tuple[str, list]] = {}  # session_id → (timestamp, [chunk])
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
    symlink.symlink_to(snapshot.relative_to(symlink.parent))


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
    if not content:
        return
    write_snapshot(content, distilled_dir, symlink)


if __name__ == "__main__":
    ramblebot_home = Path(os.environ.get("RAMBLEBOT_HOME", Path.home() / "ramblebot"))
    run_distill(
        archive=ramblebot_home / "archive",
        distilled_dir=ramblebot_home / "distilled",
        symlink=ramblebot_home / "ramblebot.md",
        api_key=os.environ["OPENAI_API_KEY"],
    )
