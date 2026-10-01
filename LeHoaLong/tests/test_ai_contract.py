"""The contract with the model: PLAN, ADAPT, parsing, retry and fallback.

Every model call is stubbed. The central claim these tests defend is that the
model cannot put a figure into the database: amounts and dates are computed in
Python, and the model is asked only for words. `test_the_model_cannot_change
_a_single_figure` is the one to read first.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from app.ai import client as ollama
from app.ai import parsing
from app.services import agent, dates
from conftest import echo_descriptions

AS_AT = date(2026, 9, 3)

MALFORMED = "I'm sorry, I can't help with that."
WRONG_SHAPE = '{"plan": "save more money"}'


# ---------------------------------------------------------------------------
# parsing -- reading what came back
# ---------------------------------------------------------------------------


def test_a_clean_response_is_parsed():
    raw = '{"steps": [{"step_order": 1, "description": "First transfer"}]}'

    assert parsing.parse_step_descriptions(raw, [1]) == {1: "First transfer"}


def test_json_wrapped_in_prose_or_a_fence_is_recovered():
    """A recoverable answer should not cost a retry."""
    raw = 'Sure! ```json\n{"steps": [{"step_order": 2, "description": "Second"}]}\n``` Hope that helps.'

    assert parsing.parse_step_descriptions(raw, [2]) == {2: "Second"}


def test_whitespace_in_a_description_is_normalised():
    raw = '{"steps": [{"step_order": 1, "description": "  keep   going\\n\\n"}]}'

    assert parsing.parse_step_descriptions(raw, [1]) == {1: "keep going"}


def test_an_over_long_description_is_truncated_not_rejected():
    raw = json.dumps({"steps": [{"step_order": 1, "description": "x" * 900}]})

    assert len(parsing.parse_step_descriptions(raw, [1])[1]) == parsing.MAX_DESCRIPTION_LENGTH


def test_a_partial_answer_keeps_what_is_usable():
    """Eight good descriptions out of twelve are worth more than none."""
    raw = json.dumps({"steps": [{"step_order": 1, "description": "First"}]})

    assert parsing.parse_step_descriptions(raw, [1, 2, 3]) == {1: "First"}


def test_entries_for_steps_that_were_not_asked_for_are_discarded():
    raw = json.dumps(
        {"steps": [{"step_order": 1, "description": "Wanted"}, {"step_order": 99, "description": "Invented"}]}
    )

    assert parsing.parse_step_descriptions(raw, [1]) == {1: "Wanted"}


@pytest.mark.parametrize(
    "raw",
    [
        MALFORMED,
        "",
        "{",
        WRONG_SHAPE,
        '{"steps": "not a list"}',
        '{"steps": []}',
        '{"steps": [{"step_order": 1}]}',                      # no description
        '{"steps": [{"step_order": 1, "description": ""}]}',   # empty description
        '{"steps": [{"step_order": "1", "description": "x"}]}',  # order not an int
        '{"steps": [{"step_order": true, "description": "x"}]}',  # bool is not an int here
        '{"steps": ["just a string"]}',
        "[1, 2, 3]",
    ],
)
def test_an_unusable_response_is_reported_as_such(raw):
    with pytest.raises(parsing.ResponseUnusable):
        parsing.parse_step_descriptions(raw, [1, 2])


def test_a_summary_is_read_when_present_and_absent_otherwise():
    with_summary = '{"steps": [], "summary": "You are behind."}'
    without = '{"steps": []}'

    assert parsing.parse_summary(with_summary) == "You are behind."
    assert parsing.parse_summary(without) is None
    assert parsing.parse_summary(MALFORMED) is None


# ---------------------------------------------------------------------------
# merge_descriptions -- where the guarantee lives
# ---------------------------------------------------------------------------


def test_merge_walks_pythons_schedule_and_takes_only_words_from_the_model():
    schedule = [
        {"step_order": 1, "step_amount": 100.00, "due_date": "2026-10-01"},
        {"step_order": 2, "step_amount": 100.00, "due_date": "2026-11-01"},
    ]

    merged = parsing.merge_descriptions(schedule, {1: "From the model"}, lambda i, n: f"Fallback {i}")

    assert merged[0] == {
        "step_order": 1,
        "step_amount": 100.00,
        "due_date": "2026-10-01",
        "description": "From the model",
    }
    assert merged[1]["description"] == "Fallback 1"


# ---------------------------------------------------------------------------
# build_schedule -- the arithmetic the model never sees
# ---------------------------------------------------------------------------


def test_the_schedule_sums_to_exactly_the_amount_owed():
    schedule = agent.build_schedule(1000.00, AS_AT, date(2026, 12, 3), first_order=1)

    assert len(schedule) == 3
    assert round(sum(item["step_amount"] for item in schedule), 2) == 1000.00
    assert [item["step_amount"] for item in schedule] == [333.33, 333.33, 333.34]


def test_the_last_instalment_absorbs_the_rounding_remainder():
    schedule = agent.build_schedule(10000.00, AS_AT, date(2027, 3, 31), first_order=1)

    amounts = [item["step_amount"] for item in schedule]
    assert len(set(amounts[:-1])) == 1  # every instalment but the last is identical
    assert round(sum(amounts), 2) == 10000.00


def test_the_final_step_falls_due_on_the_target_date_itself():
    schedule = agent.build_schedule(900.00, AS_AT, date(2026, 12, 15), first_order=1)

    assert schedule[-1]["due_date"] == "2026-12-15"
    assert [item["due_date"] for item in schedule] == ["2026-10-03", "2026-11-03", "2026-12-03", "2026-12-15"]


def test_step_numbering_continues_from_where_it_was_told_to():
    schedule = agent.build_schedule(300.00, AS_AT, date(2026, 12, 3), first_order=6)

    assert [item["step_order"] for item in schedule] == [6, 7, 8]


def test_a_one_month_plan_is_a_single_instalment():
    schedule = agent.build_schedule(500.00, AS_AT, date(2026, 9, 20), first_order=1)

    assert schedule == [{"step_order": 1, "step_amount": 500.00, "due_date": "2026-09-20"}]


def test_a_schedule_with_no_months_left_is_a_programming_error():
    with pytest.raises(ValueError):
        agent.build_schedule(500.00, AS_AT, date(2026, 8, 1), first_order=1)


# ---------------------------------------------------------------------------
# POST /api/goals/<id>/plan -- the happy path
# ---------------------------------------------------------------------------


def test_plan_returns_201_and_persists_the_schedule(client, fake_model):
    fake_model()

    response = client.post("/api/goals/7/plan")

    assert response.status_code == 201
    body = response.get_json()
    assert body["plan"]["phase"] == "plan"
    assert body["plan"]["fallback"] is False
    assert body["plan"]["step_count"] == len(body["goal"]["steps"])
    assert body["goal"]["steps"][0]["source"] == "ai"
    assert body["goal"]["steps"][0]["status"] == "pending"


def test_the_planned_steps_sum_to_what_is_still_owed(client, fake_model):
    fake_model()

    body = client.post("/api/goals/7/plan").get_json()

    total = round(sum(step["step_amount"] for step in body["goal"]["steps"]), 2)
    assert total == body["goal"]["remaining_amount"]
    assert body["goal"]["steps"][-1]["due_date"] == body["goal"]["target_date"]


def test_the_model_writes_the_descriptions(client, fake_model):
    fake_model()

    body = client.post("/api/goals/7/plan").get_json()

    assert "Put aside this month's amount" in body["goal"]["steps"][0]["description"]


def test_planning_a_goal_that_already_has_a_plan_replaces_the_pending_steps(client, fake_model):
    fake_model()
    before = client.get("/api/goals/3").get_json()
    completed = [step for step in before["steps"] if step["status"] == "complete"]

    body = client.post("/api/goals/3/plan").get_json()

    steps = body["goal"]["steps"]
    assert [step for step in steps if step["status"] == "complete"] == completed
    assert all(step["status"] == "pending" for step in steps if step not in completed)


def test_a_new_plan_is_numbered_after_the_steps_it_preserved(client, fake_model):
    fake_model()

    body = client.post("/api/goals/3/plan").get_json()

    orders = [step["step_order"] for step in body["goal"]["steps"]]
    assert orders == sorted(orders)
    assert orders[0] == 1  # the one completed step keeps its number
    assert orders[1] == 2  # and the regenerated plan carries on from there


def test_the_plan_only_covers_what_is_left_to_save(client, fake_model):
    """Goal 3 has 450.00 already in; the new plan is for the other 2,350.00."""
    fake_model()

    body = client.post("/api/goals/3/plan").get_json()

    pending = [step for step in body["goal"]["steps"] if step["status"] == "pending"]
    assert round(sum(step["step_amount"] for step in pending), 2) == 2350.00


# ---------------------------------------------------------------------------
# The guarantee
# ---------------------------------------------------------------------------


def test_the_model_cannot_change_a_single_figure(client, fake_model):
    """A model that returns its own amounts, dates and extra steps changes nothing.

    This is the architectural claim of the whole feature. Amounts and due
    dates never travel to the model and back -- they are computed in Python
    and the model's words are attached to them -- so a misbehaving,
    hallucinating or actively hostile model cannot put a wrong figure into
    the database.
    """
    fake_model(
        json.dumps(
            {
                "steps": [
                    {
                        "step_order": 1,
                        "description": "Take out a loan",
                        "step_amount": 999999.99,
                        "due_date": "1999-01-01",
                    },
                    {"step_order": 2, "description": "Invented", "step_amount": -5, "due_date": "not a date"},
                    {"step_order": 500, "description": "Not asked for", "step_amount": 1},
                ],
                "total": "one meeeellion dollars",
            }
        )
    )

    body = client.post("/api/goals/7/plan").get_json()
    steps = body["goal"]["steps"]

    assert round(sum(step["step_amount"] for step in steps), 2) == 8000.00
    assert all(step["step_amount"] > 0 for step in steps)
    assert all(step["due_date"] >= dates.to_iso(dates.today()) for step in steps)
    assert steps[-1]["due_date"] == "2027-08-31"
    assert 500 not in [step["step_order"] for step in steps]
    # The one thing it did supply was used.
    assert steps[0]["description"] == "Take out a loan"


def test_the_prompt_states_the_figures_and_asks_only_for_descriptions(client, fake_model):
    calls = fake_model()

    client.post("/api/goals/7/plan")

    prompt = calls[0]["prompt"]
    system = calls[0]["system"]
    assert "8,000.00" in prompt  # the finished figure, supplied
    assert "step_order 1:" in prompt  # the finished schedule, supplied
    assert "Never perform arithmetic" in system
    assert '"description"' in system  # the only field asked for
    assert calls[0]["json_format"] is True


# ---------------------------------------------------------------------------
# Retry and fallback
# ---------------------------------------------------------------------------


def test_an_unusable_response_is_retried_once(client, fake_model):
    calls = fake_model(MALFORMED, echo_descriptions)

    body = client.post("/api/goals/7/plan").get_json()

    assert len(calls) == 2
    assert body["plan"]["fallback"] is False
    assert "Put aside this month's amount" in body["goal"]["steps"][0]["description"]


def test_two_unusable_responses_fall_back_to_the_deterministic_plan(client, fake_model):
    calls = fake_model(MALFORMED, WRONG_SHAPE)

    response = client.post("/api/goals/7/plan")

    assert response.status_code == 201  # a bad model is not an outage
    body = response.get_json()
    assert len(calls) == 2  # one try, one retry, then stop
    assert body["plan"]["fallback"] is True
    assert body["plan"]["fallback_reason"]
    assert "Month 1 of" in body["goal"]["steps"][0]["description"]


def test_the_fallback_plan_is_a_real_plan_not_an_error_state(client, fake_model):
    fake_model(MALFORMED, MALFORMED)

    body = client.post("/api/goals/7/plan").get_json()
    steps = body["goal"]["steps"]

    assert round(sum(step["step_amount"] for step in steps), 2) == 8000.00
    assert steps[-1]["due_date"] == "2027-08-31"
    assert all(step["source"] == "ai" for step in steps)


def test_a_partial_answer_is_topped_up_rather_than_thrown_away(client, fake_model):
    fake_model(json.dumps({"steps": [{"step_order": 1, "description": "Model wrote this one"}]}))

    body = client.post("/api/goals/7/plan").get_json()
    steps = body["goal"]["steps"]

    assert body["plan"]["fallback"] is False
    assert steps[0]["description"] == "Model wrote this one"
    assert "Month 2 of" in steps[1]["description"]


# ---------------------------------------------------------------------------
# Ollama being unreachable is a different thing entirely
# ---------------------------------------------------------------------------


def test_an_unreachable_ollama_is_a_503(client, fake_model):
    fake_model(ollama.OllamaUnavailable("could not reach Ollama at http://ollama:11434"))

    response = client.post("/api/goals/7/plan")

    assert response.status_code == 503
    assert "could not reach Ollama" in response.get_json()["error"]


def test_a_model_that_was_never_pulled_says_so_and_gives_the_command(client, fake_model):
    fake_model(
        ollama.OllamaUnavailable(
            "model 'test-model:0.1b' is not pulled into the Ollama container. "
            "Run: docker compose exec ollama ollama pull test-model:0.1b"
        )
    )

    body = client.post("/api/goals/7/plan").get_json()

    assert "not pulled" in body["error"]
    assert "ollama pull" in body["error"]


def test_nothing_is_written_when_ollama_is_unreachable(client, fake_model, conn):
    fake_model(ollama.OllamaUnavailable("down"))
    before = conn.execute("SELECT COUNT(*) FROM goal_steps WHERE goal_id = 3").fetchone()[0]

    client.post("/api/goals/3/plan")

    assert conn.execute("SELECT COUNT(*) FROM goal_steps WHERE goal_id = 3").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'plan' AND goal_id = 3").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Planning refusals
# ---------------------------------------------------------------------------


def test_a_fully_funded_goal_cannot_be_planned(client, fake_model):
    fake_model()

    response = client.post("/api/goals/8/plan")

    assert response.status_code == 400
    assert any("fully funded" in detail for detail in response.get_json()["details"])


def test_a_goal_whose_target_date_has_passed_cannot_be_planned(client, fake_model):
    fake_model()
    created = client.post(
        "/api/goals",
        json={"name": "Overdue", "target_amount": 500, "target_date": "2020-01-01", "status": "paused"},
    ).get_json()

    response = client.post(f"/api/goals/{created['goal_id']}/plan")

    assert response.status_code == 400
    assert any("has passed" in detail for detail in response.get_json()["details"])


def test_planning_an_unknown_goal_is_a_404(client, fake_model):
    fake_model()

    assert client.post("/api/goals/9999/plan").status_code == 404


# ---------------------------------------------------------------------------
# POST /api/goals/<id>/replan -- ADAPT
# ---------------------------------------------------------------------------


def test_replan_returns_the_observation_and_the_adaptation(client, fake_model):
    fake_model(lambda prompt: echo_descriptions(prompt, summary="Lift the transfers a little."))

    response = client.post("/api/goals/3/replan")

    assert response.status_code == 200
    body = response.get_json()
    assert body["observe"]["phase"] == "observe"
    assert body["observe"]["status"] == "behind"
    assert body["adapt"]["phase"] == "adapt"
    assert body["adapt"]["summary"] == "Lift the transfers a little."
    assert body["adapt"]["summary_source"] == "model"


def test_replan_preserves_completed_steps_and_regenerates_only_pending_ones(client, fake_model):
    fake_model()
    before = client.get("/api/goals/1").get_json()["steps"]
    completed = [step for step in before if step["status"] == "complete"]

    body = client.post("/api/goals/1/replan").get_json()

    after = body["goal"]["steps"]
    assert body["adapt"]["steps_preserved"] == len(completed)
    assert [step for step in after if step["status"] == "complete"] == completed
    assert body["adapt"]["steps_regenerated"] == len(after) - len(completed)


def test_replan_raises_the_instalments_when_the_saver_has_fallen_behind(client, fake_model):
    """The point of the adapt phase: the shortfall is spread over what is left."""
    fake_model()

    body = client.post("/api/goals/3/replan").get_json()

    pending = [step for step in body["goal"]["steps"] if step["status"] == "pending"]
    assert round(sum(step["step_amount"] for step in pending), 2) == 2350.00
    assert body["adapt"]["revised_monthly_amount"] > 467.00  # the original instalment


def test_replan_writes_a_python_summary_when_the_model_gives_none(client, fake_model):
    fake_model(json.dumps({"steps": [{"step_order": 2, "description": "Keep going"}]}))

    body = client.post("/api/goals/3/replan").get_json()

    assert body["adapt"]["summary_source"] == "python"
    assert "behind this plan" in body["adapt"]["summary"]
    assert f"{body['observe']['variance']:,.2f}".lstrip("-") in body["adapt"]["summary"]


def test_replan_tells_the_model_what_actually_happened(client, fake_model):
    calls = fake_model()

    client.post("/api/goals/3/replan")

    prompt = calls[0]["prompt"]
    assert "behind plan" in prompt
    assert "484.00" in prompt  # the variance, already measured
    assert "Never perform arithmetic" in calls[0]["system"]


def test_replan_falls_back_like_plan_does(client, fake_model):
    fake_model(MALFORMED, MALFORMED)

    response = client.post("/api/goals/3/replan")

    assert response.status_code == 200
    body = response.get_json()
    assert body["adapt"]["fallback"] is True
    assert body["adapt"]["summary_source"] == "python"


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


def test_every_model_call_is_written_to_the_audit_trail(client, fake_model, conn):
    fake_model()
    before = conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'plan'").fetchone()[0]

    body = client.post("/api/goals/7/plan").get_json()

    after = conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'plan'").fetchone()[0]
    assert after == before + 1
    assert len(body["plan"]["log_ids"]) == 1


def test_the_audit_row_holds_the_exact_prompt_and_the_raw_response(client, fake_model, conn):
    calls = fake_model()

    body = client.post("/api/goals/7/plan").get_json()

    row = conn.execute(
        "SELECT * FROM ai_plan_log WHERE log_id = ?", (body["plan"]["log_ids"][0],)
    ).fetchone()
    assert row["prompt"] == calls[0]["prompt"]
    assert row["response"] == echo_descriptions(calls[0]["prompt"])
    assert row["model_name"] == "test-model:0.1b"


def test_a_retry_and_a_fallback_are_all_recorded(client, fake_model, conn):
    """Two attempts, then the deterministic plan: three rows, honestly labelled."""
    fake_model(MALFORMED, WRONG_SHAPE)

    body = client.post("/api/goals/7/plan").get_json()

    rows = conn.execute(
        "SELECT * FROM ai_plan_log WHERE log_id IN (?, ?, ?) ORDER BY log_id",
        tuple(body["plan"]["log_ids"]),
    ).fetchall()
    assert len(rows) == 3
    assert [row["model_name"] for row in rows] == ["test-model:0.1b", "test-model:0.1b", "python"]
    assert rows[0]["response"] == MALFORMED
    assert rows[1]["response"] == WRONG_SHAPE
    assert "FALLBACK" in rows[2]["prompt"]


def test_replan_logs_under_the_adapt_phase(client, fake_model, conn):
    fake_model()

    body = client.post("/api/goals/3/replan").get_json()

    phases = {
        conn.execute("SELECT phase FROM ai_plan_log WHERE log_id = ?", (log_id,)).fetchone()["phase"]
        for log_id in body["adapt"]["log_ids"]
    }
    assert phases == {"adapt"}


def test_the_ai_log_endpoint_shows_the_trail_for_a_goal(client, fake_model):
    fake_model()
    client.post("/api/goals/3/replan")

    body = client.get("/api/goals/3/ai-log").get_json()

    assert body["count"] >= 4  # 3 seeded rows, plus this replan's observe and adapt
    assert {entry["phase"] for entry in body["entries"]} >= {"plan", "observe", "adapt"}
    assert all(entry["prompt"] for entry in body["entries"])


def test_the_ai_log_endpoint_404s_for_an_unknown_goal(client):
    assert client.get("/api/goals/9999/ai-log").status_code == 404


def test_replan_reports_the_instalment_it_replaced_not_the_one_it_created(client, fake_model):
    """A before-and-after figure is only useful if the two are actually different."""
    fake_model()
    before = client.get("/api/goals/3/steps").get_json()["steps"]
    first_pending = next(step for step in before if step["status"] == "pending")

    adapt = client.post("/api/goals/3/replan").get_json()["adapt"]

    assert adapt["previous_monthly_amount"] == first_pending["step_amount"] == 467.00
    assert adapt["revised_monthly_amount"] == 587.50
    assert adapt["previous_monthly_amount"] != adapt["revised_monthly_amount"]


def test_replan_reports_no_previous_instalment_when_there_was_no_plan(client, fake_model):
    fake_model()

    adapt = client.post("/api/goals/7/replan").get_json()["adapt"]

    assert adapt["previous_monthly_amount"] is None
    assert adapt["steps_preserved"] == 0
