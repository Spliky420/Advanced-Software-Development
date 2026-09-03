"""Budget arithmetic and the budget endpoints.

The maths is tested against a pinned `as_at` of 2026-09-03 -- the date the
seed data is built around -- so the expected figures are exact rather than
"whatever today makes them". The endpoint tests, which cannot pin the date,
assert relationships that hold on any date instead.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import budget as budget_service
from app.services import dates

AS_AT = date(2026, 9, 3)


def _goal(target_amount=1200.0, target_date="2026-12-03", **overrides):
    """A goal dict of the shape the service layer passes around."""
    return {
        "goal_id": 1,
        "name": "Test Goal",
        "priority": "medium",
        "target_amount": target_amount,
        "target_date": target_date,
        **overrides,
    }


# ---------------------------------------------------------------------------
# months_between -- the divisor the whole calculation rests on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start, end, expected",
    [
        (date(2026, 9, 3), date(2026, 12, 3), 3),    # exact months
        (date(2026, 9, 3), date(2026, 12, 15), 4),   # part month rounds up
        (date(2026, 9, 3), date(2026, 10, 1), 1),    # under a month is still one
        (date(2026, 9, 3), date(2026, 9, 3), 0),     # today is not a month
        (date(2026, 9, 3), date(2026, 8, 1), 0),     # the past is not a month
        (date(2026, 9, 3), date(2028, 12, 31), 28),
    ],
)
def test_months_between_rounds_up_and_never_goes_negative(start, end, expected):
    """Rounded up: with six weeks left you need two instalments, not one."""
    assert dates.months_between(start, end) == expected


@pytest.mark.parametrize(
    "start, months, expected",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),   # clamps to a short month
        (date(2026, 1, 31), 2, date(2026, 3, 31)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),  # crosses the year
        (date(2028, 1, 31), 1, date(2028, 2, 29)),   # leap year
    ],
)
def test_add_months_clamps_to_the_end_of_a_short_month(start, months, expected):
    assert dates.add_months(start, months) == expected


# ---------------------------------------------------------------------------
# commitment_for_goal -- one goal's required monthly figure
# ---------------------------------------------------------------------------


def test_commitment_spreads_the_remaining_amount_over_the_months_left():
    result = budget_service.commitment_for_goal(_goal(), saved=300.0, as_at=AS_AT)

    assert result["remaining_amount"] == 900.0
    assert result["months_remaining"] == 3
    assert result["required_monthly"] == 300.0
    assert result["overdue"] is False


def test_commitment_rounds_to_cents():
    result = budget_service.commitment_for_goal(_goal(target_amount=1000.0), saved=0.0, as_at=AS_AT)

    assert result["required_monthly"] == 333.33  # 1000 / 3


def test_a_fully_funded_goal_commits_nothing_further():
    result = budget_service.commitment_for_goal(_goal(), saved=1200.0, as_at=AS_AT)

    assert result["remaining_amount"] == 0.0
    assert result["required_monthly"] == 0.0
    assert result["overdue"] is False


def test_an_over_funded_goal_commits_nothing_and_does_not_go_negative():
    result = budget_service.commitment_for_goal(_goal(), saved=5000.0, as_at=AS_AT)

    assert result["remaining_amount"] == 0.0
    assert result["required_monthly"] == 0.0


def test_an_overdue_goal_owes_the_whole_shortfall_now():
    """Dividing by zero months is not an option, and spreading it would lie."""
    result = budget_service.commitment_for_goal(
        _goal(target_date="2026-08-01"), saved=300.0, as_at=AS_AT
    )

    assert result["months_remaining"] == 0
    assert result["required_monthly"] == 900.0
    assert result["overdue"] is True


def test_a_goal_due_today_is_treated_as_overdue():
    result = budget_service.commitment_for_goal(
        _goal(target_date=dates.to_iso(AS_AT)), saved=0.0, as_at=AS_AT
    )

    assert result["months_remaining"] == 0
    assert result["overdue"] is True


def test_an_overdue_but_funded_goal_is_not_flagged_overdue():
    result = budget_service.commitment_for_goal(
        _goal(target_date="2026-08-01"), saved=1200.0, as_at=AS_AT
    )

    assert result["overdue"] is False
    assert result["required_monthly"] == 0.0


# ---------------------------------------------------------------------------
# summarise -- the whole panel, against the seeded data at a pinned date
# ---------------------------------------------------------------------------


def test_summary_totals_the_seeded_active_goals_for_user_1(conn):
    summary = budget_service.summarise(conn, user_id=1, as_at=AS_AT)

    by_id = {item["goal_id"]: item["required_monthly"] for item in summary["goals"]}
    assert by_id == {1: 828.29, 2: 500.00, 3: 587.50, 4: 300.00, 6: 700.00, 7: 666.67}
    assert summary["total_monthly_commitment"] == 3582.46


def test_user_1_is_seeded_over_budget_so_the_warning_state_is_visible(conn):
    summary = budget_service.summarise(conn, user_id=1, as_at=AS_AT)

    assert summary["monthly_budget"] == 2500.00
    assert summary["difference"] == -1082.46  # negative means over
    assert summary["status"] == "over_budget"
    assert summary["percent_of_budget_used"] == 143.3


def test_summary_for_a_user_within_budget(conn):
    summary = budget_service.summarise(conn, user_id=2, as_at=AS_AT)

    assert summary["total_monthly_commitment"] == 2014.29
    assert summary["monthly_budget"] == 6000.00
    assert summary["difference"] == 3985.71
    assert summary["status"] == "within_budget"


def test_only_active_goals_count_toward_the_commitment(conn):
    """Paused, achieved and abandoned goals are not being saved for."""
    summary = budget_service.summarise(conn, user_id=1, as_at=AS_AT)

    counted = {item["goal_id"] for item in summary["goals"]}
    assert 5 not in counted   # paused
    assert 8 not in counted   # achieved
    assert summary["active_goal_count"] == 6


def test_a_goal_with_no_plan_still_counts_against_the_budget(conn):
    """Goal 7 has no steps at all, and still requires money every month."""
    summary = budget_service.summarise(conn, user_id=1, as_at=AS_AT)

    tuition = next(item for item in summary["goals"] if item["goal_id"] == 7)
    assert tuition["required_monthly"] == 666.67
    assert tuition["saved_to_date"] == 0.0


def test_the_total_is_always_the_sum_of_the_listed_goals(conn):
    for user_id in (1, 2, 3):
        summary = budget_service.summarise(conn, user_id=user_id, as_at=AS_AT)
        assert summary["total_monthly_commitment"] == round(
            sum(item["required_monthly"] for item in summary["goals"]), 2
        )


def test_summary_for_a_user_who_has_no_budget_and_no_goals(conn):
    summary = budget_service.summarise(conn, user_id=99, as_at=AS_AT)

    assert summary["status"] == "no_budget_set"
    assert summary["monthly_budget"] is None
    assert summary["difference"] is None
    assert summary["total_monthly_commitment"] == 0.0
    assert summary["goals"] == []


def test_summary_for_a_budget_only_user_reports_an_unspent_budget(conn):
    """Users 4-10 are seeded with a budget and no goals."""
    summary = budget_service.summarise(conn, user_id=5, as_at=AS_AT)

    assert summary["monthly_budget"] == 950.00
    assert summary["total_monthly_commitment"] == 0.0
    assert summary["difference"] == 950.00
    assert summary["status"] == "within_budget"


# ---------------------------------------------------------------------------
# available_monthly -- what the planner will hand the model at step 4
# ---------------------------------------------------------------------------


def test_available_budget_excludes_the_goal_being_planned(conn):
    """Otherwise the goal is counted against the budget it is asking to use."""
    available = budget_service.available_monthly(conn, user_id=1, exclude_goal_id=3, as_at=AS_AT)

    assert available["committed_to_other_goals"] == 2994.96  # 3582.46 - 587.50
    assert available["available"] == -494.96  # already over-committed without goal 3


def test_available_budget_is_none_when_no_budget_has_been_set(conn):
    available = budget_service.available_monthly(conn, user_id=99, as_at=AS_AT)

    assert available["monthly_budget"] is None
    assert available["available"] is None


# ---------------------------------------------------------------------------
# GET /api/budget/summary
# ---------------------------------------------------------------------------


def test_summary_endpoint_is_internally_consistent(client):
    body = client.get("/api/budget/summary").get_json()

    assert body["user_id"] == 1
    assert body["as_at"] == dates.to_iso(dates.today())
    assert body["total_monthly_commitment"] == round(
        sum(goal["required_monthly"] for goal in body["goals"]), 2
    )
    assert body["difference"] == round(body["monthly_budget"] - body["total_monthly_commitment"], 2)
    assert body["status"] == ("over_budget" if body["difference"] < 0 else "within_budget")


def test_summary_endpoint_scopes_to_the_requested_user(client):
    body = client.get("/api/budget/summary?user_id=3").get_json()

    assert body["user_id"] == 3
    assert {goal["goal_id"] for goal in body["goals"]} == {12, 13}


def test_summary_endpoint_rejects_a_bad_user_id(client):
    response = client.get("/api/budget/summary?user_id=all")

    assert response.status_code == 400
    assert any("user_id must be a positive integer" in d for d in response.get_json()["details"])


def test_summary_reflects_a_newly_created_goal_immediately(client):
    before = client.get("/api/budget/summary").get_json()["total_monthly_commitment"]

    client.post(
        "/api/goals",
        json={
            "name": "Sudden Expense",
            "target_amount": 1200,
            "target_date": dates.to_iso(dates.add_months(dates.today(), 12)),
        },
    )

    after = client.get("/api/budget/summary").get_json()["total_monthly_commitment"]
    assert after == round(before + 100.0, 2)


def test_summary_reflects_a_contribution_immediately(client):
    before = client.get("/api/budget/summary").get_json()["total_monthly_commitment"]

    client.post("/api/goals/3/contributions", json={"amount": 500})

    after = client.get("/api/budget/summary").get_json()["total_monthly_commitment"]
    assert after < before  # less left to save means less required per month


# ---------------------------------------------------------------------------
# GET / PUT /api/budget/settings
# ---------------------------------------------------------------------------


def test_get_settings_returns_the_seeded_budget(client):
    body = client.get("/api/budget/settings").get_json()

    assert body["user_id"] == 1
    assert body["monthly_budget"] == 2500.00
    assert body["currency"] == "AUD"
    assert body["is_set"] is True


def test_get_settings_for_a_user_with_no_budget_is_not_a_404(client):
    """Never having set a budget is a starting state, not an error."""
    response = client.get("/api/budget/settings?user_id=99")

    assert response.status_code == 200
    body = response.get_json()
    assert body["is_set"] is False
    assert body["monthly_budget"] is None
    assert body["currency"] == "AUD"


def test_put_settings_updates_an_existing_budget(client):
    body = client.put("/api/budget/settings", json={"monthly_budget": 3200}).get_json()

    assert body["monthly_budget"] == 3200.00
    assert client.get("/api/budget/settings").get_json()["monthly_budget"] == 3200.00


def test_put_settings_creates_a_budget_for_a_user_who_had_none(client, conn):
    response = client.put("/api/budget/settings", json={"monthly_budget": 800, "user_id": 99})

    assert response.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM budget_settings WHERE user_id = 99").fetchone()[0] == 1


def test_put_settings_does_not_duplicate_a_row_on_repeat(client, conn):
    """UNIQUE (user_id): this table holds the current budget, not a history."""
    for amount in (100, 200, 300):
        client.put("/api/budget/settings", json={"monthly_budget": amount})

    assert conn.execute("SELECT COUNT(*) FROM budget_settings WHERE user_id = 1").fetchone()[0] == 1
    assert client.get("/api/budget/settings").get_json()["monthly_budget"] == 300.00


def test_put_settings_normalises_the_currency_code(client):
    body = client.put("/api/budget/settings", json={"monthly_budget": 100, "currency": "nzd"}).get_json()

    assert body["currency"] == "NZD"


def test_a_zero_budget_is_allowed(client):
    """Recording that there is nothing spare this month is legitimate."""
    response = client.put("/api/budget/settings", json={"monthly_budget": 0})

    assert response.status_code == 200
    assert response.get_json()["monthly_budget"] == 0.0


def test_a_zero_budget_reports_no_percentage_rather_than_dividing_by_zero(client):
    client.put("/api/budget/settings", json={"monthly_budget": 0})

    body = client.get("/api/budget/summary").get_json()

    assert body["percent_of_budget_used"] is None
    assert body["status"] == "over_budget"


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({}, "monthly_budget is required"),
        ({"monthly_budget": -100}, "monthly_budget must not be negative"),
        ({"monthly_budget": "heaps"}, "monthly_budget must be a number"),
        ({"monthly_budget": 100, "currency": "dollars"}, "currency must be"),
        ({"monthly_budget": 100, "currency": "A1"}, "currency must be"),
        ({"monthly_budget": 100, "user_id": -3}, "user_id must be a positive integer"),
    ],
)
def test_put_settings_rejects_invalid_payloads(client, payload, expected_detail):
    response = client.put("/api/budget/settings", json=payload)

    assert response.status_code == 400
    assert any(expected_detail in detail for detail in response.get_json()["details"])


def test_changing_the_budget_flips_the_summary_status(client):
    client.put("/api/budget/settings", json={"monthly_budget": 1_000_000})
    assert client.get("/api/budget/summary").get_json()["status"] == "within_budget"

    client.put("/api/budget/settings", json={"monthly_budget": 1})
    assert client.get("/api/budget/summary").get_json()["status"] == "over_budget"
