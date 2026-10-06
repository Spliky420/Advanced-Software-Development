"""Regression tests for init_db.check().

These exist because of a real incident. `check()` was written to verify what
seed.sql claims, but `main()` ran it on every container start -- including
against a live database. The moment a goal was replanned, its steps stopped
summing to its target (correctly: replan rebuilds the pending steps from
`target - contributions`, while completed steps keep the amounts they were
planned with, and those two need not agree). `check()` called that a problem,
`main()` returned 1, and the entrypoint's `set -eu` turned it into a
crash-looping database container that took the whole stack down.

The fix splits the claims in two, and that split is what these tests pin:

  * structural corruption is fatal always
  * seed-time invariants are fatal only on a freshly built database, and are
    advisory once real activity has touched the data

The distinction matters in both directions, so every test here asserts both
halves -- that a fresh build still refuses bad data (the marking requirement
of >=10 rows per table depends on it) and that a live one still starts.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = REPO_ROOT / "LeHoaLong" / "database"

# init_db.py is a script beside schema.sql, not an installed package.
sys.path.insert(0, str(DATABASE_DIR))

import init_db  # noqa: E402  (import must follow the sys.path edit)


@pytest.fixture
def conn(db_path):
    """A connection to this test's own seeded copy of the database."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def test_freshly_seeded_database_is_clean(conn):
    """The seed data must satisfy every claim it makes, with nothing to report."""
    fatal, advisory = init_db.check(conn, fresh=True)

    assert fatal == []
    assert advisory == []


def _replan_drift(conn):
    """Make one goal's steps stop summing to its target, as a replan does."""
    conn.execute(
        "UPDATE goal_steps SET step_amount = step_amount + 17.00 "
        "WHERE step_id = (SELECT MIN(step_id) FROM goal_steps)"
    )
    conn.commit()


def test_replan_drift_is_fatal_on_a_fresh_build(conn):
    """seed.sql itself producing a drifted goal is a bug and must fail loudly."""
    _replan_drift(conn)

    fatal, advisory = init_db.check(conn, fresh=True)

    assert advisory == []
    assert any("steps sum to" in problem for problem in fatal)


def test_replan_drift_is_only_advisory_on_a_live_database(conn):
    """The incident this module exists for: a replanned goal must still boot."""
    _replan_drift(conn)

    fatal, advisory = init_db.check(conn, fresh=False)

    assert fatal == []
    assert any("steps sum to" in note for note in advisory)


def test_row_count_shortfall_is_fatal_on_a_fresh_build(conn):
    """The >=10 rows marking requirement stays enforced where it is a guarantee."""
    conn.execute("DELETE FROM budget_settings WHERE setting_id > 3")
    conn.commit()

    fatal, advisory = init_db.check(conn, fresh=True)

    assert advisory == []
    assert any("fewer than the required" in problem for problem in fatal)


def test_row_count_shortfall_is_only_advisory_on_a_live_database(conn):
    """A user deleting their own rows is not a reason to refuse to start."""
    conn.execute("DELETE FROM budget_settings WHERE setting_id > 3")
    conn.commit()

    fatal, advisory = init_db.check(conn, fresh=False)

    assert fatal == []
    assert any("fewer than the required" in note for note in advisory)


def test_unfunded_achieved_goal_is_only_advisory_on_a_live_database(conn):
    """Marking a goal achieved early is a user action, not corruption."""
    goal_id = conn.execute(
        "SELECT goal_id FROM goals WHERE status != 'achieved' LIMIT 1"
    ).fetchone()["goal_id"]
    conn.execute("DELETE FROM contributions WHERE goal_id = ?", (goal_id,))
    conn.execute("UPDATE goals SET status = 'achieved' WHERE goal_id = ?", (goal_id,))
    conn.commit()

    fatal, advisory = init_db.check(conn, fresh=False)

    assert fatal == []
    assert any("marked achieved" in note for note in advisory)


@pytest.mark.parametrize("fresh", [True, False])
def test_orphaned_row_is_fatal_however_the_database_got_there(conn, fresh):
    """Structural corruption is the one thing that is never excusable.

    A contribution pointing at a goal that does not exist could not have been
    produced by any correct write, so the container should refuse to come up
    around it whether the file was just seeded or has been in use for weeks.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO contributions (goal_id, amount, contribution_date, notes) "
        "VALUES (99999, 10.0, '2026-01-01', 'orphan')"
    )
    conn.commit()

    fatal, _ = init_db.check(conn, fresh=fresh)

    assert any("foreign key violation" in problem for problem in fatal)


# ---------------------------------------------------------------------------
# migrate_ai_plan_log -- Release 1's two extra phases on an existing file
# ---------------------------------------------------------------------------
#
# Release 1 logs MCP tool calls and RAG answers to ai_plan_log, whose `phase`
# column is constrained by a CHECK. Every goals.db already on the
# lehoalong-db-data volume was built with the Release 0 constraint and would
# reject those rows with an IntegrityError -- at the moment of the first MCP
# call, which is to say live, in front of a marker. init_db.py migrates such a
# file in place on container start instead, and these tests pin that it
# preserves what is already there.

RELEASE_0_AI_PLAN_LOG = """
CREATE TABLE release_0_log (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id    INTEGER REFERENCES goals (goal_id) ON DELETE SET NULL,
    phase      TEXT    NOT NULL CHECK (phase IN ('plan', 'observe', 'adapt')),
    model_name TEXT    NOT NULL,
    prompt     TEXT    NOT NULL,
    response   TEXT,
    created_at TEXT    NOT NULL
);
"""


def _downgrade_to_release_0(conn):
    """Rebuild ai_plan_log with the Release 0 CHECK, keeping every row.

    The reverse of the migration, so these tests start from the shape a real
    volume is actually in rather than from an assumption about it.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        RELEASE_0_AI_PLAN_LOG
        + """
        INSERT INTO release_0_log SELECT * FROM ai_plan_log;
        DROP TABLE ai_plan_log;
        ALTER TABLE release_0_log RENAME TO ai_plan_log;
        CREATE INDEX idx_ai_plan_log_goal_id ON ai_plan_log (goal_id, created_at);
        CREATE INDEX idx_ai_plan_log_phase   ON ai_plan_log (phase);
        """
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def test_a_release_0_database_rejects_the_release_1_phases(conn):
    """The problem this migration exists for, stated as a test."""
    _downgrade_to_release_0(conn)

    assert init_db.phase_is_allowed(conn, "plan") is True
    assert init_db.phase_is_allowed(conn, "mcp") is False
    assert init_db.phase_is_allowed(conn, "rag") is False


def test_the_probe_leaves_no_row_behind(conn):
    """phase_is_allowed works by trying a real insert, so it had better roll
    that insert back -- otherwise merely starting the container would litter
    the audit trail the report cites."""
    before = conn.execute("SELECT COUNT(*) FROM ai_plan_log").fetchone()[0]

    for phase in init_db.REQUIRED_PHASES:
        init_db.phase_is_allowed(conn, phase)

    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE model_name = 'probe'").fetchone()[0] == 0


def test_migration_preserves_every_existing_row_and_its_id(conn):
    _downgrade_to_release_0(conn)
    before = conn.execute("SELECT log_id, phase, prompt FROM ai_plan_log ORDER BY log_id").fetchall()
    assert before, "the seed data should have left rows here to preserve"

    note = init_db.migrate_ai_plan_log(conn)

    after = conn.execute("SELECT log_id, phase, prompt FROM ai_plan_log ORDER BY log_id").fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert "mcp" in note and "rag" in note


def test_migration_makes_the_new_phases_insertable(conn):
    _downgrade_to_release_0(conn)

    init_db.migrate_ai_plan_log(conn)

    for phase, model in (("mcp", "mcp"), ("rag", "rag-server")):
        conn.execute(
            "INSERT INTO ai_plan_log (goal_id, phase, model_name, prompt, response, created_at) "
            "VALUES (NULL, ?, ?, 'request', 'response', '2026-10-01T09:00:00')",
            (phase, model),
        )
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase IN ('mcp', 'rag')").fetchone()[0] == 2


def test_migration_still_rejects_a_phase_that_is_not_a_phase(conn):
    """The point is to widen the constraint, not to remove it."""
    _downgrade_to_release_0(conn)
    init_db.migrate_ai_plan_log(conn)

    assert init_db.phase_is_allowed(conn, "whatever") is False


def test_migration_is_a_no_op_on_a_current_database(conn):
    """Runs on every container start, so doing nothing has to be free and
    silent -- not a rebuild of the table each time."""
    assert init_db.migrate_ai_plan_log(conn) is None


def test_migration_recreates_the_indexes(conn):
    _downgrade_to_release_0(conn)

    init_db.migrate_ai_plan_log(conn)

    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ai_plan_log'"
        )
    }
    assert {"idx_ai_plan_log_goal_id", "idx_ai_plan_log_phase"} <= names


def test_migration_keeps_the_audit_trail_surviving_a_deleted_goal(conn):
    """ai_plan_log is ON DELETE SET NULL, not CASCADE, so deleting a goal must
    not erase the record that a model was called. Rebuilding the table is
    exactly where a foreign key clause gets quietly lost."""
    _downgrade_to_release_0(conn)
    init_db.migrate_ai_plan_log(conn)

    goal_id = conn.execute("SELECT goal_id FROM ai_plan_log WHERE goal_id IS NOT NULL LIMIT 1").fetchone()[0]
    rows_before = conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE goal_id = ?", (goal_id,)).fetchone()[0]

    conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
    conn.commit()

    assert rows_before > 0
    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE goal_id = ?", (goal_id,)).fetchone()[0] == 0
    assert init_db.check(conn, fresh=False)[0] == [], "orphaned rows would be a foreign key violation"
