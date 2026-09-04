"""Neither LLM endpoint may report a figure the Python layer did not calculate.

The model is only ever handed finished numbers, so every figure that reaches a
client -- in the prompt, in the model's prose, and in the structured drift
sections -- has to trace back to allocation.build_portfolio_report or to the
drift pipeline built on top of it. This is the property that holds even when
the model reads the supplied figures badly (see CLAUDE.md, "Known limitation").
"""

import os
import re
import sqlite3

import pytest

import allocation
import app as app_module
import db
import drift
import llm

DATABASE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "database"
)

# A deliberately uneven portfolio: ETFs are plainly the largest class and
# Australian equities a much smaller one -- the pair a 0.5b model has been seen
# to confuse.
HOLDINGS = [
    ("VAS.AX", "Vanguard Australian Shares Index ETF", "ETFs",
     300, 85.00, "AUD", 97.80),
    ("VGS.AX", "Vanguard MSCI International Shares ETF", "ETFs",
     150, 98.00, "AUD", 112.30),
    ("CBA.AX", "Commonwealth Bank of Australia", "Australian equities",
     50, 95.00, "AUD", 162.50),
    ("BHP.AX", "BHP Group Limited", "Australian equities",
     200, 45.00, "AUD", 41.20),
    ("AAPL", "Apple Inc.", "International equities",
     30, 145.00, "USD", 227.50),
    ("GOLD.AX", "Global X Physical Gold", "Commodities",
     100, 30.00, "AUD", 38.75),
]

# Far enough from the actual split to guarantee at least one breach, so the
# drift review actually reaches ADAPT and calls the model.
TARGETS = [
    ("ETFs", 25.0),
    ("Australian equities", 35.0),
    ("International equities", 25.0),
    ("Commodities", 15.0),
]

NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _numbers_in(text):
    """Every number appearing in a block of text, as floats rounded to 2dp."""
    return [round(float(match), 2) for match in NUMBER_PATTERN.findall(text)]


def _floats_in(value):
    """Every float in a parsed JSON structure.

    Only floats: ints in these responses are structural (row ids, user ids,
    breach counts), never money or percentage figures.
    """
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [round(value, 2)]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _floats_in(item)]
    if isinstance(value, list):
        return [n for item in value for n in _floats_in(item)]
    return []


def _calculated_figures():
    """Every figure the Python layer calculates, rounded the way output is.

    Built by running the same pipeline the endpoints run, so the set is derived
    from the calculation rather than restated by hand. Absolute values are
    included too: a negative figure is rendered as "$-123.45" and the number
    scraped back out of that text is 123.45.
    """
    holdings = db.list_holdings(db.DEFAULT_USER_ID)
    targets = db.list_targets(db.DEFAULT_USER_ID)
    report = allocation.build_portfolio_report(holdings)

    plan_result = drift.plan(targets)
    act_result = drift.act(report["portfolio"], plan_result)
    observe_result = drift.observe(act_result, plan_result)

    figures = set()
    for source in (report, plan_result, act_result, observe_result):
        for number in _floats_in(source):
            figures.add(number)
            figures.add(abs(number))
    return figures


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "portfolio.db"
    conn = sqlite3.connect(db_path)
    try:
        with open(os.path.join(DATABASE_DIR, "init.sql"), encoding="utf-8") as handle:
            conn.executescript(handle.read())
        conn.executemany(
            """
            INSERT INTO holdings
                (user_id, ticker, asset_name, asset_class, units, average_cost,
                 currency, last_price, price_as_at, purchase_date, notes)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, '2026-08-22', '2022-01-01', NULL)
            """,
            HOLDINGS,
        )
        conn.executemany(
            "INSERT INTO allocation_targets (user_id, asset_class, target_percent)"
            " VALUES (1, ?, ?)",
            TARGETS,
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setenv("DRIFT_THRESHOLD_PERCENT", "5")

    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def compliant_model(monkeypatch):
    """Stand-in for a model that obeys the prompt: it quotes, and only quotes,
    the figures it was given."""

    def generate(prompt, system=None):
        quoted = ", ".join(f"{number:.2f}" for number in _numbers_in(prompt))
        return f"Using only the supplied figures: {quoted}.", "qwen2.5:0.5b"

    monkeypatch.setattr(llm, "generate", generate)


def test_insights_reports_no_figure_the_python_layer_did_not_calculate(
    client, compliant_model
):
    allowed = _calculated_figures()

    response = client.post("/api/insights")
    assert response.status_code == 201

    body = response.get_json()
    # Both text fields reach the client, so both have to hold. prompt_sent is
    # the load-bearing one: it is what the model is allowed to work from.
    for field in ("prompt_sent", "response_text"):
        invented = set(_numbers_in(body[field])) - allowed
        assert not invented, f"{field} contains uncalculated figures: {sorted(invented)}"


def test_drift_review_reports_no_figure_the_python_layer_did_not_calculate(
    client, compliant_model
):
    allowed = _calculated_figures()

    response = client.post("/api/drift-review")
    assert response.status_code == 200

    body = response.get_json()
    assert body["adapt"]["llm_called"] is True, "expected a breach that reaches the model"

    for field, text in (
        ("adapt.summary", body["adapt"]["summary"]),
        ("plan.description", body["plan"]["description"]),
    ):
        invented = set(_numbers_in(text)) - allowed
        assert not invented, f"{field} contains uncalculated figures: {sorted(invented)}"

    # The structured phases are pure Python; every figure in them must match.
    for phase in ("plan", "act", "observe"):
        invented = set(_floats_in(body[phase])) - allowed
        assert not invented, f"{phase} contains uncalculated figures: {sorted(invented)}"


def test_the_check_itself_catches_an_invented_figure(client):
    """Guards the assertions above: they must fail on a fabricated number."""
    allowed = _calculated_figures()

    fabricated = "The portfolio returned 87.65% over the last 12 months."

    assert set(_numbers_in(fabricated)) - allowed
