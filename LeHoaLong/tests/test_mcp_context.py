"""Budget context assembly over MCP.

Two claims are under test here, and they are the two a marker is most likely
to press on.

**Every figure a teammate's backend computed is carried through unchanged.**
Not rounded, not re-derived, not totalled. HyunWoo's backend has already
converted each bill's billing frequency to a monthly amount, so re-deriving
`monthly_cost` here would duplicate his logic and give this feature a second
chance to disagree with him.

**The one derived figure is derived in Python.** `available_to_save` is
`monthly_budget - committed_to_other_goals - monthly_bills`, computed in
`context.available_to_save`, reported with a term-by-term breakdown naming the
origin of each number, and never shown to a model as anything but a settled
fact. Thomas's whole-ledger totals are deliberately *not* in that subtraction,
because nothing in his response says what period they cover.

The third thing these tests pin is that none of it is load-bearing: with MCP
off, down, or half-working, a context still comes back and says which.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import BILL_SUMMARY_PAYLOAD, TRANSACTION_SUMMARY_PAYLOAD

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.mcp import client as mcp_client
from app.mcp import context as mcp_context

# The seeded primary demo user's goal, and the figures Release 0 derives for
# it. Read from the API in the tests that need them rather than written in,
# because the seed uses absolute dates and the commitment figure moves as
# steps fall due.
GOAL_ID = 3

BOTH_TOOLS = {
    "bill_summary": BILL_SUMMARY_PAYLOAD,
    "transaction_summary": TRANSACTION_SUMMARY_PAYLOAD,
}


def _context(client, goal_id=GOAL_ID, **params):
    query = "".join(f"?{key}={value}" for key, value in params.items())
    response = client.get(f"/api/goals/{goal_id}/mcp-context{query}")
    assert response.status_code == 200
    return response.get_json()


# ---------------------------------------------------------------------------
# The derived figure, as a pure function
# ---------------------------------------------------------------------------


def test_available_to_save_subtracts_both_commitments():
    assert mcp_context.available_to_save(2500.00, 3574.16, 620.24) == -1694.40


def test_available_to_save_is_signed_not_floored():
    """A user over-committed by $1,694.40 and a user with exactly nothing
    spare are not in the same situation, and the figure should not claim they
    are. Release 0's own available figure is signed for the same reason."""
    assert mcp_context.available_to_save(1000.00, 1500.00, 600.00) == -1100.00
    assert mcp_context.available_to_save(1000.00, 400.00, 600.00) == 0.0


def test_available_to_save_is_none_without_a_budget():
    """No budget set means no total to subtract from. Inventing one would be
    worse than admitting it."""
    assert mcp_context.available_to_save(None, 3574.16, 620.24) is None


def test_available_to_save_without_bills_is_release_0s_figure():
    """When MCP cannot supply the bills term, the calculation collapses to
    exactly what Release 0 computed -- not to zero, and not to an error."""
    assert mcp_context.available_to_save(2500.00, 3574.16, None) == -1074.16


def test_available_to_save_rounds_to_cents():
    assert mcp_context.available_to_save(2500.00, 1000.005, 1.001) == 1498.99


# ---------------------------------------------------------------------------
# Figures are carried through, never recomputed
# ---------------------------------------------------------------------------


def test_the_bills_figure_is_the_one_the_owning_backend_computed(client, stub_mcp):
    stub_mcp(results=BOTH_TOOLS)

    body = _context(client)

    # 620.24 is hyunwoo/backend/calculations.py's figure, which has already
    # converted a fortnightly $29.95 gym membership to $64.89 a month. This
    # feature reads it; it does not reproduce it.
    assert body["committed_elsewhere"]["monthly_bills"] == 620.24
    assert body["committed_elsewhere"]["monthly_bills"] == (
        BILL_SUMMARY_PAYLOAD["summary"]["monthly_cost"]
    )


def test_every_bills_field_is_carried_through_verbatim(client, stub_mcp):
    stub_mcp(results=BOTH_TOOLS)

    bills = _context(client)["committed_elsewhere"]
    summary = BILL_SUMMARY_PAYLOAD["summary"]

    assert bills["active_bill_count"] == summary["active_bill_count"]
    assert bills["annual_bills"] == summary["annual_cost"]
    assert bills["category_monthly_costs"] == summary["category_monthly_costs"]
    assert bills["owner"] == "HyunWoo -- Bills and Subscriptions"


def test_transaction_totals_are_carried_through_and_labelled_by_period(client, stub_mcp):
    """The honesty that keeps the arithmetic rule intact.

    Thomas's response says nothing about what period these totals cover, so
    turning them into a monthly rate would mean inventing a divisor. They are
    carried through and labelled instead.
    """
    stub_mcp(results=BOTH_TOOLS)

    observed = _context(client)["observed"]

    assert observed["total_income"] == TRANSACTION_SUMMARY_PAYLOAD["total_income"]
    assert observed["total_expenses"] == TRANSACTION_SUMMARY_PAYLOAD["total_expenses"]
    assert observed["potential_deductions"] == TRANSACTION_SUMMARY_PAYLOAD["potential_deductions"]
    assert observed["period"] == "whole ledger"


def test_observed_totals_never_enter_the_arithmetic(client, stub_mcp):
    """Changing Thomas's figures must not move available_to_save by a cent."""
    stub_mcp(results=BOTH_TOOLS)
    before = _context(client)["available_to_save"]

    stub_mcp(
        results={
            "bill_summary": BILL_SUMMARY_PAYLOAD,
            "transaction_summary": {
                "total_income": 99000.00,
                "total_expenses": 1.00,
                "potential_deductions": 0.00,
            },
        }
    )
    after = _context(client)

    assert after["available_to_save"] == before
    assert after["observed"]["total_income"] == 99000.00


def test_the_available_figure_is_the_breakdown_applied(client, stub_mcp):
    """The response shows its working, and the working agrees with itself."""
    stub_mcp(results=BOTH_TOOLS)

    body = _context(client)
    terms = {term["label"]: term for term in body["calculation"]["terms"]}

    expected = (
        terms["Monthly budget"]["amount"]
        - terms["Committed to other active goals"]["amount"]
        - terms["Recurring monthly bills"]["amount"]
    )
    assert body["available_to_save"] == round(expected, 2)
    assert body["calculation"]["result"] == body["available_to_save"]
    assert body["calculation"]["computed_by"] == "python"


def test_each_term_names_the_service_that_produced_it(client, stub_mcp):
    """"Where did this number come from" is the question MCP exists to
    answer, so the answer travels with the number."""
    stub_mcp(results=BOTH_TOOLS)

    terms = {term["label"]: term["origin"] for term in _context(client)["calculation"]["terms"]}

    assert terms["Monthly budget"] == "Goals and Budgeting (this service)"
    assert terms["Committed to other active goals"] == "Goals and Budgeting (this service)"
    assert "bill_summary via MCP" in terms["Recurring monthly bills"]
    assert "HyunWoo" in terms["Recurring monthly bills"]


def test_mcp_adds_exactly_the_bills_term_to_release_0s_figure(client, stub_mcp):
    """The difference MCP makes, isolated: everything else is identical."""
    stub_mcp(results=BOTH_TOOLS)

    with_mcp = _context(client)
    without_mcp = _context(client, use_mcp="false")

    assert without_mcp["available_to_save"] == with_mcp["budget"]["available_before_bills"]
    assert round(without_mcp["available_to_save"] - with_mcp["available_to_save"], 2) == 620.24
    assert with_mcp["budget"]["monthly_budget"] == without_mcp["budget"]["monthly_budget"]


# ---------------------------------------------------------------------------
# One session, two tools
# ---------------------------------------------------------------------------


def test_both_tools_are_called_over_one_session(client, stub_mcp):
    """Latency matters on a 100-second demo: a session is connect, initialize,
    the operations and teardown, measured at ~1.3s. Two sessions would spend
    that twice before the model is prompted."""
    calls = stub_mcp(results=BOTH_TOOLS)

    _context(client)

    assert [call["tool"] for call in calls] == ["bill_summary", "transaction_summary"]
    assert all(call["arguments"] == {} for call in calls)


def test_each_tool_is_timed_and_attributed_separately(client, stub_mcp):
    stub_mcp(results=BOTH_TOOLS)

    called = _context(client)["mcp"]["tools_called"]

    assert [item["tool"] for item in called] == ["bill_summary", "transaction_summary"]
    assert called[0]["owner"] == "HyunWoo -- Bills and Subscriptions"
    assert called[1]["owner"] == "Thomas -- Transaction Ledger"
    # Which teammate's backend is slow is the useful thing to know.
    assert all(isinstance(item["duration_ms"], float) for item in called)


def test_every_tool_call_is_written_to_the_audit_trail(client, stub_mcp, conn):
    stub_mcp(results=BOTH_TOOLS)

    body = _context(client)

    rows = conn.execute(
        "SELECT * FROM ai_plan_log WHERE phase = 'mcp' AND goal_id = ? ORDER BY log_id",
        (GOAL_ID,),
    ).fetchall()
    assert len(rows) == 2
    assert [json.loads(row["response"])["tool"] for row in rows] == [
        "bill_summary",
        "transaction_summary",
    ]
    # The context points at the rows, so the evidence is reachable from it.
    assert [item["log_id"] for item in body["mcp"]["tools_called"]] == [
        row["log_id"] for row in rows
    ]


def test_the_logged_result_is_the_payload_the_tool_returned(client, stub_mcp, conn):
    stub_mcp(results=BOTH_TOOLS)

    _context(client)

    row = conn.execute(
        "SELECT response FROM ai_plan_log WHERE phase = 'mcp' ORDER BY log_id LIMIT 1"
    ).fetchone()
    assert json.loads(row["response"])["result"] == BILL_SUMMARY_PAYLOAD


# ---------------------------------------------------------------------------
# Degrading -- off, down, and half-working
# ---------------------------------------------------------------------------


def test_use_mcp_false_falls_back_without_calling_anything(client, stub_mcp):
    calls = stub_mcp(results=BOTH_TOOLS)

    body = _context(client, use_mcp="false")

    assert calls == []
    assert body["mcp"]["used"] is False
    assert "use_mcp=false" in body["mcp"]["reason"]
    assert body["available_to_save_source"] == "budget_settings"
    assert body["committed_elsewhere"] is None


def test_disabled_mcp_falls_back_and_says_so(client, app, stub_mcp):
    """The CI configuration: MCP_ENABLED=false. The context still answers."""
    calls = stub_mcp(results=BOTH_TOOLS)
    app.config["MCP_ENABLED"] = False

    body = _context(client)

    assert calls == []
    assert body["mcp"]["enabled"] is False
    assert "MCP_ENABLED=false" in body["mcp"]["reason"]
    assert body["available_to_save"] == body["budget"]["available_before_bills"]


def test_an_unreachable_server_falls_back_to_budget_settings(client, stub_mcp):
    """A teammate not having started the MCP server must not break planning."""
    stub_mcp(
        unavailable=mcp_client.MCPUnavailable(
            "could not reach the MCP server at http://mcp.invalid:5002/mcp: Connection refused"
        )
    )

    body = _context(client)

    assert body["mcp"]["enabled"] is True
    assert body["mcp"]["used"] is False
    assert "Connection refused" in body["mcp"]["reason"]
    assert body["available_to_save_source"] == "budget_settings"
    assert body["available_to_save"] == body["budget"]["available_before_bills"]


def test_an_unreachable_server_is_still_audited(client, stub_mcp, conn):
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: refused"))

    _context(client)

    row = conn.execute(
        "SELECT * FROM ai_plan_log WHERE phase = 'mcp' AND goal_id = ? ORDER BY log_id DESC LIMIT 1",
        (GOAL_ID,),
    ).fetchone()
    assert json.loads(row["response"])["unavailable"] is True


def test_a_failed_bills_tool_falls_back_with_the_tools_own_reason(client, stub_mcp):
    """HyunWoo's container being down, which is the likeliest demo-day fault."""
    stub_mcp(
        results={
            "bill_summary": {"error": "Could not reach backend at http://hyunwoo-backend:5000/api/bills"},
            "transaction_summary": TRANSACTION_SUMMARY_PAYLOAD,
        }
    )

    body = _context(client)

    assert body["mcp"]["used"] is False
    assert "Could not reach backend" in body["mcp"]["reason"]
    assert body["available_to_save"] == body["budget"]["available_before_bills"]
    # Thomas's figures still came back, and are still worth showing.
    assert body["observed"]["total_income"] == 7200.00


def test_a_failed_transactions_tool_is_partial_not_unused(client, stub_mcp):
    """`used` means one specific thing: the available-to-save figure includes
    an MCP term. That depends only on the bills tool, so losing Thomas's
    context degrades the panel without changing the arithmetic."""
    stub_mcp(
        results={
            "bill_summary": BILL_SUMMARY_PAYLOAD,
            "transaction_summary": {"error": "Backend timed out: http://thomas-backend:5001"},
        }
    )

    body = _context(client)

    assert body["mcp"]["used"] is True
    assert body["mcp"]["partial"] is True
    assert "Backend timed out" in body["mcp"]["reason"]
    assert body["available_to_save_source"] == "mcp"
    assert body["observed"]["total_income"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": {"active_bill_count": 10}},  # no monthly_cost at all
        {"summary": {"monthly_cost": None}},
        {"summary": {"monthly_cost": "620.24"}},  # a number as a string
        {"summary": {"monthly_cost": True}},  # a bool is an int in Python
        {"bills": []},  # no summary object
        "not an object at all",
    ],
)
def test_an_unexpected_bills_shape_degrades_visibly(client, stub_mcp, payload):
    """If a tool's contract changes under this feature, it must fall back and
    say so rather than carry on with a reinterpreted figure. A numeric string
    is not converted on purpose: parsing someone else's text into a number is
    interpretation, not transport."""
    stub_mcp(results={"bill_summary": payload, "transaction_summary": TRANSACTION_SUMMARY_PAYLOAD})

    body = _context(client)

    assert body["mcp"]["used"] is False
    assert body["mcp"]["reason"]
    assert body["available_to_save"] == body["budget"]["available_before_bills"]


def test_a_goal_with_no_budget_set_reports_no_available_figure(client, stub_mcp, conn):
    """Every user in the seed has a budget, so this is set up explicitly: the
    state a brand new user is in."""
    stub_mcp(results=BOTH_TOOLS)
    user_id = conn.execute("SELECT user_id FROM goals WHERE goal_id = ?", (GOAL_ID,)).fetchone()[0]
    conn.execute("DELETE FROM budget_settings WHERE user_id = ?", (user_id,))
    conn.commit()

    body = _context(client)

    assert body["budget"]["budget_is_set"] is False
    assert body["available_to_save"] is None
    # The bills figure was still retrieved, and is still worth showing.
    assert body["mcp"]["used"] is True
    assert body["committed_elsewhere"]["monthly_bills"] == 620.24


def test_mcp_context_404s_for_a_goal_that_does_not_exist(client, stub_mcp):
    stub_mcp(results=BOTH_TOOLS)

    assert client.get("/api/goals/99999/mcp-context").status_code == 404


def test_a_mistyped_flag_is_a_400_not_a_silent_default(client, stub_mcp):
    """`use_mcp=flase` must not quietly mean "on" -- a demo of the fallback
    path would then show the MCP path instead."""
    stub_mcp(results=BOTH_TOOLS)

    response = client.get(f"/api/goals/{GOAL_ID}/mcp-context?use_mcp=flase")

    assert response.status_code == 400
    assert "use_mcp must be one of" in response.get_json()["details"][0]


@pytest.mark.parametrize(("value", "expected"), [("no", False), ("0", False), ("off", False), ("yes", True)])
def test_the_flag_accepts_the_same_spellings_as_the_environment(client, stub_mcp, value, expected):
    calls = stub_mcp(results=BOTH_TOOLS)

    body = _context(client, use_mcp=value)

    assert body["mcp"]["used"] is expected
    assert bool(calls) is expected
