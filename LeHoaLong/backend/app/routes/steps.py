"""Plan steps -- /api/goals/<id>/steps.

Steps are created by the planner (POST /api/goals/<id>/plan), not by this
blueprint: a plan is generated as a whole, then adjusted line by line here.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..services import steps as steps_service
from ..services import validation

bp = Blueprint("steps", __name__, url_prefix="/api/goals")


@bp.get("/<int:goal_id>/steps")
def list_steps(goal_id: int):
    """GET /api/goals/<id>/steps -- the plan, in order."""
    steps = steps_service.list_steps(get_db(), goal_id)
    return jsonify({"goal_id": goal_id, "steps": steps, "count": len(steps)}), 200


@bp.put("/<int:goal_id>/steps/<int:step_id>")
def update_step(goal_id: int, step_id: int):
    """PUT /api/goals/<id>/steps/<step_id> -- edit a step or mark it complete.

    A merge, like the goal update. Changing the description, amount or due
    date rewrites the step, so its `source` becomes 'user'; changing only the
    status leaves the provenance as it was.
    """
    clean = validation.validate_step_update(request.get_json(silent=True))
    return jsonify(steps_service.update_step(get_db(), goal_id, step_id, clean)), 200


@bp.delete("/<int:goal_id>/steps/<int:step_id>")
def delete_step(goal_id: int, step_id: int):
    """DELETE /api/goals/<id>/steps/<step_id> -- 204."""
    steps_service.delete_step(get_db(), goal_id, step_id)
    return "", 204
