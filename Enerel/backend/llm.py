import os

import requests

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
# Separate tag for embeddings: a chat model like qwen2.5:0.5b can answer
# /api/embeddings but a model built for it (default nomic-embed-text) gives
# much better retrieval quality. Never hardcoded -- always read from env, per
# CLAUDE.md's LLM access rules.
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

REQUEST_TIMEOUT_SECONDS = 60
TEMPERATURE = 0.2


class LLMUnavailableError(Exception):
    """Ollama could not be reached, timed out, or returned nothing usable."""


def _post(path, payload, model_for_error):
    url = OLLAMA_BASE_URL.rstrip("/") + path
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"could not reach Ollama at {url}: {exc}") from exc

    # Ollama answers 404 when it is running but the model tag has never been
    # pulled into the container, so it is a different problem from the one above.
    if response.status_code == 404:
        raise LLMUnavailableError(
            f"model '{model_for_error}' is not available in the Ollama container "
            f"— pull it with docker compose exec ollama ollama pull {model_for_error}"
        )

    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"Ollama returned an error response: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise LLMUnavailableError(f"Ollama returned a non-JSON response: {exc}") from exc


def generate(prompt, system=None):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE},
    }
    if system:
        payload["system"] = system

    data = _post("/api/generate", payload, OLLAMA_MODEL)

    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise LLMUnavailableError("Ollama response did not contain any generated text")

    return text.strip(), OLLAMA_MODEL


def embed(text):
    """Embed one piece of text via Ollama, returning (vector, model_name).

    vector is a list of floats. Raises LLMUnavailableError on any failure --
    unreachable Ollama, unpulled model, or a response with no usable vector.
    """
    payload = {"model": OLLAMA_EMBED_MODEL, "prompt": text}
    data = _post("/api/embeddings", payload, OLLAMA_EMBED_MODEL)

    vector = data.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise LLMUnavailableError("Ollama response did not contain an embedding vector")

    return vector, OLLAMA_EMBED_MODEL
