"""Endpoint tests run as their own CI step, with AI_MODE_ENABLED=false.

Two endpoints, exercised through Flask's test client against a real SQLite
database built from joshua/database/init.sql and the conftest seed:

1. Holdings CRUD: POST /api/holdings then GET /api/holdings/<id>.
2. POST /api/drift-review with AI switched off, so the result is fully
   predictable: no Ollama, MCP or RAG, and the summary is built in Python.

The expected drift figures are worked by hand from SEED_HOLDINGS/TARGETS
(conftest.py), not read back from the code under test:

  ETFs        300 x 97.80 + 150 x 112.30 = 46,185.00
  Aus equities 50 x 162.50 + 200 x 41.20 = 16,365.00
  Intl equities              30 x 227.50 =  6,825.00
  Commodities                100 x 38.75 =  3,875.00
  Total                                    73,250.00

  ETFs    46,185 / 73,250 = 63.05%  vs 25%  -> +38.05 overweight
  Intl     6,825 / 73,250 =  9.32%  vs 25%  -> -15.68 underweight
  Aus     16,365 / 73,250 = 22.34%  vs 35%  -> -12.66 underweight
  Comm     3,875 / 73,250 =  5.29%  vs 15%  ->  -9.71 underweight
"""

import pytest

import llm

NEW_HOLDING = {
    "ticker": "VHY.AX",
    "asset_name": "Vanguard Australian Shares High Yield ETF",
    "asset_class": "ETFs",
    "units": 40,
    "average_cost": 68.5,
    "currency": "AUD",
    "last_price": 74.25,
    "price_as_at": "2026-10-20",
    "purchase_date": "2025-03-14",
    "notes": "CI endpoint test",
}

EXPECTED_BREACHES = [
    ("ETFs", 25.0, 63.05, 38.05, "overweight"),
    ("International equities", 25.0, 9.32, 15.68, "underweight"),
    ("Australian equities", 35.0, 22.34, 12.66, "underweight"),
    ("Commodities", 15.0, 5.29, 9.71, "underweight"),
]

EXPECTED_SUMMARY = (
    "The following asset classes have drifted by at least 5.00 percentage points from target: "
    "ETFs is 38.05 percentage points overweight (target 25.00%, actual 63.05%); "
    "International equities is 15.68 percentage points underweight (target 25.00%, actual 9.32%); "
    "Australian equities is 12.66 percentage points underweight (target 35.00%, actual 22.34%); "
    "Commodities is 9.71 percentage points underweight (target 15.00%, actual 5.29%)."
)


@pytest.fixture(autouse=True)
def ai_disabled(monkeypatch):
    """Both endpoint tests run with AI off, matching the CI job's environment."""
    monkeypatch.setenv("AI_MODE_ENABLED", "false")


def test_create_then_read_holding(api_client):
    created = api_client.post("/api/holdings", json=NEW_HOLDING)

    assert created.status_code == 201
    holding = created.get_json()
    assert isinstance(holding["id"], int)
    assert holding["user_id"] == 1

    read = api_client.get(f"/api/holdings/{holding['id']}")
    assert read.status_code == 200
    stored = read.get_json()
    for field, value in NEW_HOLDING.items():
        assert stored[field] == value, field

    listed = api_client.get("/api/holdings").get_json()
    assert [h["id"] for h in listed].count(holding["id"]) == 1
    assert len(listed) == 7  # six seeded + this one

    # Validation still guards the write path.
    rejected = api_client.post("/api/holdings", json={**NEW_HOLDING, "units": -1})
    assert rejected.status_code == 400
    assert "units must be a positive number" in rejected.get_json()["errors"]


def test_drift_review_with_ai_disabled_is_predictable(api_client, monkeypatch):
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("Ollama was called with AI_MODE_ENABLED=false")

    monkeypatch.setattr(llm.requests, "post", must_not_be_called)

    response = api_client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()

    assert body["ai_enabled"] is False
    assert body["ai_used"] is False

    assert body["plan"]["threshold_percent"] == 5.0
    assert body["act"]["total_market_value"] == 73250.0
    assert body["observe"]["breach_count"] == 4
    assert [
        (b["asset_class"], b["target_percent"], b["actual_percent"], b["drift_magnitude"], b["direction"])
        for b in body["observe"]["breaches"]
    ] == EXPECTED_BREACHES
    assert body["observe"]["within_threshold"] == []

    assert body["context"]["mcp_called"] is False
    assert body["context"]["rag_called"] is False

    adapt = body["adapt"]
    assert adapt["llm_called"] is False
    assert adapt["summary_source"] == "ai_disabled"
    assert adapt["summary"] == EXPECTED_SUMMARY
    assert adapt["unsupplied_figures"] == []
    assert adapt["misattributed"] == []
    assert adapt["citations"] == []
    assert body["insight_log_id"] is None
