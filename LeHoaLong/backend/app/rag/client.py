"""The RAG client -- grounded answers from the team's shared RAG server.

The server (`rag-server/rag_http_server.py`, a host process on port 5003)
chunks the shared corpus, embeds it into Chroma, retrieves against a question
and has Ollama answer *only* from what was retrieved. This module is the
client: it asks, and it passes the answer back.

**Citations and the confidence category are passed through untouched.** Not
re-ordered, not re-labelled, not recomputed. That is a marking requirement and
also the only honest thing to do -- a confidence this backend calculated would
be this backend's opinion of someone else's retrieval. Two consequences worth
being explicit about:

  * the shared server derives its category from how *many* chunks came back
    (three or more reads as High), so it is a measure of quantity, not of
    relevance, and it never returns Low. This client does not improve on that,
    because improving on it would mean replacing it. It is recorded in the
    README's known issues instead.
  * `insufficient_evidence` is a *derived flag*, not a changed field: it is
    true when the answer is exactly the sentence the server's prompt instructs
    the model to return when the context does not support an answer. The
    answer text itself is still passed through verbatim.

**"Insufficient evidence." is a correct answer, not a failure.** When the
corpus does not support the question, that sentence is surfaced as-is. There
is deliberately no fallback to an ungrounded model answer: a grounded feature
that admits it has no evidence is behaving properly, and quietly substituting
an unsourced answer would defeat the point of grounding it.

**The retrieved chunks come from a second call.** `/answer` returns citations
but not the chunk text, and the UI needs the text for its citations list, so
`ask()` calls `/retrieve` as well. Retrieval is deterministic -- the shared
pipeline's embedding is a hash of the words, with no sampling anywhere -- so
the same question and the same corpus return the same chunks, and the text
lines up with the citations. The response carries `chunks_match_citations` so
a reader does not have to take that on trust; it would go false if the corpus
were refreshed between the two calls.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from flask import current_app

from ..errors import ServiceUnavailable

# The exact sentence rag-server/rag_pipeline.py instructs the model to return
# when the retrieved context does not support an answer. Compared on a
# stripped, case-insensitive basis because a small model will vary the
# trailing whitespace and occasionally the capitalisation, and treating
# "insufficient evidence." as a real answer would be worse than matching
# loosely.
INSUFFICIENT_EVIDENCE = "Insufficient evidence."

# Reachability probes answer /api/rag/health, which drives a status light in
# the page header. It must not block a page load.
HEALTH_TIMEOUT_SECONDS = 3.0


class RAGUnavailable(ServiceUnavailable):
    """The RAG server could not be reached, or answered unusably.

    A ServiceUnavailable subclass, so it becomes the 503 the API contract
    promises. "Insufficient evidence." is NOT this -- that is a successful,
    correct answer.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    return bool(current_app.config["RAG_ENABLED"])


def server_url() -> str:
    return str(current_app.config["RAG_SERVER_URL"]).rstrip("/")


def timeout_seconds() -> float:
    return float(current_app.config["RAG_TIMEOUT_SECONDS"])


def default_top_k() -> int:
    return int(current_app.config["RAG_TOP_K"])


def caller() -> str:
    return str(current_app.config["RAG_CALLER"])


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _post(path: str, payload: dict, timeout: float | None = None) -> dict:
    """POST to the RAG server and return its JSON body.

    The one seam the tests replace. Everything that reads a response is
    outside this function, so the parsing, the insufficient-evidence
    detection and the citation pass-through are exercised for real.
    """
    url = f"{server_url()}{path}"

    try:
        response = requests.post(url, json=payload, timeout=timeout or timeout_seconds())
    except requests.RequestException as exc:
        raise RAGUnavailable(
            f"could not reach the RAG server at {url}: {exc}. It runs as a host process, "
            "not a container -- check that it is running, and that RAG_SERVER_URL names a "
            "host this backend can reach."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RAGUnavailable(f"the RAG server at {url} returned a non-JSON response: {exc}") from exc

    if not isinstance(data, dict):
        raise RAGUnavailable(f"the RAG server at {url} returned {type(data).__name__}, not an object")

    # The server answers 500 with {"status": "error", "error": "..."} when its
    # own pipeline raises -- most often because the model its prompt asks for
    # has never been pulled into Ollama. Its message is the actionable part,
    # so it is carried through rather than replaced with a generic one.
    if response.status_code >= 400 or data.get("status") == "error":
        detail = data.get("error") or f"HTTP {response.status_code}"
        raise RAGUnavailable(f"the RAG server could not answer: {detail}")

    return data


def _get(path: str, timeout: float) -> tuple[bool, dict | None, str | None]:
    """GET from the RAG server. Returns (ok, body, detail). Never raises."""
    url = f"{server_url()}{path}"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return True, response.json(), None
    except (requests.RequestException, ValueError) as exc:
        return False, None, f"could not reach the RAG server at {url}: {exc}"


# ---------------------------------------------------------------------------
# Reading an answer
# ---------------------------------------------------------------------------


def is_insufficient(answer: str) -> bool:
    """Whether the server reported that it had no evidence to answer from."""
    return answer.strip().lower() == INSUFFICIENT_EVIDENCE.lower()


def _chunks(payload: dict) -> list[dict]:
    """The retrieved chunks, as the server described them.

    `distance` is kept under its own name rather than being converted to a
    similarity: lower means closer in Chroma, that is the server's units, and
    inverting it here would be this backend inventing a score.
    """
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


# ---------------------------------------------------------------------------
# The operations this backend needs
# ---------------------------------------------------------------------------


def _request_body(question: str, k: int) -> dict:
    """The body the shared server expects.

    `caller` is part of the contract, not plumbing: rag-server records it per
    request in its own audit file (rag-audit.jsonl), so this is what makes
    these calls attributable to this feature from that side of the boundary.
    """
    return {"query": question, "k": k, "caller": caller()}


def retrieve(question: str, top_k: int | None = None) -> dict:
    """POST /retrieve -- the chunks a question matches, with no model call."""
    k = top_k or default_top_k()
    started = time.perf_counter()
    payload = _post("/retrieve", _request_body(question, k))
    return {
        "question": question,
        "k": k,
        "chunks": _chunks(payload),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "server_url": server_url(),
    }


def ask(question: str, top_k: int | None = None) -> dict:
    """POST /answer (plus /retrieve for the chunk text) -- a grounded answer.

    Raises RAGUnavailable if the server is unreachable or answers without an
    `answer` field, which would mean its contract had changed under this
    feature. It does not raise for "Insufficient evidence.", which is a
    correct answer and comes back flagged.
    """
    k = top_k or default_top_k()
    started = time.perf_counter()

    retrieved = _post("/retrieve", _request_body(question, k))
    answered = _post("/answer", _request_body(question, k))

    answer = answered.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise RAGUnavailable(
            "the RAG server returned no answer text. Its /answer contract is "
            "{answer, citations, confidence_category, retrieval_summary}."
        )

    # Passed through exactly as received. The defaults below cover a server
    # that omitted a field entirely; they never overwrite one it sent.
    citations = answered.get("citations")
    citations = citations if isinstance(citations, list) else []
    chunks = _chunks(retrieved)
    cited_ids = [citation.get("chunk_id") for citation in citations if isinstance(citation, dict)]

    return {
        "question": question,
        "k": k,
        "answer": answer.strip(),
        "citations": citations,
        "confidence_category": answered.get("confidence_category"),
        "retrieval_summary": answered.get("retrieval_summary"),
        "retrieved_chunks": chunks,
        # Lets a reader confirm the chunk text shown really is what grounded
        # the answer, rather than taking the determinism of the retrieval on
        # trust. Only false if the corpus changed between the two calls.
        "chunks_match_citations": sorted(filter(None, cited_ids))
        == sorted(chunk.get("chunk_id") for chunk in chunks if chunk.get("chunk_id")),
        "insufficient_evidence": is_insufficient(answer),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "server_url": server_url(),
    }


def probe() -> dict:
    """Reachability, for /api/rag/health and the header indicator. Never raises."""
    status: dict[str, Any] = {
        "enabled": False,
        "reachable": False,
        "server_url": server_url(),
        "service": None,
        "detail": None,
    }

    if not is_enabled():
        status["detail"] = "RAG is disabled by configuration (RAG_ENABLED=false)."
        return status

    status["enabled"] = True
    ok, body, detail = _get("/health", HEALTH_TIMEOUT_SECONDS)
    if not ok:
        status["detail"] = detail
        return status

    status["reachable"] = True
    status["service"] = (body or {}).get("service")
    return status
