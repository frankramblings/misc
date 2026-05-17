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

    # Verify correct arguments were passed to upsert
    call_kwargs = mock_collection.upsert.call_args.kwargs
    assert call_kwargs["ids"] == ["bbb"]
    assert call_kwargs["documents"] == ["new chunk"]
    # None values (provider, model_id) should be filtered out of metadata
    assert "provider" not in call_kwargs["metadatas"][0]
    assert "model_id" not in call_kwargs["metadatas"][0]


def test_run_embed_clears_staging_after_success(tmp_path):
    staging = _make_staging(tmp_path, [
        {"chunk_id": "ccc", "text": "cleared chunk", "source": "claude-code",
         "host": "bespin", "project": "myapp", "session_id": "s1",
         "timestamp": "2026-01-01T00:00:00Z", "role": "user",
         "chunk_index": 0, "provider": None, "model_id": None},
    ])
    chroma_dir = tmp_path / "chroma"

    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    mock_voyage = MagicMock()
    mock_voyage.embed.return_value = MagicMock(embeddings=[[0.1, 0.2, 0.3]])

    with patch("pipeline.embed.chromadb.PersistentClient", return_value=mock_client), \
         patch("pipeline.embed.voyageai.Client", return_value=mock_voyage):
        run_embed(staging, chroma_dir, api_key="test-key")

    assert staging.read_text() == ""


def test_run_embed_returns_early_if_staging_missing(tmp_path):
    chroma_dir = tmp_path / "chroma"
    mock_voyage = MagicMock()
    with patch("pipeline.embed.chromadb.PersistentClient"), \
         patch("pipeline.embed.voyageai.Client", return_value=mock_voyage):
        run_embed(tmp_path / ".ingest_staging.jsonl", chroma_dir, api_key="test-key")
    mock_voyage.embed.assert_not_called()
