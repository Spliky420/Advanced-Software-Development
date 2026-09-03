"""Data access for the contributions table."""

from __future__ import annotations

import sqlite3

COLUMNS = ("contribution_id", "goal_id", "amount", "contribution_date", "notes")

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM contributions"


def list_for_goal(conn: sqlite3.Connection, goal_id: int) -> list[sqlite3.Row]:
    """Every contribution for one goal, newest first."""
    return conn.execute(
        f"{_SELECT} WHERE goal_id = ? ORDER BY contribution_date DESC, contribution_id DESC",
        (goal_id,),
    ).fetchall()


def total_for_goal(conn: sqlite3.Connection, goal_id: int) -> float:
    """Everything ever contributed to one goal. 0.0 if there is nothing."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM contributions WHERE goal_id = ?", (goal_id,)
    ).fetchone()
    return float(row[0])


def totals_by_goal(conn: sqlite3.Connection, goal_ids: list[int]) -> dict[int, float]:
    """Contribution totals for many goals at once.

    One grouped query rather than one per goal: the dashboard lists every
    goal, and a per-goal query there is the classic N+1.
    """
    if not goal_ids:
        return {}
    placeholders = ", ".join("?" for _ in goal_ids)
    rows = conn.execute(
        f"""
        SELECT goal_id, SUM(amount) AS total
          FROM contributions
         WHERE goal_id IN ({placeholders})
         GROUP BY goal_id
        """,
        goal_ids,
    ).fetchall()
    totals = {goal_id: 0.0 for goal_id in goal_ids}
    totals.update({int(row["goal_id"]): float(row["total"]) for row in rows})
    return totals


def count_for_goal(conn: sqlite3.Connection, goal_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM contributions WHERE goal_id = ?", (goal_id,)).fetchone()[0])


def insert_contribution(
    conn: sqlite3.Connection,
    *,
    goal_id: int,
    amount: float,
    contribution_date: str,
    notes: str | None,
) -> int:
    """Insert one contribution and return its id."""
    cursor = conn.execute(
        "INSERT INTO contributions (goal_id, amount, contribution_date, notes) VALUES (?, ?, ?, ?)",
        (goal_id, amount, contribution_date, notes),
    )
    return int(cursor.lastrowid)
