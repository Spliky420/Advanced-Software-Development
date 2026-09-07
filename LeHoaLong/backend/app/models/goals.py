"""Data access for the goals table.

This layer only ever moves rows in and out of SQLite. No arithmetic, no HTTP
concepts, no defaulting -- the service layer above decides what a missing
user_id means, and this layer is handed the answer.

Every function takes the connection explicitly rather than reaching for
flask.g, so the same functions work under a plain sqlite3 connection in a
test or a script.
"""

from __future__ import annotations

import sqlite3

COLUMNS = (
    "goal_id",
    "user_id",
    "name",
    "target_amount",
    "target_date",
    "priority",
    "status",
    "created_at",
    "updated_at",
)

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM goals"

# Highest priority first, then the nearest deadline. This is the order the
# dashboard shows, and doing it in SQL keeps it stable across endpoints.
_ORDER = """
    ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
             target_date,
             goal_id
"""

# Columns a client is allowed to change through PUT. Anything else in the
# payload has already been rejected by validation; this is the second lock.
UPDATABLE = ("name", "target_amount", "target_date", "priority", "status")


def list_goals(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> list[sqlite3.Row]:
    """Every goal matching the given filters. `user_id=None` means all users."""
    where: list[str] = []
    params: list = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if priority is not None:
        where.append("priority = ?")
        params.append(priority)

    sql = _SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += _ORDER
    return conn.execute(sql, params).fetchall()


def get_goal(conn: sqlite3.Connection, goal_id: int) -> sqlite3.Row | None:
    """One goal, or None if there is no such row."""
    return conn.execute(f"{_SELECT} WHERE goal_id = ?", (goal_id,)).fetchone()


def insert_goal(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    name: str,
    target_amount: float,
    target_date: str,
    priority: str,
    status: str,
    timestamp: str,
) -> int:
    """Insert a goal and return its new id."""
    cursor = conn.execute(
        """
        INSERT INTO goals (user_id, name, target_amount, target_date, priority, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, name, target_amount, target_date, priority, status, timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def update_goal(conn: sqlite3.Connection, goal_id: int, changes: dict, *, timestamp: str) -> bool:
    """Apply the given column changes. Returns False if the goal is gone.

    updated_at is always written, so the caller cannot forget it.
    """
    fields = {key: value for key, value in changes.items() if key in UPDATABLE}
    assignments = ", ".join(f"{field} = ?" for field in fields)
    assignments = f"{assignments}, updated_at = ?" if assignments else "updated_at = ?"

    cursor = conn.execute(
        f"UPDATE goals SET {assignments} WHERE goal_id = ?",
        (*fields.values(), timestamp, goal_id),
    )
    return cursor.rowcount > 0


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> bool:
    """Delete a goal. Returns False if it was not there.

    Steps and contributions go with it by ON DELETE CASCADE; ai_plan_log rows
    survive with goal_id set to NULL, deliberately, because they are the audit
    trail (see schema.sql).
    """
    cursor = conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
    return cursor.rowcount > 0


def goal_exists(conn: sqlite3.Connection, goal_id: int) -> bool:
    return conn.execute("SELECT 1 FROM goals WHERE goal_id = ?", (goal_id,)).fetchone() is not None
