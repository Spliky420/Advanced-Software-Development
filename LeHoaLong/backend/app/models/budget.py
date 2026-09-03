"""Data access for the budget_settings table.

One current budget per user, enforced by UNIQUE (user_id) in the schema --
this table holds the budget as it stands, not a history of changes.
"""

from __future__ import annotations

import sqlite3

COLUMNS = ("setting_id", "user_id", "monthly_budget", "currency", "updated_at")

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM budget_settings"


def get_for_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    """This user's budget, or None if they have never set one."""
    return conn.execute(f"{_SELECT} WHERE user_id = ?", (user_id,)).fetchone()


def upsert(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    monthly_budget: float,
    currency: str,
    updated_at: str,
) -> sqlite3.Row:
    """Set this user's budget, inserting or updating as needed.

    ON CONFLICT rather than a SELECT-then-branch: one statement, so two
    concurrent writes cannot both decide the row is missing and race to
    insert it.
    """
    conn.execute(
        """
        INSERT INTO budget_settings (user_id, monthly_budget, currency, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (user_id) DO UPDATE SET
            monthly_budget = excluded.monthly_budget,
            currency       = excluded.currency,
            updated_at     = excluded.updated_at
        """,
        (user_id, monthly_budget, currency, updated_at),
    )
    row = get_for_user(conn, user_id)
    assert row is not None  # just written
    return row
