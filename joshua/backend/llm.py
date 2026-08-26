import os

import requests

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")

REQUEST_TIMEOUT_SECONDS = 60
TEMPERATURE = 0.2


class LLMUnavailableError(Exception):
    """Ollama could not be reached, timed out, or returned nothing usable."""


def generate(prompt, system=None):
    url = OLLAMA_BASE_URL.rstrip("/") + "/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE},
    }
    if system:
        payload["system"] = system

    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"could not reach Ollama at {url}: {exc}") from exc

    # Ollama answers 404 when it is running but the model tag has never been
    # pulled into the container, so it is a different problem from the one above.
    if response.status_code == 404:
        raise LLMUnavailableError(
            f"model '{OLLAMA_MODEL}' is not available in the Ollama container "
            f"— pull it with docker compose exec ollama ollama pull {OLLAMA_MODEL}"
        )

    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"Ollama returned an error response: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMUnavailableError(f"Ollama returned a non-JSON response: {exc}") from exc

    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise LLMUnavailableError("Ollama response did not contain any generated text")

    return text.strip(), OLLAMA_MODEL
