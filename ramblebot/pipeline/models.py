import hashlib
from dataclasses import dataclass
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
    if overlap >= max_tokens:
        raise ValueError(f"overlap ({overlap}) must be less than max_tokens ({max_tokens})")
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
