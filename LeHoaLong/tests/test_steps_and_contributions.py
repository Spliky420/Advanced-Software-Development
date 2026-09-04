"""Steps and contributions endpoints.

Seed facts these lean on: goal 1 has 12 steps (1-5 complete), goal 3 has 6
steps and 2 contributions totalling 450.00, goal 7 has no plan and no money.
"""

from __future__ import annotations

import pytest
from app.services import dates

PAST_DATE = "2020-01-01"


def _future_date() -> str:
    return dates.to_iso(dates.add_months(dates.today(), 6))


# ---------------------------------------------------------------------------
# GET /api/goals/<id>/steps
# ---------------------------------------------------------------------------


def test_steps_are_returned_in_plan_order(client):
    body = client.get("/api/goals/1/steps").get_json()

    assert body["count"] == 12
    assert body["goal_id"] == 1
    assert [step["step_order"] for step in body["steps"]] == list(range(1, 13))


def test_steps_of_a_goal_with_no_plan_are_an_empty_list(client):
    body = client.get("/api/goals/7/steps").get_json()

    assert body["steps"] == []
    assert body["count"] == 0


def test_steps_404_when_the_goal_does_not_exist(client):
    """An empty list would read as "no plan" rather than "no such goal"."""
    response = client.get("/api/goals/9999/steps")

    assert response.status_code == 404
    assert response.get_json()["error"] == "No goal with id 9999"


# ---------------------------------------------------------------------------
# PUT /api/goals/<id>/steps/<step_id>
# ---------------------------------------------------------------------------


def test_marking_a_step_complete(client):
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][1]["step_id"]

    body = client.put(f"/api/goals/3/steps/{step_id}", json={"status": "complete"}).get_json()

    assert body["status"] == "complete"


def test_marking_complete_leaves_provenance_alone(client):
    """Ticking a step off is bookkeeping, not authorship."""
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][1]["step_id"]

    body = client.put(f"/api/goals/3/steps/{step_id}", json={"status": "complete"}).get_json()

    assert body["source"] == "ai"


def test_editing_the_substance_of_an_ai_step_makes_it_the_users(client):
    """Once the amount is the user's, the step is no longer what the model wrote."""
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][2]["step_id"]

    body = client.put(f"/api/goals/3/steps/{step_id}", json={"step_amount": 600}).get_json()

    assert body["step_amount"] == 600.0
    assert body["source"] == "user"


def test_rewriting_a_step_to_its_existing_value_does_not_change_provenance(client):
    step = client.get("/api/goals/3/steps").get_json()["steps"][2]

    body = client.put(
        f"/api/goals/3/steps/{step['step_id']}", json={"step_amount": step["step_amount"]}
    ).get_json()

    assert body["source"] == "ai"


def test_a_step_can_be_edited_in_several_ways_at_once(client):
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][3]["step_id"]

    body = client.put(
        f"/api/goals/3/steps/{step_id}",
        json={"description": "Skip a takeaway week", "step_amount": 500, "due_date": "2026-10-20"},
    ).get_json()

    assert body["description"] == "Skip a takeaway week"
    assert body["step_amount"] == 500.0
    assert body["due_date"] == "2026-10-20"


def test_a_step_amount_of_zero_is_allowed(client):
    """A step can be an action with no money attached, and the schema says so."""
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][4]["step_id"]

    response = client.put(f"/api/goals/3/steps/{step_id}", json={"step_amount": 0})

    assert response.status_code == 200
    assert response.get_json()["step_amount"] == 0.0


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({"step_amount": -10}, "step_amount must not be negative"),
        ({"step_amount": "lots"}, "step_amount must be a number"),
        ({"due_date": "20th of never"}, "due_date must be an ISO-8601 date"),
        ({"status": "donezo"}, "status must be one of"),
        ({"description": ""}, "description must not be empty"),
        ({"step_order": 3}, "step_order cannot be changed"),
        ({"source": "user"}, "source cannot be changed"),
        ({"goal_id": 9}, "goal_id cannot be changed"),
        ({}, "no updatable fields supplied"),
    ],
)
def test_step_update_rejects_invalid_payloads(client, payload, expected_detail):
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][0]["step_id"]

    response = client.put(f"/api/goals/3/steps/{step_id}", json=payload)

    assert response.status_code == 400
    assert any(expected_detail in detail for detail in response.get_json()["details"])


def test_a_step_cannot_be_reached_through_the_wrong_goal(client):
    """Scoping by goal as well as by id: goal 1 does not own goal 3's steps."""
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][0]["step_id"]

    response = client.put(f"/api/goals/1/steps/{step_id}", json={"status": "complete"})

    assert response.status_code == 404


def test_step_update_404s_for_an_unknown_step(client):
    response = client.put("/api/goals/3/steps/9999", json={"status": "complete"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/goals/<id>/steps/<step_id>
# ---------------------------------------------------------------------------


def test_deleting_a_step_leaves_the_rest_of_the_plan_intact(client):
    steps = client.get("/api/goals/3/steps").get_json()["steps"]
    doomed = steps[2]

    assert client.delete(f"/api/goals/3/steps/{doomed['step_id']}").status_code == 204

    remaining = client.get("/api/goals/3/steps").get_json()
    assert remaining["count"] == 5
    assert doomed["step_id"] not in [step["step_id"] for step in remaining["steps"]]


def test_deleting_a_step_does_not_renumber_the_others(client):
    """step_order is a stable sort key, not a display index."""
    steps = client.get("/api/goals/3/steps").get_json()["steps"]
    client.delete(f"/api/goals/3/steps/{steps[2]['step_id']}")

    orders = [step["step_order"] for step in client.get("/api/goals/3/steps").get_json()["steps"]]
    assert orders == [1, 2, 4, 5, 6]  # the gap is deliberate


def test_deleting_a_step_does_not_touch_contributions(client):
    steps = client.get("/api/goals/3/steps").get_json()["steps"]

    client.delete(f"/api/goals/3/steps/{steps[0]['step_id']}")

    assert client.get("/api/goals/3").get_json()["saved_to_date"] == 450.0


def test_step_delete_404s_twice(client):
    step_id = client.get("/api/goals/3/steps").get_json()["steps"][0]["step_id"]

    assert client.delete(f"/api/goals/3/steps/{step_id}").status_code == 204
    assert client.delete(f"/api/goals/3/steps/{step_id}").status_code == 404


# ---------------------------------------------------------------------------
# GET /api/goals/<id>/contributions
# ---------------------------------------------------------------------------


def test_contributions_are_listed_newest_first_with_a_total(client):
    body = client.get("/api/goals/3/contributions").get_json()

    assert body["count"] == 2
    assert body["total"] == 450.0
    dates_listed = [item["contribution_date"] for item in body["contributions"]]
    assert dates_listed == sorted(dates_listed, reverse=True)


def test_contributions_of_an_unfunded_goal_total_zero(client):
    body = client.get("/api/goals/7/contributions").get_json()

    assert body["contributions"] == []
    assert body["total"] == 0.0


def test_contributions_404_when_the_goal_does_not_exist(client):
    assert client.get("/api/goals/9999/contributions").status_code == 404


# ---------------------------------------------------------------------------
# POST /api/goals/<id>/contributions -- the ACT phase
# ---------------------------------------------------------------------------


def test_recording_a_contribution_returns_201_and_the_recalculated_goal(client):
    response = client.post("/api/goals/3/contributions", json={"amount": 550, "notes": "Catch-up"})

    assert response.status_code == 201
    body = response.get_json()
    assert body["contribution"]["amount"] == 550.0
    assert body["contribution"]["notes"] == "Catch-up"
    assert body["goal"]["saved_to_date"] == 1000.0  # 450 seeded + 550
    assert body["goal"]["remaining_amount"] == 1800.0
    assert body["goal"]["fully_funded"] is False


def test_a_contribution_defaults_to_today(client):
    body = client.post("/api/goals/3/contributions", json={"amount": 25}).get_json()

    assert body["contribution"]["contribution_date"] == dates.to_iso(dates.today())


def test_a_contribution_that_completes_a_goal_is_flagged_not_auto_applied(client):
    """The app reports that the target is met; changing the status is the user's call."""
    body = client.post("/api/goals/3/contributions", json={"amount": 2350}).get_json()

    assert body["goal"]["fully_funded"] is True
    assert body["goal"]["remaining_amount"] == 0.0
    assert body["goal"]["status"] == "active"  # not silently flipped to 'achieved'


def test_recording_a_contribution_does_not_mark_any_step_complete(client):
    """Steps are the plan; contributions are money. The observe phase compares them."""
    before = [step["status"] for step in client.get("/api/goals/3/steps").get_json()["steps"]]

    client.post("/api/goals/3/contributions", json={"amount": 467})

    after = [step["status"] for step in client.get("/api/goals/3/steps").get_json()["steps"]]
    assert before == after


def test_a_contribution_shows_up_in_the_goal_detail_and_the_list(client):
    client.post("/api/goals/3/contributions", json={"amount": 100})

    detail = client.get("/api/goals/3").get_json()
    assert detail["saved_to_date"] == 550.0
    assert detail["contribution_count"] == 3

    listed = client.get("/api/goals").get_json()["goals"]
    assert next(goal for goal in listed if goal["goal_id"] == 3)["saved_to_date"] == 550.0


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({}, "amount is required"),
        ({"amount": 0}, "amount must be greater than 0"),
        ({"amount": -50}, "amount must be greater than 0"),
        ({"amount": "fifty"}, "amount must be a number"),
        ({"amount": True}, "amount must be a number"),
        ({"amount": 50, "contribution_date": "yesterday"}, "contribution_date must be an ISO-8601 date"),
        ({"amount": 50, "notes": "x" * 501}, "notes must be 500 characters or fewer"),
    ],
)
def test_contribution_rejects_invalid_payloads(client, payload, expected_detail):
    response = client.post("/api/goals/3/contributions", json=payload)

    assert response.status_code == 400
    assert any(expected_detail in detail for detail in response.get_json()["details"])


def test_a_future_dated_contribution_is_rejected(client):
    """This table records money that has moved -- that is what makes it the act phase."""
    response = client.post(
        "/api/goals/3/contributions", json={"amount": 50, "contribution_date": _future_date()}
    )

    assert response.status_code == 400
    assert any("in the future" in detail for detail in response.get_json()["details"])


def test_a_back_dated_contribution_is_allowed(client):
    """Catching up on paperwork is normal; only the future is impossible."""
    response = client.post(
        "/api/goals/3/contributions", json={"amount": 50, "contribution_date": PAST_DATE}
    )

    assert response.status_code == 201


def test_contribution_404s_for_a_goal_that_does_not_exist(client):
    response = client.post("/api/goals/9999/contributions", json={"amount": 50})

    assert response.status_code == 404


def test_a_contribution_is_not_written_when_the_goal_is_missing(client, conn):
    before = conn.execute("SELECT COUNT(*) FROM contributions").fetchone()[0]

    client.post("/api/goals/9999/contributions", json={"amount": 50})

    assert conn.execute("SELECT COUNT(*) FROM contributions").fetchone()[0] == before
