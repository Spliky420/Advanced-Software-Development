from types import SimpleNamespace

import pytest
import requests

import integrations
import llm


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
