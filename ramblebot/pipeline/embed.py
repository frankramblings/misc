import json
import os
import time
from pathlib import Path
from typing import Iterator

import chromadb
import voyageai

COLLECTION_NAME = "ramblebot"
BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "100"))
BATCH_DELAY = float(os.environ.get("EMBED_BATCH_DELAY", "0"))
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

    lines = [line for line in staging_path.read_text().splitlines() if line.strip()]
    if not lines:
        return

    all_records = [json.loads(line) for line in lines]

    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    voyage = voyageai.Client(api_key=api_key)

    # Filter to records not yet in ChromaDB (deduplicate IDs before querying)
    all_ids = list(dict.fromkeys(r["chunk_id"] for r in all_records))
    existing = collection.get(ids=all_ids, include=[])["ids"]
    existing_set = set(existing)
    new_records = [r for r in all_records if r["chunk_id"] not in existing_set]

    if not new_records:
        return

    for batch in batch_chunks(new_records, BATCH_SIZE):
        if BATCH_DELAY > 0:
            time.sleep(BATCH_DELAY)
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
