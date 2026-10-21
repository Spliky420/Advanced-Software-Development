"""The Multi-Agent Review endpoints, with the Multi-Agent Server mocked.

requests.post inside multi_agent_client is replaced by FakeServer, which
records every request and answers with a canned status and body, so no test
opens a socket. Covers the happy path, the evidence and timeout sent, and
every failure the brief names: AI off, server down, timeout, and the
server's 400 / 404 / 409 / 503.
"""

import pytest
import requests

import app as app_module
import multi_agent_client

RUN_ID = "785b03cafab14facafb9ef4416af93d3"

RUN = {
    "run_id": RUN_ID,
    "status": "awaiting_human",
    "plan": [{"step": 1, "action": "Examine the 'holdings' evidence.", "evidence": ["holdings"]}],
    "work": "Step 1: ...",
    "review": {"risks": ["r"], "recommendations": ["c"]},
    "model": "stub",
    "stub": True,
    "human_review": None,
    "error": None,
}


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeServer:
    def __init__(self, status_code=201, body=None, raises=None):
        self.status_code, self.body, self.raises = status_code, body, raises
        self.calls = []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return FakeResponse(self.status_code, self.body)


@pytest.fixture
def server(monkeypatch):
    """Install a FakeServer; tests reconfigure it before calling the API."""
    monkeypatch.setenv("MULTI_AGENT_URL", "http://agents.test:5004")
    fake = FakeServer(201, RUN)
    monkeypatch.setattr(multi_agent_client.requests, "post", fake)
    return fake


# --- starting a workflow ----------------------------------------------------


def test_start_returns_the_full_run(api_client, server):
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 201
    body = response.get_json()
    assert body["run"] == RUN
    assert body["task"] == "Review my portfolio allocation and drift"


def test_start_sends_the_contract_body_with_a_long_timeout(api_client, server):
    api_client.post("/api/multi-agent/workflow")

    [call] = server.calls
    assert call["url"] == "http://agents.test:5004/workflow"
    assert call["json"]["task"] == "Review my portfolio allocation and drift"
    assert call["json"]["caller"] == "joshua"
    assert set(call["json"]["evidence"]) == {"holdings", "allocation", "drift"}
    # Long and separate from the 5s MCP/RAG timeouts.
    assert call["timeout"] == (5, 190)


def test_evidence_figures_come_from_python(api_client, server, monkeypatch):
    """Every evidence figure is one the backend's own endpoints report."""
    allocation_body = api_client.get("/api/allocation").get_json()
    api_client.post("/api/multi-agent/workflow")
    evidence = server.calls[0]["json"]["evidence"]
    # The fake replaces requests.post module-wide, so keep the drift review
    # below off Ollama; its figures do not depend on AI either way.
    monkeypatch.setenv("AI_MODE_ENABLED", "false")

    assert evidence["allocation"] == allocation_body["portfolio"]
    assert len(evidence["holdings"]) == len(allocation_body["holdings"])
    for sent, reported in zip(evidence["holdings"], allocation_body["holdings"]):
        assert sent["market_value"] == reported["market_value"]

    drift_body = api_client.post("/api/drift-review").get_json()
    assert evidence["drift"]["breaches"] == drift_body["observe"]["breaches"]
    assert evidence["drift"]["threshold_percent"] == drift_body["observe"]["threshold_percent"]


def test_start_with_ai_off_never_calls_the_server(api_client, server, monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 503
    assert response.get_json()["code"] == "disabled"
    assert server.calls == []


def test_start_when_the_server_is_not_running(api_client, server):
    server.raises = requests.exceptions.ConnectionError("refused")
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "unreachable"
    assert "not running" in body["error"]


def test_start_when_the_server_times_out(api_client, server):
    server.raises = requests.exceptions.ReadTimeout("slow")
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 504
    assert response.get_json()["code"] == "timeout"


def test_start_when_the_agents_cannot_run(api_client, server):
    server.status_code = 503
    server.body = {"error": "agent_unavailable", "detail": "plan phase failed", "run_id": RUN_ID}
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "agent_unavailable"
    assert body["run_id"] == RUN_ID
    assert body["detail"] == "plan phase failed"


def test_start_rejected_by_the_server_is_a_502(api_client, server):
    """This backend built the whole body, so a 400 is its own bug, not the user's."""
    server.status_code = 400
    server.body = {"error": "validation_failed", "detail": "task is required", "fields": {"task": "is required"}}
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 502
    assert response.get_json()["code"] == "validation_failed"


def test_start_with_a_non_json_reply(api_client, server):
    server.status_code = 502
    server.body = ValueError("not json")
    response = api_client.post("/api/multi-agent/workflow")

    assert response.status_code == 502
    assert response.get_json()["code"] == "error"


# --- the human review -------------------------------------------------------

DECIDED = {"run_id": RUN_ID, "status": "complete", "decision": "approve",
           "decided_at": "2026-10-21T04:17:28+00:00"}


def _review(api_client, body, run_id=RUN_ID):
    return api_client.post(f"/api/multi-agent/workflow/{run_id}/review", json=body)


@pytest.mark.parametrize("decision_body", [
    {"decision": "approve"},
    {"decision": "approve", "note": "looks right"},
    {"decision": "correct", "corrected": "ETFs are 9.30 points overweight."},
    {"decision": "partial", "note": "plan accepted, work not"},
    {"decision": "reject", "note": "wrong"},
])
def test_review_passes_each_decision_through(api_client, server, decision_body):
    server.status_code, server.body = 200, {**DECIDED, "decision": decision_body["decision"]}
    response = _review(api_client, decision_body)

    assert response.status_code == 200
    assert response.get_json()["status"] == "complete"
    [call] = server.calls
    assert call["url"] == f"http://agents.test:5004/workflow/{RUN_ID}/review"
    assert call["timeout"] == (5, 190)
    for key, value in decision_body.items():
        assert call["json"][key] == value
    assert call["json"]["reviewer"] == "joshua"


def test_review_validation_errors_reach_the_user(api_client, server):
    server.status_code = 400
    server.body = {
        "error": "validation_failed",
        "detail": "corrected is required for a correct decision -- the corrected text",
        "fields": {"corrected": "is required for a correct decision -- the corrected text"},
    }
    response = _review(api_client, {"decision": "correct"})

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "validation_failed"
    assert "corrected" in body["fields"]


def test_review_of_an_unknown_run(api_client, server):
    server.status_code = 404
    server.body = {"error": "not_found", "detail": "no workflow run", "run_id": RUN_ID}
    response = _review(api_client, {"decision": "approve"})

    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_second_review_is_a_conflict(api_client, server):
    server.status_code = 409
    server.body = {"error": "conflict", "detail": "run is 'complete'", "run_id": RUN_ID}
    response = _review(api_client, {"decision": "reject"})

    assert response.status_code == 409
    assert "already been reviewed" in response.get_json()["error"]


def test_review_rejects_a_malformed_run_id_without_calling_the_server(api_client, server):
    response = _review(api_client, {"decision": "approve"}, run_id="not-a-run-id")

    assert response.status_code == 404
    assert server.calls == []


def test_review_needs_a_json_object(api_client, server):
    response = api_client.post(
        f"/api/multi-agent/workflow/{RUN_ID}/review", data="approve", content_type="text/plain"
    )
    assert response.status_code == 400
    assert server.calls == []


def test_review_with_ai_off_never_calls_the_server(api_client, server, monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    response = _review(api_client, {"decision": "approve"})

    assert response.status_code == 503
    assert server.calls == []


def test_empty_url_disables_the_client(monkeypatch, server):
    monkeypatch.setenv("MULTI_AGENT_URL", "")
    result = multi_agent_client.start_workflow("t", {"a": 1})

    assert result["status"] == "disabled"
    assert server.calls == []


def test_default_url_is_the_host_address(monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_URL", raising=False)
    assert multi_agent_client.get_server_url() == "http://host.docker.internal:5004"


def test_app_module_imports_the_client():
    assert app_module.multi_agent_client is multi_agent_client
