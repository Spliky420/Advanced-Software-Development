"""Budget -- /api/budget.

Unlike goals, a budget is always about exactly one user, so these endpoints
take ?user_id= and fall back to the single-user default rather than offering
an "all users" view.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from config import DEFAULT_USER_ID

from ..db import get_db
from ..services import budget as budget_service
from ..services import validation

bp = Blueprint("budget", __name__, url_prefix="/api/budget")


@bp.get("/summary")
def summary():
    """GET /api/budget/summary?user_id= -- monthly commitment vs budget.

    `difference` is budget minus commitment, signed: negative is over budget.
    Every figure is calculated in Python; see services/budget.py for the
    definition of a goal's required monthly commitment.
    """
    user_id = validation.validate_user_id_arg(request.args, DEFAULT_USER_ID)
    return jsonify(budget_service.summarise(get_db(), user_id)), 200


@bp.get("/settings")
def get_settings():
    """GET /api/budget/settings?user_id= -- the stored budget.

    200 with `is_set: false` when the user has never set one; that is a
    normal starting state, not a 404.
    """
    user_id = validation.validate_user_id_arg(request.args, DEFAULT_USER_ID)
    return jsonify(budget_service.get_settings(get_db(), user_id)), 200


@bp.put("/settings")
def put_settings():
    """PUT /api/budget/settings -- set the budget, inserting or updating."""
    clean = validation.validate_budget_settings(request.get_json(silent=True), DEFAULT_USER_ID)
    return jsonify(budget_service.set_settings(get_db(), clean)), 200
