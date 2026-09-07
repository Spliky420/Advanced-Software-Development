"""Data access for the goal_steps table.

Read helpers only at this stage -- the goal detail view needs them. The write
side (edit, complete, delete, and the bulk rewrite the replan endpoint does)
arrives with the steps and agent routes.
"""

from __future__ import annotations

import sqlite3

COLUMNS = (
    "step_id",
    "goal_id",
    "step_order",
    "description",
    "step_amount",
    "due_date",
    "status",
    "source",
    "created_at",
)

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM goal_steps"


def list_for_goal(conn: sqlite3.Connection, goal_id: int) -> list[sqlite3.Row]:
    """Every step for one goal, in plan order."""
    return conn.execute(f"{_SELECT} WHERE goal_id = ? ORDER BY step_order", (goal_id,)).fetchall()


def get_step(conn: sqlite3.Connection, goal_id: int, step_id: int) -> sqlite3.Row | None:
    """One step, scoped to its goal.

    Scoping by goal as well as by id means /api/goals/1/steps/99 cannot reach
    a step belonging to goal 2 -- it 404s, which is the honest answer.
    """
    return conn.execute(f"{_SELECT} WHERE goal_id = ? AND step_id = ?", (goal_id, step_id)).fetchone()


def required_to_date(conn: sqlite3.Connection, goal_id: int, as_at: str) -> float:
    """Total of the step amounts due on or before `as_at`.

    This is the plan's expectation of how much should have been saved by now.
    Comparing it against contributions is the whole of the observe phase.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(step_amount), 0) FROM goal_steps WHERE goal_id = ? AND due_date <= ?",
        (goal_id, as_at),
    ).fetchone()
    return float(row[0])


def count_for_goal(conn: sqlite3.Connection, goal_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM goal_steps WHERE goal_id = ?", (goal_id,)).fetchone()[0])


# Columns a client may change through PUT. `source` is provenance, not a
# client-supplied field -- the service sets it, and step_order/goal_id are
# structural.
UPDATABLE = ("description", "step_amount", "due_date", "status")


def update_step(conn: sqlite3.Connection, goal_id: int, step_id: int, changes: dict) -> bool:
    """Apply column changes to one step. False if it is not there.

    `source` is accepted here because the service decides it -- editing the
    substance of an AI-written step makes it the user's step.
    """
    allowed = UPDATABLE + ("source",)
    fields = {key: value for key, value in changes.items() if key in allowed}
    if not fields:
        return get_step(conn, goal_id, step_id) is not None

    assignments = ", ".join(f"{field} = ?" for field in fields)
    cursor = conn.execute(
        f"UPDATE goal_steps SET {assignments} WHERE goal_id = ? AND step_id = ?",
        (*fields.values(), goal_id, step_id),
    )
    return cursor.rowcount > 0


def delete_step(conn: sqlite3.Connection, goal_id: int, step_id: int) -> bool:
    """Delete one step. False if it was not there.

    No renumbering afterwards: step_order is a stable sort key, not a display
    index, and shuffling it would mean rewriting every later row (and fighting
    the UNIQUE (goal_id, step_order) constraint on the way). A gap in the
    sequence is harmless -- the UI numbers what it renders.
    """
    cursor = conn.execute("DELETE FROM goal_steps WHERE goal_id = ? AND step_id = ?", (goal_id, step_id))
    return cursor.rowcount > 0


def insert_step(
    conn: sqlite3.Connection,
    *,
    goal_id: int,
    step_order: int,
    description: str,
    step_amount: float,
    due_date: str,
    status: str,
    source: str,
    created_at: str,
) -> int:
    """Insert one step and return its id."""
    cursor = conn.execute(
        """
        INSERT INTO goal_steps (goal_id, step_order, description, step_amount, due_date, status, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (goal_id, step_order, description, step_amount, due_date, status, source, created_at),
    )
    return int(cursor.lastrowid)


def delete_pending(conn: sqlite3.Connection, goal_id: int) -> int:
    """Delete every pending step for a goal, returning how many went.

    The replan endpoint's first move: completed and skipped steps are history
    and must survive a regeneration.
    """
    cursor = conn.execute("DELETE FROM goal_steps WHERE goal_id = ? AND status = 'pending'", (goal_id,))
    return cursor.rowcount


def max_step_order(conn: sqlite3.Connection, goal_id: int, *, exclude_pending: bool = False) -> int:
    """The highest step_order in use for a goal, or 0 when it has no steps.

    `exclude_pending` answers the question the planner actually asks: once the
    pending steps have been thrown away, what is the last number the surviving
    history uses? Asking it before the delete rather than after keeps the whole
    regeneration inside one transaction.
    """
    sql = "SELECT COALESCE(MAX(step_order), 0) FROM goal_steps WHERE goal_id = ?"
    if exclude_pending:
        sql += " AND status != 'pending'"
    return int(conn.execute(sql, (goal_id,)).fetchone()[0])
