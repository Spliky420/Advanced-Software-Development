"""The OBSERVE phase -- GET /api/goals/<id>/progress.

Pure Python arithmetic: no test in this file needs a model, and the autouse
network block would fail it if one tried.

Service-level tests pin `as_at` to 2026-09-03, the date the seed data is
built around, so the expected figures are exact. Endpoint tests, which run on
whatever today is, assert relationships instead.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import agent, dates

AS_AT = date(2026, 9, 3)


def _observe(conn, goal_id, **kwargs):
    return agent.observe(conn, goal_id, as_at=AS_AT, **kwargs)


# ---------------------------------------------------------------------------
# Classification against the seeded goals
# ---------------------------------------------------------------------------


def test_a_goal_keeping_up_with_its_plan_is_on_track(service_conn):
    """Goal 1 is 32.00 ahead on a 4,170.00 expectation -- inside tolerance."""
    result = _observe(service_conn, 1, log=False)

    assert result["saved_to_date"] == 4202.00
    assert result["required_to_date"] == 4170.00
    assert result["variance"] == 32.00
    assert result["variance_tolerance"] == 41.70  # 1% of what was required
    assert result["status"] == "on_track"


def test_a_goal_that_has_missed_instalments_is_behind(service_conn):
    """Goal 3 -- the replan demo."""
    result = _observe(service_conn, 3, log=False)

    assert result["saved_to_date"] == 450.00
    assert result["required_to_date"] == 934.00
    assert result["variance"] == -484.00
    assert result["status"] == "behind"
    assert result["overdue_step_count"] == 1


def test_a_goal_well_past_its_plan_is_ahead(service_conn):
    result = _observe(service_conn, 9, log=False)

    assert result["variance"] == 2000.00
    assert result["status"] == "ahead"


def test_a_fully_funded_goal_is_achieved_whatever_the_variance(service_conn):
    result = _observe(service_conn, 8, log=False)

    assert result["remaining_amount"] == 0.0
    assert result["status"] == "achieved"
    assert result["percent_complete"] == 100.0


def test_a_goal_with_no_plan_has_nothing_to_be_behind(service_conn):
    """Goal 7 has no steps: required_to_date is 0, and has_plan says why."""
    result = _observe(service_conn, 7, log=False)

    assert result["has_plan"] is False
    assert result["step_count"] == 0
    assert result["required_to_date"] == 0.0
    assert result["status"] == "on_track"


def test_a_goal_with_neither_plan_nor_contributions(service_conn):
    result = _observe(service_conn, 13, log=False)

    assert result["saved_to_date"] == 0.0
    assert result["has_plan"] is False
    assert result["projected_completion_date"] is None


# ---------------------------------------------------------------------------
# The tolerance band
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variance, required, expected",
    [
        (-50.0, 1000.0, "behind"),    # tolerance is 10.00
        (-10.0, 1000.0, "on_track"),  # exactly on the band edge
        (-10.01, 1000.0, "behind"),
        (10.01, 1000.0, "ahead"),
        (0.0, 0.0, "on_track"),
        (-0.50, 0.0, "on_track"),     # floored at 1.00, so cents never trip it
        (-1.01, 0.0, "behind"),
    ],
)
def test_classify_applies_the_tolerance_band(variance, required, expected):
    tolerance = max(1.0, required * 0.01)

    assert agent.classify(variance, required, remaining_amount=500.0, tolerance=tolerance) == expected


def test_classify_calls_a_funded_goal_achieved_before_anything_else(service_conn):
    assert agent.classify(-9999.0, 1000.0, remaining_amount=0.0, tolerance=10.0) == "achieved"


def test_the_tolerance_is_configurable(app, service_conn):
    """A team that wants a stricter reading changes an env var, not the code."""
    app.config["PROGRESS_TOLERANCE_PERCENT"] = 0.1  # 4.17 on goal 1

    result = _observe(service_conn, 1, log=False)

    assert result["variance_tolerance"] == 4.17
    assert result["status"] == "ahead"  # +32.00 now sits outside the band


# ---------------------------------------------------------------------------
# Projected completion date
# ---------------------------------------------------------------------------


def test_projection_extrapolates_the_average_rate_so_far(service_conn):
    """Goal 1: 4,202.00 over 5 months is 840.40/month; 5,798.00 left is 7 more."""
    result = _observe(service_conn, 1, log=False)

    assert result["projected_completion_date"] == "2027-04-03"


def test_a_goal_can_be_on_track_and_still_project_past_its_target(service_conn):
    """On track against the plan, three days late on the current rate."""
    result = _observe(service_conn, 1, log=False)

    assert result["status"] == "on_track"
    assert result["target_date"] == "2027-03-31"
    assert result["projected_meets_target"] is False


def test_projection_is_unknown_when_nothing_has_been_saved():
    """There is no rate to extrapolate from, and guessing would be worse."""
    projected = agent.project_completion(
        saved_to_date=0.0, remaining_amount=1000.0, started=date(2026, 1, 1), as_at=AS_AT
    )

    assert projected is None


def test_projection_of_a_funded_goal_is_today():
    projected = agent.project_completion(
        saved_to_date=1000.0, remaining_amount=0.0, started=date(2026, 1, 1), as_at=AS_AT
    )

    assert projected == "2026-09-03"


def test_a_derisory_saving_rate_projects_nothing_rather_than_the_year_3000():
    projected = agent.project_completion(
        saved_to_date=0.01, remaining_amount=1_000_000.0, started=date(2026, 1, 1), as_at=AS_AT
    )

    assert projected is None


def test_projection_handles_a_goal_created_today():
    """months_between is 0, and dividing by it would be a crash."""
    projected = agent.project_completion(
        saved_to_date=500.0, remaining_amount=500.0, started=AS_AT, as_at=AS_AT
    )

    assert projected == "2026-10-03"  # one month at 500/month


# ---------------------------------------------------------------------------
# Logging to ai_plan_log
# ---------------------------------------------------------------------------


def test_an_observation_is_written_to_the_audit_trail(service_conn):
    before = service_conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'observe'").fetchone()[0]

    result = _observe(service_conn, 3)

    after = service_conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE phase = 'observe'").fetchone()[0]
    assert after == before + 1
    assert result["logged"] is True
    assert result["log_id"] is not None


def test_the_observe_row_records_python_not_a_model(service_conn):
    """No model is called in this phase, and the audit trail should say so."""
    result = _observe(service_conn, 3)

    row = service_conn.execute(
        "SELECT * FROM ai_plan_log WHERE log_id = ?", (result["log_id"],)
    ).fetchone()
    assert row["model_name"] == "python"
    assert row["phase"] == "observe"
    assert "variance -484.00" in row["prompt"]


def test_an_unchanged_observation_is_not_logged_twice(service_conn):
    """The dashboard polls this per goal card; identical rows are noise."""
    first = _observe(service_conn, 3)
    second = _observe(service_conn, 3)

    assert first["logged"] is True
    assert second["logged"] is False
    assert second["log_id"] is None


def test_a_changed_observation_is_logged_again(service_conn, client):
    _observe(service_conn, 3)
    client.post("/api/goals/3/contributions", json={"amount": 100})

    assert _observe(service_conn, 3)["logged"] is True


# ---------------------------------------------------------------------------
# GET /api/goals/<id>/progress
# ---------------------------------------------------------------------------


def test_progress_endpoint_returns_the_observation(client):
    body = client.get("/api/goals/3/progress").get_json()

    assert body["phase"] == "observe"
    assert body["goal_id"] == 3
    assert body["status"] == "behind"
    assert body["as_at"] == dates.to_iso(dates.today())


def test_progress_variance_is_always_saved_minus_required(client):
    for goal_id in (1, 2, 3, 8, 9, 12):
        body = client.get(f"/api/goals/{goal_id}/progress").get_json()
        assert body["variance"] == round(body["saved_to_date"] - body["required_to_date"], 2)


def test_progress_reflects_a_contribution_immediately(client):
    before = client.get("/api/goals/3/progress").get_json()

    client.post("/api/goals/3/contributions", json={"amount": 484})

    after = client.get("/api/goals/3/progress").get_json()
    assert after["saved_to_date"] == round(before["saved_to_date"] + 484, 2)
    assert after["variance"] == round(before["variance"] + 484, 2)
    assert after["status"] == "on_track"  # exactly closes the 484.00 gap


def test_progress_404s_for_a_goal_that_does_not_exist(client):
    assert client.get("/api/goals/9999/progress").status_code == 404


def test_progress_never_calls_the_model(client, fake_model):
    """The autouse network block would catch a real call; this catches a stub one."""
    calls = fake_model()

    client.get("/api/goals/3/progress")

    assert calls == []
