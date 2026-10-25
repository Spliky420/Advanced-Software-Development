"""GET /api/goals/<id>/progress -- the OBSERVE phase, over real HTTP."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import MONEY, json_body, months_between, response_date, saved


def _goal_ids(oracle) -> list[int]:
    return [row[0] for row in oracle.execute("SELECT goal_id FROM goals ORDER BY goal_id")]


def test_every_seeded_goal_reports_figures_matching_the_database(api, oracle):
    goal_ids = _goal_ids(oracle)
    assert len(goal_ids) >= 10, "the seed data should hold at least 10 goals"

    for goal_id in goal_ids:
        response = api.get(f"/api/goals/{goal_id}/progress")
        assert response.status_code == 200, (goal_id, response.text)
        body = json_body(response)
        as_at = response_date(body)
        goal = oracle.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()

        saved_to_date = saved(oracle, goal_id)
        required_to_date = round(
            oracle.execute(
                "SELECT COALESCE(SUM(step_amount), 0) FROM goal_steps WHERE goal_id = ? AND due_date <= ?",
                (goal_id, as_at.isoformat()),
            ).fetchone()[0],
            2,
        )
        remaining = round(max(goal["target_amount"] - saved_to_date, 0.0), 2)

        assert body["goal_id"] == goal_id
        assert body["goal_name"] == goal["name"]
        assert body["phase"] == "observe"
        assert body["target_amount"] == pytest.approx(goal["target_amount"], abs=MONEY)
        assert body["target_date"] == goal["target_date"]
        assert body["saved_to_date"] == pytest.approx(saved_to_date, abs=MONEY), goal_id
        assert body["required_to_date"] == pytest.approx(required_to_date, abs=MONEY), goal_id
        assert body["variance"] == pytest.approx(saved_to_date - required_to_date, abs=MONEY), goal_id
        assert body["remaining_amount"] == pytest.approx(remaining, abs=MONEY), goal_id
        assert body["percent_complete"] == pytest.approx(
            round(saved_to_date / goal["target_amount"] * 100, 1), abs=0.1
        ), goal_id
        assert body["months_remaining"] == months_between(as_at, date.fromisoformat(goal["target_date"])), goal_id


def test_step_counts_match_the_database(api, oracle):
    for goal_id in _goal_ids(oracle):
        body = json_body(api.get(f"/api/goals/{goal_id}/progress"))
        as_at = body["as_at"]
        steps = oracle.execute("SELECT status, due_date FROM goal_steps WHERE goal_id = ?", (goal_id,)).fetchall()

        assert body["step_count"] == len(steps), goal_id
        assert body["has_plan"] is (len(steps) > 0), goal_id
        assert body["pending_step_count"] == sum(s["status"] == "pending" for s in steps), goal_id
        assert body["overdue_step_count"] == sum(
            s["status"] == "pending" and s["due_date"] <= as_at for s in steps
        ), goal_id


def test_status_is_one_of_the_documented_values(api, oracle):
    statuses = set()
    for goal_id in _goal_ids(oracle):
        statuses.add(json_body(api.get(f"/api/goals/{goal_id}/progress"))["status"])
    assert statuses <= {"ahead", "on_track", "behind", "achieved"}, statuses


def test_unknown_goal_is_a_json_404(api, oracle):
    missing = oracle.execute("SELECT COALESCE(MAX(goal_id), 0) + 1000 FROM goals").fetchone()[0]
    response = api.get(f"/api/goals/{missing}/progress")
    assert response.status_code == 404
    assert "error" in json_body(response)


def test_non_numeric_goal_id_is_a_json_404_not_a_500(api):
    response = api.get("/api/goals/not-a-number/progress")
    assert response.status_code == 404
    assert "error" in json_body(response)
