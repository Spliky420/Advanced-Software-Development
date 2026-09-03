"""Goal business logic.

Sits between the routes and the models. Everything numeric in a goal
response is computed here, in Python -- percentages, remaining amounts,
totals. The LLM is never asked to do any of it (CLAUDE.md, and the point the
technical report makes).
"""

from __future__ import annotations

import sqlite3

from ..errors import NotFound
from ..models import contributions as contributions_model
from ..models import goals as goals_model
from ..models import steps as steps_model
from . import dates, serialise


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_goals(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    """The goal list, each row carrying its funding figures.

    Contribution totals come back in one grouped query rather than one per
    goal, so the dashboard costs two queries however many goals there are.
    """
    rows = goals_model.list_goals(
        conn,
        user_id=filters.get("user_id"),
        status=filters.get("status"),
        priority=filters.get("priority"),
    )
    goals = [serialise.goal(row) for row in rows]
    totals = contributions_model.totals_by_goal(conn, [goal["goal_id"] for goal in goals])
    for goal in goals:
        goal.update(serialise.funding(goal["target_amount"], totals.get(goal["goal_id"], 0.0)))
    return goals


def get_goal_or_404(conn: sqlite3.Connection, goal_id: int) -> dict:
    """One goal as a flat dict, or raise NotFound."""
    row = goals_model.get_goal(conn, goal_id)
    if row is None:
        raise NotFound(f"No goal with id {goal_id}")
    return serialise.goal(row)


def get_goal_detail(conn: sqlite3.Connection, goal_id: int) -> dict:
    """One goal with its ordered steps and its contribution total."""
    goal = get_goal_or_404(conn, goal_id)
    saved = contributions_model.total_for_goal(conn, goal_id)
    goal.update(serialise.funding(goal["target_amount"], saved))
    goal["steps"] = [serialise.step(row) for row in steps_model.list_for_goal(conn, goal_id)]
    goal["contributions"] = [
        serialise.contribution(row) for row in contributions_model.list_for_goal(conn, goal_id)
    ]
    goal["contribution_count"] = len(goal["contributions"])
    return goal


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def create_goal(conn: sqlite3.Connection, clean: dict, *, default_user_id: int) -> dict:
    """Create a goal from an already-validated payload.

    The user id is stamped server-side: it is whatever the client named, or
    the single-user default when it named nobody. created_at and updated_at
    are set here too -- a client cannot backdate a row.
    """
    timestamp = dates.now_iso()
    goal_id = goals_model.insert_goal(
        conn,
        user_id=clean.get("user_id", default_user_id),
        name=clean["name"],
        target_amount=clean["target_amount"],
        target_date=clean["target_date"],
        priority=clean["priority"],
        status=clean["status"],
        timestamp=timestamp,
    )
    conn.commit()
    return get_goal_detail(conn, goal_id)


def update_goal(conn: sqlite3.Connection, goal_id: int, clean: dict) -> dict:
    """Apply validated changes to an existing goal."""
    if not goals_model.update_goal(conn, goal_id, clean, timestamp=dates.now_iso()):
        raise NotFound(f"No goal with id {goal_id}")
    conn.commit()
    return get_goal_detail(conn, goal_id)


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    """Delete a goal and everything hanging off it.

    Steps and contributions cascade. ai_plan_log rows are kept with a NULL
    goal_id: the audit trail of what the model was asked outlives the goal.
    """
    if not goals_model.delete_goal(conn, goal_id):
        raise NotFound(f"No goal with id {goal_id}")
    conn.commit()
