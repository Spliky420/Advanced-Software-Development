"""Chunking and embedding/indexing -- prepares a document for retrieval.

Chunking is pure Python and has nothing to do with the LLM. Indexing calls
Ollama once per chunk to get its embedding vector and stores the result via
db.replace_embeddings.

Indexing is deliberately soft-fail: if Ollama or the embedding model is
unavailable, index_document() reports that rather than raising, so creating
or editing a document never fails just because the embedding model has not
been pulled yet. Only /api/documents/:id/search (retrieval) needs indexing to
have actually succeeded.
"""

import db
import llm

CHUNK_SIZE_CHARS = 800
CHUNK_OVERLAP_CHARS = 100


def chunk_text(text, chunk_size=CHUNK_SIZE_CHARS, overlap=CHUNK_OVERLAP_CHARS):
    """Split text into overlapping chunks, breaking on whitespace where
    possible so a chunk does not end mid-word. Returns a list of strings,
    always at least one (even for text shorter than chunk_size).
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            # Prefer to break at the last whitespace inside the window so
            # chunks read as whole words, not just a hard character cut.
            break_at = text.rfind(" ", start, end)
            if break_at > start:
                end = break_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break

        # Next chunk starts `overlap` characters back from where this one
        # ended -- but snapped forward to the next word boundary, so a chunk
        # never starts mid-word the way stepping from `start` by a fixed
        # amount would (that ignores how far `end` actually moved above).
        next_start = max(end - overlap, start + 1)
        if next_start < end:
            space_idx = text.find(" ", next_start, end)
            next_start = space_idx + 1 if space_idx != -1 else end
        start = next_start

    return chunks


def index_document(document_id, body_text, embed_fn=None, store_fn=None):
    """Chunk body_text, embed every chunk, and store the result.

    Returns {"indexed": bool, "chunk_count": int, "embedding_model": str|None,
    "error": str|None}. Never raises -- a failure to reach Ollama is reported
    in the return value, not an exception, so callers (document create/update)
    can save the document regardless.
    """
    embed = embed_fn if embed_fn is not None else llm.embed
    store = store_fn if store_fn is not None else db.replace_embeddings

    chunks = chunk_text(body_text)
    if not chunks:
        store(document_id, [], None)
        return {"indexed": True, "chunk_count": 0, "embedding_model": None, "error": None}

    embedded = []
    embedding_model = None
    try:
        for index, chunk in enumerate(chunks):
            vector, embedding_model = embed(chunk)
            embedded.append(
                {"chunk_index": index, "chunk_text": chunk, "embedding_vector": vector}
            )
    except llm.LLMUnavailableError as exc:
        # Nothing is stored on partial failure -- any previously indexed
        # chunks for this document are left as-is rather than half-replaced.
        return {"indexed": False, "chunk_count": 0, "embedding_model": None, "error": str(exc)}

    store(document_id, embedded, embedding_model)
    return {
        "indexed": True,
        "chunk_count": len(embedded),
        "embedding_model": embedding_model,
        "error": None,
    }
