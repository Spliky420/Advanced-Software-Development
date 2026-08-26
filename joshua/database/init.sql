-- init.sql
-- Schema for the portfolio/insight database (Joshua's microservice).
-- SQLite. Run once to (re)create the schema; use seed.sql to load sample data.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS insight_log;
DROP TABLE IF EXISTS allocation_targets;
DROP TABLE IF EXISTS holdings;

-- One row per position a user holds (a single ticker bought at one average cost).
CREATE TABLE holdings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    ticker         TEXT NOT NULL,
    asset_name     TEXT NOT NULL,
    asset_class    TEXT NOT NULL,
    units          REAL NOT NULL,
    average_cost   REAL NOT NULL,          -- cost per unit, in `currency`
    currency       TEXT NOT NULL,
    last_price     REAL,                   -- most recent known price per unit, in `currency`
    price_as_at    TEXT,                   -- ISO8601 date the last_price was observed
    purchase_date  TEXT NOT NULL,          -- ISO8601 date
    notes          TEXT
);

-- A user's target allocation per asset class. One row per (user_id, asset_class);
-- targets for a given user should sum to 100.
CREATE TABLE allocation_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    asset_class     TEXT NOT NULL,
    target_percent  REAL NOT NULL,
    UNIQUE (user_id, asset_class)
);

-- Audit trail of every LLM call made on a user's behalf. prompt_sent already
-- contains any figures the LLM needs (computed in Python) -- the LLM performs
-- no arithmetic of its own.
CREATE TABLE insight_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    created_at     TEXT NOT NULL,          -- ISO8601 timestamp
    request_type   TEXT NOT NULL,
    prompt_sent    TEXT NOT NULL,
    model_name     TEXT NOT NULL,          -- e.g. llama3.1:8b, qwen2.5:0.5b
    response_text  TEXT
);

CREATE INDEX idx_holdings_user_id ON holdings (user_id);
CREATE INDEX idx_holdings_asset_class ON holdings (asset_class);
CREATE INDEX idx_allocation_targets_user_id ON allocation_targets (user_id);
CREATE INDEX idx_insight_log_user_id ON insight_log (user_id);
