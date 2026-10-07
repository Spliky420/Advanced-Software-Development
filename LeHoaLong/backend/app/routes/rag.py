"""RAG endpoints -- /api/rag and the goal explanation.

    POST /api/rag/ask              a general grounded question
    GET  /api/rag/health           the status indicator. Fast, never 503.
    POST /api/goals/<id>/explain   this goal's situation, grounded

The browser never calls the RAG server. It goes through here, which is what
makes the audit row, the timeout policy and the "Insufficient evidence."
handling apply to every caller rather than to whichever caller remembered.

**How the goal explanation is built, and why in that order.** The question is
assembled in Python from figures this feature already computed -- the same
observation `GET /progress` returns -- and the concept words come first, with
the figures after. That ordering is not cosmetic. The shared pipeline embeds a
question by hashing its words, and uses the same string both to retrieve and
to answer; a question that opens with four currency amounts retrieves against
those amounts. Leading with "behind on a savings goal" and "contributions" is
what makes the retrieval find the paragraphs about being behind on a savings
goal.

The Python figures are also returned in their own `situation` block, so the UI
shows this feature's numbers as its numbers. The grounded answer is advice
about the concepts; the figures beside it are authoritative regardless of what
the model wrote about them -- which is the standing caveat in CLAUDE.md about
a small model misreading correctly-supplied figures.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..errors import ServiceUnavailable
from ..rag import audit
from ..rag import client as rag_client
from ..services import agent as agent_service
from ..services import goals as goals_service
from ..services import validation

bp = Blueprint("rag", __name__, url_prefix="/api/rag")

# The goal-scoped route, same reasoning as the MCP one: the path belongs to
# the goals namespace while the subject is RAG.
goal_bp = Blueprint("rag_goals", __name__, url_prefix="/api/goals")


def _require_enabled() -> None:
    """503 when RAG is switched off, which is how CI runs."""
    if not rag_client.is_enabled():
        raise ServiceUnavailable(
            "RAG is disabled by configuration (RAG_ENABLED=false). "
            "Goals, planning and the rest of this API are unaffected."
        )


def _answer(
    conn, *, goal_id: int | None, question: str, top_k: int | None, relevance_text: str | None = None
) -> tuple[dict, int]:
    """Ask, log, and return the body. Shared by both question endpoints."""
    try:
        result = rag_client.ask(question, top_k, relevance_text=relevance_text)
    except rag_client.RAGUnavailable as exc:
        audit.record_unavailable(conn, goal_id=goal_id, question=question, detail=str(exc))
        raise

    result["log_id"] = audit.record_answer(conn, goal_id=goal_id, result=result)
    return result, 200


@bp.post("/ask")
def ask():
    """POST /api/rag/ask -- a grounded answer to any question.

    Body: {"question": "...", "top_k": 5}

    200 with `insufficient_evidence: true` when the corpus does not support
    the question. That is a correct answer, surfaced exactly as the server
    gave it, and deliberately not replaced by an ungrounded one.
    """
    clean = validation.validate_rag_question(request.get_json(silent=True))
    _require_enabled()

    body, status = _answer(get_db(), goal_id=None, question=clean["question"], top_k=clean["top_k"])
    return jsonify(body), status


@bp.get("/health")
def health():
    """GET /api/rag/health -- is the RAG server reachable?

    Always 200, including when the answer is no. Same reasoning as the MCP
    probe: this drives a status light, and it is not folded into the service
    /health because the container's healthcheck must not fail over an
    optional integration being switched off.
    """
    return jsonify(rag_client.probe()), 200


@goal_bp.post("/<int:goal_id>/explain")
def explain(goal_id: int):
    """POST /api/goals/<id>/explain -- this goal's situation, grounded.

    Observe runs first (pure Python, no model) and its figures build the
    question. `?top_k=` or a `top_k` body field overrides the retrieval
    depth.
    """
    conn = get_db()
    goals_service.get_goal_or_404(conn, goal_id)
    clean = validation.validate_rag_options(request.get_json(silent=True), request.args)
    _require_enabled()

    # OBSERVE, not logged again: this is a read of the same figures
    # /progress reports, and an explanation is not a new observation.
    observation = agent_service.observe(conn, goal_id, log=False)
    question = build_goal_question(observation)

    # The relevance check reads the concept sentence only: the goal's name and
    # figures appended after it are this feature's own data, and would never
    # appear in the corpus however relevant the retrieval was.
    body, status = _answer(
        conn,
        goal_id=goal_id,
        question=question,
        top_k=clean["top_k"],
        relevance_text=goal_concepts(observation),
    )
    body["situation"] = _situation(observation)
    return jsonify(body), status


def _situation(observation: dict) -> dict:
    """The Python-computed figures behind the question, returned as figures.

    Every one of these came from services/agent.observe. They are in the
    response so the UI can state them itself rather than relying on the
    model's prose to repeat them correctly.
    """
    return {
        "goal_name": observation["goal_name"],
        "as_at": observation["as_at"],
        "status": observation["status"],
        "saved_to_date": observation["saved_to_date"],
        "required_to_date": observation["required_to_date"],
        "variance": observation["variance"],
        "target_amount": observation["target_amount"],
        "target_date": observation["target_date"],
        "remaining_amount": observation["remaining_amount"],
        "percent_complete": observation["percent_complete"],
        "months_remaining": observation["months_remaining"],
        "projected_completion_date": observation["projected_completion_date"],
        "computed_by": "python",
    }


# The concept vocabulary each status should retrieve against. Written as the
# words the corpus uses, because the shared pipeline matches on word overlap
# rather than meaning -- a question that says "lagging" would not find a
# paragraph that says "behind".
_STATUS_QUESTIONS = {
    "behind": (
        "What does it mean to be behind on a savings goal, and how should "
        "monthly contributions be adjusted to catch up before the target date?"
    ),
    "ahead": (
        "What does it mean to be ahead on a savings goal, and should "
        "contributions be reduced or the target date brought forward?"
    ),
    "on_track": (
        "What does it mean for a savings goal to be on track, and how should "
        "contributions continue until the target date?"
    ),
    "achieved": (
        "What happens when a savings goal is achieved, and how should the "
        "budget and remaining goals be prioritised afterwards?"
    ),
}


def goal_concepts(observation: dict) -> str:
    """The concept sentence for this goal's status -- the part about meaning."""
    return _STATUS_QUESTIONS.get(observation["status"], _STATUS_QUESTIONS["on_track"])


def build_goal_question(observation: dict) -> str:
    """Turn an observation into a question for the RAG server.

    Concept words first, figures second -- see this module's docstring. The
    figures are stated plainly and are never asked about arithmetically: the
    question asks what the situation *means*, which is a text question, and
    the numbers in it have already been computed.
    """
    concepts = goal_concepts(observation)

    return (
        f"{concepts}\n\n"
        f"My situation for the goal {observation['goal_name']!r}, as at "
        f"{observation['as_at']}: status {observation['status']}, "
        f"saved {observation['saved_to_date']:,.2f} of a "
        f"{observation['target_amount']:,.2f} target due {observation['target_date']}, "
        f"the plan expected {observation['required_to_date']:,.2f} by now "
        f"(variance {observation['variance']:+,.2f}), with "
        f"{observation['remaining_amount']:,.2f} still to save over "
        f"{observation['months_remaining']} month(s)."
    )
