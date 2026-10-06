"""Release 1 endpoints: MCP glossary lookup and RAG grounded Q&A.

MCP and RAG are never reached for real here -- the same rule CI enforces by
running with MCP_ENABLED=false / RAG_ENABLED=false. Each test stubs the one
network leg it needs (mcp_client._run, rag_client.retrieve/answer).
"""

import sqlite3

import pytest

import db
import library_qa
import mcp_client
import rag_client
from test_app import client, make_payload, no_real_ollama_calls  # noqa: F401 -- pytest fixtures
from test_mcp_client import text_result

# Captured at import, before the autouse fixture below stubs it out.
REAL_RETRIEVE = rag_client.retrieve

VOLATILITY_DOC = make_payload(
    title="Volatility and the ETF",
    body_text="Market volatility rose as investors sold the ETF. Dollar-cost averaging helps.",
)


@pytest.fixture(autouse=True)
def modes_on_and_isolated(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setattr(mcp_client, "_run", lambda *a: pytest.fail("MCP should have been stubbed"))
    monkeypatch.setattr(rag_client, "retrieve", lambda *a: pytest.fail("RAG /retrieve should have been stubbed"))
    monkeypatch.setattr(rag_client, "answer", lambda *a: pytest.fail("RAG /answer should have been stubbed"))
    # Creating a document indexes it; keep that off the network too.
    monkeypatch.setattr("embeddings.index_document", lambda *a: {"indexed": False})


def create_doc(client, payload=VOLATILITY_DOC):
    response = client.post("/api/documents", json=payload)
    assert response.status_code == 201
    return response.get_json()["id"]


def stub_mcp(monkeypatch, payload):
    calls = []

    def fake_run(url, tool, arguments):
        calls.append((tool, arguments))
        return text_result(payload)

    monkeypatch.setattr(mcp_client, "_run", fake_run)
    return calls


def log_rows(request_type):
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM document_ai_log WHERE request_type = ?", (request_type,)
        )]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# GET /api/library/integrations
# --------------------------------------------------------------------------

def test_integrations_reports_modes_and_boundary(client, monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    body = client.get("/api/library/integrations").get_json()

    assert body["mcp"]["enabled"] is True
    assert body["mcp"]["allowed_tools"] == ["glossary_lookup"]
    assert body["rag"]["enabled"] is False


# --------------------------------------------------------------------------
# POST /api/documents/:id/glossary -- MCP
# --------------------------------------------------------------------------

def test_glossary_lookup_calls_mcp_tool_with_normalised_term(client, monkeypatch):
    doc_id = create_doc(client)
    calls = stub_mcp(monkeypatch, {"term": "Volatility", "definition": "A statistical measure of dispersion."})

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "volatility"})
    body = response.get_json()

    assert response.status_code == 200
    assert calls == [("glossary_lookup", {"term": "Volatility"})]
    assert body["tool"] == "glossary_lookup"
    assert body["found"] is True
    assert body["definition"] == "A statistical measure of dispersion."
    assert body["term"] == "volatility"


def test_glossary_lookup_keeps_acronyms_and_is_logged(client, monkeypatch):
    doc_id = create_doc(client)
    calls = stub_mcp(monkeypatch, {"term": "ETF", "definition": "Exchange-Traded Fund"})

    body = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "ETF"}).get_json()

    assert calls == [("glossary_lookup", {"term": "ETF"})]
    [row] = log_rows("mcp_glossary_lookup")
    assert row["id"] == body["ai_log_id"]
    assert row["document_id"] == doc_id
    assert row["model_name"] == "mcp:glossary_lookup"
    assert row["response_text"] == "Exchange-Traded Fund"


def test_hyphenated_multi_word_term_is_title_cased(client, monkeypatch):
    doc_id = create_doc(client)
    calls = stub_mcp(monkeypatch, {"term": "Dollar-Cost Averaging", "definition": "x"})

    client.post(f"/api/documents/{doc_id}/glossary", json={"term": "dollar-cost  averaging"})

    assert calls == [("glossary_lookup", {"term": "Dollar-Cost Averaging"})]


def test_term_not_in_glossary_is_a_valid_result_not_an_error(client, monkeypatch):
    doc_id = create_doc(client)
    stub_mcp(monkeypatch, {"error": "Backend returned 400: http://maxwell-backend:5000/api/glossary/Helps"})

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "helps"})
    body = response.get_json()

    assert response.status_code == 200
    assert body["found"] is False
    assert body["definition"] is None
    assert "not in the financial glossary" in body["message"]


def test_glossary_backend_down_behind_mcp_is_502(client, monkeypatch):
    doc_id = create_doc(client)
    stub_mcp(monkeypatch, {"error": "Could not reach backend at http://maxwell-backend:5000/api/glossary/ETF"})

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "ETF"})

    assert response.status_code == 502
    assert log_rows("mcp_glossary_lookup") == []


def test_term_must_appear_in_the_document(client, monkeypatch):
    doc_id = create_doc(client)

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "mortgage"})

    assert response.status_code == 400
    assert "does not appear in this document" in response.get_json()["error"]


def test_partial_word_does_not_count_as_appearing(client):
    doc_id = create_doc(client)
    # "vol" is inside "volatility" but is not a word of the document.
    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "vol"})
    assert response.status_code == 400


@pytest.mark.parametrize("term", [None, "", " ", "x", "a" * 61, "ETF; DROP TABLE", "<script>"])
def test_invalid_terms_are_rejected_before_mcp(client, term):
    doc_id = create_doc(client)
    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": term})
    assert response.status_code == 400


def test_glossary_on_missing_document_is_404(client):
    response = client.post("/api/documents/999/glossary", json={"term": "ETF"})
    assert response.status_code == 404


def test_glossary_with_mcp_disabled_is_503(client, monkeypatch):
    doc_id = create_doc(client)
    monkeypatch.setenv("MCP_ENABLED", "false")

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "ETF"})

    assert response.status_code == 503
    assert response.get_json()["mcp_enabled"] is False


def test_glossary_with_mcp_unreachable_is_503(client, monkeypatch):
    doc_id = create_doc(client)

    def boom(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(mcp_client, "_run", boom)

    response = client.post(f"/api/documents/{doc_id}/glossary", json={"term": "ETF"})

    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"]


# --------------------------------------------------------------------------
# POST /api/library/ask -- RAG
# --------------------------------------------------------------------------

LIBRARY_CHUNK = {
    "rank": 1,
    "chunk_id": "Enerel_research_library_knowledge_2",
    "source_id": "Enerel_research_library_knowledge.txt",
    "text": "The Research Library summarizes a long document map-reduce style.",
    "distance": 0.9,
}


def stub_rag(monkeypatch, chunks, answer_text="Each chunk is summarized, then combined."):
    answers = []
    monkeypatch.setattr(rag_client, "retrieve", lambda q, k: list(chunks))

    def fake_answer(q, k):
        answers.append(q)
        return {"answer": answer_text, "confidence_category": "High", "citations": []}

    monkeypatch.setattr(rag_client, "answer", fake_answer)
    return answers


def test_ask_returns_grounded_answer_with_citations_and_confidence(client, monkeypatch):
    stub_rag(monkeypatch, [LIBRARY_CHUNK])

    response = client.post("/api/library/ask", json={"question": "How does the library summarize a long document?"})
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "answered"
    assert body["answer"] == "Each chunk is summarized, then combined."
    assert body["confidence_category"] == "High"
    assert body["citations"] == [{
        "source_id": "Enerel_research_library_knowledge.txt",
        "chunk_id": "Enerel_research_library_knowledge_2",
        "matched_terms": ["library", "summarize", "long", "document"],
        "snippet": LIBRARY_CHUNK["text"],
    }]
    assert [body[p]["phase"] for p in ("plan", "act", "observe", "adapt")] == ["plan", "act", "observe", "adapt"]

    [row] = log_rows("rag_ask")
    assert row["id"] == body["ai_log_id"]
    assert row["model_name"] == "rag-server"


def test_ask_unrelated_question_is_insufficient_context_without_a_model_call(client, monkeypatch):
    answers = stub_rag(monkeypatch, [LIBRARY_CHUNK])

    body = client.post("/api/library/ask", json={"question": "Who won the football world cup?"}).get_json()

    assert body["status"] == "insufficient_context"
    assert body["confidence_category"] == "Insufficient"
    assert body["citations"] == []
    assert body["answer"] == library_qa.INSUFFICIENT_ANSWER
    assert body["adapt"]["llm_called"] is False
    assert answers == []


def test_ask_model_insufficient_evidence_has_no_citations(client, monkeypatch):
    stub_rag(monkeypatch, [LIBRARY_CHUNK], answer_text="Insufficient evidence.")

    body = client.post("/api/library/ask", json={"question": "How does the library summarize a long document?"}).get_json()

    assert body["status"] == "insufficient_context"
    assert body["citations"] == []
    assert body["confidence_category"] == "Insufficient"


@pytest.mark.parametrize("payload", [None, {}, {"question": ""}, {"question": "what is it?"}, {"question": 5}])
def test_ask_bad_question_is_400(client, payload):
    response = client.post("/api/library/ask", json=payload)
    assert response.status_code == 400


def test_ask_with_rag_disabled_is_503(client, monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    # Restore the real client so its own disabled check is what stops it;
    # requests.post is refused in case that check ever regresses.
    monkeypatch.setattr(rag_client, "retrieve", REAL_RETRIEVE)
    monkeypatch.setattr(rag_client.requests, "post", lambda *a, **k: pytest.fail("RAG reached while disabled"))

    response = client.post("/api/library/ask", json={"question": "summarize documents"})

    assert response.status_code == 503
    assert response.get_json()["rag_enabled"] is False


def test_ask_with_rag_unreachable_is_503(client, monkeypatch):
    def boom(q, k):
        raise rag_client.RAGUnavailableError("could not reach the RAG server")

    monkeypatch.setattr(rag_client, "retrieve", boom)

    response = client.post("/api/library/ask", json={"question": "summarize documents"})

    assert response.status_code == 503
    assert log_rows("rag_ask") == []

