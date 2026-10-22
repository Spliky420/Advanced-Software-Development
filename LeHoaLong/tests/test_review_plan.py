"""Release 2: the multi-agent plan review, end to end against the real server in stub mode.

    POST /api/goals/<id>/review-plan            start
    GET  /api/agents/workflow/<run_id>          poll
    POST /api/agents/workflow/<run_id>/review   decide
    GET  /api/agents/health                     status light
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

GOAL = 3  # New Laptop: one completed step and five pending, target 2026-12-15
EMPTY_GOAL = 7  # Masters Tuition Deposit: no steps yet
FUNDED_GOAL = 8  # achieved -- nothing left to plan


def _steps(conn, goal_id):
    return [
        dict(row)
        for row in conn.execute(
            "SELECT step_order, step_amount, due_date, status, description, source "
            "FROM goal_steps WHERE goal_id = ? ORDER BY step_order",
            (goal_id,),
        )
    ]


def _agent_rows(conn):
    return [
        {**dict(row), "body": json.loads(row["response"])}
        for row in conn.execute("SELECT * FROM ai_plan_log WHERE phase = 'agent' ORDER BY log_id")
    ]


def _start(client, multi_agent, goal_id=GOAL):
    response = client.post(f"/api/goals/{goal_id}/review-plan", json={"use_mcp": False})
    assert response.status_code == 202, response.get_json()
    run_id = response.get_json()["review"]["run_id"]
    multi_agent.wait_for(run_id, "awaiting_human")
    return run_id, response.get_json()


def _decide(client, run_id, **body):
    return client.post(f"/api/agents/workflow/{run_id}/review", json=body)


# ---------------------------------------------------------------------------
# Degrading: disabled, unreachable, erroring
# ---------------------------------------------------------------------------


def test_disabled_returns_the_python_proposal_and_says_so(client, conn):
    before = _steps(conn, GOAL)
    response = client.post(f"/api/goals/{GOAL}/review-plan")
    assert response.status_code == 200
    body = response.get_json()

    review = body["review"]
    assert review["status"] == "unavailable"
    assert review["run_id"] is None
    assert "MULTI_AGENT_ENABLED=false" in review["reason"]
    assert review["multi_agent"] == {"enabled": False, "used": False, "server_url": "http://multi-agent.invalid:5004"}
    assert review["fallback"]["path"] == f"/api/goals/{GOAL}/plan"
    assert body["proposal"]["steps"], "the Python proposal is still returned"

    # Degrading never writes a plan the person did not see reviewed.
    assert _steps(conn, GOAL) == before
    (row,) = _agent_rows(conn)
    assert row["model_name"] == "python"
    assert row["body"]["event"] == "unavailable"


def test_unreachable_server_degrades_with_its_reason(client, conn, multi_agent):
    multi_agent.unavailable()
    before = _steps(conn, GOAL)
    body = client.post(f"/api/goals/{GOAL}/review-plan").get_json()
    assert body["review"]["status"] == "unavailable"
    assert "could not reach the multi-agent server" in body["review"]["reason"]
    assert body["review"]["multi_agent"]["enabled"] is True
    assert _steps(conn, GOAL) == before


def test_a_server_answer_outside_the_contract_degrades_too(client, multi_agent, monkeypatch):
    from app.multiagent import client as ma_client

    monkeypatch.setattr(ma_client, "_request", lambda *a, **k: (500, {"error": "internal_error", "detail": "boom"}))
    body = client.post(f"/api/goals/{GOAL}/review-plan").get_json()
    assert body["review"]["status"] == "unavailable"
    assert "HTTP 500 -- boom" in body["review"]["reason"]


# ---------------------------------------------------------------------------
# Starting a review
# ---------------------------------------------------------------------------


def test_start_returns_202_with_a_run_id_and_sends_an_async_run(client, conn, multi_agent):
    response = client.post(f"/api/goals/{GOAL}/review-plan", json={"use_mcp": False})
    assert response.status_code == 202
    body = response.get_json()
    run_id = body["review"]["run_id"]
    assert body["review"]["status"] == "started"
    assert body["review"]["poll_path"] == f"/api/agents/workflow/{run_id}"
    assert body["review"]["workflow"]["status"] == "planning"

    (sent,) = [call for call in multi_agent.calls if call["path"] == "/workflow"]
    assert sent["method"] == "POST"
    assert sent["payload"]["async"] is True
    assert sent["payload"]["caller"] == "lehoalong-goals-budgeting"
    assert sent["payload"]["evidence"] == body["evidence"]

    (row,) = _agent_rows(conn)
    assert row["model_name"] == "multi-agent"
    assert row["body"]["event"] == "proposed"
    assert row["body"]["run_id"] == run_id
    # The prompt column is exactly what was sent, so the row is the evidence.
    assert json.loads(row["prompt"]) == {"task": sent["payload"]["task"], "evidence": sent["payload"]["evidence"]}


def test_starting_a_review_writes_nothing_to_the_goal(client, conn, multi_agent):
    before = _steps(conn, GOAL)
    _start(client, multi_agent)
    assert _steps(conn, GOAL) == before


def test_the_proposal_is_pythons_schedule_and_closes_the_gap(client, conn, multi_agent):
    _, body = _start(client, multi_agent)
    proposal = body["proposal"]
    saved = conn.execute("SELECT SUM(amount) FROM contributions WHERE goal_id = ?", (GOAL,)).fetchone()[0]
    target = conn.execute("SELECT target_amount FROM goals WHERE goal_id = ?", (GOAL,)).fetchone()[0]

    assert proposal["total_scheduled"] == pytest.approx(target - saved, abs=0.01)
    assert proposal["steps"][-1]["due_date"] == "2026-12-15"
    # Numbered after the one completed step, which the plan leaves alone.
    assert proposal["steps"][0]["step_order"] == 2


def test_every_figure_in_the_evidence_is_one_python_computed(client, multi_agent):
    """The agents are never handed a number this backend did not calculate."""
    _, body = _start(client, multi_agent)
    evidence, proposal = body["evidence"], body["proposal"]

    python_figures = {
        proposal["monthly_amount"], proposal["final_amount"], proposal["total_scheduled"],
        *(step["step_amount"] for step in proposal["steps"]),
        *(step["step_order"] for step in proposal["steps"]),
    }
    goal = evidence["goal"]
    python_figures |= {goal["target_amount"], goal["saved_to_date"], goal["remaining_amount"], goal["percent_complete"]}
    python_figures |= {value for value in evidence["progress"].values() if isinstance(value, (int, float))}
    python_figures |= {value for value in evidence["budget"].values() if isinstance(value, (int, float))}
    python_figures.add(proposal["step_count"])

    numbers = [
        float(value)
        for value in re.findall(r"(?<![\w.-])-?\d+(?:\.\d+)?(?![\w-])", json.dumps(evidence))
    ]
    assert numbers
    for number in numbers:
        figures = (float(figure) for figure in python_figures if not isinstance(figure, bool))
        assert any(abs(number - figure) < 1e-9 for figure in figures), number
    assert "do not recalculate" in body["task"]


@pytest.mark.parametrize("goal_id, status", [(99999, 404), (FUNDED_GOAL, 400)])
def test_goals_that_cannot_be_planned_are_refused_before_the_server(client, multi_agent, goal_id, status):
    assert client.post(f"/api/goals/{goal_id}/review-plan").status_code == status
    assert multi_agent.calls == []


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def test_poll_shows_the_agents_output_and_whether_it_can_be_applied(client, multi_agent):
    run_id, start = _start(client, multi_agent)
    body = client.get(f"/api/agents/workflow/{run_id}").get_json()

    assert body["workflow"]["status"] == "awaiting_human"
    assert body["workflow"]["plan"] and body["workflow"]["work"]
    assert body["workflow"]["stub"] is True
    assert body["proposal"] == start["proposal"]
    assert body["stale"] == {"is_stale": False, "reasons": []}
    assert body["can_decide"] is True and body["can_apply"] is True
    assert body["decision"] is None


def test_poll_shows_progress_while_the_agents_run(client, multi_agent):
    released = multi_agent.hold_worker()
    run_id = client.post(f"/api/goals/{GOAL}/review-plan").get_json()["review"]["run_id"]
    multi_agent.wait_for(run_id, "working")

    body = client.get(f"/api/agents/workflow/{run_id}").get_json()
    assert body["workflow"]["status"] == "working"
    assert body["workflow"]["plan"], "the Planner's output is visible before the Worker finishes"
    assert body["can_decide"] is False
    released.set()


def test_a_run_this_backend_did_not_start_is_404(client, multi_agent):
    """Not a general proxy: a run another feature started is not readable here."""
    other = multi_agent.server.post("/workflow", json={"task": "t", "evidence": {}, "caller": "someone-else"})
    run_id = other.get_json()["run_id"]
    response = client.get(f"/api/agents/workflow/{run_id}")
    assert response.status_code == 404
    assert response.get_json()["error"].startswith("no plan review with run id")


def test_a_server_that_lost_its_history_is_404_saying_so(client, multi_agent):
    run_id, _ = _start(client, multi_agent)
    multi_agent.store._runs.clear()
    response = client.get(f"/api/agents/workflow/{run_id}")
    assert response.status_code == 404
    assert "history was probably reset" in response.get_json()["error"]


def test_polling_an_unreachable_server_is_503(client, multi_agent):
    run_id, _ = _start(client, multi_agent)
    multi_agent.unavailable()
    assert client.get(f"/api/agents/workflow/{run_id}").status_code == 503


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


def test_approve_applies_exactly_the_frozen_proposal(client, conn, multi_agent):
    run_id, start = _start(client, multi_agent)
    completed_before = [step for step in _steps(conn, GOAL) if step["status"] != "pending"]

    response = _decide(client, run_id, decision="approve")
    assert response.status_code == 200
    body = response.get_json()
    assert body["applied"] is True
    assert body["steps_applied"] == len(start["proposal"]["steps"])
    assert body["workflow_status"] == "complete"

    after = _steps(conn, GOAL)
    assert [step for step in after if step["status"] != "pending"] == completed_before
    pending = [step for step in after if step["status"] == "pending"]
    assert [(s["step_order"], s["step_amount"], s["due_date"], s["description"]) for s in pending] == [
        (s["step_order"], s["step_amount"], s["due_date"], s["description"]) for s in start["proposal"]["steps"]
    ]

    decided = _agent_rows(conn)[-1]
    assert decided["model_name"] == "human"
    assert decided["body"]["decision"] == "approve"
    # The agents' output the person decided on is kept with the decision.
    assert decided["body"]["workflow"]["work"]
    assert multi_agent.store.get(run_id)["human_review"]["decision"] == "approve"


def test_correct_applies_and_records_the_corrected_rationale(client, conn, multi_agent):
    run_id, _ = _start(client, multi_agent)
    response = _decide(client, run_id, decision="correct", corrected="Fine, but pay the first one from the bonus.")
    assert response.status_code == 200
    assert response.get_json()["applied"] is True
    assert response.get_json()["rationale"] == "Fine, but pay the first one from the bonus."

    decided = _agent_rows(conn)[-1]
    assert "pay the first one from the bonus" in decided["prompt"]
    assert decided["body"]["corrected"] == "Fine, but pay the first one from the bonus."
    assert multi_agent.store.get(run_id)["human_review"]["corrected"] == "Fine, but pay the first one from the bonus."


@pytest.mark.parametrize("decision, extra", [("partial", {"note": "the schedule, not the risks"}), ("reject", {})])
def test_partial_and_reject_apply_nothing(client, conn, multi_agent, decision, extra):
    run_id, _ = _start(client, multi_agent)
    before = _steps(conn, GOAL)
    body = _decide(client, run_id, decision=decision, **extra).get_json()
    assert body["applied"] is False and body["steps_applied"] == 0 and body["goal"] is None
    assert _steps(conn, GOAL) == before
    assert _agent_rows(conn)[-1]["body"]["decision"] == decision


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({}, "decision is required"),
        ({"decision": "maybe"}, "decision must be one of"),
        ({"decision": "correct"}, "corrected is required"),
        ({"decision": "partial"}, "note is required"),
        ({"decision": "approve", "corrected": "x"}, "only accepted with decision 'correct'"),
        ({"decision": "approve", "note": 5}, "note must be a string"),
    ],
)
def test_bad_decisions_are_400_and_never_reach_the_server(client, multi_agent, body, fragment):
    run_id, _ = _start(client, multi_agent)
    sent_before = len(multi_agent.calls)
    response = _decide(client, run_id, **body)
    assert response.status_code == 400
    assert any(fragment in detail for detail in response.get_json()["details"])
    assert len(multi_agent.calls) == sent_before


def test_a_second_decision_is_409(client, multi_agent):
    run_id, _ = _start(client, multi_agent)
    assert _decide(client, run_id, decision="reject").status_code == 200
    second = _decide(client, run_id, decision="approve")
    assert second.status_code == 409
    assert "already decided: reject" in second.get_json()["error"]


def test_a_decided_review_is_served_from_the_log_even_if_the_server_is_gone(client, multi_agent):
    run_id, _ = _start(client, multi_agent)
    _decide(client, run_id, decision="approve")
    multi_agent.unavailable()
    body = client.get(f"/api/agents/workflow/{run_id}").get_json()
    assert body["decision"]["decision"] == "approve"
    assert body["can_decide"] is False


def test_a_decided_review_reads_as_complete_matching_the_server(client, multi_agent):
    """Found driving the UI: the stored run was the pre-decision one, so the
    stage tracker went on showing "your turn" after the person had decided."""
    run_id, _ = _start(client, multi_agent)
    _decide(client, run_id, decision="partial", note="the schedule only")
    workflow = client.get(f"/api/agents/workflow/{run_id}").get_json()["workflow"]
    server = multi_agent.store.get(run_id)

    assert workflow["status"] == "complete" == server["status"]
    for key in ("decision", "note", "corrected", "reviewer"):
        assert workflow["human_review"][key] == server["human_review"][key], key


def test_a_contribution_after_the_review_started_makes_approve_409(client, conn, multi_agent):
    run_id, _ = _start(client, multi_agent)
    client.post(f"/api/goals/{GOAL}/contributions", json={"amount": 50, "contribution_date": "2026-10-01"})
    before = _steps(conn, GOAL)

    poll = client.get(f"/api/agents/workflow/{run_id}").get_json()
    assert poll["stale"]["is_stale"] is True and poll["can_apply"] is False and poll["can_decide"] is True

    response = _decide(client, run_id, decision="approve")
    assert response.status_code == 409
    assert any("amount saved" in reason for reason in response.get_json()["details"])
    assert _steps(conn, GOAL) == before
    # The server was not told, so the run can still be rejected.
    assert multi_agent.store.get(run_id)["status"] == "awaiting_human"
    assert _decide(client, run_id, decision="reject").status_code == 200


def test_a_first_instalment_now_in_the_past_makes_approve_409(client, multi_agent, monkeypatch):
    from app.services import dates

    run_id, start = _start(client, multi_agent)
    first_due = date.fromisoformat(start["proposal"]["first_due_date"])
    monkeypatch.setattr(dates, "today", lambda: first_due)
    response = _decide(client, run_id, decision="approve")
    assert response.status_code == 409
    assert any("no longer in the future" in reason for reason in response.get_json()["details"])


def test_a_deleted_goal_can_still_be_rejected(client, conn, multi_agent):
    run_id, _ = _start(client, multi_agent)
    assert client.delete(f"/api/goals/{GOAL}").status_code in (200, 204)

    approve = _decide(client, run_id, decision="approve")
    assert approve.status_code == 409
    assert any("deleted" in reason for reason in approve.get_json()["details"])

    assert _decide(client, run_id, decision="reject").status_code == 200
    decided = _agent_rows(conn)[-1]
    assert decided["goal_id"] is None and decided["body"]["goal_id"] == GOAL


def test_deciding_while_the_agents_are_still_running_is_409(client, multi_agent):
    released = multi_agent.hold_worker()
    run_id = client.post(f"/api/goals/{GOAL}/review-plan").get_json()["review"]["run_id"]
    multi_agent.wait_for(run_id, "working")
    response = _decide(client, run_id, decision="approve")
    assert response.status_code == 409
    assert "working" in response.get_json()["error"]
    released.set()


def test_a_failed_run_cannot_be_decided_and_says_why(client, multi_agent, monkeypatch):
    import agents as ma_agents

    def down(*args, **kwargs):
        raise ma_agents.AgentUnavailable("Ollama timed out after 55s")

    monkeypatch.setattr(ma_agents, "review", down)
    run_id = client.post(f"/api/goals/{GOAL}/review-plan").get_json()["review"]["run_id"]
    multi_agent.wait_for(run_id, "failed")
    response = _decide(client, run_id, decision="reject")
    assert response.status_code == 409
    assert "review phase -- Ollama timed out" in response.get_json()["error"]


def test_a_server_refusal_rolls_the_plan_back(client, conn, multi_agent):
    """The plan is written, the server says no, and the goal is exactly as it was."""
    run_id, _ = _start(client, multi_agent)
    # Someone decides on the server directly, between our checks and our call.
    from app.multiagent import client as ma_client

    real_get = ma_client.get_run

    def get_then_race(run):
        body = real_get(run)
        multi_agent.server.post(f"/workflow/{run}/review", json={"decision": "reject"})
        return body

    before = _steps(conn, GOAL)
    rows_before = len(_agent_rows(conn))
    import app.services.review as review_service

    review_service.client.get_run = get_then_race
    try:
        response = _decide(client, run_id, decision="approve")
    finally:
        review_service.client.get_run = real_get
    assert response.status_code == 409
    assert "refused the decision" in response.get_json()["error"]
    assert _steps(conn, GOAL) == before
    assert len(_agent_rows(conn)) == rows_before


def test_an_unreachable_server_at_decision_time_is_503_and_changes_nothing(client, conn, multi_agent, monkeypatch):
    run_id, _ = _start(client, multi_agent)
    from app.multiagent import client as ma_client

    def unreachable(*args, **kwargs):
        raise ma_client.MultiAgentUnavailable("could not reach the multi-agent server")

    monkeypatch.setattr(ma_client, "decide", unreachable)
    before, rows_before = _steps(conn, GOAL), len(_agent_rows(conn))
    assert _decide(client, run_id, decision="approve").status_code == 503
    assert _steps(conn, GOAL) == before
    assert len(_agent_rows(conn)) == rows_before


def test_deciding_while_switched_off_is_503(client, app, multi_agent):
    run_id, _ = _start(client, multi_agent)
    app.config["MULTI_AGENT_ENABLED"] = False
    response = _decide(client, run_id, decision="approve")
    assert response.status_code == 503
    assert "MULTI_AGENT_ENABLED=false" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_when_disabled(client):
    body = client.get("/api/agents/health").get_json()
    assert body["enabled"] is False and body["reachable"] is False
    assert "MULTI_AGENT_ENABLED=false" in body["detail"]


def test_health_when_reachable(client, multi_agent):
    body = client.get("/api/agents/health").get_json()
    assert body["enabled"] is True and body["reachable"] is True
    assert body["stub"] is True


def test_health_when_unreachable_is_still_200(client, multi_agent):
    multi_agent.unavailable()
    response = client.get("/api/agents/health")
    assert response.status_code == 200
    assert response.get_json()["reachable"] is False


# ---------------------------------------------------------------------------
# AI-Mode switched off
# ---------------------------------------------------------------------------


def test_ai_mode_off_plans_without_calling_the_model(client, app, conn, fake_model):
    calls = fake_model()
    app.config["AI_MODE_ENABLED"] = False
    response = client.post(f"/api/goals/{EMPTY_GOAL}/plan")
    assert response.status_code == 201
    plan = response.get_json()["plan"]
    assert plan["fallback"] is True and plan["llm_called"] is False
    assert "AI_MODE_ENABLED=false" in plan["fallback_reason"]
    assert calls == []

    (row,) = conn.execute(
        "SELECT model_name, prompt FROM ai_plan_log WHERE phase = 'plan' AND goal_id = ?", (EMPTY_GOAL,)
    )
    assert row["model_name"] == "python"
    assert row["prompt"].startswith("FALLBACK: AI-Mode is disabled")


def test_ai_mode_off_health_does_not_probe_ollama(client, app, stub_ollama):
    app.config["AI_MODE_ENABLED"] = False
    body = client.get("/health").get_json()
    assert body["ollama"]["enabled"] is False
    assert body["ollama"]["reachable"] is None
