"""Multi-agent plan review -- /api/agents and the goal-scoped start.

    POST /api/goals/<id>/review-plan            start a review of this goal's plan
    GET  /api/agents/workflow/<run_id>          the review as it stands; poll this
    POST /api/agents/workflow/<run_id>/review   the human decision
    GET  /api/agents/health                     the status indicator. Fast, never 503.

The browser never calls the multi-agent server. It goes through here, which
is what makes the evidence Python's, the decision rules this feature's, and
the audit row unconditional. See services/review.py for the whole flow.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..services import review as review_service
from ..services import validation

bp = Blueprint("agents", __name__, url_prefix="/api/agents")

# The start belongs in the goals namespace, like /plan and /explain: its
# subject is a goal. The run it creates is addressed under /api/agents.
goal_bp = Blueprint("agents_goals", __name__, url_prefix="/api/goals")


@goal_bp.post("/<int:goal_id>/review-plan")
def review_plan(goal_id: int):
    """POST /api/goals/<id>/review-plan -- propose a plan and send it to the agents.

    202 with the run id when a review started; poll GET /api/agents/workflow/<run_id>.
    200 with `review.status: "unavailable"` and the reason when the multi-agent
    server is off or down -- the Python proposal is still in the body, and
    `review.fallback` names the Release 1 endpoint that applies a plan
    without review. Nothing is written to the goal by this endpoint.

    Accepts `use_mcp` like /plan, because the proposal's affordability uses
    the same cross-feature budget figure.
    """
    use_mcp = validation.flag_value("use_mcp", request.get_json(silent=True), request.args, default=True)
    body, status = review_service.start_review(get_db(), goal_id, use_mcp=use_mcp)
    return jsonify(body), status


@bp.get("/workflow/<run_id>")
def get_workflow(run_id: str):
    """GET /api/agents/workflow/<run_id> -- the agents' progress and the proposal.

    `stale` says whether the goal has changed since the review started, and
    `can_apply` whether approve or correct would be accepted right now.
    """
    return jsonify(review_service.get_review(get_db(), run_id)), 200


@bp.post("/workflow/<run_id>/review")
def review_workflow(run_id: str):
    """POST /api/agents/workflow/<run_id>/review -- approve, correct, partial or reject.

    Body: {"decision": "...", "note": "...", "corrected": "..."}

    approve and correct apply the frozen proposal to the goal; partial and
    reject record the decision only. 409 if already decided, if the review is
    not awaiting a decision, or -- for approve and correct -- if the goal has
    changed since the review started.
    """
    clean = validation.validate_review_decision(request.get_json(silent=True))
    return jsonify(review_service.decide(get_db(), run_id, clean)), 200


@bp.get("/health")
def health():
    """GET /api/agents/health -- reachability for the status light. Always 200."""
    return jsonify(review_service.health()), 200
