import pytest
import requests

import llm


class FakeResponse:
    """Minimal stand-in for requests.Response covering what llm.generate uses."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        return self._payload


def test_connection_failure_reports_that_ollama_was_unreachable(monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", refuse)

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this portfolio")

    message = str(exc_info.value)
    assert "could not reach Ollama at" in message
    assert llm.OLLAMA_BASE_URL in message
    assert "pull" not in message


def test_timeout_reports_that_ollama_was_unreachable(monkeypatch):
    def time_out(*args, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(llm.requests, "post", time_out)

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this portfolio")

    assert "could not reach Ollama at" in str(exc_info.value)


def test_404_reports_that_the_model_is_not_pulled(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(404, {"error": 'model "llama3.1:8b" not found'}),
    )

    with pytest.raises(llm.LLMUnavailableError) as exc_info:
        llm.generate("summarise this portfolio")

    message = str(exc_info.value)
    assert "could not reach Ollama" not in message
    assert "model 'llama3.1:8b' is not available in the Ollama container" in message
    assert "docker compose exec ollama ollama pull llama3.1:8b" in message
