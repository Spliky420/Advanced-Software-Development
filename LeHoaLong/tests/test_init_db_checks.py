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
