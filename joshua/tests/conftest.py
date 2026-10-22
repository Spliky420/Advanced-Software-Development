import os
import sqlite3
import sys

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database")

# A small fixed portfolio for endpoint tests. Far enough from TARGETS that
# ETFs breach overweight and Australian equities underweight at the 5-point
# threshold, so a drift review always reaches ADAPT.
SEED_HOLDINGS = [
    ("VAS.AX", "Vanguard Australian Shares Index ETF", "ETFs", 300, 85.00, "AUD", 97.80),
    ("VGS.AX", "Vanguard MSCI International Shares ETF", "ETFs", 150, 98.00, "AUD", 112.30),
    ("CBA.AX", "Commonwealth Bank of Australia", "Australian equities", 50, 95.00, "AUD", 162.50),
    ("BHP.AX", "BHP Group Limited", "Australian equities", 200, 45.00, "AUD", 41.20),
    ("AAPL", "Apple Inc.", "International equities", 30, 145.00, "USD", 227.50),
    ("GOLD.AX", "Global X Physical Gold", "Commodities", 100, 30.00, "AUD", 38.75),
]
SEED_TARGETS = [
    ("ETFs", 25.0),
    ("Australian equities", 35.0),
    ("International equities", 25.0),
    ("Commodities", 15.0),
]


@pytest.fixture(autouse=True)
def _mcp_and_rag_off_by_default(monkeypatch):
    """Keep every test off the network: an empty MCP_SERVER_URL or
    RAG_SERVER_URL switches that client off. Tests that exercise either one
    set their own URL."""
    monkeypatch.setenv("MCP_SERVER_URL", "")
    monkeypatch.setenv("RAG_SERVER_URL", "")


@pytest.fixture(autouse=True)
def _ai_mode_on_by_default(monkeypatch):
    """Most tests exercise the AI paths against a stand-in model, so they need
    AI_MODE_ENABLED on whatever the runner's environment says (CI sets it to
    false). Tests of the off switch set it to false themselves. With it on,
    nothing still reaches a real service: every model call in the suite is
    monkeypatched or injected, and CI points Ollama at an unreachable port."""
    monkeypatch.setenv("AI_MODE_ENABLED", "true")


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """A Flask test client over a fresh database seeded with SEED_HOLDINGS and
    SEED_TARGETS, built from the real schema in joshua/database/init.sql."""
    import app as app_module
    import db

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
            SEED_HOLDINGS,
        )
        conn.executemany(
            "INSERT INTO allocation_targets (user_id, asset_class, target_percent) VALUES (1, ?, ?)",
            SEED_TARGETS,
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setenv("DRIFT_THRESHOLD_PERCENT", "5")

    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()
