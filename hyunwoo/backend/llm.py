import os

import requests


# Shared Ollama service and selected model.
OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL",
    "http://ollama:11434",
).rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")


class LLMError(RuntimeError):
    pass


# Ask Ollama for one complete response.
def generate(prompt):
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
    except requests.RequestException as error:
        raise LLMError("Could not reach the Ollama service.") from error

    if response.status_code == 404:
        raise LLMError(
            f"Model {OLLAMA_MODEL} is not available in Ollama."
        )

    if response.status_code != 200:
        raise LLMError(
            f"Ollama returned HTTP {response.status_code}."
        )

    try:
        text = response.json().get("response", "").strip()
    except ValueError as error:
        raise LLMError("Ollama returned an invalid response.") from error

    if not text:
        raise LLMError("Ollama returned an empty response.")

    return text
