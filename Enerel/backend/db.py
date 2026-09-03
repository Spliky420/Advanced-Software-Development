import json
import os
import sqlite3

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "library.db"),
)

# Release 0 is single-user. user_id stays in the schema and every query below
# is still scoped by it, so adding real multi-user support later is a matter
# of passing a real user_id through instead of this constant, not a rewrite.
DEFAULT_USER_ID = 1

DOCUMENT_COLUMNS = ("user_id", "title", "source", "doc_type", "published_on", "body_text")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ping():
    conn = get_connection()
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()


def _document_row_to_dict(row):
    """Decode key_points (stored as a JSON string) back into a list."""
    doc = dict(row)
    raw_key_points = doc.get("key_points")
    if raw_key_points:
        try:
            doc["key_points"] = json.loads(raw_key_points)
        except (TypeError, ValueError):
            doc["key_points"] = []
    else:
        doc["key_points"] = []
    return doc


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------

def list_documents(user_id, filters=None):
    """List documents for user_id, optionally filtered.

    filters (all optional): q (substring match on title or source),
    doc_type (exact match), date_from / date_to (inclusive range on
    published_on, ISO8601 date strings).
    """
    filters = filters or {}
    clauses = ["user_id = ?"]
    params = [user_id]

    q = filters.get("q")
    if q:
        clauses.append("(title LIKE ? OR source LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])

    doc_type = filters.get("doc_type")
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)

    date_from = filters.get("date_from")
    if date_from:
        clauses.append("published_on >= ?")
        params.append(date_from)

    date_to = filters.get("date_to")
    if date_to:
        clauses.append("published_on <= ?")
        params.append(date_to)

    sql = (
        "SELECT id, user_id, title, source, doc_type, published_on, "
        "summary_text, key_points, summary_model, summarized_at, created_at, updated_at "
        "FROM documents WHERE " + " AND ".join(clauses) + " ORDER BY id DESC"
    )

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_document_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_document(document_id, user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id)
        ).fetchone()
        return _document_row_to_dict(row) if row is not None else None
    finally:
        conn.close()


def create_document(data, user_id, created_at):
    payload = dict(data)
    payload["user_id"] = user_id
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO documents
                (user_id, title, source, doc_type, published_on, body_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(payload[col] for col in DOCUMENT_COLUMNS) + (created_at, created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _document_row_to_dict(row)
    finally:
        conn.close()


def update_document(document_id, data, user_id, updated_at):
    payload = dict(data)
    payload["user_id"] = user_id
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE documents SET
                user_id = ?, title = ?, source = ?, doc_type = ?, published_on = ?,
                body_text = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            tuple(payload[col] for col in DOCUMENT_COLUMNS) + (updated_at, document_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id)
        ).fetchone()
        return _document_row_to_dict(row)
    finally:
        conn.close()


def delete_document(document_id, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def store_summary(document_id, user_id, summary_text, key_points, model_name, summarized_at):
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE documents SET
                summary_text = ?, key_points = ?, summary_model = ?, summarized_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (summary_text, json.dumps(key_points), model_name, summarized_at, document_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id)
        ).fetchone()
        return _document_row_to_dict(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# document_embeddings
# ---------------------------------------------------------------------------

def replace_embeddings(document_id, chunks, embedding_model):
    """Replace all stored chunks/embeddings for one document.

    chunks: list of {"chunk_index": int, "chunk_text": str, "embedding_vector": [float, ...]}
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM document_embeddings WHERE document_id = ?", (document_id,))
        conn.executemany(
            """
            INSERT INTO document_embeddings
                (document_id, chunk_index, chunk_text, embedding_vector, embedding_model)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    document_id,
                    c["chunk_index"],
                    c["chunk_text"],
                    json.dumps(c["embedding_vector"]),
                    embedding_model,
                )
                for c in chunks
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_all_embeddings(user_id):
    """All chunks + embeddings across every document owned by user_id, joined
    with the parent document's metadata -- what retrieval.py scores against.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.document_id, e.chunk_index, e.chunk_text, e.embedding_vector,
                   e.embedding_model, d.title, d.source, d.doc_type, d.published_on
            FROM document_embeddings e
            JOIN documents d ON d.id = e.document_id
            WHERE d.user_id = ?
            """,
            (user_id,),
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["embedding_vector"] = json.loads(item["embedding_vector"])
            results.append(item)
        return results
    finally:
        conn.close()


def count_embeddings(document_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM document_embeddings WHERE document_id = ?", (document_id,)
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# document_ai_log
# ---------------------------------------------------------------------------

def create_ai_log(entry, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO document_ai_log
                (user_id, document_id, created_at, request_type, prompt_sent, model_name, response_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                entry.get("document_id"),
                entry["created_at"],
                entry["request_type"],
                entry.get("prompt_sent"),
                entry["model_name"],
                entry.get("response_text"),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM document_ai_log WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()
