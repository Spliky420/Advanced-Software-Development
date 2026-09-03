"""Budget arithmetic.

Every figure in the budget panel is calculated here, in Python. Nothing in
this module talks to the LLM, and the LLM is never asked to add anything up
(CLAUDE.md).

The central quantity is one goal's **required monthly commitment**:

    remaining_amount / months_remaining

which reads as "what you must put aside each month, from today, to hit this
goal on time". Three properties make it the right definition:

  * it works whether or not the goal has an AI plan yet, so a brand new goal
    counts against the budget the moment it is created;
  * it is the same arithmetic the planner uses to lay out steps, so the
    budget panel and the generated plan can never disagree;
  * it re-derives from today's date, so a goal that has fallen behind
    automatically shows a higher monthly figure rather than a stale one.

`as_at` is a parameter rather than a call to today() inside the maths, so the
tests can pin a date and assert exact figures.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..models import budget as budget_model
from ..models import contributions as contributions_model
from ..models import goals as goals_model
from . import dates, serialise

# Only active goals commit money. A paused, achieved or abandoned goal is not
# something the user is currently saving for, so counting it would overstate
# the commitment and trigger a false over-budget warning.
COMMITTING_STATUS = "active"

DEFAULT_CURRENCY = "AUD"


# ---------------------------------------------------------------------------
# The core calculation
# ---------------------------------------------------------------------------


def commitment_for_goal(goal: dict, saved: float, as_at: date) -> dict:
    """What one goal requires per month, plus the figures behind it."""
    funding = serialise.funding(goal["target_amount"], saved)
    remaining = funding["remaining_amount"]
    months_remaining = dates.months_between(as_at, dates.parse_date(goal["target_date"]))

    if remaining <= 0:
        # Already funded: it costs nothing more, whatever the calendar says.
        required_monthly = 0.0
    elif months_remaining == 0:
        # The target date has passed and money is still owed. The whole
        # shortfall is due now -- dividing by zero months would be worse than
        # useless, and spreading it over an imaginary month would understate
        # what the user actually has to find.
        required_monthly = remaining
    else:
        required_monthly = round(remaining / months_remaining, 2)

    return {
        "goal_id": goal["goal_id"],
        "name": goal["name"],
        "priority": goal["priority"],
        "target_amount": goal["target_amount"],
        "target_date": goal["target_date"],
        **funding,
        "months_remaining": months_remaining,
        "required_monthly": required_monthly,
        "overdue": months_remaining == 0 and remaining > 0,
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings(conn: sqlite3.Connection, user_id: int) -> dict:
    """This user's budget settings.

    A user who has never set a budget is not an error -- it is the state
    every user starts in. The response says so with `is_set: false` and a
    null budget, so the frontend can prompt rather than show a broken panel.
    """
    row = budget_model.get_for_user(conn, user_id)
    if row is None:
        return {
            "user_id": user_id,
            "monthly_budget": None,
            "currency": DEFAULT_CURRENCY,
            "updated_at": None,
            "is_set": False,
        }
    return {**serialise.budget_settings(row), "is_set": True}


def set_settings(conn: sqlite3.Connection, clean: dict) -> dict:
    """Insert or update this user's budget."""
    row = budget_model.upsert(
        conn,
        user_id=clean["user_id"],
        monthly_budget=clean["monthly_budget"],
        currency=clean["currency"],
        updated_at=dates.now_iso(),
    )
    conn.commit()
    return {**serialise.budget_settings(row), "is_set": True}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarise(conn: sqlite3.Connection, user_id: int, as_at: date | None = None) -> dict:
    """Total monthly commitment across this user's active goals vs their budget.

    `difference` is budget minus commitment, signed: negative means over
    budget by that much, positive means that much of the budget is unspent.
    """
    as_at = as_at or dates.today()

    rows = goals_model.list_goals(conn, user_id=user_id, status=COMMITTING_STATUS)
    goals = [serialise.goal(row) for row in rows]
    totals = contributions_model.totals_by_goal(conn, [goal["goal_id"] for goal in goals])

    commitments = [
        commitment_for_goal(goal, totals.get(goal["goal_id"], 0.0), as_at) for goal in goals
    ]
    total_commitment = round(sum(item["required_monthly"] for item in commitments), 2)

    settings = get_settings(conn, user_id)
    monthly_budget = settings["monthly_budget"]

    summary = {
        "user_id": user_id,
        "as_at": dates.to_iso(as_at),
        "currency": settings["currency"],
        "monthly_budget": monthly_budget,
        "budget_is_set": settings["is_set"],
        "total_monthly_commitment": total_commitment,
        "active_goal_count": len(commitments),
        "overdue_goal_count": sum(1 for item in commitments if item["overdue"]),
        "goals": commitments,
    }

    if monthly_budget is None:
        summary["difference"] = None
        summary["percent_of_budget_used"] = None
        summary["status"] = "no_budget_set"
        return summary

    difference = round(monthly_budget - total_commitment, 2)
    summary["difference"] = difference
    summary["percent_of_budget_used"] = (
        round(total_commitment / monthly_budget * 100, 1) if monthly_budget > 0 else None
    )
    summary["status"] = "over_budget" if difference < 0 else "within_budget"
    return summary


def available_monthly(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    exclude_goal_id: int | None = None,
    as_at: date | None = None,
) -> dict:
    """How much monthly budget is free, ignoring one goal's own commitment.

    This is what the planner hands the model as "available monthly budget":
    the user's budget less what their *other* active goals already require.
    Excluding the goal being planned matters -- otherwise the goal would be
    counted against the very budget it is asking to use.

    `available` is None when no budget has been set: the planner then works
    from the goal's own arithmetic alone rather than inventing a figure.
    """
    summary = summarise(conn, user_id, as_at)
    committed_elsewhere = round(
        sum(
            item["required_monthly"]
            for item in summary["goals"]
            if item["goal_id"] != exclude_goal_id
        ),
        2,
    )
    monthly_budget = summary["monthly_budget"]
    return {
        "monthly_budget": monthly_budget,
        "currency": summary["currency"],
        "committed_to_other_goals": committed_elsewhere,
        "available": None if monthly_budget is None else round(monthly_budget - committed_elsewhere, 2),
    }
