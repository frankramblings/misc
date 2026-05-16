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


def test_split_raises_if_overlap_gte_max_tokens():
    with pytest.raises(ValueError, match="overlap"):
        split_into_chunks("some text", max_tokens=50, overlap=50)
