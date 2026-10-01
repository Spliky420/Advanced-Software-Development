"""The agentic loop -- plan, progress and replan.

Three of the loop's four phases live here. The fourth, ACT, is
POST /api/goals/<id>/contributions in routes/contributions.py: recording a
contribution needs no model, and the loop exists to react to it.

Also serves the audit trail these phases write, so the evidence for the
report is reachable from the API rather than only by opening the database.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..db import get_db
from ..models import ai_log as ai_log_model
from ..services import agent as agent_service
from ..services import goals as goals_service

bp = Blueprint("agent", __name__, url_prefix="/api/goals")


@bp.post("/<int:goal_id>/plan")
def plan(goal_id: int):
    """POST /api/goals/<id>/plan -- PLAN. 201 with the persisted schedule.

    503 only if Ollama is unreachable or the model is not pulled. A model
    that answers badly is retried once and then replaced by the deterministic
    even-split plan, which still returns 201 with `plan.fallback` set.
    """
    return jsonify(agent_service.plan_goal(get_db(), goal_id)), 201


@bp.get("/<int:goal_id>/progress")
def progress(goal_id: int):
    """GET /api/goals/<id>/progress -- OBSERVE. Pure Python, never a model call."""
    return jsonify(agent_service.observe(get_db(), goal_id)), 200


@bp.post("/<int:goal_id>/replan")
def replan(goal_id: int):
    """POST /api/goals/<id>/replan -- ADAPT. 200 with the observation and the new steps."""
    return jsonify(agent_service.replan_goal(get_db(), goal_id)), 200


@bp.get("/<int:goal_id>/ai-log")
def ai_log(goal_id: int):
    """GET /api/goals/<id>/ai-log -- the audit trail for this goal, newest first.

    Not part of the original endpoint list: added so the prompt-and-response
    evidence the report needs can be read without opening the database by
    hand, and so the demo can show the loop's own paper trail.
    """
    conn = get_db()
    goals_service.get_goal_or_404(conn, goal_id)
    rows = ai_log_model.list_for_goal(conn, goal_id)
    entries = [
        {
            "log_id": int(row["log_id"]),
            "goal_id": None if row["goal_id"] is None else int(row["goal_id"]),
            "phase": row["phase"],
            "model_name": row["model_name"],
            "prompt": row["prompt"],
            "response": row["response"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return jsonify({"goal_id": goal_id, "entries": entries, "count": len(entries)}), 200
