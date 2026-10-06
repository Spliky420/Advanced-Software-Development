"""ai_plan_log writes for the RAG phase.

Every grounded answer leaves a row with `phase = 'rag'`, carrying the question
asked, the chunk ids that grounded it, the answer and the confidence category.
That is the evidence a report needs to show a grounded response was grounded:
the citation list is in the row, not only on the screen it was rendered on.

`model_name` is the literal `'rag-server'` rather than a model tag. A model
*did* run -- inside the shared RAG server -- but that server does not report
which one in its response, and `rag_pipeline.py` currently hardcodes the tag
rather than reading OLLAMA_MODEL. Writing the tag this backend happens to have
configured would be a guess, and a wrong one whenever the two differ. The
pull request that makes that file read the environment would also let it
report what it used; until then this is the honest value. See the README's
known issues.
"""

from __future__ import annotations

import json
import sqlite3

from ..models import ai_log as ai_log_model
from ..services import dates

PHASE = "rag"

# A grounded answer plus five chunk ids is small; a pathological question is
# not. Truncation keeps one row from dominating the table, and says so.
MAX_RESPONSE_CHARS = 8000


def _json(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, default=str)
    if len(text) <= MAX_RESPONSE_CHARS:
        return text
    return json.dumps(
        {"truncated": True, "original_length": len(text), "head": text[:MAX_RESPONSE_CHARS]},
        sort_keys=True,
    )


def record_answer(conn: sqlite3.Connection, *, goal_id: int | None, result: dict) -> int:
    """Log one grounded answer. `result` is what client.ask returned."""
    citations = [
        citation.get("chunk_id")
        for citation in result.get("citations") or []
        if isinstance(citation, dict)
    ]
    sources = sorted(
        {
            citation.get("source_id")
            for citation in result.get("citations") or []
            if isinstance(citation, dict) and citation.get("source_id")
        }
    )

    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=ai_log_model.RAG_SERVER,
        # The question verbatim: for this phase the question IS what was sent.
        prompt=result["question"],
        response=_json(
            {
                "answer": result["answer"],
                "chunk_ids": citations,
                "source_ids": sources,
                "confidence_category": result.get("confidence_category"),
                "insufficient_evidence": bool(result.get("insufficient_evidence")),
                "retrieval_summary": result.get("retrieval_summary"),
                "k": result.get("k"),
                "duration_ms": result.get("duration_ms"),
                "server_url": result.get("server_url"),
            }
        ),
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id


def record_unavailable(conn: sqlite3.Connection, *, goal_id: int | None, question: str, detail: str) -> int:
    """Log a question the RAG server could not answer at all.

    The attempt is worth a row for the same reason an MCP failure is: the
    claim that this feature degrades gracefully is only demonstrable if the
    failures appear in the audit trail rather than vanishing from it.
    """
    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=ai_log_model.RAG_SERVER,
        prompt=question,
        response=_json({"unavailable": True, "detail": detail}),
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id
