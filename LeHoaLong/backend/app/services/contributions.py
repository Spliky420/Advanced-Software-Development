"""Contribution business logic.

Recording a contribution is the ACT phase of the agentic loop: the one place
where the user does something rather than plans something. It needs no model
call, which is exactly why it is the cheapest phase to demonstrate.

The response carries the goal's recalculated funding figures so the UI can
redraw the progress bar without a second request.
"""

from __future__ import annotations

import sqlite3

from ..models import contributions as contributions_model
from . import goals as goals_service
from . import serialise


def list_contributions(conn: sqlite3.Connection, goal_id: int) -> list[dict]:
    goals_service.get_goal_or_404(conn, goal_id)
    return [serialise.contribution(row) for row in contributions_model.list_for_goal(conn, goal_id)]


def create_contribution(conn: sqlite3.Connection, goal_id: int, clean: dict) -> dict:
    """Record money paid toward a goal.

    Deliberately does not mark any step complete and does not flip the goal
    to 'achieved' when the target is reached -- both are the user's calls, and
    guessing at them would put the app's opinion into the user's records. The
    response flags `fully_funded` so the UI can offer the change instead.
    """
    goal = goals_service.get_goal_or_404(conn, goal_id)

    contribution_id = contributions_model.insert_contribution(
        conn,
        goal_id=goal_id,
        amount=clean["amount"],
        contribution_date=clean["contribution_date"],
        notes=clean["notes"],
    )
    conn.commit()

    saved = contributions_model.total_for_goal(conn, goal_id)
    funding = serialise.funding(goal["target_amount"], saved)

    row = next(
        row
        for row in contributions_model.list_for_goal(conn, goal_id)
        if int(row["contribution_id"]) == contribution_id
    )
    return {
        "contribution": serialise.contribution(row),
        "goal": {
            "goal_id": goal_id,
            "name": goal["name"],
            "target_amount": goal["target_amount"],
            "status": goal["status"],
            **funding,
            "fully_funded": funding["remaining_amount"] == 0,
        },
    }
