"""Thin client for the team's RAG server (rag-server/ on main).

Coded against the contract in joshua/RAG_INTEGRATION.md. Per the Release 1
brief the RAG server runs on the host, not as a compose service, so from
inside the joshua-backend container it is reached through
host.docker.internal -- and when nobody has started it, an unreachable server
is the normal case. That has to degrade to "unavailable", never to a 500.

Same shape as mcp_client, plus a machine-readable status: every public call
returns {"endpoint", "ok", "status", "data", "error"}, where status is one of
"ok", "disabled", "unreachable", "timeout" or "error", and never raises for a
server-side problem.

Retrieval distances are passed through untouched. The server decides what a
distance means (L2 today, possibly cosine later), so this module never ranks,
inverts or thresholds on it: chunks keep the order the server gave them.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

DEFAULT_RAG_SERVER_URL = "http://host.docker.internal:5003"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_K = 5


def get_server_url():
    """The RAG base URL from RAG_SERVER_URL, or None when RAG is switched off.

    Unset means the default host address; set-but-empty is the off switch.
    """
    raw = os.environ.get("RAG_SERVER_URL")
    if raw is None:
        return DEFAULT_RAG_SERVER_URL
    raw = raw.strip().rstrip("/")
    return raw or None


def get_timeout_seconds():
    """Per-request timeout from RAG_TIMEOUT_SECONDS.

    Unparseable or non-positive values fall back to the default.
    """
    raw = os.environ.get("RAG_TIMEOUT_SECONDS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return value


def _ok(endpoint, data):
    return {"endpoint": endpoint, "ok": True, "status": "ok", "data": data, "error": None}


def _unavailable(endpoint, status, reason):
    if status != "disabled":
        logger.warning("RAG %s unavailable (%s): %s", endpoint, status, reason)
    return {"endpoint": endpoint, "ok": False, "status": status, "data": None, "error": reason}


def _request(method, endpoint, payload=None):
    """One HTTP call; returns (body, None) or (None, (status, reason))."""
    base_url = get_server_url()
    if base_url is None:
        return None, ("disabled", "RAG is disabled (RAG_SERVER_URL is empty)")

    url = base_url + endpoint
    timeout = get_timeout_seconds()
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        return None, ("timeout", f"RAG server did not respond within {timeout:g}s")
    except requests.exceptions.RequestException as exc:
        return None, ("unreachable", f"could not reach RAG server at {url}: {type(exc).__name__}")

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code != 200:
        detail = body.get("error") if isinstance(body, dict) else None
        return None, ("error", f"RAG server returned {response.status_code}" + (f": {detail}" if detail else ""))
    if not isinstance(body, dict):
        return None, ("error", "RAG server returned a non-JSON response")
    if body.get("status") == "error":
        return None, ("error", f"RAG server reported an error: {body.get('error', 'no detail')}")
    return body, None


def _clean_query(query):
    return query.strip() if isinstance(query, str) else ""


def _request_body(query, k):
    # k is the RAG server's name for it and top_k the MCP server's; sending
    # both survives either convention.
    k = max(1, int(k))
    return {"query": query, "k": k, "top_k": k}


def health():
    """GET /health. ok only when the server says {"status": "ok"}."""
    body, failure = _request("GET", "/health")
    if failure:
        return _unavailable("/health", *failure)
    if body.get("status") != "ok":
        return _unavailable("/health", "error", f"unexpected health status: {body.get('status')!r}")
    return _ok("/health", body)


def retrieve(query, k=DEFAULT_K):
    """POST /retrieve. data = {"query", "chunks": [...]} in server order.

    Each chunk keeps rank, chunk_id, source_id, text and distance exactly as
    sent. Entries without usable text are dropped; nothing is re-sorted.
    """
    query = _clean_query(query)
    if not query:
        return _unavailable("/retrieve", "error", "query is required")

    body, failure = _request("POST", "/retrieve", _request_body(query, k))
    if failure:
        return _unavailable("/retrieve", *failure)

    results = body.get("results")
    if not isinstance(results, list):
        return _unavailable("/retrieve", "error", "response had no results list")

    chunks = [
        {
            "rank": item.get("rank"),
            "chunk_id": item.get("chunk_id"),
            "source_id": item.get("source_id"),
            "text": item["text"],
            "distance": item.get("distance"),
        }
        for item in results
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
    ]
    return _ok("/retrieve", {"query": query, "chunks": chunks})


def answer(query, k=DEFAULT_K):
    """POST /answer. data = {"answer", "citations", "confidence_category"}.

    The server generates this answer with its own LLM call, so it can easily
    take longer than RAG_TIMEOUT_SECONDS allows for /retrieve.
    """
    query = _clean_query(query)
    if not query:
        return _unavailable("/answer", "error", "query is required")

    body, failure = _request("POST", "/answer", _request_body(query, k))
    if failure:
        return _unavailable("/answer", *failure)

    text = body.get("answer")
    if not isinstance(text, str):
        return _unavailable("/answer", "error", "response had no answer")

    citations = body.get("citations")
    return _ok("/answer", {
        "answer": text,
        "citations": [dict(c) for c in citations if isinstance(c, dict)] if isinstance(citations, list) else [],
        "confidence_category": body.get("confidence_category"),
    })
