import pytest

import llm
from embeddings import chunk_text, index_document

LONG_TEXT = " ".join(f"word{i}" for i in range(400))  # > 800 chars, several chunks


def test_short_text_is_a_single_chunk():
    text = "A short piece of research text."
    assert chunk_text(text, chunk_size=800, overlap=100) == [text]


def test_empty_text_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_long_text_is_split_into_multiple_chunks():
    chunks = chunk_text(LONG_TEXT, chunk_size=800, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 800 for chunk in chunks)


def test_chunks_do_not_split_words_mid_way():
    chunks = chunk_text(LONG_TEXT, chunk_size=800, overlap=100)

    for chunk in chunks:
        assert not chunk.startswith(" ") and not chunk.endswith(" ")
        assert all(token.startswith("word") for token in chunk.split(" ") if token)


def test_concatenated_chunks_cover_the_whole_text_with_overlap():
    chunks = chunk_text(LONG_TEXT, chunk_size=800, overlap=100)

    # Every word should reappear somewhere, i.e. nothing from the middle of
    # the text is silently dropped between chunks.
    covered_words = set().union(*(chunk.split(" ") for chunk in chunks))
    assert set(LONG_TEXT.split(" ")) <= covered_words


def stub_embed(text, dim=4):
    # Deterministic "embedding": vector derived from text length so
    # different chunks get different vectors.
    return [float(len(text) % (i + 2)) for i in range(dim)], "stub-embed-model"


def failing_embed(text):
    raise llm.LLMUnavailableError("could not reach Ollama at http://ollama:11434")


def test_index_document_stores_one_embedding_per_chunk():
    stored = {}

    def store_fn(document_id, chunks, embedding_model):
        stored.update(document_id=document_id, chunks=chunks, embedding_model=embedding_model)

    result = index_document(1, "hello world " * 200, embed_fn=stub_embed, store_fn=store_fn)

    assert result["indexed"] is True
    assert result["error"] is None
    assert result["chunk_count"] == len(stored["chunks"])
    assert stored["document_id"] == 1
    assert stored["embedding_model"] == "stub-embed-model"
    for i, chunk in enumerate(stored["chunks"]):
        assert chunk["chunk_index"] == i
        assert isinstance(chunk["embedding_vector"], list)


def test_index_document_handles_empty_body_text():
    embed_calls = []
    stored = {}

    def embed_fn(text):
        embed_calls.append(text)
        return stub_embed(text)

    def store_fn(document_id, chunks, embedding_model):
        stored["chunks"] = chunks

    result = index_document(1, "   ", embed_fn=embed_fn, store_fn=store_fn)

    assert result["indexed"] is True
    assert result["chunk_count"] == 0
    assert stored["chunks"] == []
    assert embed_calls == []


def test_index_document_soft_fails_when_ollama_unavailable():
    stored_calls = []

    def store_fn(document_id, chunks, embedding_model):
        stored_calls.append((document_id, chunks, embedding_model))

    result = index_document(1, "some body text", embed_fn=failing_embed, store_fn=store_fn)

    assert result["indexed"] is False
    assert result["chunk_count"] == 0
    assert "could not reach Ollama" in result["error"]
    # Nothing is written on partial failure.
    assert stored_calls == []
