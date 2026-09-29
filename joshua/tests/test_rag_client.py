"""RAG client and the grounded drift review.

No RAG container is needed: StubRAGServer is a real local HTTP server speaking
the contract in joshua/RAG_INTEGRATION.md, so timeouts, HTTP 500s and JSON
parsing all go through the real requests code path.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import allocation
import db
import drift
import llm
import rag_client

from test_no_invented_figures import (  # noqa: F401 -- pytest fixtures
    _calculated_figures,
    _numbers_in,
    client,
)

# Deliberately out of distance order: the client must not re-sort.
PASSAGES = [
    {"rank": 1, "chunk_id": "pf_2", "source_id": "pf.txt",
     "text": "Rebalancing returns a portfolio to its target mix.", "distance": 0.91},
    {"rank": 2, "chunk_id": "pf_7", "source_id": "pf.txt",
     "text": "Index ETFs became widespread after 1993; some charge fees near 12% of returns.",
     "distance": 0.12},
    {"rank": 3, "chunk_id": "eq_1", "source_id": "equities.txt",
     "text": "Equities are ownership stakes in companies.", "distance": 0.55},
]


class StubRAGServer:
    """Serves one configurable response per path and records every request."""

    def __init__(self):
        self.responses = {}
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else None
                stub.requests.append({"method": self.command, "path": self.path, "body": body})
                status, payload, delay = stub.responses.get(
                    self.path, (404, {"error": "not_found"}, 0)
                )
                time.sleep(delay)
                data = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client gave up (timeout test)

            do_GET = _reply
            do_POST = _reply

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def respond(self, path, payload, status=200, delay=0):
        self.responses[path] = (status, payload, delay)


@pytest.fixture
def rag_server(monkeypatch):
    server = StubRAGServer()
    server.thread.start()
    monkeypatch.setenv("RAG_SERVER_URL", server.url)
    monkeypatch.setenv("RAG_TIMEOUT_SECONDS", "2")
    yield server
    server.httpd.shutdown()
    server.httpd.server_close()


def retrieve_payload(results):
    return {"status": "success", "query": "q", "k": 3, "results": results}


# --------------------------------------------------------------------------
# Client: the four required cases
# --------------------------------------------------------------------------

def test_answer_returns_answer_citations_and_confidence(rag_server):
    rag_server.respond("/answer", {
        "status": "success",
        "query": "what is an ETF",
        "answer": "An ETF is a fund traded on an exchange.",
        "citations": [
            {"chunk_id": "pf_7", "source_id": "pf.txt"},
            {"chunk_id": "pf_2", "source_id": "pf.txt"},
        ],
        "confidence_category": "Medium",
        "retrieval_summary": {"k": 5, "retrieved_count": 2},
    })

    result = rag_client.answer("what is an ETF", k=5)

    assert result["ok"] is True
    assert result["data"] == {
        "answer": "An ETF is a fund traded on an exchange.",
        "citations": [
            {"chunk_id": "pf_7", "source_id": "pf.txt"},
            {"chunk_id": "pf_2", "source_id": "pf.txt"},
        ],
        "confidence_category": "Medium",
    }
    assert rag_server.requests[0]["body"] == {"query": "what is an ETF", "k": 5, "top_k": 5}


def test_empty_results_are_ok_and_empty(rag_server):
    rag_server.respond("/retrieve", retrieve_payload([]))

    result = rag_client.retrieve("anything", k=3)

    assert result["ok"] is True
    assert result["data"]["chunks"] == []


def test_http_500_is_reported_as_unavailable(rag_server):
    rag_server.respond("/retrieve", {"status": "error", "error": "collection missing"}, status=500)

    result = rag_client.retrieve("anything")

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"] == "RAG server returned 500: collection missing"


def test_slow_server_times_out_instead_of_hanging(rag_server, monkeypatch):
    monkeypatch.setenv("RAG_TIMEOUT_SECONDS", "0.2")
    rag_server.respond("/retrieve", retrieve_payload(PASSAGES), delay=1.5)

    started = time.monotonic()
    result = rag_client.retrieve("anything")

    assert time.monotonic() - started < 1.2
    assert result["ok"] is False
    assert "did not respond within 0.2s" in result["error"]


# --------------------------------------------------------------------------
# Client: contract details
# --------------------------------------------------------------------------

def test_retrieve_sends_k_and_top_k_and_keeps_server_order(rag_server):
    rag_server.respond("/retrieve", retrieve_payload(PASSAGES))

    result = rag_client.retrieve("rebalancing", k=3)

    assert rag_server.requests[0]["body"] == {"query": "rebalancing", "k": 3, "top_k": 3}
    chunks = result["data"]["chunks"]
    assert [c["chunk_id"] for c in chunks] == ["pf_2", "pf_7", "eq_1"]
    # Distances pass through untouched, in their original (unsorted) order.
    assert [c["distance"] for c in chunks] == [0.91, 0.12, 0.55]


def test_retrieve_drops_entries_without_text_but_does_not_reorder(rag_server):
    rag_server.respond("/retrieve", retrieve_payload([
        PASSAGES[0], {"rank": 2, "chunk_id": "x", "distance": 0.1}, PASSAGES[2],
    ]))

    chunks = rag_client.retrieve("q")["data"]["chunks"]

    assert [c["chunk_id"] for c in chunks] == ["pf_2", "eq_1"]


def test_200_with_error_status_is_unavailable(rag_server):
    rag_server.respond("/retrieve", {"status": "error", "error": "boom"})

    assert rag_client.retrieve("q")["ok"] is False


def test_response_without_results_list_is_unavailable(rag_server):
    rag_server.respond("/retrieve", {"status": "success"})

    result = rag_client.retrieve("q")

    assert result["ok"] is False
    assert "no results list" in result["error"]


def test_health(rag_server):
    rag_server.respond("/health", {"status": "ok", "service": "rag-server"})

    assert rag_client.health()["ok"] is True


def test_empty_query_is_rejected_without_a_request(rag_server):
    assert rag_client.retrieve("   ")["ok"] is False
    assert rag_server.requests == []


def test_unreachable_server_degrades(monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("RAG_SERVER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("RAG_TIMEOUT_SECONDS", "3")

    result = rag_client.retrieve("q")

    assert result["ok"] is False
    assert "RAG server" in result["error"]


def test_empty_server_url_disables_rag():
    # conftest sets RAG_SERVER_URL to "" for every test.
    result = rag_client.retrieve("q")

    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_unset_server_url_defaults_to_the_compose_address(monkeypatch):
    monkeypatch.delenv("RAG_SERVER_URL")

    assert rag_client.get_server_url() == "http://rag-server:5003"


# --------------------------------------------------------------------------
# Grounded drift review
# --------------------------------------------------------------------------

def figures_block(prompt):
    """The PORTFOLIO FIGURES part of a user prompt, without the reference."""
    return prompt.split(drift.REFERENCE_HEADING)[0]


@pytest.fixture
def recording_model(monkeypatch):
    """A model that obeys the prompt: it quotes only the portfolio figures."""
    calls = []

    def generate(prompt, system=None):
        calls.append({"prompt": prompt, "system": system})
        quoted = ", ".join(f"{n:.2f}" for n in _numbers_in(figures_block(prompt)))
        return f"Using only the supplied figures: {quoted}.", "stub-model"

    monkeypatch.setattr(llm, "generate", generate)
    return calls


def test_retrieved_passages_ground_the_prompt_and_are_cited_in_order(
    client, rag_server, recording_model
):
    rag_server.respond("/retrieve", retrieve_payload(PASSAGES))

    body = client.post("/api/drift-review").get_json()

    prompt = recording_model[0]["prompt"]
    assert drift.REFERENCE_HEADING in prompt
    assert PASSAGES[0]["text"] in prompt
    assert "reference material" in recording_model[0]["system"].lower()
    assert "verbatim" in recording_model[0]["system"]

    adapt_section = body["adapt"]
    assert adapt_section["summary_source"] == "model"
    rag_citations = [c for c in adapt_section["citations"] if c["kind"] == "rag"]
    assert [(c["chunk_id"], c["distance"]) for c in rag_citations] == [
        ("pf_2", 0.91), ("pf_7", 0.12), ("eq_1", 0.55),
    ]
    assert body["context"]["retrieval"]["status"] == "found"


def test_a_number_from_retrieved_text_never_becomes_a_portfolio_figure(
    client, rag_server, monkeypatch
):
    # Precondition: the passage's year and percentage are not figures the
    # pipeline calculates, so either one in the output can only be a leak.
    allowed = _calculated_figures()
    assert {1993.0, 12.0}.isdisjoint(allowed)

    def quotes_the_reference_material(prompt, system=None):
        return "ETFs are 12% overweight, a trend since 1993.", "stub-model"

    monkeypatch.setattr(llm, "generate", quotes_the_reference_material)
    rag_server.respond("/retrieve", retrieve_payload(PASSAGES))

    body = client.post("/api/drift-review").get_json()
    adapt_section = body["adapt"]

    assert adapt_section["summary_source"] == "fallback"
    assert {1993.0, 12.0} <= set(adapt_section["unsupplied_figures"])
    assert adapt_section["citations"] == [], "a rejected summary cites nothing"

    summary_figures = set(_numbers_in(adapt_section["summary"]))
    assert summary_figures.isdisjoint({1993.0, 12.0})
    assert summary_figures <= allowed

    # And the figures are exactly allocation.py's, run through the same
    # pipeline the endpoint runs.
    report = allocation.build_portfolio_report(db.list_holdings(db.DEFAULT_USER_ID))
    plan_result = drift.plan(db.list_targets(db.DEFAULT_USER_ID))
    act_result = drift.act(report["portfolio"], plan_result)
    observe_result = drift.observe(act_result, plan_result)
    assert adapt_section["summary"] == drift.build_fallback_summary(observe_result)


def test_empty_retrieval_leaves_the_reference_block_out(client, rag_server, recording_model):
    rag_server.respond("/retrieve", retrieve_payload([]))

    body = client.post("/api/drift-review").get_json()

    assert drift.REFERENCE_HEADING not in recording_model[0]["prompt"]
    assert body["context"]["retrieval"]["status"] == "empty"
    assert body["adapt"]["citations"] == []
    assert body["adapt"]["summary_source"] == "model"


def test_drift_review_succeeds_with_the_rag_server_returning_500(
    client, rag_server, recording_model
):
    rag_server.respond("/retrieve", {"status": "error", "error": "down"}, status=500)

    response = client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()
    assert body["context"]["retrieval"]["status"] == "unavailable"
    assert body["adapt"]["summary_source"] == "model"


def test_drift_review_succeeds_with_the_rag_server_timing_out(
    client, rag_server, recording_model, monkeypatch
):
    monkeypatch.setenv("RAG_TIMEOUT_SECONDS", "0.2")
    rag_server.respond("/retrieve", retrieve_payload(PASSAGES), delay=1.5)

    response = client.post("/api/drift-review")

    assert response.status_code == 200
    assert response.get_json()["context"]["retrieval"]["status"] == "unavailable"
