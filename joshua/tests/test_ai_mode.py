"""AI_MODE_ENABLED=false: no AI service is called, and nothing else breaks.

With the switch off, every client refuses before opening a connection,
CRUD and allocation behave exactly as with it on, /api/insights answers a
clean JSON 503, and /api/drift-review still returns its Python-computed
figures with the Python fallback summary. The same degradation applies when
the switch is on but Ollama cannot answer.
"""

import pytest

import ai_mode
import drift
import llm
import mcp_client
import rag_client

NEW_HOLDING = {
    "ticker": "ZZTEST",
    "asset_name": "AI-off test holding",
    "asset_class": "Cash",
    "units": 10,
    "average_cost": 1.0,
    "currency": "AUD",
    "last_price": 1.0,
    "purchase_date": "2026-01-02",
}


@pytest.fixture
def ai_off(monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")


@pytest.fixture
def no_network(monkeypatch):
    """Fail the test if any client tries to open a connection."""

    def refuse(*args, **kwargs):
        raise AssertionError("an AI service was called with AI_MODE_ENABLED=false")

    monkeypatch.setattr(llm.requests, "post", refuse)
    monkeypatch.setattr(rag_client.requests, "request", refuse)
    monkeypatch.setattr(mcp_client.asyncio, "run", refuse)


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "OFF", " false "])
def test_false_values_switch_ai_off(monkeypatch, value):
    monkeypatch.setenv("AI_MODE_ENABLED", value)
    assert ai_mode.is_enabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "anything", ""])
def test_other_values_leave_ai_on(monkeypatch, value):
    monkeypatch.setenv("AI_MODE_ENABLED", value)
    assert ai_mode.is_enabled() is True


def test_unset_means_on(monkeypatch):
    monkeypatch.delenv("AI_MODE_ENABLED", raising=False)
    assert ai_mode.is_enabled() is True


def test_every_client_refuses_without_a_connection(ai_off, no_network, monkeypatch):
    # URLs set, so only the switch can be what stops each call.
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp.invalid:5002/mcp")
    monkeypatch.setenv("RAG_SERVER_URL", "http://rag.invalid:5003")

    with pytest.raises(llm.LLMDisabledError):
        llm.generate("figures")

    retrieved = rag_client.retrieve("query", 3)
    assert retrieved["ok"] is False
    assert retrieved["status"] == "disabled"

    [tool] = mcp_client.call_tools([("glossary_lookup", {"term": "ETF"})])
    assert tool["ok"] is False
    assert "AI mode is disabled" in tool["error"]


def test_crud_and_allocation_work_with_ai_off(api_client, ai_off, no_network):
    created = api_client.post("/api/holdings", json=NEW_HOLDING)
    assert created.status_code == 201
    holding_id = created.get_json()["id"]

    read = api_client.get(f"/api/holdings/{holding_id}")
    assert read.status_code == 200
    assert read.get_json()["ticker"] == "ZZTEST"

    updated = api_client.put(f"/api/holdings/{holding_id}", json={**NEW_HOLDING, "units": 20})
    assert updated.status_code == 200
    assert updated.get_json()["units"] == 20

    assert api_client.get("/api/allocation").status_code == 200
    assert api_client.get("/api/targets").status_code == 200

    assert api_client.delete(f"/api/holdings/{holding_id}").status_code == 204
    assert api_client.get(f"/api/holdings/{holding_id}").status_code == 404


def test_insights_says_ai_is_disabled(api_client, ai_off, no_network):
    response = api_client.post("/api/insights")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ai_status"] == "disabled"
    assert body["ai_enabled"] is False
    assert "AI is disabled" in body["error"]
    assert "Traceback" not in response.get_data(as_text=True)


def test_insights_says_ai_is_unavailable_when_ollama_fails(api_client, monkeypatch):
    def unreachable(prompt, system=None):
        raise llm.LLMUnavailableError("could not reach Ollama")

    monkeypatch.setattr(llm, "generate", unreachable)
    response = api_client.post("/api/insights")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ai_status"] == "unavailable"
    assert body["ai_enabled"] is True
    assert "AI is unavailable" in body["error"]


def _expected_fallback(api_client):
    """The fallback summary built from the same pipeline the endpoint runs."""
    import allocation
    import db

    targets = db.list_targets(db.DEFAULT_USER_ID)
    report = allocation.build_portfolio_report(db.list_holdings(db.DEFAULT_USER_ID))
    plan_result = drift.plan(targets)
    observe_result = drift.observe(drift.act(report["portfolio"], plan_result), plan_result)
    return drift.build_fallback_summary(observe_result)


def test_drift_review_with_ai_off_returns_figures_and_fallback(api_client, ai_off, no_network):
    response = api_client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ai_used"] is False
    assert body["ai_enabled"] is False

    # The figures are all still there.
    assert body["observe"]["breach_count"] >= 1
    assert body["act"]["drift_by_class"]
    assert body["act"]["total_market_value"] > 0

    # Nothing AI-backed ran.
    assert body["context"]["mcp_called"] is False
    assert body["context"]["rag_called"] is False
    assert "AI mode is disabled" in body["context"]["reason"]
    adapt = body["adapt"]
    assert adapt["llm_called"] is False
    assert adapt["summary_source"] == "ai_disabled"
    assert adapt["citations"] == []
    assert body["insight_log_id"] is None

    assert adapt["summary"] == _expected_fallback(api_client)


def test_drift_review_survives_ollama_failing(api_client, monkeypatch):
    def unreachable(prompt, system=None):
        raise llm.LLMUnavailableError("could not reach Ollama")

    monkeypatch.setattr(llm, "generate", unreachable)
    response = api_client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ai_enabled"] is True
    assert body["ai_used"] is False
    assert body["adapt"]["summary_source"] == "ai_unavailable"
    assert body["adapt"]["ai_error"] == "could not reach Ollama"
    assert body["adapt"]["summary"] == _expected_fallback(api_client)


def test_drift_review_reports_ai_used_when_the_model_answers(api_client, monkeypatch):
    def compliant(prompt, system=None):
        return "ETFs are overweight.", "stand-in"

    monkeypatch.setattr(llm, "generate", compliant)
    body = api_client.post("/api/drift-review").get_json()

    assert body["ai_used"] is True
    assert body["adapt"]["llm_called"] is True
    assert body["adapt"]["summary_source"] == "model"
