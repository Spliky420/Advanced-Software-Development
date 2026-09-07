-- schema.sql
-- Schema for the Goals & Budgeting database (Le Hoa Long's microservice).
-- SQLite. Run once to (re)create the schema; use seed.sql to load sample data.
--
-- Conventions:
--   * every id is INTEGER PRIMARY KEY AUTOINCREMENT
--   * every date/timestamp is ISO-8601 TEXT
--       - dates:      YYYY-MM-DD
--       - timestamps: YYYY-MM-DDTHH:MM:SS
--   * enum-like columns are constrained with CHECK, so a bad status can never
--     reach the database even if a caller bypasses the API's validation layer
--   * money is REAL, matching the rest of the repo. All arithmetic on it
--     happens in Python (see CLAUDE.md) and is rounded at the service layer.

PRAGMA foreign_keys = ON;

-- Dropped child-first so the foreign keys never block the drop.
DROP TABLE IF EXISTS ai_plan_log;
DROP TABLE IF EXISTS contributions;
DROP TABLE IF EXISTS goal_steps;
DROP TABLE IF EXISTS budget_settings;
DROP TABLE IF EXISTS goals;

-- ---------------------------------------------------------------------------
-- goals: one savings goal belonging to one user.
-- ---------------------------------------------------------------------------
CREATE TABLE goals (
    goal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    name          TEXT    NOT NULL,
    target_amount REAL    NOT NULL CHECK (target_amount > 0),
    target_date   TEXT    NOT NULL,                  -- ISO-8601 date
    priority      TEXT    NOT NULL DEFAULT 'medium'
                          CHECK (priority IN ('high', 'medium', 'low')),
    status        TEXT    NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'paused', 'achieved', 'abandoned')),
    created_at    TEXT    NOT NULL,                  -- ISO-8601 timestamp
    updated_at    TEXT    NOT NULL                   -- ISO-8601 timestamp
);

-- ---------------------------------------------------------------------------
-- goal_steps: the ordered savings plan for a goal.
--
-- `source` records who authored the step: 'ai' for one the LLM produced (or
-- the deterministic fallback plan stood in for), 'user' for one the user wrote
-- or edited by hand. Adapt/replan only ever rewrites 'pending' steps, so a
-- completed step is never lost to a regeneration.
-- ---------------------------------------------------------------------------
CREATE TABLE goal_steps (
    step_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id     INTEGER NOT NULL REFERENCES goals (goal_id) ON DELETE CASCADE,
    step_order  INTEGER NOT NULL CHECK (step_order > 0),
    description TEXT    NOT NULL,
    step_amount REAL    NOT NULL CHECK (step_amount >= 0),
    due_date    TEXT    NOT NULL,                    -- ISO-8601 date
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'complete', 'skipped')),
    source      TEXT    NOT NULL DEFAULT 'ai'
                        CHECK (source IN ('ai', 'user')),
    created_at  TEXT    NOT NULL,                    -- ISO-8601 timestamp
    UNIQUE (goal_id, step_order)
);

-- ---------------------------------------------------------------------------
-- contributions: money actually put toward a goal. This is the ACT phase of
-- the agentic loop -- the only table the user writes to by doing rather than
-- by planning.
-- ---------------------------------------------------------------------------
CREATE TABLE contributions (
    contribution_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id           INTEGER NOT NULL REFERENCES goals (goal_id) ON DELETE CASCADE,
    amount            REAL    NOT NULL CHECK (amount > 0),
    contribution_date TEXT    NOT NULL,              -- ISO-8601 date
    notes             TEXT
);

-- ---------------------------------------------------------------------------
-- ai_plan_log: audit trail of every phase of the agentic loop.
--
-- Two deliberate choices here:
--
--   * ON DELETE SET NULL, not CASCADE. This table is the evidence trail for
--     the technical report; deleting a goal must not erase the record that a
--     model was called. goal_id is therefore nullable, and the prompt text
--     names the goal so an orphaned row is still readable.
--
--   * model_name is NOT NULL and holds the literal 'python' for phases that
--     ran without touching the LLM. OBSERVE is pure Python arithmetic, and
--     PLAN/ADAPT fall back to a deterministic even split when the model
--     misbehaves -- both still get logged, and 'python' is how you tell them
--     apart from a real model call when reading the table.
-- ---------------------------------------------------------------------------
CREATE TABLE ai_plan_log (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id    INTEGER REFERENCES goals (goal_id) ON DELETE SET NULL,
    phase      TEXT    NOT NULL CHECK (phase IN ('plan', 'observe', 'adapt')),
    model_name TEXT    NOT NULL,                     -- e.g. qwen2.5:0.5b, llama3.1:8b, python
    prompt     TEXT    NOT NULL,                     -- exact text sent, figures already computed
    response   TEXT,                                 -- raw response, before parsing
    created_at TEXT    NOT NULL                      -- ISO-8601 timestamp
);

-- ---------------------------------------------------------------------------
-- budget_settings: the user's monthly savings budget.
--
-- DOCUMENTED ADDITION to the registered design: the feature spec requires a
-- budget summary panel comparing total monthly commitment against a budget,
-- and the original four-table design had nowhere to store that budget. See
-- the README.
--
-- UNIQUE (user_id) -- one current budget per user, not a history.
-- ---------------------------------------------------------------------------
CREATE TABLE budget_settings (
    setting_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL UNIQUE,
    monthly_budget REAL    NOT NULL CHECK (monthly_budget >= 0),
    currency       TEXT    NOT NULL DEFAULT 'AUD',
    updated_at     TEXT    NOT NULL                  -- ISO-8601 timestamp
);

-- ---------------------------------------------------------------------------
-- Indexes: every column the API filters or joins on.
-- ---------------------------------------------------------------------------
CREATE INDEX idx_goals_user_id            ON goals (user_id);
CREATE INDEX idx_goals_status             ON goals (status);
CREATE INDEX idx_goals_priority           ON goals (priority);
CREATE INDEX idx_goal_steps_goal_id       ON goal_steps (goal_id, step_order);
CREATE INDEX idx_goal_steps_status        ON goal_steps (status);
CREATE INDEX idx_contributions_goal_id    ON contributions (goal_id, contribution_date);
CREATE INDEX idx_ai_plan_log_goal_id      ON ai_plan_log (goal_id, created_at);
CREATE INDEX idx_ai_plan_log_phase        ON ai_plan_log (phase);
