"""Goals CRUD -- /api/goals.

Routes stay thin on purpose: parse the request, call a service, choose a
status code. No SQL and no arithmetic in this file.
"""

from __future__ import annotations

from config import DEFAULT_USER_ID
from flask import Blueprint, jsonify, request

from ..db import get_db
from ..services import goals as goals_service
from ..services import validation

bp = Blueprint("goals", __name__, url_prefix="/api/goals")


def _json_body():
    """The request body as JSON.

    `silent=True` turns Werkzeug's HTML 400 for malformed JSON into our own
    JSON error, which is what a fetch() caller can actually read.
    """
    return request.get_json(silent=True)


@bp.get("")
def list_goals():
    """GET /api/goals -- the goal list.

    Filters: ?status= ?priority= ?user_id=

    With no user_id the list is scoped to the single-user default, which is
    the Release 0 behaviour required by CLAUDE.md. `?user_id=all` lifts that
    scoping so the seeded data for every user is visible in one call.
    """
    filters = validation.validate_goal_filters(request.args)
    if "user_id" not in filters:
        filters["user_id"] = DEFAULT_USER_ID

    goals = goals_service.list_goals(get_db(), filters)
    return jsonify({"goals": goals, "count": len(goals)}), 200


@bp.get("/<int:goal_id>")
def get_goal(goal_id: int):
    """GET /api/goals/<id> -- one goal with its steps and contribution total."""
    return jsonify(goals_service.get_goal_detail(get_db(), goal_id)), 200


@bp.post("")
def create_goal():
    """POST /api/goals -- create a goal. 201 with the created resource."""
    clean = validation.validate_goal_create(_json_body())
    goal = goals_service.create_goal(get_db(), clean, default_user_id=DEFAULT_USER_ID)
    return jsonify(goal), 201, {"Location": f"/api/goals/{goal['goal_id']}"}


@bp.put("/<int:goal_id>")
def update_goal(goal_id: int):
    """PUT /api/goals/<id> -- update a goal.

    A merge, not a replace: fields left out of the body keep their current
    values. Validation therefore needs the current row to check rules that
    span fields, such as the past-target-date rule for active goals.
    """
    conn = get_db()
    current = goals_service.get_goal_or_404(conn, goal_id)
    clean = validation.validate_goal_update(_json_body(), current)
    return jsonify(goals_service.update_goal(conn, goal_id, clean)), 200


@bp.delete("/<int:goal_id>")
def delete_goal(goal_id: int):
    """DELETE /api/goals/<id> -- 204, cascading to steps and contributions."""
    goals_service.delete_goal(get_db(), goal_id)
    return "", 204
