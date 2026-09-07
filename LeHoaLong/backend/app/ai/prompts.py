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


def _schedule_lines(schedule: list[dict], currency: str) -> str:
    """Render the computed schedule as one line per instalment."""
    return "\n".join(
        f"  step_order {item['step_order']}: {currency} {item['step_amount']:,.2f} due {item['due_date']}"
        for item in schedule
    )


def build_plan_prompt(*, goal: dict, schedule: list[dict], currency: str, available_monthly) -> str:
    """The PLAN prompt: goal, budget context, and the finished schedule."""
    if available_monthly is None:
        budget_line = "Available monthly budget: not recorded by this user."
    else:
        budget_line = (
            f"Available monthly budget after this user's other active goals: "
            f"{currency} {available_monthly:,.2f}."
        )
        if available_monthly < schedule[0]["step_amount"]:
            budget_line += (
                " This plan asks for more than that, so the descriptions should"
                " acknowledge that the goal is a stretch on the current budget."
            )

    return (
        f"Goal: {goal['name']}\n"
        f"Target: {currency} {goal['target_amount']:,.2f} by {goal['target_date']}\n"
        f"Already saved: {currency} {goal['saved_to_date']:,.2f}\n"
        f"Still to save: {currency} {goal['remaining_amount']:,.2f}\n"
        f"Priority: {goal['priority']}\n"
        f"{budget_line}\n\n"
        f"The schedule below is final and was calculated by the application.\n"
        f"Write one description for each step_order, and change nothing else.\n\n"
        f"{_schedule_lines(schedule, currency)}\n"
    )


def build_adapt_prompt(
    *, goal: dict, observation: dict, schedule: list[dict], currency: str, available_monthly
) -> str:
    """The ADAPT prompt: the same, plus the variance observe already measured."""
    variance = observation["variance"]
    direction = "behind" if variance < 0 else "ahead of"
    budget_line = (
        "Available monthly budget: not recorded by this user."
        if available_monthly is None
        else f"Available monthly budget after this user's other active goals: {currency} {available_monthly:,.2f}."
    )

    return (
        f"Goal: {goal['name']}\n"
        f"Target: {currency} {goal['target_amount']:,.2f} by {goal['target_date']}\n"
        f"As at {observation['as_at']}, this saver is {direction} plan.\n"
        f"  Saved to date:    {currency} {observation['saved_to_date']:,.2f}\n"
        f"  Plan expected:    {currency} {observation['required_to_date']:,.2f}\n"
        f"  Variance:         {currency} {variance:,.2f} ({observation['status']})\n"
        f"  Still to save:    {currency} {goal['remaining_amount']:,.2f}\n"
        f"{budget_line}\n\n"
        f"Completed instalments are unchanged and are not listed.\n"
        f"The revised schedule below is final and was calculated by the application.\n"
        f"Write one description for each step_order, plus one sentence of summary.\n\n"
        f"{_schedule_lines(schedule, currency)}\n"
    )
