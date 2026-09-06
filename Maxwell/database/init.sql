-- init.sql
-- Schema for the financial‑glossary database (Maxwell's microservice).
-- SQLite. Run once to (re)create the schema; use seed.sql to load sample data.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS terms;

CREATE TABLE terms (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    term    TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL
);

CREATE INDEX idx_terms_term ON terms (term);
