"""Contributions -- /api/goals/<id>/contributions.

POST here is the ACT phase of the agentic loop. It is plain CRUD with no
model call, which is the point: the loop's act phase is the user doing
something real, and the service only has to record it accurately.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..services import contributions as contributions_service
from ..services import validation

bp = Blueprint("contributions", __name__, url_prefix="/api/goals")


@bp.get("/<int:goal_id>/contributions")
def list_contributions(goal_id: int):
    """GET /api/goals/<id>/contributions -- newest first."""
    items = contributions_service.list_contributions(get_db(), goal_id)
    total = round(sum(item["amount"] for item in items), 2)
    return jsonify({"goal_id": goal_id, "contributions": items, "count": len(items), "total": total}), 200


@bp.post("/<int:goal_id>/contributions")
def create_contribution(goal_id: int):
    """POST /api/goals/<id>/contributions -- record money paid in. 201.

    The body carries the goal's recalculated funding figures so the UI can
    redraw the progress bar without a follow-up request.
    """
    clean = validation.validate_contribution_create(request.get_json(silent=True))
    result = contributions_service.create_contribution(get_db(), goal_id, clean)
    location = f"/api/goals/{goal_id}/contributions"
    return jsonify(result), 201, {"Location": location}
