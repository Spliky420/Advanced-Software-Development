"""Planning and replanning with cross-feature context.

The claim Release 1 makes about planning is narrow and worth stating exactly,
because it is easy to overclaim: **MCP changes the verdict on a plan, not the
arithmetic of it.**

The instalment amount stays `remaining / months_remaining`. Re-cutting
instalments to fit the available-to-save figure would silently miss the target
date the user asked for, which is a worse answer than an honest "this is a
stretch". So these tests assert that the schedule is byte-identical with MCP on
and off, while the affordability verdict, the prompt's wording and the response
all change.

The second claim is that none of it is load-bearing. With MCP off, the server
down, or a teammate's backend down, planning still returns 201 with a real
plan built from budget settings alone, and says in `plan.mcp.reason` which
happened. Two independent fallbacks exist and must not be confused: the model
answering badly (`plan.fallback`) and MCP not contributing (`plan.mcp.used`).

No test here opens a socket. The model is the `fake_model` stand-in and the
MCP transport is `stub_mcp`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from conftest import BILL_SUMMARY_PAYLOAD, TRANSACTION_SUMMARY_PAYLOAD

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.mcp import client as mcp_client

GOAL_ID = 3
BILLS_MONTHLY = BILL_SUMMARY_PAYLOAD["summary"]["monthly_cost"]  # 620.24, HyunWoo's figure

BOTH_TOOLS = {
    "bill_summary": BILL_SUMMARY_PAYLOAD,
    "transaction_summary": TRANSACTION_SUMMARY_PAYLOAD,
}

MALFORMED = "not json at all"


def _plan(client, goal_id=GOAL_ID, **body):
    response = client.post(f"/api/goals/{goal_id}/plan", json=body or None)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _replan(client, goal_id=GOAL_ID, **body):
    response = client.post(f"/api/goals/{goal_id}/replan", json=body or None)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _pending(body):
    """The steps a plan just wrote.

    Planning replaces the pending steps and leaves completed ones alone --
    they are history. So `plan.total_scheduled` covers these, not every step
    on the goal. Goal 3 is seeded with one completed instalment, which is
    exactly why this distinction has to be respected here.
    """
    return [step for step in body["goal"]["steps"] if step["status"] == "pending"]


# ---------------------------------------------------------------------------
# Both paths produce a real plan
# ---------------------------------------------------------------------------


def test_planning_with_mcp_on_produces_a_valid_schedule(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    body = _plan(client)
    plan, steps = body["plan"], _pending(body)

    assert plan["step_count"] == len(steps) > 0
    assert plan["total_scheduled"] == round(sum(step["step_amount"] for step in steps), 2)
    # The instalments still sum to what is left to save, and still land on the
    # day the user asked for. MCP changed neither.
    assert plan["total_scheduled"] == body["goal"]["remaining_amount"]
    assert plan["final_due_date"] == body["goal"]["target_date"]
    assert plan["mcp"]["used"] is True


def test_planning_with_mcp_off_produces_a_valid_schedule(client, fake_model, stub_mcp):
    """Release 0 behaviour, unchanged and still reachable on demand."""
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    body = _plan(client, use_mcp=False)
    plan, steps = body["plan"], _pending(body)

    assert plan["step_count"] == len(steps) > 0
    assert plan["total_scheduled"] == round(sum(step["step_amount"] for step in steps), 2)
    assert plan["total_scheduled"] == body["goal"]["remaining_amount"]
    assert plan["mcp"]["used"] is False
    assert plan["mcp"]["source"] == "budget_settings"


def test_the_schedule_is_identical_with_mcp_on_and_off(client, fake_model, stub_mcp):
    """The architectural claim, as a test.

    MCP must not move a single instalment or due date. If it did, the plan
    would stop landing on the target date the user chose, and the feature
    would be quietly changing the answer rather than qualifying it.
    """
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    without = _plan(client, use_mcp=False)
    with_mcp = _plan(client, use_mcp=True)

    def schedule(body):
        return [(step["step_order"], step["step_amount"], step["due_date"]) for step in body["goal"]["steps"]]

    assert schedule(with_mcp) == schedule(without)
    assert with_mcp["plan"]["monthly_amount"] == without["plan"]["monthly_amount"]
    assert with_mcp["plan"]["total_scheduled"] == without["plan"]["total_scheduled"]


# ---------------------------------------------------------------------------
# What MCP does change
# ---------------------------------------------------------------------------


def test_the_available_figure_is_net_of_the_bills_mcp_reported(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    body = _plan(client)
    plan, context = body["plan"], body["mcp_context"]

    release_0_figure = context["budget"]["available_before_bills"]
    assert plan["available_monthly_budget"] == round(release_0_figure - BILLS_MONTHLY, 2)
    assert plan["mcp"]["available_to_save"] == plan["available_monthly_budget"]
    assert plan["mcp"]["source"] == "mcp"


def test_the_shortfall_is_computed_in_python(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    plan = _plan(client)["plan"]

    expected = round(max(plan["monthly_amount"] - plan["available_monthly_budget"], 0.0), 2)
    assert plan["shortfall"] == expected
    assert plan["within_budget"] is (plan["monthly_amount"] <= plan["available_monthly_budget"])


def test_the_seeded_user_is_over_committed_so_the_plan_is_a_stretch(client, fake_model, stub_mcp):
    """Not an incidental assertion -- it is the demo case.

    User 1's goals already require more per month than their budget before
    bills are counted at all, so adding HyunWoo's $620.24 makes the available
    figure more negative and the shortfall larger. This is the number on
    screen in the video.
    """
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    plan = _plan(client)["plan"]

    assert plan["available_monthly_budget"] < 0
    assert plan["within_budget"] is False
    assert plan["shortfall"] > plan["monthly_amount"]


def test_mcp_tightens_the_verdict_without_touching_the_amount(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    without = _plan(client, use_mcp=False)["plan"]
    with_mcp = _plan(client, use_mcp=True)["plan"]

    assert with_mcp["monthly_amount"] == without["monthly_amount"]
    assert with_mcp["available_monthly_budget"] < without["available_monthly_budget"]
    assert with_mcp["shortfall"] > without["shortfall"]


# ---------------------------------------------------------------------------
# What the model is told
# ---------------------------------------------------------------------------


def test_the_prompt_states_the_bills_figure_as_settled_fact(client, fake_model, stub_mcp):
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client)
    prompt = calls[0]["prompt"]

    assert "Already committed every month to recurring bills" in prompt
    assert f"{BILLS_MONTHLY:,.2f}" in prompt
    # Provenance travels with the figure, so the logged prompt is evidence of
    # where every number in it came from.
    assert "supplied by the household bills service, which calculated it" in prompt


def test_the_prompt_labels_the_ledger_totals_with_their_period(client, fake_model, stub_mcp):
    """The honesty that keeps the arithmetic rule intact.

    A small model told "income 7,200" would be entitled to read it as
    monthly. Thomas's backend does not say what period it covers, so the
    prompt says what it does know.
    """
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client)
    prompt = calls[0]["prompt"]

    assert "Observed over the whole transaction ledger (NOT a monthly figure)" in prompt
    assert f"{TRANSACTION_SUMMARY_PAYLOAD['total_income']:,.2f}" in prompt


def test_the_prompt_says_what_the_available_figure_accounts_for(client, fake_model, stub_mcp):
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    with_mcp = _plan(client)
    available = with_mcp["plan"]["available_monthly_budget"]

    prompt = calls[0]["prompt"]
    assert "other active goals and their recurring bills" in prompt
    assert f"{available:,.2f}" in prompt
    assert "stretch on the current budget" in prompt


def test_with_mcp_off_the_prompt_makes_no_mention_of_bills(client, fake_model, stub_mcp):
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client, use_mcp=False)
    prompt = calls[0]["prompt"]

    assert "recurring bills" not in prompt
    assert "transaction ledger" not in prompt
    assert "after this user's other active goals:" in prompt


def test_the_model_is_still_never_asked_for_a_number(client, fake_model, stub_mcp):
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client)

    assert "Never perform arithmetic" in calls[0]["system"]
    assert "description" in calls[0]["system"]
    assert "The schedule below is final and was calculated by the application." in calls[0]["prompt"]


def test_a_figure_the_model_returns_is_discarded_unread(client, fake_model, stub_mcp):
    """The strongest form of the arithmetic guarantee: a model-supplied amount
    cannot reach the plan, because nothing ever reads one."""
    stub_mcp(results=BOTH_TOOLS)

    def answer_with_invented_amounts(prompt):
        """A well-formed answer that also tries to set the amounts.

        The step_orders are read out of the prompt so the descriptions are
        usable -- otherwise this would exercise the malformed-response
        fallback instead of the point, which is that a usable answer's extra
        fields are never read.
        """
        orders = [int(found) for found in re.findall(r"step_order (\d+):", prompt)]
        return json.dumps(
            {
                "steps": [
                    {
                        "step_order": order,
                        "description": "Transfer the amount",
                        "step_amount": 999999.99,
                        "due_date": "2099-01-01",
                    }
                    for order in orders
                ]
            }
        )

    fake_model(answer_with_invented_amounts)

    body = _plan(client)

    amounts = [step["step_amount"] for step in _pending(body)]
    due_dates = [step["due_date"] for step in _pending(body)]
    assert 999999.99 not in amounts
    assert "2099-01-01" not in due_dates
    assert body["plan"]["fallback"] is False, "the answer was usable; this is not the fallback path"
    # The instalments are Python's, and they still sum to what is owed.
    assert body["plan"]["total_scheduled"] == round(sum(amounts), 2)
    assert body["plan"]["total_scheduled"] == body["goal"]["remaining_amount"]
    # The model's words were kept, though -- that is its job.
    assert any("Transfer the amount" in step["description"] for step in _pending(body))


# ---------------------------------------------------------------------------
# Falling back -- and the two fallbacks never being confused
# ---------------------------------------------------------------------------


def test_an_unreachable_mcp_server_still_returns_a_plan(client, fake_model, stub_mcp):
    """A teammate not having started the MCP server must not cost a plan."""
    fake_model()
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: Connection refused"))

    body = _plan(client)
    plan = body["plan"]

    assert plan["step_count"] > 0
    assert plan["mcp"]["used"] is False
    assert "Connection refused" in plan["mcp"]["reason"]
    assert plan["available_monthly_budget"] == body["mcp_context"]["budget"]["available_before_bills"]


def test_a_teammates_backend_being_down_still_returns_a_plan(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(
        results={
            "bill_summary": {"error": "Could not reach backend at http://hyunwoo-backend:5000/api/bills"},
            "transaction_summary": TRANSACTION_SUMMARY_PAYLOAD,
        }
    )

    plan = _plan(client)["plan"]

    assert plan["step_count"] > 0
    assert plan["mcp"]["used"] is False
    assert plan["mcp"]["tools_failed"] == ["bill_summary"]
    assert "Could not reach backend" in plan["mcp"]["reason"]


def test_disabled_mcp_reports_itself_as_configuration_not_failure(client, app, fake_model, stub_mcp):
    """The CI configuration. A marker should be able to tell "switched off"
    from "tried and failed" at a glance."""
    fake_model()
    stub_mcp(results=BOTH_TOOLS)
    app.config["MCP_ENABLED"] = False

    plan = _plan(client)["plan"]

    assert plan["mcp"]["enabled"] is False
    assert plan["mcp"]["used"] is False
    assert "MCP_ENABLED=false" in plan["mcp"]["reason"]
    assert plan["mcp"]["tools_called"] == []


def test_the_two_fallbacks_are_reported_separately(client, fake_model, stub_mcp):
    """A bad model answer and an absent MCP server are different failures with
    different fixes, and one must never be reported as the other."""
    fake_model(MALFORMED, MALFORMED)
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: refused"))

    plan = _plan(client)["plan"]

    # The model misbehaved: descriptions are Python's.
    assert plan["fallback"] is True
    assert plan["fallback_reason"]
    # MCP was absent: the budget figure is Release 0's.
    assert plan["mcp"]["used"] is False
    assert "could not reach" in plan["mcp"]["reason"]
    # And the plan is still real.
    assert plan["step_count"] > 0


def test_mcp_working_does_not_mask_ollama_being_down(client, fake_model, stub_mcp):
    """MCP succeeding must not turn an infrastructure 503 into a 201."""
    from app.ai.client import OllamaUnavailable

    stub_mcp(results=BOTH_TOOLS)
    fake_model(OllamaUnavailable("could not reach Ollama at http://ollama.invalid:11434"))

    response = client.post(f"/api/goals/{GOAL_ID}/plan")

    assert response.status_code == 503
    assert "Ollama" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# The flag, and the audit trail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sender", ["body", "query"])
def test_the_flag_is_accepted_in_a_body_or_a_query_string(client, fake_model, stub_mcp, sender):
    """The frontend sends JSON; the curl sequence in the docs uses a URL."""
    fake_model()
    calls = stub_mcp(results=BOTH_TOOLS)

    if sender == "body":
        response = client.post(f"/api/goals/{GOAL_ID}/plan", json={"use_mcp": False})
    else:
        response = client.post(f"/api/goals/{GOAL_ID}/plan?use_mcp=false")

    assert response.status_code == 201
    assert response.get_json()["plan"]["mcp"]["used"] is False
    assert calls == []


def test_planning_defaults_to_using_mcp(client, fake_model, stub_mcp):
    """Release 1 behaviour is what the feature does, not something a caller
    has to opt into."""
    fake_model()
    calls = stub_mcp(results=BOTH_TOOLS)

    plan = _plan(client)["plan"]

    assert plan["mcp"]["used"] is True
    assert [call["tool"] for call in calls] == ["bill_summary", "transaction_summary"]


def test_a_mistyped_flag_is_a_400(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    response = client.post(f"/api/goals/{GOAL_ID}/plan", json={"use_mcp": "flase"})

    assert response.status_code == 400
    assert "use_mcp must be one of" in response.get_json()["details"][0]


def test_every_tool_call_behind_a_plan_is_in_the_goals_audit_trail(client, fake_model, stub_mcp):
    """One request, one readable paper trail: two MCP rows and the model
    exchange, all attributed to this goal."""
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client)
    entries = client.get(f"/api/goals/{GOAL_ID}/ai-log").get_json()["entries"]

    mcp_entries = [entry for entry in entries if entry["phase"] == "mcp"]
    plan_entries = [entry for entry in entries if entry["phase"] == "plan"]

    assert len(mcp_entries) == 2
    assert {entry["model_name"] for entry in mcp_entries} == {"mcp"}
    assert plan_entries
    assert json.loads(mcp_entries[0]["response"])["tool"] in {"bill_summary", "transaction_summary"}


def test_the_logged_plan_prompt_carries_the_mcp_figures(client, fake_model, stub_mcp):
    """Why the audit trail needs no extra MCP annotation on the plan row: the
    prompt was logged verbatim, and the prompt states the figures and where
    they came from."""
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _plan(client)
    entries = client.get(f"/api/goals/{GOAL_ID}/ai-log").get_json()["entries"]

    logged_prompt = next(entry["prompt"] for entry in entries if entry["phase"] == "plan")
    assert f"{BILLS_MONTHLY:,.2f}" in logged_prompt
    assert "household bills service" in logged_prompt


# ---------------------------------------------------------------------------
# Replan behaves the same way
# ---------------------------------------------------------------------------


def test_replanning_with_mcp_uses_the_same_available_figure(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    body = _replan(client)
    adapt = body["adapt"]

    assert adapt["mcp"]["used"] is True
    assert adapt["available_monthly_budget"] == round(
        body["mcp_context"]["budget"]["available_before_bills"] - BILLS_MONTHLY, 2
    )
    assert adapt["steps_regenerated"] > 0


def test_replanning_reports_the_fallback_too(client, fake_model, stub_mcp):
    fake_model()
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: refused"))

    adapt = _replan(client)["adapt"]

    assert adapt["steps_regenerated"] > 0
    assert adapt["mcp"]["used"] is False
    assert "could not reach" in adapt["mcp"]["reason"]


def test_replanning_keeps_the_revised_amount_free_of_mcp(client, fake_model, stub_mcp):
    """Same claim as for plan: the re-cut instalment is remaining / months,
    and the available figure does not enter it."""
    fake_model()
    stub_mcp(results=BOTH_TOOLS)

    body = _replan(client)
    observe, adapt = body["observe"], body["adapt"]

    assert adapt["revised_monthly_amount"] == round(
        observe["remaining_amount"] / observe["months_remaining"], 2
    )


def test_the_adapt_prompt_states_the_budget_without_scolding(client, fake_model, stub_mcp):
    """Adapt reacts to what already happened, so the revised instalment is
    what it is. Telling the model the plan is unaffordable in the same breath
    as asking it not to scold would be a prompt arguing with itself -- so the
    figure is stated and the stretch sentence is left to the plan phase.
    """
    calls = fake_model()
    stub_mcp(results=BOTH_TOOLS)

    _replan(client)
    prompt = calls[0]["prompt"]

    assert "other active goals and their recurring bills" in prompt
    assert "stretch on the current budget" not in prompt
    assert "never scold" in calls[0]["system"]
