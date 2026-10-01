"""Ollama client.

The only path to an LLM in this project: the shared `ollama` service on the
compose network. No commercial API is ever called, and the model tag always
comes from configuration rather than from a literal in the code (CLAUDE.md).

Two entry points: `ping()` for /health, and `generate()` for the agentic
endpoints. Parsing what comes back is prompts.py and parsing.py's job -- this
module's only opinions are about transport.
"""

from __future__ import annotations

import requests
from flask import current_app

from ..errors import ServiceUnavailable

# /health should answer quickly even when Ollama is missing entirely, so it
# uses its own short timeout rather than the generous one a generation gets.
HEALTH_TIMEOUT_SECONDS = 2.0


def base_url() -> str:
    return str(current_app.config["OLLAMA_BASE_URL"]).rstrip("/")


def model_name() -> str:
    return str(current_app.config["OLLAMA_MODEL"])


def ping() -> dict:
    """Report whether Ollama is reachable and whether our model is pulled.

    Three outcomes, and the difference between them is the whole point:

      reachable=False  the container is not answering at all
      reachable=True, model_available=False
                       Ollama is up but the configured tag has never been
                       pulled into its volume -- a host-side `ollama pull`
                       does not count
      reachable=True, model_available=True
                       ready

    Never raises: /health has to answer even when everything else is broken.
    """
    wanted = model_name()
    result = {
        "reachable": False,
        "model": wanted,
        "model_available": False,
        "base_url": base_url(),
        "detail": None,
    }

    try:
        response = requests.get(f"{base_url()}/api/tags", timeout=HEALTH_TIMEOUT_SECONDS)
        response.raise_for_status()
        tags = response.json().get("models", [])
    except requests.RequestException as exc:
        result["detail"] = f"could not reach Ollama at {base_url()}: {exc}"
        return result
    except ValueError as exc:  # JSON that is not JSON
        result["reachable"] = True
        result["detail"] = f"Ollama returned an unreadable response: {exc}"
        return result

    result["reachable"] = True
    available = {str(tag.get("name", "")) for tag in tags if isinstance(tag, dict)}
    if wanted in available:
        result["model_available"] = True
    else:
        result["detail"] = (
            f"model {wanted!r} is not pulled into the Ollama container. "
            f"Run: docker compose exec ollama ollama pull {wanted}"
        )
    return result


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


class OllamaUnavailable(ServiceUnavailable):
    """Ollama could not be reached, or the configured model is not pulled.

    A ServiceUnavailable subclass, so letting it propagate produces the 503
    the API contract promises. This is infrastructure being wrong, and is a
    different thing entirely from the model answering badly -- that is not an
    error at all, it is the case the fallback plan exists for.
    """


def generate(prompt: str, *, system: str | None = None, json_format: bool = True) -> tuple[str, str]:
    """Send one prompt to Ollama and return (raw_text, model_name).

    `json_format` sets Ollama's own `format: "json"`, which constrains
    decoding to syntactically valid JSON. It is a help, not a guarantee: the
    result can still be valid JSON of entirely the wrong shape, which is why
    every caller parses and validates before persisting anything.

    Raises OllamaUnavailable for transport failures and for a model that has
    never been pulled. It never raises for a bad answer.
    """
    url = f"{base_url()}/api/generate"
    model = model_name()
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # Low but non-zero: the descriptions should read naturally without the
        # model wandering away from the instructions.
        "options": {"temperature": float(current_app.config.get("OLLAMA_TEMPERATURE", 0.2))},
    }
    if system:
        payload["system"] = system
    if json_format:
        payload["format"] = "json"

    try:
        response = requests.post(
            url, json=payload, timeout=float(current_app.config["OLLAMA_TIMEOUT_SECONDS"])
        )
    except requests.RequestException as exc:
        raise OllamaUnavailable(f"could not reach Ollama at {url}: {exc}") from exc

    # A running Ollama answers 404 when the tag has never been pulled into its
    # volume. That is a different problem from the container being down, and
    # the message has to say which, because the fixes differ.
    if response.status_code == 404:
        raise OllamaUnavailable(
            f"model {model!r} is not pulled into the Ollama container. "
            f"Run: docker compose exec ollama ollama pull {model}"
        )

    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaUnavailable(f"Ollama returned an error response: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise OllamaUnavailable(f"Ollama returned a non-JSON envelope: {exc}") from exc

    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise OllamaUnavailable("Ollama returned an empty response")

    return text.strip(), model
