"""Cross-feature budget context, assembled over MCP.

**Why MCP earns its place in this feature.** A savings plan is only realistic
if it accounts for money already committed elsewhere. This backend knows what
the user's *goals* require each month; it has no idea that $620.24 a month
already goes out on electricity, internet, insurance and a gym membership,
because those live in another student's database. Two tools close that gap:

    bill_summary         HyunWoo  -- recurring monthly commitments
    transaction_summary  Thomas   -- observed income and spending

**Nothing here recomputes a supplied figure.** Every number these tools return
is carried through exactly as the owning backend produced it, and this module
reads named fields rather than deriving anything from them. HyunWoo's
`calculations.py` has already converted each bill's billing frequency to a
monthly amount -- a fortnightly $29.95 gym membership becomes $64.89 -- so
`monthly_cost` arrives ready to use, and re-deriving it here would be both
duplicated logic and a second place to get it wrong.

**One figure is derived, and Python derives it.** `available_to_save` is:

    monthly_budget - committed_to_other_goals - monthly_bills

signed, not floored. The first two terms are this feature's own Release 0
arithmetic; the third is the MCP contribution. It is reported with a term by
term breakdown naming where each number came from, so the plan response can
show its working. The model is never asked to do this subtraction, and never
sees it as anything other than a settled fact.

**Why Thomas's figures are not in that subtraction.** `transaction_summary`
returns whole-ledger totals -- `total_income`, `total_expenses` -- with no
period attached anywhere in the response. Turning them into a monthly rate
would mean inventing a divisor, which is precisely the arithmetic-by-
assumption CLAUDE.md's rule exists to prevent. They are carried through,
labelled `period: "whole ledger"`, shown in the UI and stated in the prompt as
observed context. They inform the saver; they do not silently move the
instalment figure.

**Degrading is a first-class outcome, not an error path.** MCP disabled, the
server down, a teammate's backend down, or a tool answering in an unexpected
shape all produce a context that says so in `mcp.reason` and falls back to
Release 0's budget-settings figure. The feature must never break because
somebody else's container is not running.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..services import dates
from . import audit
from . import client as mcp_client

# The two tools this feature calls, in the order they are called, with the
# teammate who owns the data behind each. The owner strings are for the UI and
# the report: "where did this number come from" is the question MCP exists to
# answer, so the answer travels with the number.
BILLS_TOOL = "bill_summary"
TRANSACTIONS_TOOL = "transaction_summary"

TOOL_OWNERS = {
    BILLS_TOOL: "HyunWoo -- Bills and Subscriptions",
    TRANSACTIONS_TOOL: "Thomas -- Transaction Ledger",
}

# Where each term of the available-to-save calculation comes from. Spelled out
# rather than left implicit, because the whole point of the breakdown is to be
# able to point at a figure and say which service computed it.
OWN_ORIGIN = "Goals and Budgeting (this service)"
MCP_ORIGIN = f"{BILLS_TOOL} via MCP ({TOOL_OWNERS[BILLS_TOOL]})"


# ---------------------------------------------------------------------------
# The one derived figure
# ---------------------------------------------------------------------------


def available_to_save(
    monthly_budget: float | None,
    committed_to_other_goals: float,
    monthly_bills: float | None,
) -> float | None:
    """What is left each month once other goals and the bills are paid.

    None when no monthly budget has been set: there is then no total to
    subtract from, and inventing one would be worse than admitting it.

    Deliberately NOT floored at zero. A user whose goals and bills already
    exceed their budget is over-committed by a specific amount, and that
    amount is the useful fact -- flooring it would report "nothing spare" for
    both a user with $0.00 left and a user who is $1,694.40 short. Release 0's
    own available figure is signed for the same reason.
    """
    if monthly_budget is None:
        return None
    total = monthly_budget - committed_to_other_goals - (monthly_bills or 0.0)
    return round(total, 2)


def _number(value: object) -> float | None:
    """A figure a tool supplied, if it really is one.

    Rejects bools (which are ints in Python) and strings. A numeric string is
    not converted on purpose: parsing someone else's text into a number is
    interpretation, and if a tool's contract changes shape this should degrade
    visibly rather than quietly carry on with a reinterpreted figure.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Reading each tool's payload -- field access only, no arithmetic
# ---------------------------------------------------------------------------


def _read_bills(call: dict) -> dict:
    """What bill_summary contributes: one monthly figure, plus its context.

    Shape, from hyunwoo/backend (GET /api/bills + GET /api/summary):

        {"bills": [...], "summary": {"monthly_cost": 620.24, ...}}
    """
    reading: dict = {
        "tool": BILLS_TOOL,
        "owner": TOOL_OWNERS[BILLS_TOOL],
        "monthly_bills": None,
        "active_bill_count": None,
        "annual_bills": None,
        "category_monthly_costs": None,
        "bill_count_returned": None,
        "detail": None,
    }

    if call["is_error"]:
        reading["detail"] = call["error"]
        return reading

    payload = call["result"]
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        reading["detail"] = f"{BILLS_TOOL} returned no summary object"
        return reading

    monthly = _number(summary.get("monthly_cost"))
    if monthly is None:
        reading["detail"] = f"{BILLS_TOOL} returned no usable monthly_cost figure"
        return reading

    bills = payload.get("bills") if isinstance(payload, dict) else None
    reading.update(
        {
            # Carried through exactly as HyunWoo's backend computed it.
            "monthly_bills": monthly,
            "active_bill_count": summary.get("active_bill_count"),
            "annual_bills": _number(summary.get("annual_cost")),
            "category_monthly_costs": summary.get("category_monthly_costs"),
            "bill_count_returned": len(bills) if isinstance(bills, list) else None,
        }
    )
    return reading


def _read_transactions(call: dict) -> dict:
    """What transaction_summary contributes: observed totals, as observed.

    Shape, from mcp-server/tools.py reading Thomas's backend:

        {"total_income": 7200.0, "total_expenses": 3410.55,
         "potential_deductions": 480.25}

    `period` is stated on every reading so no consumer -- UI, prompt or
    reader of the report -- can mistake a whole-ledger total for a monthly
    one. Nothing divides these figures.
    """
    reading: dict = {
        "tool": TRANSACTIONS_TOOL,
        "owner": TOOL_OWNERS[TRANSACTIONS_TOOL],
        "total_income": None,
        "total_expenses": None,
        "potential_deductions": None,
        "period": "whole ledger",
        "detail": None,
    }

    if call["is_error"]:
        reading["detail"] = call["error"]
        return reading

    payload = call["result"]
    if not isinstance(payload, dict):
        reading["detail"] = f"{TRANSACTIONS_TOOL} returned no summary object"
        return reading

    reading.update(
        {
            "total_income": _number(payload.get("total_income")),
            "total_expenses": _number(payload.get("total_expenses")),
            "potential_deductions": _number(payload.get("potential_deductions")),
        }
    )
    if reading["total_income"] is None and reading["total_expenses"] is None:
        reading["detail"] = f"{TRANSACTIONS_TOOL} returned no usable income or expense figures"
    return reading


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _breakdown(
    monthly_budget: float | None,
    committed_to_other_goals: float,
    monthly_bills: float | None,
    result: float | None,
) -> dict:
    """The available-to-save calculation, term by term, with origins.

    This is what the UI panel renders and what the report quotes. Every term
    names the service that produced it, which is how a reader can satisfy
    themselves that the MCP figure is MCP's and the rest is mine.
    """
    terms = [
        {
            "label": "Monthly budget",
            "operator": "+",
            "amount": monthly_budget,
            "origin": OWN_ORIGIN,
        },
        {
            "label": "Committed to other active goals",
            "operator": "-",
            "amount": committed_to_other_goals,
            "origin": OWN_ORIGIN,
        },
    ]
    if monthly_bills is not None:
        terms.append(
            {
                "label": "Recurring monthly bills",
                "operator": "-",
                "amount": monthly_bills,
                "origin": MCP_ORIGIN,
            }
        )

    return {
        "formula": "monthly_budget - committed_to_other_goals - recurring_monthly_bills",
        "terms": terms,
        "result": result,
        # Stated in the payload, not just in a comment: the arithmetic rule is
        # a claim this feature makes to a marker, and the API should say it.
        "computed_by": "python",
    }


def assemble(
    conn: sqlite3.Connection,
    *,
    goal_id: int | None,
    budget: dict,
    as_at: date | None = None,
    use_mcp: bool = True,
) -> dict:
    """Build the budget context for one goal. Never raises for MCP problems.

    `budget` is what services/budget.available_monthly returned: this user's
    monthly budget, what their *other* active goals already require, and
    Release 0's available figure. MCP adds one term to that.

    Every tool call is written to ai_plan_log, attributed to `goal_id` when
    there is one, including the calls that failed and the case where the
    server could not be reached at all.
    """
    as_at = as_at or dates.today()
    monthly_budget = budget.get("monthly_budget")
    committed = float(budget.get("committed_to_other_goals") or 0.0)

    status: dict = {
        "enabled": mcp_client.is_enabled(),
        "used": False,
        "partial": False,
        "reason": None,
        "server_url": None,
        "tools_called": [],
    }
    readings: dict = {"bills": None, "transactions": None}

    calls: list[dict] = []
    if not use_mcp:
        status["reason"] = "MCP was switched off for this request (use_mcp=false)."
    elif not status["enabled"]:
        status["reason"] = "MCP is disabled by configuration (MCP_ENABLED=false)."
    else:
        status["server_url"] = mcp_client.server_url()
        try:
            # One session for both tools -- see client.call_tools.
            calls = mcp_client.call_tools([(BILLS_TOOL, {}), (TRANSACTIONS_TOOL, {})])
        except mcp_client.MCPUnavailable as exc:
            status["reason"] = str(exc)
            audit.record_unavailable(
                conn,
                goal_id=goal_id,
                detail=str(exc),
                attempted=f"tools/call {BILLS_TOOL} + {TRANSACTIONS_TOOL}",
            )

    for call in calls:
        call["log_id"] = audit.record_tool_call(conn, goal_id=goal_id, call=call)
        status["tools_called"].append(
            {
                "tool": call["tool"],
                "owner": TOOL_OWNERS.get(call["tool"]),
                "arguments": call["arguments"],
                "is_error": call["is_error"],
                "error": call["error"],
                "duration_ms": call["duration_ms"],
                "log_id": call["log_id"],
            }
        )

    by_tool = {call["tool"]: call for call in calls}
    if BILLS_TOOL in by_tool:
        readings["bills"] = _read_bills(by_tool[BILLS_TOOL])
    if TRANSACTIONS_TOOL in by_tool:
        readings["transactions"] = _read_transactions(by_tool[TRANSACTIONS_TOOL])

    bills = readings["bills"]
    monthly_bills = bills["monthly_bills"] if bills else None

    # `used` means one specific thing: the available-to-save figure below
    # includes an MCP-supplied term. That depends only on the bills figure --
    # Thomas's totals are context, and never enter the arithmetic -- so a
    # failure there is `partial`, not unused.
    if monthly_bills is not None:
        status["used"] = True
        failures = [item for item in status["tools_called"] if item["is_error"]]
        unusable = [
            reading["detail"]
            for reading in (readings["transactions"],)
            if reading and reading["detail"]
        ]
        if failures or unusable:
            status["partial"] = True
            status["reason"] = (
                "The recurring-bills figure was retrieved, but "
                + "; ".join([item["error"] for item in failures] + unusable)
                + "."
            )
    elif calls and status["reason"] is None:
        status["reason"] = (bills or {}).get("detail") or f"{BILLS_TOOL} returned no usable figure."

    available = available_to_save(monthly_budget, committed, monthly_bills)

    return {
        "goal_id": goal_id,
        "as_at": dates.to_iso(as_at),
        "currency": budget.get("currency"),
        "mcp": status,
        "budget": {
            "monthly_budget": monthly_budget,
            "budget_is_set": monthly_budget is not None,
            "committed_to_other_goals": committed,
            # Release 0's figure, kept alongside so the difference MCP made is
            # visible rather than asserted.
            "available_before_bills": budget.get("available"),
        },
        "committed_elsewhere": bills,
        "observed": readings["transactions"],
        "available_to_save": available,
        "available_to_save_source": "mcp" if status["used"] else "budget_settings",
        "calculation": _breakdown(monthly_budget, committed, monthly_bills, available),
    }
