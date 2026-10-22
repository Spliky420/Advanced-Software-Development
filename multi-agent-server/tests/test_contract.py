"""Every route and every error shape, against the stub agents.

These pin the contract circulated to the team. If one of these has to
change, five teammates' integrations change with it.
"""

import pytest

import agents
import server
from conftest import EVIDENCE

CONTRACT_KEYS = {"run_id", "status", "plan", "work", "review", "model", "stub"}


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------


def test_health_shape(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "model": "test-model:tag",
        "stub": True,
        "ollama_reachable": False,
    }


def test_health_reports_ollama_reachable(client, monkeypatch):
    monkeypatch.setattr(agents, "ping", lambda config: True)
    assert client.get("/health").get_json()["ollama_reachable"] is True


def test_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "from-env:1b")
    monkeypatch.setenv("STUB_AGENTS", "true")
    monkeypatch.setattr(agents, "ping", lambda config: False)
    app = server.create_app({"TESTING": True})
    body = app.test_client().get("/health").get_json()
    assert body["model"] == "from-env:1b"
    assert body["stub"] is True


# --------------------------------------------------------------------------
# POST /workflow
# --------------------------------------------------------------------------


def test_create_returns_201_with_contract_body(run):
    assert CONTRACT_KEYS <= set(run)
    assert run["status"] == "awaiting_human"
    assert run["stub"] is True
    assert run["model"] == "stub"
    assert isinstance(run["run_id"], str) and run["run_id"]
    assert isinstance(run["work"], str) and run["work"]
    assert set(run["review"]) == {"risks", "recommendations"}
    assert isinstance(run["review"]["risks"], list)
    assert isinstance(run["review"]["recommendations"], list)
    assert run["human_review"] is None


def test_stub_plan_steps_name_the_evidence_they_need(run):
    assert run["plan"], "the plan has at least one step"
    for index, step in enumerate(run["plan"], start=1):
        assert step["step"] == index
        assert isinstance(step["action"], str) and step["action"]
        assert set(step["evidence"]) <= set(EVIDENCE)


def test_stub_never_restates_evidence_figures(run):
    # The stub derives everything from evidence keys -- no value from the
    # evidence, and certainly no computed figure, appears in the work.
    assert "12.5" not in run["work"]


def test_caller_is_optional(client):
    response = client.post("/workflow", json={"task": "t", "evidence": {}})
    assert response.status_code == 201


@pytest.mark.parametrize(
    "body, field, reason",
    [
        ({"evidence": {}}, "task", "is required"),
        ({"task": "", "evidence": {}}, "task", "must be a non-empty string"),
        ({"task": "   ", "evidence": {}}, "task", "must be a non-empty string"),
        ({"task": 7, "evidence": {}}, "task", "must be a non-empty string"),
        ({"task": "t"}, "evidence", "is required"),
        ({"task": "t", "evidence": ["a"]}, "evidence", "must be a JSON object"),
        ({"task": "t", "evidence": "text"}, "evidence", "must be a JSON object"),
        ({"task": "t", "evidence": {}, "caller": 3}, "caller", "must be a non-empty string when supplied"),
    ],
)
def test_create_validation_errors_name_the_field(client, body, field, reason):
    response = client.post("/workflow", json=body)
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_failed"
    assert payload["fields"][field] == reason
    assert field in payload["detail"]


def test_missing_task_and_evidence_both_reported(client):
    payload = client.post("/workflow", json={}).get_json()
    assert set(payload["fields"]) == {"task", "evidence"}


@pytest.mark.parametrize("data", ["not json", "[1, 2]", ""])
def test_create_rejects_a_body_that_is_not_a_json_object(client, data):
    response = client.post("/workflow", data=data, content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["fields"] == {"body": "must be a JSON object"}


def test_ollama_unavailable_is_503_naming_the_problem(client, monkeypatch):
    def unreachable(*args, **kwargs):
        raise agents.AgentUnavailable("could not reach Ollama at http://ollama.invalid:11434")

    monkeypatch.setattr(agents, "plan", unreachable)
    response = client.post("/workflow", json={"task": "t", "evidence": {}})
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["error"] == "agent_unavailable"
    assert "could not reach Ollama" in payload["detail"]
    assert "plan" in payload["detail"]
    assert payload["run_id"]


def test_real_mode_with_ollama_down_is_503_not_500(app, monkeypatch):
    def refused(*args, **kwargs):
        raise agents.requests.ConnectionError("connection refused")

    monkeypatch.setattr(agents.requests, "post", refused)
    app.config["STUB_AGENTS"] = False
    response = app.test_client().post("/workflow", json={"task": "t", "evidence": {}})
    assert response.status_code == 503
    assert "could not reach Ollama" in response.get_json()["detail"]


# --------------------------------------------------------------------------
# GET /workflow/<run_id>
# --------------------------------------------------------------------------


def test_get_returns_the_same_body(client, run):
    response = client.get(f"/workflow/{run['run_id']}")
    assert response.status_code == 200
    assert response.get_json() == run


def test_get_unknown_run_is_404(client):
    response = client.get("/workflow/does-not-exist")
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["error"] == "not_found"
    assert payload["run_id"] == "does-not-exist"


def test_get_does_not_leak_audit_fields(client, run):
    body = client.get(f"/workflow/{run['run_id']}").get_json()
    assert "phases" not in body
    assert "evidence" not in body


# --------------------------------------------------------------------------
# POST /workflow/<run_id>/review
# --------------------------------------------------------------------------


def test_review_response_shape(client, run):
    response = client.post(f"/workflow/{run['run_id']}/review", json={"decision": "approve"})
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"run_id", "status", "decision", "decided_at"}
    assert payload["run_id"] == run["run_id"]
    assert payload["status"] == "complete"
    assert payload["decision"] == "approve"
    assert payload["decided_at"]


def test_review_unknown_run_is_404(client):
    response = client.post("/workflow/does-not-exist/review", json={"decision": "approve"})
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


@pytest.mark.parametrize(
    "body, field",
    [
        ({}, "decision"),
        ({"decision": "maybe"}, "decision"),
        ({"decision": "correct"}, "corrected"),
        ({"decision": "correct", "corrected": "  "}, "corrected"),
        ({"decision": "approve", "corrected": "text"}, "corrected"),
        ({"decision": "partial"}, "note"),
        ({"decision": "approve", "note": 5}, "note"),
        ({"decision": "approve", "reviewer": ""}, "reviewer"),
    ],
)
def test_review_validation_errors_name_the_field(client, run, body, field):
    response = client.post(f"/workflow/{run['run_id']}/review", json=body)
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_failed"
    assert field in payload["fields"]


def test_review_rejects_a_body_that_is_not_a_json_object(client, run):
    response = client.post(
        f"/workflow/{run['run_id']}/review", data="nope", content_type="application/json"
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Anything else is JSON too
# --------------------------------------------------------------------------


def test_unknown_route_is_json_404(client):
    response = client.get("/nowhere")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_wrong_method_is_json_405(client):
    response = client.get("/workflow")
    assert response.status_code == 405
    assert response.get_json()["error"] == "method_not_allowed"
