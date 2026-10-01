"""Step business logic.

A step is a line of the savings plan. Two different acts can happen to one,
and the difference matters for provenance:

  * editing its substance -- description, amount or due date. The step is no
    longer what the model wrote, so `source` flips from 'ai' to 'user'.
  * ticking it off -- a status change. That is bookkeeping about the plan,
    not authorship, so `source` is left alone.

Completing a step does NOT create a contribution. Steps are the plan; the
contributions table is money that actually moved. Conflating them would make
the observe phase compare the plan against itself.
"""

from __future__ import annotations

import sqlite3

from ..errors import NotFound
from ..models import goals as goals_model
from ..models import steps as steps_model
from . import serialise

# Changing any of these makes the step the user's work rather than the
# model's. Status is deliberately not in the set.
SUBSTANTIVE_FIELDS = ("description", "step_amount", "due_date")


def _require_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    """404 for a step collection under a goal that does not exist.

    Without this, /api/goals/9999/steps would cheerfully return an empty
    list, which reads as "this goal has no plan" rather than "no such goal".
    """
    if not goals_model.goal_exists(conn, goal_id):
        raise NotFound(f"No goal with id {goal_id}")


def list_steps(conn: sqlite3.Connection, goal_id: int) -> list[dict]:
    _require_goal(conn, goal_id)
    return [serialise.step(row) for row in steps_model.list_for_goal(conn, goal_id)]


def get_step_or_404(conn: sqlite3.Connection, goal_id: int, step_id: int) -> dict:
    _require_goal(conn, goal_id)
    row = steps_model.get_step(conn, goal_id, step_id)
    if row is None:
        raise NotFound(f"No step with id {step_id} on goal {goal_id}")
    return serialise.step(row)


def update_step(conn: sqlite3.Connection, goal_id: int, step_id: int, clean: dict) -> dict:
    """Apply validated changes to one step."""
    current = get_step_or_404(conn, goal_id, step_id)

    changes = dict(clean)
    edits_substance = any(
        field in changes and changes[field] != current[field] for field in SUBSTANTIVE_FIELDS
    )
    if edits_substance and current["source"] == "ai":
        changes["source"] = "user"

    if not steps_model.update_step(conn, goal_id, step_id, changes):
        raise NotFound(f"No step with id {step_id} on goal {goal_id}")
    conn.commit()
    return get_step_or_404(conn, goal_id, step_id)


def delete_step(conn: sqlite3.Connection, goal_id: int, step_id: int) -> None:
    _require_goal(conn, goal_id)
    if not steps_model.delete_step(conn, goal_id, step_id):
        raise NotFound(f"No step with id {step_id} on goal {goal_id}")
    conn.commit()
