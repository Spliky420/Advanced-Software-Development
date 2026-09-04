-- init.sql
-- Schema for the research library database (Enerel's microservice).
-- SQLite. Run once to (re)create the schema; use seed.sql to load sample data.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS document_ai_log;
DROP TABLE IF EXISTS document_embeddings;
DROP TABLE IF EXISTS documents;

-- One row per research document the user has added to their library.
-- Release 0 is single-user (see CLAUDE.md): every query is scoped to
-- DEFAULT_USER_ID, but user_id stays in the schema for real multi-user
-- support later.
--
-- summary_text / key_points / summary_model / summarized_at are the latest
-- AI summary, denormalised onto the row so GET /api/documents/:id/summary is
-- a single lookup. Every summarize call is still fully audited in
-- document_ai_log below, so history is never lost when a re-summarize
-- overwrites these columns.
CREATE TABLE documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    title          TEXT NOT NULL,
    source         TEXT,                   -- publisher / site / author, free text
    doc_type       TEXT NOT NULL,           -- one of validation.DOC_TYPES
    published_on   TEXT,                    -- ISO8601 date, nullable (not always known)
    body_text      TEXT NOT NULL,
    summary_text   TEXT,                    -- latest AI summary, null until summarized
    key_points     TEXT,                    -- latest AI key points, JSON array of strings
    summary_model  TEXT,                    -- OLLAMA_MODEL tag used for the latest summary
    summarized_at  TEXT,                    -- ISO8601 timestamp of the latest summary
    created_at     TEXT NOT NULL,           -- ISO8601 timestamp
    updated_at     TEXT NOT NULL            -- ISO8601 timestamp
);

-- Chunked + embedded text for retrieval. One document produces many chunks.
-- embedding_vector is a JSON-encoded array of floats -- SQLite has no native
-- vector type, and similarity is computed in Python (see retrieval.py), so a
-- portable text encoding is all storage needs to provide.
CREATE TABLE document_embeddings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index       INTEGER NOT NULL,
    chunk_text        TEXT NOT NULL,
    embedding_vector  TEXT NOT NULL,        -- JSON array of floats
    embedding_model   TEXT NOT NULL,        -- OLLAMA_EMBED_MODEL tag used
    UNIQUE (document_id, chunk_index)
);

-- Audit trail of every LLM call made on a user's behalf (summarize and
-- search), mirroring joshua/database's insight_log. prompt_sent already
-- contains any content the model needs -- summarization and embedding are
-- both legitimate model tasks, but no numeric figure is ever computed by the
-- model; see CLAUDE.md's arithmetic rule.
CREATE TABLE document_ai_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    document_id    INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,           -- ISO8601 timestamp
    request_type   TEXT NOT NULL,           -- 'summarize' | 'search'
    prompt_sent    TEXT,
    model_name     TEXT NOT NULL,           -- e.g. llama3.1:8b, qwen2.5:0.5b, nomic-embed-text
    response_text  TEXT
);

CREATE INDEX idx_documents_user_id      ON documents (user_id);
CREATE INDEX idx_documents_doc_type     ON documents (doc_type);
CREATE INDEX idx_documents_published_on ON documents (published_on);
CREATE INDEX idx_document_embeddings_document_id ON document_embeddings (document_id);
CREATE INDEX idx_document_ai_log_user_id ON document_ai_log (user_id);
CREATE INDEX idx_document_ai_log_document_id ON document_ai_log (document_id);
