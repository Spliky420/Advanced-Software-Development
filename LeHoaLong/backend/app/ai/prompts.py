"""Prompt templates for the plan and adapt phases.

The architectural rule this module exists to enforce:

    **The model is never asked for a number.**

Python computes the whole schedule first -- how many instalments, how much
each one is, and what date each falls due. The prompt states those figures as
settled fact, and the response schema asks only for a `description` per step
and, for adapt, a one-sentence `summary`.

That is stronger than checking the model's arithmetic afterwards. A figure
cannot come back wrong because no figure is ever asked for: amounts and dates
never round-trip through the model at all. See parsing.py, which merges the
model's words into Python's schedule rather than the other way round.

The remaining exposure is prose: a model could still write a number into a
description. The prompts tell it not to (the UI renders the real amount
beside every step anyway), but nothing at runtime strips one out -- the same
honest caveat Joshua's README records for his insight text.

Release 1 adds cross-feature context to these prompts, and the rule does not
bend for it. The recurring-bills figure comes from another student's backend
over MCP, the available-to-save figure is subtracted in Python
(app/mcp/context.py), and both reach the prompt as finished statements of
fact. The model is told what the figures are so its wording can acknowledge a
stretched budget; it is never asked to combine them.

Thomas's income and spending totals are stated with the period they cover
("the whole transaction ledger"), because that is what his backend reports.
Describing them as monthly would be a figure this feature invented, and a
small model told "income 7,200" would be entitled to treat it as monthly.
"""

from __future__ import annotations

PLAN_SYSTEM_PROMPT = (
    "You are a savings coach helping someone reach a savings goal. "
    "You will be given a goal and a schedule of instalments that has ALREADY "
    "been calculated for you. Your only job is to write a short, encouraging "
    "description for each instalment. "
    "Never perform arithmetic. Never state a dollar amount or a date in a "
    "description -- the app displays those next to your text. "
    "Reply with JSON only, in exactly this shape: "
    '{"steps": [{"step_order": <integer>, "description": "<short sentence>"}]}. '
    "Include one entry for every step_order you are given, and no others."
)

ADAPT_SYSTEM_PROMPT = (
    "You are a savings coach. A saver has fallen off, or moved ahead of, "
    "their plan. You will be given the measured variance and a REVISED "
    "schedule of instalments that has ALREADY been calculated for you. "
    "Your job is to write a short description for each remaining instalment, "
    "plus one sentence of summary explaining what changed and why. "
    "Never perform arithmetic. Never state a dollar amount or a date in a "
    "description -- the app displays those next to your text. Be matter of "
    "fact and encouraging; never scold. "
    "Reply with JSON only, in exactly this shape: "
    '{"steps": [{"step_order": <integer>, "description": "<short sentence>"}], '
    '"summary": "<one sentence>"}. '
    "Include one entry for every step_order you are given, and no others."
)


def _money(currency: str, amount: float) -> str:
    return f"{currency} {amount:,.2f}"


def _context_lines(context: dict | None, currency: str) -> str:
    """The MCP-supplied context, as statements of fact. Empty when there is none.

    Only ever describes figures another service computed or that Python
    subtracted. Each line names where its number came from, which is as much
    for the reader of the logged prompt as for the model: the audit row for a
    plan then carries the provenance of every figure in it.
    """
    if not context or not context.get("mcp", {}).get("used"):
        return ""

    lines = []
    bills = context.get("committed_elsewhere") or {}
    if bills.get("monthly_bills") is not None:
        count = bills.get("active_bill_count")
        counted = f" across {count} active bills" if isinstance(count, int) else ""
        lines.append(
            f"Already committed every month to recurring bills{counted}: "
            f"{_money(currency, bills['monthly_bills'])} "
            f"(supplied by the household bills service, which calculated it)."
        )

    observed = context.get("observed") or {}
    if observed.get("total_income") is not None or observed.get("total_expenses") is not None:
        parts = []
        if observed.get("total_income") is not None:
            parts.append(f"income {_money(currency, observed['total_income'])}")
        if observed.get("total_expenses") is not None:
            parts.append(f"spending {_money(currency, observed['total_expenses'])}")
        lines.append(
            "Observed over the whole transaction ledger (NOT a monthly figure): "
            + ", ".join(parts)
            + " (supplied by the transactions service)."
        )

    return "\n".join(lines) + "\n" if lines else ""


def _schedule_lines(schedule: list[dict], currency: str) -> str:
    """Render the computed schedule as one line per instalment."""
    return "\n".join(
        f"  step_order {item['step_order']}: {currency} {item['step_amount']:,.2f} due {item['due_date']}"
        for item in schedule
    )


def _budget_line(available_monthly, currency: str, context: dict | None, stretch_below: float | None) -> str:
    """What is left to save each month, and whether the plan fits inside it.

    The wording changes with what the figure accounts for, because neither a
    model nor a marker reading the logged prompt should have to guess. With
    MCP the figure is net of recurring bills as well as the user's other
    goals; without it, only the other goals, exactly as in Release 0.

    `stretch_below` is the instalment the plan asks for, or None to leave the
    stretch sentence out altogether.
    """
    if available_monthly is None:
        return "Available monthly budget: not recorded by this user."

    after = (
        "this user's other active goals and their recurring bills"
        if context and context.get("mcp", {}).get("used")
        else "this user's other active goals"
    )
    line = f"Available to save each month after {after}: {_money(currency, available_monthly)}."
    if stretch_below is not None and available_monthly < stretch_below:
        line += (
            " This plan asks for more than that, so the descriptions should"
            " acknowledge that the goal is a stretch on the current budget."
        )
    return line


def build_plan_prompt(
    *, goal: dict, schedule: list[dict], currency: str, available_monthly, context: dict | None = None
) -> str:
    """The PLAN prompt: goal, budget context, and the finished schedule."""
    budget_line = _budget_line(available_monthly, currency, context, schedule[0]["step_amount"])

    return (
        f"Goal: {goal['name']}\n"
        f"Target: {currency} {goal['target_amount']:,.2f} by {goal['target_date']}\n"
        f"Already saved: {currency} {goal['saved_to_date']:,.2f}\n"
        f"Still to save: {currency} {goal['remaining_amount']:,.2f}\n"
        f"Priority: {goal['priority']}\n"
        f"{_context_lines(context, currency)}"
        f"{budget_line}\n\n"
        f"The schedule below is final and was calculated by the application.\n"
        f"Write one description for each step_order, and change nothing else.\n\n"
        f"{_schedule_lines(schedule, currency)}\n"
    )


def build_adapt_prompt(
    *,
    goal: dict,
    observation: dict,
    schedule: list[dict],
    currency: str,
    available_monthly,
    context: dict | None = None,
) -> str:
    """The ADAPT prompt: the same, plus the variance observe already measured."""
    variance = observation["variance"]
    direction = "behind" if variance < 0 else "ahead of"
    # No stretch sentence on this one: adapt reacts to what already happened,
    # and the revised instalment is what it is. Telling the model the plan is
    # unaffordable in the same breath as asking it not to scold would be a
    # prompt arguing with itself.
    budget_line = _budget_line(available_monthly, currency, context, None)

    return (
        f"Goal: {goal['name']}\n"
        f"Target: {currency} {goal['target_amount']:,.2f} by {goal['target_date']}\n"
        f"As at {observation['as_at']}, this saver is {direction} plan.\n"
        f"  Saved to date:    {currency} {observation['saved_to_date']:,.2f}\n"
        f"  Plan expected:    {currency} {observation['required_to_date']:,.2f}\n"
        f"  Variance:         {currency} {variance:,.2f} ({observation['status']})\n"
        f"  Still to save:    {currency} {goal['remaining_amount']:,.2f}\n"
        f"{_context_lines(context, currency)}"
        f"{budget_line}\n\n"
        f"Completed instalments are unchanged and are not listed.\n"
        f"The revised schedule below is final and was calculated by the application.\n"
        f"Write one description for each step_order, plus one sentence of summary.\n\n"
        f"{_schedule_lines(schedule, currency)}\n"
    )
