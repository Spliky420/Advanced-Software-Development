"""GET /api/budget/summary -- monthly commitment against budget, over real HTTP."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import MONEY, json_body, months_between, response_date, saved

DEFAULT_USER_ID = 1  # config.py's DEFAULT_USER_ID; the seed data's main user


def expected_summary(oracle, user_id: int, as_at: date) -> dict:
    """The summary, recomputed from SQL and the documented formula.

    A goal's required monthly commitment is remaining / months_remaining
    (services/budget.py): 0 once funded, the whole remainder once the target
    date has passed. Only `active` goals commit money.
    """
    goals = oracle.execute(
        "SELECT goal_id, target_amount, target_date FROM goals WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchall()
    commitments = {}
    for goal in goals:
        remaining = round(max(goal["target_amount"] - saved(oracle, goal["goal_id"]), 0.0), 2)
        months = months_between(as_at, date.fromisoformat(goal["target_date"]))
        if remaining <= 0:
            monthly = 0.0
        elif months == 0:
            monthly = remaining
        else:
            monthly = round(remaining / months, 2)
        commitments[goal["goal_id"]] = {"required_monthly": monthly, "overdue": months == 0 and remaining > 0}

    total = round(sum(item["required_monthly"] for item in commitments.values()), 2)
    budget = oracle.execute(
        "SELECT monthly_budget, currency FROM budget_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    return {"commitments": commitments, "total": total, "budget": budget}


def assert_summary_matches(body: dict, oracle, user_id: int) -> None:
    expected = expected_summary(oracle, user_id, response_date(body))

    assert body["user_id"] == user_id
    assert body["active_goal_count"] == len(expected["commitments"]), user_id
    assert {goal["goal_id"] for goal in body["goals"]} == set(expected["commitments"]), user_id
    for goal in body["goals"]:
        want = expected["commitments"][goal["goal_id"]]
        assert goal["required_monthly"] == pytest.approx(want["required_monthly"], abs=MONEY), goal
        assert goal["overdue"] is want["overdue"], goal
    assert body["overdue_goal_count"] == sum(item["overdue"] for item in expected["commitments"].values())
    assert body["total_monthly_commitment"] == pytest.approx(expected["total"], abs=MONEY), user_id

    budget = expected["budget"]
    if budget is None:
        assert body["budget_is_set"] is False
        assert body["monthly_budget"] is None
        assert body["difference"] is None
        assert body["status"] == "no_budget_set"
        return

    difference = round(budget["monthly_budget"] - expected["total"], 2)
    assert body["budget_is_set"] is True
    assert body["monthly_budget"] == pytest.approx(budget["monthly_budget"], abs=MONEY)
    assert body["currency"] == budget["currency"]
    assert body["difference"] == pytest.approx(difference, abs=MONEY), user_id
    assert body["status"] == ("over_budget" if difference < 0 else "within_budget"), user_id


def test_default_user_summary_matches_the_database(api, oracle):
    response = api.get("/api/budget/summary")
    assert response.status_code == 200, response.text
    body = json_body(response)
    assert body["user_id"] == DEFAULT_USER_ID
    assert body["active_goal_count"] > 0, "the default user should have active goals in the seed"
    assert_summary_matches(body, oracle, DEFAULT_USER_ID)


def test_every_seeded_user_summary_matches_the_database(api, oracle):
    user_ids = [
        row[0]
        for row in oracle.execute("SELECT user_id FROM goals UNION SELECT user_id FROM budget_settings ORDER BY 1")
    ]
    for user_id in user_ids:
        response = api.get("/api/budget/summary", params={"user_id": user_id})
        assert response.status_code == 200, (user_id, response.text)
        assert_summary_matches(json_body(response), oracle, user_id)


def test_a_user_with_no_goals_and_no_budget_is_200_not_an_error(api, oracle):
    unknown = oracle.execute(
        "SELECT MAX(id) + 1000 FROM (SELECT user_id AS id FROM goals UNION SELECT user_id FROM budget_settings)"
    ).fetchone()[0]
    response = api.get("/api/budget/summary", params={"user_id": unknown})
    assert response.status_code == 200
    body = json_body(response)
    assert body["active_goal_count"] == 0
    assert body["total_monthly_commitment"] == 0
    assert body["status"] == "no_budget_set"


@pytest.mark.parametrize("user_id", ["abc", "0", "-3", "1.5"])
def test_an_invalid_user_id_is_a_json_400_naming_the_field(api, user_id):
    response = api.get("/api/budget/summary", params={"user_id": user_id})
    assert response.status_code == 400
    body = json_body(response)
    assert any("user_id" in detail for detail in body["details"]), body
