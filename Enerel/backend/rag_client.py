"""HTTP client for the team's shared, non-containerised RAG server.

rag-server/rag_http_server.py exposes POST /retrieve (ranked chunks, no
model call) and POST /answer (retrieve + one Ollama call that writes the
answer). Both are plain JSON over HTTP, so this is a thin requests wrapper.

RAG is switched off with RAG_ENABLED=false (CI does this), which makes every
call raise RAGDisabledError instead of trying to reach a server that is not
running there.
"""

import os

import requests

DEFAULT_RAG_SERVER_URL = "http://host.docker.internal:5003"
CALLER = "Enerel"

# /retrieve is a vector lookup and returns quickly. /answer makes one Ollama
# generation call with its own 120s timeout, so this must sit above that --
# and below gunicorn's --timeout in the Dockerfile, or the worker is killed
# before a slow answer arrives.
RETRIEVE_TIMEOUT_SECONDS = 15
ANSWER_TIMEOUT_SECONDS = 150


class RAGDisabledError(Exception):
    """RAG mode is switched off by configuration (RAG_ENABLED=false)."""


class RAGUnavailableError(Exception):
    """The RAG server could not be reached, timed out, or returned an error."""


def rag_enabled():
    return os.environ.get("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def server_url():
    return os.environ.get("RAG_SERVER_URL", DEFAULT_RAG_SERVER_URL).rstrip("/")


def _post(path, payload, timeout):
    if not rag_enabled():
        raise RAGDisabledError("RAG mode is disabled (RAG_ENABLED=false)")

    url = server_url() + path
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise RAGUnavailableError(f"could not reach the RAG server at {url}: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RAGUnavailableError(f"RAG server returned a non-JSON response from {url}") from exc

    if response.status_code >= 400 or data.get("status") == "error":
        detail = data.get("error") or f"HTTP {response.status_code}"
        raise RAGUnavailableError(f"RAG server error from {url}: {detail}")

    return data


def retrieve(query, k):
    """POST /retrieve -- returns the list of ranked chunks."""
    data = _post("/retrieve", {"query": query, "k": k, "caller": CALLER}, RETRIEVE_TIMEOUT_SECONDS)
    results = data.get("results")
    if not isinstance(results, list):
        raise RAGUnavailableError("RAG server /retrieve response had no results list")
    return results


def answer(query, k):
    """POST /answer -- returns the server's full answer payload."""
    data = _post("/answer", {"query": query, "k": k, "caller": CALLER}, ANSWER_TIMEOUT_SECONDS)
    if not isinstance(data.get("answer"), str):
        raise RAGUnavailableError("RAG server /answer response had no answer text")
    return data
