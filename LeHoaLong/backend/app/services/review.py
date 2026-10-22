"""The multi-agent plan review -- Release 2's human-in-the-loop PLAN.

    POST /api/goals/<id>/review-plan            start_review()
    GET  /api/agents/workflow/<run_id>          get_review()
    POST /api/agents/workflow/<run_id>/review   decide()

Release 0's PLAN writes a schedule straight to the goal. This path puts
three agents and a person between the schedule and the goal:

  1. **Python proposes.** The same `prepare()` that plan and replan use
     builds the instalment schedule -- every amount and every date -- and the
     affordability verdict. That proposal is frozen and stored, with the
     facts it was computed from.
  2. **The agents review.** The proposal and the figures behind it go to the
     shared multi-agent server as evidence. Its Planner, Worker and Reviewer
     write about them; none is asked for a number, and nothing they write is
     ever read back into the plan.
  3. **A person decides.** `approve` and `correct` apply the frozen proposal
     -- exactly the amounts and dates the agents and the person looked at.
     `correct` also records the person's corrected rationale. `partial` and
     `reject` apply nothing and are recorded only.

**A stale proposal is refused, not re-applied.** If a contribution lands,
the target moves, or a step is completed between the review starting and
the decision, the frozen schedule no longer closes the gap it was built
for. Applying it would put numbers on the goal that nobody reviewed, and
silently recomputing would apply numbers the agents never saw. So approve
and correct answer 409 naming what changed, and the person starts a new
review. Partial and reject are still accepted: refusing a plan is never
wrong.

**The multi-agent server is never load-bearing.** Disabled, unreachable or
answering outside its contract, starting a review still returns the Python
proposal with `review.status: "unavailable"` and the reason, and points at
the Release 1 path (POST /plan) that applies a plan without agent review.
Nothing is written to the goal on that path -- a person asked for a review,
and applying a plan they did not see reviewed would be a surprise.

Every step is logged to ai_plan_log with phase `agent`: the evidence sent
and the run id when a review starts (or why it could not), and the decision
with the agents' full output when one is made.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from config import DEFAULT_USER_ID

from ..errors import Conflict, NotFound, ServiceUnavailable
from ..models import ai_log as ai_log_model
from ..models import contributions as contributions_model
from ..models import goals as goals_model
from ..models import steps as steps_model
from ..multiagent import client
from . import agent as agent_service
from . import dates
from . import goals as goals_service

PHASE = "agent"

# Decisions that write the proposal to the goal. The other two are records.
APPLYING_DECISIONS = ("approve", "correct")

# The schedule goes to the agents in full up to this many instalments. Past
# it, the summary figures alone: a five-year goal is sixty near-identical
# lines that would crowd a small model's context without telling it more.
MAX_SCHEDULE_IN_EVIDENCE = 12

TASK = (
    "Review the proposed savings plan for the goal named in the evidence. Judge whether "
    "the instalment schedule is realistic given the goal's progress so far and the budget "
    "evidence, and name the risks a person should weigh before approving it. Every figure "
    "in the evidence is already calculated and final -- do not recalculate, total or "
    "estimate any of them."
)


# ---------------------------------------------------------------------------
# The proposal, the evidence, and the facts they were computed from
# ---------------------------------------------------------------------------


def _basis(conn: sqlite3.Connection, goal: dict) -> dict:
    """The facts the proposed schedule depends on.

    The schedule is `remaining / months` laid out from the next free step
    number to the target date, so these are exactly what would change it.
    """
    return {
        "target_amount": round(float(goal["target_amount"]), 2),
        "target_date": goal["target_date"],
        "saved_to_date": round(float(goal["saved_to_date"]), 2),
        "first_step_order": steps_model.max_step_order(conn, goal["goal_id"], exclude_pending=True) + 1,
        "status": goal["status"],
    }


def _proposal(prepared: dict) -> dict:
    """Python's plan, with the deterministic descriptions it will be applied with."""
    schedule = prepared["schedule"]
    steps = [
        {**item, "description": agent_service.default_description(index, len(schedule))}
        for index, item in enumerate(schedule)
    ]
    monthly = steps[0]["step_amount"]
    return {
        "steps": steps,
        "step_count": len(steps),
        "monthly_amount": monthly,
        "final_amount": steps[-1]["step_amount"],
        "total_scheduled": round(sum(item["step_amount"] for item in steps), 2),
        "first_due_date": steps[0]["due_date"],
        "final_due_date": steps[-1]["due_date"],
        "currency": prepared["budget"]["currency"],
        **agent_service.affordability(monthly, prepared["available"]),
        "mcp": agent_service.mcp_block(prepared["context"]),
    }


def _evidence(goal: dict, proposal: dict, observation: dict, budget: dict) -> dict:
    """What the agents are given. Every value was computed in Python.

    Keys are named for what they hold, because the Planner refers to the
    evidence by key and a person reads its plan by those names.
    """
    schedule = {
        "instalment_count": proposal["step_count"],
        "monthly_amount": proposal["monthly_amount"],
        "final_instalment_amount": proposal["final_amount"],
        "first_due_date": proposal["first_due_date"],
        "final_due_date": proposal["final_due_date"],
        "total_scheduled": proposal["total_scheduled"],
    }
    if proposal["step_count"] <= MAX_SCHEDULE_IN_EVIDENCE:
        schedule["instalments"] = [
            {"number": item["step_order"], "amount": item["step_amount"], "due_date": item["due_date"]}
            for item in proposal["steps"]
        ]
    return {
        "goal": {
            "name": goal["name"],
            "priority": goal["priority"],
            "target_amount": goal["target_amount"],
            "target_date": goal["target_date"],
            "saved_to_date": goal["saved_to_date"],
            "remaining_amount": goal["remaining_amount"],
            "percent_complete": goal["percent_complete"],
            "currency": proposal["currency"],
        },
        "progress": {
            "status": observation["status"],
            "required_to_date": observation["required_to_date"],
            "variance": observation["variance"],
            "months_remaining": observation["months_remaining"],
            "projected_completion_date": observation["projected_completion_date"],
        },
        "proposed_schedule": schedule,
        "budget": {
            "monthly_budget": budget["monthly_budget"],
            "available_to_save": proposal["available_monthly_budget"],
            "available_to_save_source": proposal["mcp"]["source"],
            "plan_within_budget": proposal["within_budget"],
            "monthly_shortfall": proposal["shortfall"],
        },
    }


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _staleness(conn: sqlite3.Connection, record: dict, today: date | None = None) -> list[str]:
    """Why the frozen proposal can no longer be applied as it stands. Empty if it can."""
    goal_id = record["goal_id"]
    try:
        goal = goals_service.get_goal_or_404(conn, goal_id)
    except NotFound:
        return [f"goal {goal_id} has been deleted"]

    goal["saved_to_date"] = contributions_model.total_for_goal(conn, goal_id)
    now, then = _basis(conn, goal), record["basis"]

    labels = {
        "target_amount": "the target amount",
        "target_date": "the target date",
        "saved_to_date": "the amount saved (a contribution was added or removed)",
        "first_step_order": "the completed steps (one was completed, skipped or edited)",
        "status": "the goal's status",
    }
    problems = [
        f"{labels[key]} changed from {then[key]} to {now[key]}" for key in labels if now[key] != then[key]
    ]

    today_iso = dates.to_iso(today or dates.today())
    first_due = record["proposal"]["first_due_date"]
    if first_due <= today_iso:
        problems.append(f"the first instalment was due on {first_due}, which is no longer in the future")
    return problems


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


def _log(conn: sqlite3.Connection, *, goal_id: int | None, model_name: str, prompt: str, response: dict) -> int:
    return ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=model_name,
        prompt=prompt,
        response=json.dumps(response, sort_keys=True, default=str),
        created_at=dates.now_iso(),
    )


def _record(conn: sqlite3.Connection, run_id: str) -> tuple[dict, dict | None]:
    """The review this backend started under `run_id`, and its decision if any.

    Only runs this backend started can be read or decided through it, so the
    endpoints are not a general proxy onto other features' runs.
    """
    proposed = decided = None
    for row in ai_log_model.agent_events(conn, run_id):
        body = json.loads(row["response"])
        body["log_id"] = int(row["log_id"])
        if body.get("event") == "proposed":
            proposed = body
        elif body.get("event") == "decided":
            decided = body
    if proposed is None:
        raise NotFound(f"no plan review with run id {run_id} was started by this backend")
    return proposed, decided


def _decision_summary(decided: dict | None) -> dict | None:
    if decided is None:
        return None
    return {key: decided[key] for key in ("decision", "note", "corrected", "applied", "steps_applied", "decided_at")}


# ---------------------------------------------------------------------------
# The three operations
# ---------------------------------------------------------------------------


def start_review(conn: sqlite3.Connection, goal_id: int, *, use_mcp: bool = True) -> tuple[dict, int]:
    """Build the proposal and send it for review. 202 when a run started, 200 when not."""
    prepared = agent_service.prepare(conn, goal_id, None, use_mcp=use_mcp)
    goal = prepared["goal"]
    proposal = _proposal(prepared)
    observation = agent_service.observe(conn, goal_id, as_at=prepared["as_at"], log=False)
    evidence = _evidence(goal, proposal, observation, prepared["budget"])
    basis = _basis(conn, goal)
    sent = json.dumps({"task": TASK, "evidence": evidence}, sort_keys=True)

    body = {
        "goal_id": goal_id,
        "proposal": proposal,
        "evidence": evidence,
        "task": TASK,
    }

    reason = None
    run = None
    if not client.is_enabled():
        reason = client.DISABLED_REASON
    else:
        try:
            run = client.start_review(TASK, evidence)
        except client.MultiAgentUnavailable as exc:
            reason = str(exc)

    multi_agent = {"enabled": client.is_enabled(), "used": run is not None, "server_url": client.server_url()}

    if run is None:
        body["review"] = {
            "status": "unavailable",
            "run_id": None,
            "reason": reason,
            "multi_agent": multi_agent,
            # The Release 1 path: the same Python schedule, applied without a
            # review. Offered, not taken -- see the module docstring.
            "fallback": {
                "mode": "release_1",
                "method": "POST",
                "path": f"/api/goals/{goal_id}/plan",
                "description": "Generate and apply the plan directly, without an agent review (Release 1).",
            },
        }
        body["log_id"] = _log(
            conn, goal_id=goal_id, model_name=ai_log_model.PYTHON,
            prompt=f"Plan review for goal {goal_id} not started: {reason}",
            response={"event": "unavailable", "run_id": None, "goal_id": goal_id, "reason": reason},
        )
        conn.commit()
        return body, 200

    run_id = run["run_id"]
    body["review"] = {
        "status": "started",
        "run_id": run_id,
        "workflow": run,
        "poll_path": f"/api/agents/workflow/{run_id}",
        "multi_agent": multi_agent,
    }
    body["log_id"] = _log(
        conn, goal_id=goal_id, model_name=ai_log_model.MULTI_AGENT,
        prompt=sent,
        response={
            "event": "proposed", "run_id": run_id, "goal_id": goal_id,
            "proposal": proposal, "basis": basis, "workflow": run,
        },
    )
    conn.commit()
    return body, 202


def get_review(conn: sqlite3.Connection, run_id: str) -> dict:
    """The review as it stands: the agents' progress, the proposal, and whether it can still be applied."""
    record, decided = _record(conn, run_id)

    if decided is not None:
        # Complete, and the run body was stored when it was decided, so there
        # is nothing the server could add -- and nothing it could break.
        workflow = decided["workflow"]
    else:
        workflow = _live_run(run_id)

    stale = _staleness(conn, record) if decided is None else []
    awaiting = workflow["status"] == client.AWAITING_HUMAN and decided is None
    return {
        "run_id": run_id,
        "goal_id": record["goal_id"],
        "workflow": workflow,
        "proposal": record["proposal"],
        "stale": {"is_stale": bool(stale), "reasons": stale},
        "decision": _decision_summary(decided),
        # What the review controls offer. Partial and reject stay open when
        # the proposal is stale; approve and correct do not.
        "can_decide": awaiting,
        "can_apply": awaiting and not stale,
        "log_id": record["log_id"],
    }


def _live_run(run_id: str) -> dict:
    try:
        return client.get_run(run_id)
    except client.RunNotFound as exc:
        raise NotFound(
            f"the multi-agent server has no record of run {run_id} -- its workflow history was "
            "probably reset. Start a new review."
        ) from exc


def decide(conn: sqlite3.Connection, run_id: str, clean: dict) -> dict:
    """Record the human decision, and apply the frozen proposal if it says to.

    Order matters. Everything that can refuse locally is checked first, so a
    refusal leaves the server's run still awaiting a decision. Then the plan
    and the log row are written inside one uncommitted transaction, the
    server is told, and the transaction commits only if the server accepted
    -- so the goal and the server's record cannot disagree about whether a
    decision was made. The write lock is held for that one call, which is a
    single local request against the server's own store.
    """
    if not client.is_enabled():
        raise ServiceUnavailable(f"{client.DISABLED_REASON} The review cannot be decided while it is off.")

    record, decided = _record(conn, run_id)
    decision = clean["decision"]
    if decided is not None:
        raise Conflict(
            f"this review was already decided: {decided['decision']} at {decided['decided_at']}"
        )

    applies = decision in APPLYING_DECISIONS
    if applies:
        problems = _staleness(conn, record)
        if problems:
            raise Conflict(
                "the goal has changed since the agents reviewed this plan, so it would no longer "
                "close the gap it was built for. Start a new review, or reject this one.",
                details=problems,
            )

    workflow = _live_run(run_id)
    if workflow["status"] != client.AWAITING_HUMAN:
        error = workflow.get("error") or {}
        why = f": {error.get('phase')} phase -- {error.get('detail')}" if error else ""
        raise Conflict(f"the review is {workflow['status']}{why}; only a review awaiting a decision can be decided")

    goal_id = record["goal_id"]
    steps = record["proposal"]["steps"] if applies else []
    rationale = clean["corrected"] if decision == "correct" else clean["note"]
    decided_at = dates.now_iso()

    if applies:
        agent_service.persist_schedule(conn, goal_id, steps)
    # A goal deleted since the review started can still have the review
    # rejected. Its log row then belongs to no goal, as every log row of a
    # deleted goal does (ON DELETE SET NULL); the goal id stays in the JSON.
    goal_exists = goals_model.get_goal(conn, goal_id) is not None
    log_id = _log(
        conn, goal_id=goal_id if goal_exists else None, model_name=ai_log_model.HUMAN,
        prompt=(
            f"Human decision '{decision}' on multi-agent plan review {run_id} for goal {goal_id}. "
            + (f"Rationale: {rationale}" if rationale else "No rationale given.")
        ),
        response={
            "event": "decided", "run_id": run_id, "goal_id": goal_id, "decision": decision,
            "note": clean["note"], "corrected": clean["corrected"], "applied": applies,
            "steps_applied": len(steps), "decided_at": decided_at, "workflow": workflow,
        },
    )

    try:
        server = client.decide(
            run_id, decision=decision, note=clean["note"], corrected=clean["corrected"],
            reviewer=f"{client.caller()} (user {DEFAULT_USER_ID})",
        )
    except client.RunConflict as exc:
        conn.rollback()
        raise Conflict(f"the multi-agent server refused the decision: {exc}") from exc
    except client.RunNotFound as exc:
        conn.rollback()
        raise NotFound(f"the multi-agent server no longer has run {run_id}; start a new review") from exc
    except client.MultiAgentUnavailable:
        conn.rollback()
        raise
    conn.commit()

    return {
        "run_id": run_id,
        "goal_id": goal_id,
        "decision": decision,
        "applied": applies,
        "steps_applied": len(steps),
        "rationale": rationale or None,
        "workflow_status": server["status"],
        "decided_at": decided_at,
        "log_id": log_id,
        "goal": goals_service.get_goal_detail(conn, goal_id) if applies else None,
    }


def health() -> dict:
    return client.probe()
