"""Plan -> Act -> Observe -> Adapt.

The four phases of the agentic loop, mapped to the four endpoints:

    PLAN     POST /api/goals/<id>/plan            plan_goal()
    ACT      POST /api/goals/<id>/contributions   services/contributions.py
    OBSERVE  GET  /api/goals/<id>/progress        observe()
    ADAPT    POST /api/goals/<id>/replan          replan_goal()

ACT lives in the contributions service because it is not an AI operation at
all -- it is the user putting money aside, and the loop's whole point is that
the other three phases react to it.

Two rules hold throughout:

**Python does the arithmetic.** `build_schedule` decides how many instalments
there are, what each one costs and when it falls due, before any prompt is
written. The model is asked for descriptions, never for figures, and
`parsing.merge_descriptions` attaches its words to Python's schedule rather
than reading a schedule back out of it. A wrong number cannot come back
because no number is ever sent for the model to change.

**A misbehaving model is not an outage.** If the response cannot be parsed,
the call is retried once, and if that also fails the deterministic even-split
plan stands in. The endpoint still returns 201 with a real plan, flagged
`fallback: true`. Ollama being unreachable is different -- that is
infrastructure, and it is a clean 503.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date

from flask import current_app

from ..ai import client, parsing, prompts
from ..errors import ValidationFailed
from ..models import ai_log as ai_log_model
from ..models import contributions as contributions_model
from ..models import steps as steps_model
from . import budget as budget_service
from . import dates, serialise
from . import goals as goals_service

# One retry, then fall back. A second retry against a small model that has
# already failed twice buys latency, not reliability.
MAX_MODEL_ATTEMPTS = 2

# A projection further out than this is not information, it is a rounding
# artefact of a tiny contribution rate. Report "unknown" instead.
MAX_PROJECTION_MONTHS = 1200


# ---------------------------------------------------------------------------
# Pure arithmetic -- no model, no database
# ---------------------------------------------------------------------------


def build_schedule(remaining_amount: float, as_at: date, target_date: date, first_order: int) -> list[dict]:
    """Split `remaining_amount` into monthly instalments ending on the target date.

    Every instalment is the same to the cent except the last, which absorbs
    the rounding remainder so the instalments sum to exactly the amount owed.
    The final due date is the target date itself rather than a month-step, so
    a plan always lands on the day the user asked for.
    """
    months = dates.months_between(as_at, target_date)
    if months == 0:
        raise ValueError("cannot build a schedule with no months remaining")

    per_month = round(remaining_amount / months, 2)
    schedule: list[dict] = []
    for index in range(months):
        is_last = index == months - 1
        if is_last:
            amount = round(max(remaining_amount - per_month * (months - 1), 0.0), 2)
            due = target_date
        else:
            amount = per_month
            due = dates.add_months(as_at, index + 1)
        schedule.append(
            {
                "step_order": first_order + index,
                "step_amount": amount,
                "due_date": dates.to_iso(due),
            }
        )
    return schedule


def default_description(index: int, total: int) -> str:
    """The deterministic description used when the model does not supply one.

    Written to read like a plan rather than like an error, because it is one:
    the schedule is exactly the schedule the model would have been describing.
    """
    position = f"Month {index + 1} of {total}"
    if total == 1:
        return "Final transfer to complete this goal"
    if index == 0:
        return f"{position} -- make the first transfer and set up an automatic payment"
    if index == total - 1:
        return f"{position} -- final transfer to complete this goal"
    return f"{position} -- set aside the scheduled amount"


def classify(variance: float, required_to_date: float, remaining_amount: float, tolerance: float) -> str:
    """Turn a variance into on_track / behind / ahead / achieved."""
    if remaining_amount <= 0:
        return "achieved"
    if variance < -tolerance:
        return "behind"
    if variance > tolerance:
        return "ahead"
    return "on_track"


def project_completion(
    *, saved_to_date: float, remaining_amount: float, started: date, as_at: date
) -> str | None:
    """When this goal lands if the saver keeps up their average rate so far.

    Rate is measured over the goal's whole life rather than the last month or
    two: it is the figure the user can least argue with, and it does not
    swing wildly on one missed payday.

    None means "cannot say" -- nothing has been saved yet, so there is no rate
    to extrapolate from.
    """
    if remaining_amount <= 0:
        return dates.to_iso(as_at)
    elapsed_months = max(dates.months_between(started, as_at), 1)
    monthly_rate = saved_to_date / elapsed_months
    if monthly_rate <= 0:
        return None
    months_needed = math.ceil(remaining_amount / monthly_rate)
    if months_needed > MAX_PROJECTION_MONTHS:
        return None
    return dates.to_iso(dates.add_months(as_at, months_needed))


# ---------------------------------------------------------------------------
# OBSERVE
# ---------------------------------------------------------------------------


def _tolerance_for(required_to_date: float) -> float:
    percent = float(current_app.config["PROGRESS_TOLERANCE_PERCENT"])
    floor = float(current_app.config["PROGRESS_TOLERANCE_FLOOR"])
    return round(max(floor, required_to_date * percent / 100), 2)


def observe(conn: sqlite3.Connection, goal_id: int, *, as_at: date | None = None, log: bool = True) -> dict:
    """OBSERVE: saved-to-date against required-to-date. Pure Python.

    `required_to_date` is the sum of the step amounts already due -- what the
    plan said should have been saved by now. A goal with no plan has nothing
    due, so it reads as on_track; `has_plan` says so explicitly rather than
    letting the caller mistake it for a goal that is genuinely keeping up.
    """
    goal = goals_service.get_goal_or_404(conn, goal_id)
    as_at = as_at or dates.today()
    as_at_iso = dates.to_iso(as_at)

    saved_to_date = round(contributions_model.total_for_goal(conn, goal_id), 2)
    required_to_date = round(steps_model.required_to_date(conn, goal_id, as_at_iso), 2)
    funding = serialise.funding(goal["target_amount"], saved_to_date)
    variance = round(saved_to_date - required_to_date, 2)
    tolerance = _tolerance_for(required_to_date)
    status = classify(variance, required_to_date, funding["remaining_amount"], tolerance)

    steps = steps_model.list_for_goal(conn, goal_id)
    target_date = dates.parse_date(goal["target_date"])
    projected = project_completion(
        saved_to_date=saved_to_date,
        remaining_amount=funding["remaining_amount"],
        started=dates.parse_date(goal["created_at"][:10]),
        as_at=as_at,
    )

    observation = {
        "phase": "observe",
        "description": (
            "Compare what has actually been contributed against what the plan "
            "expected by this date. Pure Python arithmetic; the model is not "
            "involved in this phase."
        ),
        "goal_id": goal_id,
        "goal_name": goal["name"],
        "as_at": as_at_iso,
        "status": status,
        "saved_to_date": saved_to_date,
        "required_to_date": required_to_date,
        "variance": variance,
        "variance_tolerance": tolerance,
        "target_amount": goal["target_amount"],
        "target_date": goal["target_date"],
        **funding,
        "months_remaining": dates.months_between(as_at, target_date),
        "has_plan": len(steps) > 0,
        "step_count": len(steps),
        "pending_step_count": sum(1 for step in steps if step["status"] == "pending"),
        "overdue_step_count": sum(
            1 for step in steps if step["status"] == "pending" and step["due_date"] <= as_at_iso
        ),
        "projected_completion_date": projected,
        "projected_meets_target": None if projected is None else projected <= goal["target_date"],
    }

    log_id = _log_observation(conn, goal_id, observation) if log else None
    observation["log_id"] = log_id
    observation["logged"] = log_id is not None
    return observation


def _log_observation(conn: sqlite3.Connection, goal_id: int, observation: dict) -> int | None:
    """Write an observe row, unless it would duplicate the last one.

    The dashboard calls /progress once per goal card, so logging every call
    unconditionally would bury the genuinely interesting rows under identical
    ones from page refreshes. A row is written whenever the observation has
    actually changed -- which includes the date rolling over, since `as_at` is
    part of what is compared. The response says which happened via `logged`.
    """
    payload = json.dumps(
        {
            key: observation[key]
            for key in (
                "as_at",
                "status",
                "saved_to_date",
                "required_to_date",
                "variance",
                "projected_completion_date",
            )
        },
        sort_keys=True,
    )

    previous = ai_log_model.latest_for_goal(conn, goal_id, "observe")
    if previous is not None and previous["response"] == payload:
        return None

    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase="observe",
        model_name=ai_log_model.PYTHON,
        prompt=(
            f"Observation for goal {goal_id} ({observation['goal_name']}) at {observation['as_at']}: "
            f"saved to date {observation['saved_to_date']:.2f}, "
            f"required to date {observation['required_to_date']:.2f}, "
            f"variance {observation['variance']:+.2f}, status {observation['status']}."
        ),
        response=payload,
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id


# ---------------------------------------------------------------------------
# Talking to the model
# ---------------------------------------------------------------------------


def _ask_model(prompt: str, system: str, expected_orders: list[int]) -> dict:
    """Send the prompt, retry once on an unusable answer, then give up quietly.

    Returns everything the caller needs to both use and audit the exchange.
    Raises only for Ollama being unreachable -- a bad answer is a normal,
    expected outcome with a defined consequence.
    """
    attempts: list[dict] = []
    last_problem: str | None = None

    for _ in range(MAX_MODEL_ATTEMPTS):
        raw, model = client.generate(prompt, system=system)
        attempts.append({"model_name": model, "prompt": prompt, "response": raw})
        try:
            descriptions = parsing.parse_step_descriptions(raw, expected_orders)
        except parsing.ResponseUnusable as exc:
            last_problem = str(exc)
            continue
        return {
            "descriptions": descriptions,
            "summary": parsing.parse_summary(raw),
            "attempts": attempts,
            "fallback": False,
            "fallback_reason": None,
            "model_name": model,
        }

    return {
        "descriptions": {},
        "summary": None,
        "attempts": attempts,
        "fallback": True,
        "fallback_reason": last_problem or "no usable response",
        "model_name": attempts[-1]["model_name"] if attempts else None,
    }


def _write_exchange_log(
    conn: sqlite3.Connection, goal_id: int, phase: str, outcome: dict, schedule: list[dict]
) -> list[int]:
    """Record the exchange: one row per model attempt, plus a fallback row.

    Every prompt sent and every raw response is stored verbatim -- this table
    is the evidence for the report. When the fallback plan stood in, a final
    row with model_name 'python' says so and carries the plan that was
    actually persisted, which is how the seeded fallback rows read too.
    """
    log_ids = []
    timestamp = dates.now_iso()

    for attempt in outcome["attempts"]:
        log_ids.append(
            ai_log_model.insert_log(
                conn,
                goal_id=goal_id,
                phase=phase,
                model_name=attempt["model_name"],
                prompt=attempt["prompt"],
                response=attempt["response"],
                created_at=timestamp,
            )
        )

    if outcome["fallback"]:
        log_ids.append(
            ai_log_model.insert_log(
                conn,
                goal_id=goal_id,
                phase=phase,
                model_name=ai_log_model.PYTHON,
                prompt=(
                    f"FALLBACK after {len(outcome['attempts'])} unusable response(s) "
                    f"({outcome['fallback_reason']}). The deterministic even-split plan below "
                    f"was generated in Python and persisted instead."
                ),
                response=json.dumps({"steps": schedule, "note": "fallback"}),
                created_at=timestamp,
            )
        )
    return log_ids


# ---------------------------------------------------------------------------
# PLAN and ADAPT
# ---------------------------------------------------------------------------


def _prepare(conn: sqlite3.Connection, goal_id: int, as_at: date | None) -> dict:
    """The shared groundwork for both plan and replan.

    Both need the same things: the goal with its funding figures, a schedule
    covering what is left, and how much monthly budget the user's *other*
    goals have not already claimed.
    """
    goal = goals_service.get_goal_or_404(conn, goal_id)
    as_at = as_at or dates.today()

    saved = contributions_model.total_for_goal(conn, goal_id)
    goal.update(serialise.funding(goal["target_amount"], saved))

    if goal["remaining_amount"] <= 0:
        raise ValidationFailed(
            [
                f"goal {goal_id} is already fully funded "
                f"({goal['saved_to_date']:.2f} of {goal['target_amount']:.2f}); there is nothing left to plan"
            ]
        )

    target_date = dates.parse_date(goal["target_date"])
    if dates.months_between(as_at, target_date) == 0:
        raise ValidationFailed(
            [
                f"goal {goal_id} has a target date of {goal['target_date']}, which has passed; "
                "move the target date before generating a plan"
            ]
        )

    first_order = steps_model.max_step_order(conn, goal_id, exclude_pending=True) + 1
    schedule = build_schedule(goal["remaining_amount"], as_at, target_date, first_order)
    budget = budget_service.available_monthly(
        conn, goal["user_id"], exclude_goal_id=goal_id, as_at=as_at
    )
    return {"goal": goal, "as_at": as_at, "schedule": schedule, "budget": budget}


def _persist(conn: sqlite3.Connection, goal_id: int, merged: list[dict]) -> None:
    """Replace the pending steps with the newly described schedule.

    Completed and skipped steps are untouched: they are history, and a
    regeneration must never erase what the user has already done.
    """
    timestamp = dates.now_iso()
    steps_model.delete_pending(conn, goal_id)
    for item in merged:
        steps_model.insert_step(
            conn,
            goal_id=goal_id,
            step_order=item["step_order"],
            description=item["description"],
            step_amount=item["step_amount"],
            due_date=item["due_date"],
            status="pending",
            source="ai",
            created_at=timestamp,
        )


def plan_goal(conn: sqlite3.Connection, goal_id: int, *, as_at: date | None = None) -> dict:
    """PLAN: generate and persist an ordered schedule of savings steps."""
    context = _prepare(conn, goal_id, as_at)
    goal, schedule, budget = context["goal"], context["schedule"], context["budget"]

    prompt = prompts.build_plan_prompt(
        goal=goal,
        schedule=schedule,
        currency=budget["currency"],
        available_monthly=budget["available"],
    )
    outcome = _ask_model(prompt, prompts.PLAN_SYSTEM_PROMPT, [item["step_order"] for item in schedule])
    merged = parsing.merge_descriptions(schedule, outcome["descriptions"], default_description)

    _persist(conn, goal_id, merged)
    log_ids = _write_exchange_log(conn, goal_id, "plan", outcome, schedule)
    conn.commit()

    return {
        "plan": {
            "phase": "plan",
            "description": (
                "Calculate the instalments needed to close the gap by the target "
                "date, then have the model describe each one. Every amount and "
                "date here was computed in Python."
            ),
            "step_count": len(merged),
            "total_scheduled": round(sum(item["step_amount"] for item in merged), 2),
            "monthly_amount": merged[0]["step_amount"],
            "first_due_date": merged[0]["due_date"],
            "final_due_date": merged[-1]["due_date"],
            "available_monthly_budget": budget["available"],
            "within_budget": (
                None if budget["available"] is None else merged[0]["step_amount"] <= budget["available"]
            ),
            "model_name": outcome["model_name"],
            "llm_called": bool(outcome["attempts"]),
            "fallback": outcome["fallback"],
            "fallback_reason": outcome["fallback_reason"],
            "log_ids": log_ids,
        },
        "goal": goals_service.get_goal_detail(conn, goal_id),
    }


def replan_goal(conn: sqlite3.Connection, goal_id: int, *, as_at: date | None = None) -> dict:
    """ADAPT: re-cut the remaining steps around the variance observe measured.

    Runs observe first so the model is told what actually happened, then
    rebuilds only the pending steps. The summary is the model's if it wrote a
    usable one, and a deterministic Python sentence otherwise -- either way
    every figure in it was calculated here.
    """
    observation = observe(conn, goal_id, as_at=as_at, log=True)
    context = _prepare(conn, goal_id, as_at)
    goal, schedule, budget = context["goal"], context["schedule"], context["budget"]

    prompt = prompts.build_adapt_prompt(
        goal=goal,
        observation=observation,
        schedule=schedule,
        currency=budget["currency"],
        available_monthly=budget["available"],
    )
    outcome = _ask_model(prompt, prompts.ADAPT_SYSTEM_PROMPT, [item["step_order"] for item in schedule])
    merged = parsing.merge_descriptions(schedule, outcome["descriptions"], default_description)

    # Read the outgoing plan before it is replaced: the before-and-after
    # instalment figure is the clearest single number in the response, and it
    # only exists while the old pending steps are still there.
    existing = steps_model.list_for_goal(conn, goal_id)
    preserved = sum(1 for step in existing if step["status"] != "pending")
    previous_monthly = next(
        (round(float(step["step_amount"]), 2) for step in existing if step["status"] == "pending"),
        None,
    )

    _persist(conn, goal_id, merged)
    log_ids = _write_exchange_log(conn, goal_id, "adapt", outcome, schedule)
    conn.commit()

    summary = outcome["summary"] or _fallback_summary(observation, merged, budget["currency"])

    return {
        "observe": observation,
        "adapt": {
            "phase": "adapt",
            "description": (
                "Re-cut the remaining instalments around the measured variance, "
                "leaving completed steps alone. The revised amounts were "
                "calculated in Python before the model saw them."
            ),
            "summary": summary,
            "summary_source": "model" if outcome["summary"] else "python",
            "steps_preserved": preserved,
            "steps_regenerated": len(merged),
            "previous_monthly_amount": previous_monthly,
            "revised_monthly_amount": merged[0]["step_amount"],
            "final_due_date": merged[-1]["due_date"],
            "available_monthly_budget": budget["available"],
            "model_name": outcome["model_name"],
            "llm_called": bool(outcome["attempts"]),
            "fallback": outcome["fallback"],
            "fallback_reason": outcome["fallback_reason"],
            "log_ids": log_ids,
        },
        "goal": goals_service.get_goal_detail(conn, goal_id),
    }


def _fallback_summary(observation: dict, merged: list[dict], currency: str) -> str:
    """A summary written in Python, for when the model did not supply one.

    Every figure in this sentence comes from the observation or the schedule,
    which is the same guarantee the model's version gets.
    """
    variance = observation["variance"]
    if observation["status"] == "behind":
        opening = f"You are {currency} {abs(variance):,.2f} behind this plan."
    elif observation["status"] == "ahead":
        opening = f"You are {currency} {abs(variance):,.2f} ahead of this plan."
    else:
        opening = "You are on track with this plan."
    return (
        f"{opening} The remaining {len(merged)} instalment(s) have been recalculated to "
        f"{currency} {merged[0]['step_amount']:,.2f} per month so the goal still lands on "
        f"{observation['target_date']}."
    )
