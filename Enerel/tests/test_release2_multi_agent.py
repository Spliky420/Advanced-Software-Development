"""Release 2 endpoints: the shared Multi-Agent Server workflow and its human
review gate.

The Multi-Agent Server is never reached for real here -- the same rule CI
enforces by running with MULTI_AGENT_ENABLED=false. FakeMultiAgentServer
stands in for it at the one network leg (multi_agent_client.requests.request)
and keeps the server's state machine: planning -> awaiting_human ->
complete, 404 for an unknown run and 409 for a second review.
"""

import json
import sqlite3
import uuid

import pytest
import requests

import db
import multi_agent_client
import workflow_evidence
from test_app import client, make_payload, no_real_ollama_calls  # noqa: F401 -- pytest fixtures

REPORT_DOC = make_payload(
    title="ETF Fees in 2025",
    doc_type="report",
    body_text=(
        "Average ETF expense ratios fell to 0.15% in 2025.\n\n"
        "Index funds still dominate inflows. Investors should compare fees!"
    ),
)


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


class FakeMultiAgentServer:
    """Just enough of multi-agent-server/server.py's contract to drive the
    backend: async POST /workflow, GET /workflow/<id>, POST .../review."""

    def __init__(self):
        self.runs = {}
        self.calls = []

    def __call__(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json))
        path = url.replace(multi_agent_client.server_url(), "")

        if method == "POST" and path == "/workflow":
            run_id = uuid.uuid4().hex
            self.runs[run_id] = {
                "run_id": run_id,
                "status": "planning",
                "plan": [],
                "work": "",
                "review": {"risks": [], "recommendations": []},
                "model": "stub",
                "stub": True,
                "human_review": None,
                "error": None,
            }
            return FakeResponse(202, self.runs[run_id])

        run_id = path.split("/")[2]
        run = self.runs.get(run_id)
        if run is None:
            return FakeResponse(404, {"error": "not_found", "detail": f"no run {run_id}"})

        if method == "GET":
            return FakeResponse(200, run)

        if run["status"] != "awaiting_human":
            return FakeResponse(409, {"error": "conflict", "detail": "run is not awaiting_human"})
        run["status"] = "complete"
        run["human_review"] = json
        return FakeResponse(200, {"run_id": run_id, "status": "complete", "decision": json["decision"]})

    def finish_agents(self, run_id):
        self.runs[run_id].update({
            "status": "awaiting_human",
            "plan": [{"step": 1, "action": "Examine the 'document_text' evidence.", "evidence": ["document_text"]}],
            "work": "Step 1: The document has 18 words.\nTakeaways:\n1. **Fees** fell.\n2. Compare fees.",
            "review": {"risks": ["None."], "recommendations": ["Approve."]},
        })


@pytest.fixture(autouse=True)
def multi_agent_on(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_URL", "http://multi-agent.test:5004")
    monkeypatch.setattr(
        multi_agent_client.requests, "request",
        lambda *a, **k: pytest.fail("the Multi-Agent Server should have been stubbed"),
    )
    # Creating a document indexes it; keep that off the network too.
    monkeypatch.setattr("embeddings.index_document", lambda *a: {"indexed": False})


@pytest.fixture
def fake_server(monkeypatch):
    server = FakeMultiAgentServer()
    monkeypatch.setattr(multi_agent_client.requests, "request", server)
    return server


def create_doc(client, payload=REPORT_DOC):
    response = client.post("/api/documents", json=payload)
    assert response.status_code == 201
    return response.get_json()["id"]


def log_rows(request_type):
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM document_ai_log WHERE request_type = ?", (request_type,)
        )]
    finally:
        conn.close()


def start_run(client, fake_server, doc_id):
    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 202
    run_id = response.get_json()["run_id"]
    fake_server.finish_agents(run_id)
    return run_id


# --------------------------------------------------------------------------
# evidence -- every figure computed in Python
# --------------------------------------------------------------------------

def test_text_statistics_are_computed_in_python():
    stats = workflow_evidence.text_statistics("One two. Three four five!\n\nSix seven?")
    assert stats == {"word_count": 7, "sentence_count": 3, "paragraph_count": 2, "character_count": 37}


def test_evidence_truncates_long_documents_and_says_so():
    document = {"title": "Long", "doc_type": "other", "body_text": "word " * 1000}
    text_sent = workflow_evidence.build_evidence(document)["document_text"]
    assert text_sent["cut_short"] is True
    assert len(text_sent["text"]) == workflow_evidence.TEXT_SENT_CHARS
    assert workflow_evidence.sent_summary(document)["characters_sent"] == workflow_evidence.TEXT_SENT_CHARS


def test_evidence_includes_existing_summary_only_when_there_is_one():
    document = {"title": "T", "doc_type": "other", "body_text": "Text."}
    assert "existing_summary" not in workflow_evidence.build_evidence(document)
    document.update(summary_text="A summary.", key_points=["One"])
    assert workflow_evidence.build_evidence(document)["existing_summary"]["key_points"] == ["One"]


# --------------------------------------------------------------------------
# POST /api/documents/<id>/multi-agent
# --------------------------------------------------------------------------

def test_start_workflow_sends_python_evidence_and_logs_the_run(client, fake_server):
    doc_id = create_doc(client)
    response = client.post(f"/api/documents/{doc_id}/multi-agent")

    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "planning"
    assert body["document_id"] == doc_id

    method, url, sent = fake_server.calls[0]
    assert (method, url) == ("POST", "http://multi-agent.test:5004/workflow")
    assert sent["caller"] == "Enerel"
    assert sent["async"] is True
    assert set(sent["evidence"]) == {"document_metadata", "document_text"}
    assert body["sent"]["word_count"] == 18
    assert sent["evidence"]["document_metadata"]["title"] == "ETF Fees in 2025"

    [row] = log_rows("multi_agent_workflow")
    assert row["response_text"] == body["run_id"]
    assert row["document_id"] == doc_id
    assert json.loads(row["prompt_sent"])["task"] == sent["task"]


def test_start_workflow_unknown_document_is_404_without_a_call(client, fake_server):
    assert client.post("/api/documents/999/multi-agent").status_code == 404
    assert fake_server.calls == []


def test_start_workflow_disabled_is_503_without_a_call(client, monkeypatch):
    doc_id = create_doc(client)
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")

    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 503
    assert response.get_json()["multi_agent_enabled"] is False
    assert log_rows("multi_agent_workflow") == []


def test_start_workflow_server_down_is_503(client, monkeypatch):
    doc_id = create_doc(client)

    def refuse(*a, **k):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(multi_agent_client.requests, "request", refuse)
    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "unreachable"
    assert "multi-agent-server/run.sh" in body["error"]
    assert "could not reach the Multi-Agent Server" in body["detail"]


def test_start_workflow_timeout_is_504(client, monkeypatch):
    doc_id = create_doc(client)

    def slow(*a, **k):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(multi_agent_client.requests, "request", slow)
    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 504
    assert response.get_json()["code"] == "timeout"


def test_agents_unavailable_keeps_the_servers_code(client, monkeypatch):
    doc_id = create_doc(client)
    monkeypatch.setattr(
        multi_agent_client.requests, "request",
        lambda *a, **k: FakeResponse(503, {"error": "agent_unavailable", "detail": "Ollama is down"}),
    )
    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "agent_unavailable"
    assert "STUB_AGENTS=true" in body["error"]
    assert "Ollama is down" in body["detail"]


def test_server_rejecting_our_own_request_is_502_not_400(client, monkeypatch):
    doc_id = create_doc(client)
    monkeypatch.setattr(
        multi_agent_client.requests, "request",
        lambda *a, **k: FakeResponse(400, {"error": "validation_failed", "detail": "task is required",
                                           "fields": {"task": "is required"}}),
    )
    response = client.post(f"/api/documents/{doc_id}/multi-agent")
    assert response.status_code == 502
    assert response.get_json()["fields"] == {"task": "is required"}


# --------------------------------------------------------------------------
# GET /api/multi-agent/runs/<run_id>
# --------------------------------------------------------------------------

def test_get_run_returns_agent_output(client, fake_server):
    run_id = start_run(client, fake_server, create_doc(client))

    response = client.get(f"/api/multi-agent/runs/{run_id}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "awaiting_human"
    assert body["plan"][0]["evidence"] == ["document_text"]


def test_get_run_hides_repeated_lines(client, fake_server):
    run_id = start_run(client, fake_server, create_doc(client))
    fake_server.runs[run_id]["work"] = "Step 1: Stats.\n- Words: 18\n- Words: 18\n-  words: 18\n- Fees fell."

    body = client.get(f"/api/multi-agent/runs/{run_id}").get_json()
    assert body["work"] == "Step 1: Stats.\n- Words: 18\n- Fees fell."
    assert body["work_repeated_lines_removed"] == 2


def test_get_run_refuses_runs_this_backend_did_not_start(client, fake_server):
    foreign = uuid.uuid4().hex
    fake_server.runs[foreign] = {"run_id": foreign, "status": "awaiting_human"}

    assert client.get(f"/api/multi-agent/runs/{foreign}").status_code == 404
    assert client.get("/api/multi-agent/runs/not-a-run-id").status_code == 404
    assert fake_server.calls == []


# --------------------------------------------------------------------------
# POST /api/multi-agent/runs/<run_id>/review -- the human gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("review", [
    {"decision": "approve"},
    {"decision": "correct", "corrected": "The document has 18 words and 3 sentences."},
    {"decision": "partial", "note": "Step 1 is accepted; the rest needs work."},
    {"decision": "reject", "note": "Off topic."},
])
def test_each_human_decision_completes_the_run_and_is_logged(client, fake_server, review):
    run_id = start_run(client, fake_server, create_doc(client))

    response = client.post(f"/api/multi-agent/runs/{run_id}/review", json=review)
    assert response.status_code == 200
    assert response.get_json()["status"] == "complete"
    assert response.get_json()["decision"] == review["decision"]

    sent = fake_server.calls[-1][2]
    assert sent["decision"] == review["decision"]
    assert sent["reviewer"] == "Enerel"

    [row] = log_rows("multi_agent_review")
    assert row["prompt_sent"] == run_id
    assert row["model_name"] == "human"
    assert json.loads(row["response_text"])["decision"] == review["decision"]

    expected_brief = {
        "approve": fake_server.runs[run_id]["work"],
        "partial": fake_server.runs[run_id]["work"],
        "correct": review.get("corrected"),
        "reject": None,
    }[review["decision"]]
    assert response.get_json()["brief_text"] == expected_brief
    assert json.loads(row["response_text"])["brief_text"] == expected_brief


# --------------------------------------------------------------------------
# GET /api/documents/<id>/brief -- the accepted result
# --------------------------------------------------------------------------

def test_brief_is_404_until_one_is_accepted(client, fake_server):
    doc_id = create_doc(client)
    assert client.get(f"/api/documents/{doc_id}/brief").status_code == 404

    run_id = start_run(client, fake_server, doc_id)
    client.post(f"/api/multi-agent/runs/{run_id}/review", json={"decision": "reject"})
    assert client.get(f"/api/documents/{doc_id}/brief").status_code == 404
    assert client.get("/api/documents/999/brief").status_code == 404


def test_approved_brief_is_shown_with_its_takeaways(client, fake_server):
    doc_id = create_doc(client)
    run_id = start_run(client, fake_server, doc_id)
    client.post(f"/api/multi-agent/runs/{run_id}/review", json={"decision": "approve"})

    body = client.get(f"/api/documents/{doc_id}/brief").get_json()
    assert body["run_id"] == run_id
    assert body["decision"] == "approve"
    assert body["takeaways"] == ["Fees fell.", "Compare fees."]


def test_latest_accepted_brief_wins_and_a_later_reject_keeps_it(client, fake_server):
    doc_id = create_doc(client)
    first = start_run(client, fake_server, doc_id)
    client.post(f"/api/multi-agent/runs/{first}/review", json={"decision": "approve"})
    second = start_run(client, fake_server, doc_id)
    client.post(f"/api/multi-agent/runs/{second}/review",
                json={"decision": "correct", "corrected": "- Fees fell to 0.15%."})
    third = start_run(client, fake_server, doc_id)
    client.post(f"/api/multi-agent/runs/{third}/review", json={"decision": "reject"})

    body = client.get(f"/api/documents/{doc_id}/brief").get_json()
    assert body["run_id"] == second
    assert body["takeaways"] == ["Fees fell to 0.15%."]


def test_takeaways_are_list_items_only():
    assert workflow_evidence.takeaways("Step 1: Look.\nStep 2: Sum up.") == []
    assert workflow_evidence.takeaways("Plain prose only.") == []
    assert workflow_evidence.takeaways("- `document_metadata` **matters**") == ["document_metadata matters"]
    assert workflow_evidence.takeaways("- A\n- B\n- A\n- A") == ["A", "B"]


@pytest.mark.parametrize("review, message", [
    ({"decision": "maybe"}, "decision must be one of"),
    ({"decision": "correct"}, "corrected is required"),
    ({"decision": "partial"}, "note is required"),
    ({"decision": "approve", "corrected": "x"}, "corrected is only allowed"),
])
def test_invalid_review_is_400_and_not_forwarded(client, fake_server, review, message):
    run_id = start_run(client, fake_server, create_doc(client))
    calls_before = len(fake_server.calls)

    response = client.post(f"/api/multi-agent/runs/{run_id}/review", json=review)
    assert response.status_code == 400
    assert message in response.get_json()["error"]
    assert len(fake_server.calls) == calls_before


def test_second_review_is_409_from_the_server(client, fake_server):
    run_id = start_run(client, fake_server, create_doc(client))
    assert client.post(f"/api/multi-agent/runs/{run_id}/review", json={"decision": "approve"}).status_code == 200

    response = client.post(f"/api/multi-agent/runs/{run_id}/review", json={"decision": "reject"})
    assert response.status_code == 409
    assert response.get_json()["code"] == "conflict"
    assert "already been reviewed" in response.get_json()["error"]


def test_integrations_reports_multi_agent_mode(client, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    body = client.get("/api/library/integrations").get_json()
    assert body["multi_agent"] == {"enabled": False, "server_url": "http://multi-agent.test:5004"}
