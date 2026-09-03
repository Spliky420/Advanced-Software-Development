"""Row-to-dict converters.

One place where a sqlite3.Row becomes JSON-safe Python, so every endpoint
that returns a step returns the same shape, and money is rounded to cents
exactly once on the way out.

Kept separate from the service modules so that steps, contributions and
budget can all use them without importing each other.
"""

from __future__ import annotations

import sqlite3


def goal(row: sqlite3.Row) -> dict:
    return {
        "goal_id": int(row["goal_id"]),
        "user_id": int(row["user_id"]),
        "name": row["name"],
        "target_amount": round(float(row["target_amount"]), 2),
        "target_date": row["target_date"],
        "priority": row["priority"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def step(row: sqlite3.Row) -> dict:
    return {
        "step_id": int(row["step_id"]),
        "goal_id": int(row["goal_id"]),
        "step_order": int(row["step_order"]),
        "description": row["description"],
        "step_amount": round(float(row["step_amount"]), 2),
        "due_date": row["due_date"],
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def contribution(row: sqlite3.Row) -> dict:
    return {
        "contribution_id": int(row["contribution_id"]),
        "goal_id": int(row["goal_id"]),
        "amount": round(float(row["amount"]), 2),
        "contribution_date": row["contribution_date"],
        "notes": row["notes"],
    }


def budget_settings(row: sqlite3.Row) -> dict:
    return {
        "setting_id": int(row["setting_id"]),
        "user_id": int(row["user_id"]),
        "monthly_budget": round(float(row["monthly_budget"]), 2),
        "currency": row["currency"],
        "updated_at": row["updated_at"],
    }


def funding(target_amount: float, saved: float) -> dict:
    """The three funding figures every view of a goal carries.

    percent_complete is deliberately uncapped: over-funding a goal is real
    and the dashboard should be able to say so. The progress bar caps its own
    width instead.
    """
    saved = round(saved, 2)
    return {
        "saved_to_date": saved,
        "remaining_amount": round(max(target_amount - saved, 0.0), 2),
        "percent_complete": round(saved / target_amount * 100, 1) if target_amount > 0 else 0.0,
    }
