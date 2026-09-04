import pytest
import requests

import llm


class FakeResponse:
    """Minimal stand-in for requests.Response covering what llm uses."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        return self._payload


# --------------------------------------------------------------------------
# generate()
# --------------------------------------------------------------------------

def test_generate_connection_failure_reports_that_ollama_was_unreachable(monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", refuse)

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this document")

    message = str(exc_info.value)
    assert "could not reach Ollama at" in message
    assert llm.OLLAMA_BASE_URL in message
    assert "pull" not in message


def test_generate_timeout_reports_that_ollama_was_unreachable(monkeypatch):
    def time_out(*args, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(llm.requests, "post", time_out)

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this document")

    assert "could not reach Ollama at" in str(exc_info.value)


def test_generate_404_reports_that_the_model_is_not_pulled(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(404, {"error": 'model "llama3.1:8b" not found'}),
    )

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this document")

    message = str(exc_info.value)
    assert "could not reach Ollama" not in message
    assert "model 'llama3.1:8b' is not available in the Ollama container" in message
    assert "docker compose exec ollama ollama pull llama3.1:8b" in message


def test_generate_returns_text_and_model_on_success(monkeypatch):
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {"response": "  A summary.  "}),
    )

    text, model_name = llm.generate("summarise this document")

    assert text == "A summary."
    assert model_name == llm.OLLAMA_MODEL


def test_generate_raises_when_response_has_no_usable_text(monkeypatch):
    monkeypatch.setattr(
        llm.requests, "post", lambda *args, **kwargs: FakeResponse(200, {"response": "   "})
    )

    with pytest.raises(llm.LLMUnavailableError):
        llm.generate("summarise this document")


# --------------------------------------------------------------------------
# embed()
# --------------------------------------------------------------------------

def test_embed_connection_failure_reports_that_ollama_was_unreachable(monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", refuse)

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.embed("some chunk of text")

    assert "could not reach Ollama at" in str(exc_info.value)


def test_embed_404_reports_that_the_embedding_model_is_not_pulled(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setattr(
        llm.requests, "post", lambda *args, **kwargs: FakeResponse(404, {"error": "not found"})
    )

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.embed("some chunk of text")

    message = str(exc_info.value)
    assert "model 'nomic-embed-text' is not available in the Ollama container" in message
    assert "docker compose exec ollama ollama pull nomic-embed-text" in message


def test_embed_returns_vector_and_model_on_success(monkeypatch):
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {"embedding": [0.1, 0.2, 0.3]}),
    )

    vector, model_name = llm.embed("some chunk of text")

    assert vector == [0.1, 0.2, 0.3]
    assert model_name == llm.OLLAMA_EMBED_MODEL


def test_embed_raises_when_response_has_no_vector(monkeypatch):
    monkeypatch.setattr(
        llm.requests, "post", lambda *args, **kwargs: FakeResponse(200, {"embedding": []})
    )

    with pytest.raises(llm.LLMUnavailableError):
        llm.embed("some chunk of text")


def test_embed_model_defaults_to_a_dedicated_embedding_tag():
    # OLLAMA_EMBED_MODEL is a separate env var from OLLAMA_MODEL on purpose --
    # a chat model like the qwen2.5:0.5b default answers /api/embeddings but
    # gives much weaker retrieval quality than a model built for it.
    assert llm.OLLAMA_EMBED_MODEL == "nomic-embed-text"
