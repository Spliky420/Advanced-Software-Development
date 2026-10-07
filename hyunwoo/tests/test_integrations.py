from types import SimpleNamespace
from pathlib import Path

import pytest
import requests

import integrations
import llm
import provider_references


def tool_result(**changes):
    data = {
        "bills": [{"name": "Netflix"}],
        "summary": {
            "active_bill_count": 10, "auto_renew_count": 9,
            "monthly_cost": 620.24, "annual_cost": 7442.9,
        },
    }
    return SimpleNamespace(isError=False, structuredContent=data, content=[], **changes)


def mock_mcp(monkeypatch, result):
    monkeypatch.setenv("MCP_ENABLED", "true")

    async def call():
        return result

    monkeypatch.setattr(integrations, "_call_bill_tool", call)


def test_mcp_returns_shared_tool_result(client, monkeypatch):
    mock_mcp(monkeypatch, tool_result())
    response = client.post("/api/bills/mcp")
    assert response.status_code == 200
    assert response.json["tool"] == "bill_summary"
    assert response.json["result"]["summary"]["monthly_cost"] == 620.24


def test_mcp_reads_json_text_content(monkeypatch):
    import json
    result = tool_result()
    result.content = [SimpleNamespace(type="text", text=json.dumps(result.structuredContent))]
    result.structuredContent = None
    mock_mcp(monkeypatch, result)
    assert integrations.bill_tool()["result"]["summary"]["active_bill_count"] == 10


@pytest.mark.parametrize("failure", ["tool_error", "backend_error", "invalid"])
def test_mcp_rejects_tool_failures(client, monkeypatch, failure):
    result = tool_result()
    if failure == "tool_error":
        result.isError = True
    elif failure == "backend_error":
        result.structuredContent = {"error": "Backend unreachable"}
    else:
        result.structuredContent = {"bills": []}
    mock_mcp(monkeypatch, result)
    assert client.post("/api/bills/mcp").status_code == 503


def test_mcp_connection_failure_is_503(client, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")

    async def unavailable():
        raise OSError("Connection refused")

    monkeypatch.setattr(integrations, "_call_bill_tool", unavailable)
    assert client.post("/api/bills/mcp").status_code == 503


def test_disabled_modes_never_contact_services(client, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    monkeypatch.setattr(integrations, "_call_bill_tool", lambda: pytest.fail("MCP called"))
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("Network called"))
    assert client.post("/api/bills/mcp").status_code == 503
    assert client.post("/api/bills/rag", json={"query": "How are bills calculated?"}).status_code == 503
    with pytest.raises(llm.LLMError, match="disabled"):
        llm.generate("test")
    assert client.get("/api/summary").status_code == 200


CONTEXT = {
    "source_id": "HyunWoo_bills_knowledge.txt", "chunk_id": "bills_2",
    "text": "Fortnightly bills are converted into monthly cost by multiplying by 26 and dividing by 12.",
}


def mock_rag(monkeypatch, answer=None, contexts=None):
    monkeypatch.setenv("RAG_ENABLED", "true")
    calls = []

    def request(path, payload):
        calls.append((path, payload))
        if path == "/retrieve":
            return {"results": contexts if contexts is not None else [CONTEXT]}
        return answer if answer is not None else {
            "answer": "Multiply the fortnightly amount by 26 and divide by 12.",
            "citations": [{"source_id": CONTEXT["source_id"], "chunk_id": CONTEXT["chunk_id"]}],
        }

    monkeypatch.setattr(integrations, "_rag_request", request)
    return calls


def test_rag_returns_answer_with_verified_source_and_confidence(client, monkeypatch):
    calls = mock_rag(monkeypatch)
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert response.json["confidence_category"] == "High"
    assert response.json["citations"][0]["excerpt"] == CONTEXT["text"]
    assert [path for path, _ in calls] == ["/retrieve", "/answer"]
    assert calls[0][1]["caller"] == "hyunwoo"
    assert all(payload["source_ids"] == [CONTEXT["source_id"]] for _, payload in calls)


def test_bills_query_ignores_other_features_even_if_words_match(client, monkeypatch):
    foreign = {**CONTEXT, "source_id": "Enerel_investment_terms_knowledge.txt"}
    calls = mock_rag(monkeypatch, contexts=[foreign])
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["status"] == "insufficient_context"
    assert response.json["llm_called"] is False
    assert len(calls) == 1


def test_expanded_corpus_cannot_replace_the_bills_reference(client, monkeypatch):
    foreign = {**CONTEXT, "source_id": "Enerel_investment_terms_knowledge.txt"}
    calls = mock_rag(monkeypatch, contexts=[foreign, CONTEXT], answer={
        "answer": CONTEXT["text"], "citations": [foreign, CONTEXT],
    })
    response = client.post("/api/bills/rag", json={
        "query": "How are fortnightly bills converted to a monthly cost?",
    })
    assert response.json["status"] == "success"
    assert response.json["answer"] == CONTEXT["text"]
    assert [item["source_id"] for item in response.json["citations"]] == [CONTEXT["source_id"]]
    assert all(payload["source_ids"] == [CONTEXT["source_id"]] for _, payload in calls)


def test_unrelated_query_skips_answer_generation(client, monkeypatch):
    calls = mock_rag(monkeypatch)
    response = client.post("/api/bills/rag", json={"query": "Who won the lunar football tournament?"})
    assert response.json["status"] == "insufficient_context"
    assert response.json["confidence_category"] == "Low"
    assert response.json["citations"] == []
    assert response.json["llm_called"] is False
    assert len(calls) == 1


def test_unverified_numerical_answer_uses_original_source(client, monkeypatch):
    mock_rag(monkeypatch, answer={
        "answer": "Multiply the fortnightly amount by 52 and divide by 12.",
        "citations": [{"source_id": CONTEXT["source_id"], "chunk_id": CONTEXT["chunk_id"]}],
    })
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["source_excerpt_fallback_used"] is True
    assert response.json["llm_called"] is True
    assert CONTEXT["text"] in response.json["answer"]
    assert "52" not in response.json["answer"]


def test_exact_source_quote_is_preserved(client, monkeypatch):
    mock_rag(monkeypatch, answer={
        "answer": CONTEXT["text"],
        "citations": [{"source_id": CONTEXT["source_id"], "chunk_id": CONTEXT["chunk_id"]}],
    })
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["source_excerpt_fallback_used"] is False
    assert response.json["answer_kind"] == "generated"
    assert response.json["answer"] == CONTEXT["text"]


def test_empty_retrieval_returns_insufficient_context(client, monkeypatch):
    mock_rag(monkeypatch, contexts=[])
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["status"] == "insufficient_context"


def test_model_insufficient_evidence_is_displayed_as_insufficient_context(client, monkeypatch):
    mock_rag(monkeypatch, answer={"answer": "Insufficient evidence."})
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["status"] == "insufficient_context"
    assert response.json["llm_called"] is True


def test_declined_bills_answer_can_show_strong_verified_source(client, monkeypatch):
    mock_rag(monkeypatch, answer={"answer": "Insufficient evidence.", "citations": [CONTEXT]})
    response = client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"})
    assert response.json["status"] == "success"
    assert response.json["answer_kind"] == "source_excerpt"
    assert response.json["source_excerpt_fallback_reason"] == "model_abstention"
    assert response.json["llm_called"] is True
    assert "The model could not produce an answer" in response.json["answer"]
    assert CONTEXT["text"] in response.json["answer"]


@pytest.mark.parametrize("citation", [
    {"source_id": "invented.txt", "chunk_id": "fake"},
    {"source_id": [], "chunk_id": "fake"},
])
def test_declined_answer_cannot_bypass_citation_validation(client, monkeypatch, citation):
    mock_rag(monkeypatch, answer={"answer": "Insufficient evidence.", "citations": [citation]})
    assert client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"}).status_code == 503


@pytest.mark.parametrize("citations", [[], [{"source_id": "invented.txt", "chunk_id": "fake"}], [{"source_id": [], "chunk_id": "fake"}]])
def test_uncited_or_invented_sources_are_rejected(client, monkeypatch, citations):
    mock_rag(monkeypatch, answer={"answer": "An unsupported answer.", "citations": citations})
    assert client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"}).status_code == 503


@pytest.mark.parametrize("payload", [[], {}, {"query": " "}, {"query": 123}, {"query": "x" * 501}, {"query": "bills", "k": 0}, {"query": "bills", "k": True}])
def test_rag_invalid_input_is_rejected(client, monkeypatch, payload):
    monkeypatch.setattr(integrations, "rag_answer", lambda *a: pytest.fail("RAG called"))
    assert client.post("/api/bills/rag", json=payload).status_code == 400


def test_rag_unavailable_keeps_existing_api_working(client, monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "true")

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", unavailable)
    assert client.post("/api/bills/rag", json={"query": "Fortnightly monthly cost"}).status_code == 503
    assert client.get("/health").json["status"] == "healthy"
    assert len(client.get("/api/bills").json) == 10


def provider_context(source):
    path = Path(__file__).resolve().parents[2] / "rag-server" / "corpus" / source
    return {"source_id": source, "chunk_id": f"{path.stem}_1", "text": path.read_text()}


@pytest.mark.parametrize("source", provider_references.SOURCES)
def test_provider_documents_keep_facts_and_metadata_in_one_chunk(source):
    context = provider_context(source)
    assert len(context["text"].split()) <= 80
    assert f"Source: {provider_references.SOURCES[source]['source_url']}" in context["text"]
    assert f"Checked: {provider_references.CHECKED_ON}" in context["text"]


@pytest.mark.parametrize("query,source", [
    ("How do I cancel Netflix?", "HyunWoo_provider_Netflix_cancel.txt"),
    ("Where can I find my Netflix billing date?", "HyunWoo_provider_Netflix_billing.txt"),
    ("Why is the Netflix cancel option missing?", "HyunWoo_provider_Netflix_partner.txt"),
    ("Will I keep my Spotify playlists after cancelling?", "HyunWoo_provider_Spotify_cancel.txt"),
    ("What happens if I cancel a Spotify free trial?", "HyunWoo_provider_Spotify_trial.txt"),
    ("How can I change my Spotify billing date?", "HyunWoo_provider_Spotify_billing.txt"),
])
def test_provider_answers_include_checked_official_source(client, monkeypatch, query, source):
    context = provider_context(source)
    mock_rag(monkeypatch, contexts=[context], answer={
        "answer": "The provider gives these instructions.", "citations": [context],
    })
    response = client.post("/api/bills/rag", json={"query": query})
    assert response.json["status"] == "success"
    citation = response.json["citations"][0]
    assert citation["source_url"] == provider_references.SOURCES[source]["source_url"]
    assert citation["checked_on"] == "2026-10-02"
    assert response.json["source_excerpt_fallback_reason"] == "provider_grounding"
    assert provider_references.reference_body(context["text"]) in response.json["answer"]
    assert "Source:" not in response.json["answer"]


@pytest.mark.parametrize("query,source", [
    ("How do I cancel Netflix?", "HyunWoo_provider_Netflix_cancel.txt"),
    ("Where can I find my Netflix billing date?", "HyunWoo_provider_Netflix_billing.txt"),
    ("Why is the Netflix cancel option missing?", "HyunWoo_provider_Netflix_partner.txt"),
    ("Will I keep my Spotify playlists after cancelling?", "HyunWoo_provider_Spotify_cancel.txt"),
    ("What happens if I cancel a Spotify free trial?", "HyunWoo_provider_Spotify_trial.txt"),
    ("How can I change my Spotify billing date?", "HyunWoo_provider_Spotify_billing.txt"),
])
def test_supported_provider_refusals_show_labelled_reference(client, monkeypatch, query, source):
    context = provider_context(source)
    calls = mock_rag(monkeypatch, contexts=[context], answer={
        "answer": "Insufficient evidence.", "citations": [context],
    })
    response = client.post("/api/bills/rag", json={"query": query})
    assert response.json["status"] == "success"
    assert response.json["answer_kind"] == "source_excerpt"
    assert response.json["source_excerpt_fallback_reason"] == "model_abstention"
    assert response.json["llm_called"] is True
    assert "The model could not produce an answer" in response.json["answer"]
    assert provider_references.reference_body(context["text"]) in response.json["answer"]
    assert response.json["citations"][0]["source_url"] == provider_references.SOURCES[source]["source_url"]
    assert all(payload["source_ids"] == [source] for _, payload in calls)


@pytest.mark.parametrize("answer", [
    {"answer": "Insufficient evidence."},
    {"status": "insufficient_context", "answer": "The source cannot resolve this question."},
])
def test_weak_source_match_does_not_override_model_refusal(client, monkeypatch, answer):
    context = provider_context("HyunWoo_provider_Spotify_cancel.txt")
    mock_rag(monkeypatch, contexts=[context], answer={**answer, "citations": [context]})
    response = client.post("/api/bills/rag", json={"query": "Spotify cancellation tax consequences"})
    assert response.json["status"] == "insufficient_context"
    assert response.json["citations"] == []
    assert response.json["confidence_category"] == "Low"
    assert response.json["llm_called"] is True


def test_model_refusal_cannot_use_a_retrieved_but_wrong_provider_citation(client, monkeypatch):
    spotify = provider_context("HyunWoo_provider_Spotify_cancel.txt")
    netflix = provider_context("HyunWoo_provider_Netflix_cancel.txt")
    mock_rag(monkeypatch, contexts=[spotify, netflix], answer={
        "answer": "Insufficient evidence.", "citations": [netflix],
    })
    response = client.post("/api/bills/rag", json={"query": "Will I keep my Spotify playlists after cancelling?"})
    assert response.json["status"] == "insufficient_context"
    assert response.json["citations"] == []


@pytest.mark.parametrize("query", [
    "What is Netflix's current price in Australia?",
    "What is Netflix's cancellation fee?",
    "Can I get a refund after cancelling Netflix?",
    "What is Spotify's student discount?",
    "What promotions does Spotify offer?",
    "What is my Netflix password?",
])
def test_missing_provider_topics_never_generate_an_answer(client, monkeypatch, query):
    contexts = [provider_context(source) for source in provider_references.SOURCES]
    calls = mock_rag(monkeypatch, contexts=contexts)
    response = client.post("/api/bills/rag", json={"query": query})
    assert response.json["status"] == "insufficient_context"
    assert response.json["llm_called"] is False
    assert len(calls) == 1


def test_provider_question_does_not_use_other_provider_or_app_facts(client, monkeypatch):
    contexts = [provider_context("HyunWoo_provider_Netflix_cancel.txt"), {
        "source_id": "HyunWoo_bills_knowledge.txt", "chunk_id": "bills_1",
        "text": "Spotify cancellation is not performed by this app.",
    }]
    calls = mock_rag(monkeypatch, contexts=contexts)
    response = client.post("/api/bills/rag", json={"query": "How do I cancel Spotify?"})
    assert response.json["status"] == "insufficient_context"
    assert len(calls) == 1


def test_free_trial_question_requires_trial_context(client, monkeypatch):
    calls = mock_rag(monkeypatch, contexts=[provider_context("HyunWoo_provider_Spotify_cancel.txt")])
    response = client.post("/api/bills/rag", json={"query": "What happens if I cancel a Spotify free trial?"})
    assert response.json["status"] == "insufficient_context"
    assert len(calls) == 1


def test_provider_policy_hallucination_uses_reference_instead(client, monkeypatch):
    context = provider_context("HyunWoo_provider_Netflix_cancel.txt")
    mock_rag(monkeypatch, contexts=[context], answer={
        "answer": "After cancellation, Netflix stays free forever.",
        "citations": [context],
    })
    response = client.post("/api/bills/rag", json={"query": "What happens when I cancel Netflix?"})
    assert "forever" not in response.json["answer"]
    assert "paid period" in response.json["answer"]
    assert response.json["source_excerpt_fallback_used"] is True


def test_model_cannot_choose_a_provider_source_link(client, monkeypatch):
    context = provider_context("HyunWoo_provider_Spotify_cancel.txt")
    mock_rag(monkeypatch, contexts=[context], answer={
        "answer": provider_references.reference_body(context["text"]),
        "citations": [{**context, "source_url": "javascript:alert(1)", "checked_on": "2099-01-01"}],
    })
    response = client.post("/api/bills/rag", json={"query": "How do I cancel Spotify?"})
    assert response.json["source_excerpt_fallback_used"] is False
    citation = response.json["citations"][0]
    assert citation["source_url"] == provider_references.SPOTIFY_CANCEL_URL
    assert citation["checked_on"] == provider_references.CHECKED_ON
