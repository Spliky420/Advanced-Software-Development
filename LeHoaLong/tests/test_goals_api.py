"""Goals CRUD, the health endpoint, and the cross-cutting HTTP behaviour.

Everything runs against a temporary copy of the real seeded database, so the
expected counts below are the seed data's counts: 13 goals across 3 users,
8 of them user 1's.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import create_app

FUTURE_DATE = "2030-06-30"
PAST_DATE = "2020-01-01"


def _goal_ids(payload) -> list[int]:
    return [goal["goal_id"] for goal in payload["goals"]]


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_reports_ok_when_database_and_model_are_present(client, stub_ollama):
    stub_ollama(reachable=True, model_available=True)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["database"]["reachable"] is True
    assert body["ollama"]["model_available"] is True


def test_health_stays_ok_when_ollama_is_down(client, stub_ollama):
    """Ollama is a soft dependency: CRUD works fine without a model."""
    stub_ollama(reachable=False, model_available=False, detail="could not reach Ollama")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert response.get_json()["ollama"]["reachable"] is False


def test_health_is_503_when_the_database_is_unusable(tmp_path, stub_ollama):
    """The database is a hard dependency, so an uninitialised file is a 503."""
    app = create_app({"TESTING": True, "DB_PATH": str(tmp_path / "not-initialised.db")})
    stub_ollama(reachable=True)

    response = app.test_client().get("/health")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "degraded"
    assert body["database"]["reachable"] is False
    assert "goals" in body["database"]["detail"]


# ---------------------------------------------------------------------------
# GET /api/goals -- listing and filtering
# ---------------------------------------------------------------------------


def test_list_defaults_to_the_single_user_scope(client):
    """With no user_id the list is scoped to DEFAULT_USER_ID (Release 0)."""
    body = client.get("/api/goals").get_json()

    assert body["count"] == 8
    assert {goal["user_id"] for goal in body["goals"]} == {1}


def test_list_can_be_scoped_to_another_user(client):
    body = client.get("/api/goals?user_id=2").get_json()

    assert body["count"] == 3
    assert {goal["user_id"] for goal in body["goals"]} == {2}


def test_list_all_lifts_the_user_scope(client):
    body = client.get("/api/goals?user_id=all").get_json()

    assert body["count"] == 13
    assert {goal["user_id"] for goal in body["goals"]} == {1, 2, 3}


def test_list_filters_by_status_and_priority_together(client):
    body = client.get("/api/goals?user_id=all&status=active&priority=high").get_json()

    assert sorted(_goal_ids(body)) == [1, 3, 6, 9, 12]
    for goal in body["goals"]:
        assert goal["status"] == "active"
        assert goal["priority"] == "high"


def test_list_orders_by_priority_then_deadline(client):
    """High priority first, then the nearest target date -- dashboard order."""
    goals = client.get("/api/goals").get_json()["goals"]

    priorities = [goal["priority"] for goal in goals]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)
    high_dates = [goal["target_date"] for goal in goals if goal["priority"] == "high"]
    assert high_dates == sorted(high_dates)


def test_list_rows_carry_funding_figures_calculated_in_python(client):
    """Every list row is ready to draw a progress bar without a second call."""
    goals = client.get("/api/goals").get_json()["goals"]
    emergency_fund = next(goal for goal in goals if goal["goal_id"] == 1)

    assert emergency_fund["saved_to_date"] == 4202.00
    assert emergency_fund["remaining_amount"] == 5798.00
    assert emergency_fund["percent_complete"] == 42.0


def test_list_reports_zero_funding_rather_than_null_for_an_unfunded_goal(client):
    goals = client.get("/api/goals").get_json()["goals"]
    tuition = next(goal for goal in goals if goal["goal_id"] == 7)

    assert tuition["saved_to_date"] == 0.0
    assert tuition["percent_complete"] == 0.0
    assert tuition["remaining_amount"] == 8000.00


@pytest.mark.parametrize(
    "query, expected_detail",
    [
        ("status=finished", "status must be one of"),
        ("priority=urgent", "priority must be one of"),
        ("user_id=-1", "user_id must be a positive integer"),
        ("user_id=nobody", "user_id must be a positive integer"),
    ],
)
def test_list_rejects_unusable_filters(client, query, expected_detail):
    response = client.get(f"/api/goals?{query}")

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "Validation failed"
    assert any(expected_detail in detail for detail in body["details"])


# ---------------------------------------------------------------------------
# GET /api/goals/<id>
# ---------------------------------------------------------------------------


def test_detail_includes_ordered_steps_and_the_contribution_total(client):
    body = client.get("/api/goals/1").get_json()

    assert body["name"] == "Emergency Fund"
    assert body["saved_to_date"] == 4202.00
    assert body["contribution_count"] == 5
    assert len(body["steps"]) == 12
    assert [step["step_order"] for step in body["steps"]] == list(range(1, 13))
    assert body["steps"][0]["status"] == "complete"


def test_detail_of_a_goal_with_no_plan_returns_empty_collections(client):
    body = client.get("/api/goals/7").get_json()

    assert body["steps"] == []
    assert body["contributions"] == []
    assert body["contribution_count"] == 0
    assert body["saved_to_date"] == 0.0


def test_detail_404s_for_a_goal_that_does_not_exist(client):
    response = client.get("/api/goals/9999")

    assert response.status_code == 404
    assert response.get_json()["error"] == "No goal with id 9999"


# ---------------------------------------------------------------------------
# POST /api/goals
# ---------------------------------------------------------------------------


def test_create_returns_201_with_the_stored_goal_and_a_location_header(client, conn):
    response = client.post(
        "/api/goals",
        json={"name": "New Bike Helmet", "target_amount": 180, "target_date": FUTURE_DATE, "priority": "low"},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert response.headers["Location"] == f"/api/goals/{body['goal_id']}"
    assert body["name"] == "New Bike Helmet"
    assert body["target_amount"] == 180.0
    assert body["status"] == "active"  # defaulted
    assert body["saved_to_date"] == 0.0
    assert body["steps"] == []

    stored = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (body["goal_id"],)).fetchone()
    assert stored["name"] == "New Bike Helmet"
    assert stored["created_at"] == stored["updated_at"]


def test_create_stamps_the_default_user_when_the_client_names_none(client):
    body = client.post(
        "/api/goals", json={"name": "Unowned", "target_amount": 100, "target_date": FUTURE_DATE}
    ).get_json()

    assert body["user_id"] == 1
    assert body["priority"] == "medium"  # defaulted


def test_create_accepts_an_explicit_user_id(client):
    body = client.post(
        "/api/goals",
        json={"name": "For user 3", "target_amount": 100, "target_date": FUTURE_DATE, "user_id": 3},
    ).get_json()

    assert body["user_id"] == 3


def test_create_ignores_a_client_supplied_timestamp(client, conn):
    """created_at is set server-side; a client cannot backdate a row."""
    body = client.post(
        "/api/goals",
        json={
            "name": "Backdated",
            "target_amount": 100,
            "target_date": FUTURE_DATE,
            "created_at": "1999-01-01T00:00:00",
        },
    ).get_json()

    assert not body["created_at"].startswith("1999")


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({"target_amount": 100, "target_date": FUTURE_DATE}, "name is required"),
        ({"name": "   ", "target_amount": 100, "target_date": FUTURE_DATE}, "name must not be empty"),
        ({"name": "x" * 121, "target_amount": 100, "target_date": FUTURE_DATE}, "name must be 120 characters or fewer"),
        ({"name": "No amount", "target_date": FUTURE_DATE}, "target_amount is required"),
        ({"name": "Negative", "target_amount": -5, "target_date": FUTURE_DATE}, "target_amount must be greater than 0"),
        ({"name": "Zero", "target_amount": 0, "target_date": FUTURE_DATE}, "target_amount must be greater than 0"),
        ({"name": "Text amount", "target_amount": "lots", "target_date": FUTURE_DATE}, "target_amount must be a number"),
        ({"name": "Boolean amount", "target_amount": True, "target_date": FUTURE_DATE}, "target_amount must be a number"),
        ({"name": "Huge", "target_amount": 1e12, "target_date": FUTURE_DATE}, "target_amount must be"),
        ({"name": "No date", "target_amount": 100}, "target_date is required"),
        ({"name": "Bad date", "target_amount": 100, "target_date": "30/06/2030"}, "target_date must be an ISO-8601 date"),
        ({"name": "Unpadded date", "target_amount": 100, "target_date": "2030-6-3"}, "target_date must be an ISO-8601 date"),
        ({"name": "Past date", "target_amount": 100, "target_date": PAST_DATE}, "is in the past"),
        ({"name": "Bad priority", "target_amount": 100, "target_date": FUTURE_DATE, "priority": "urgent"}, "priority must be one of"),
        ({"name": "Bad status", "target_amount": 100, "target_date": FUTURE_DATE, "status": "done"}, "status must be one of"),
        ({"name": "Bad user", "target_amount": 100, "target_date": FUTURE_DATE, "user_id": 0}, "user_id must be a positive integer"),
    ],
)
def test_create_rejects_invalid_payloads(client, payload, expected_detail):
    response = client.post("/api/goals", json=payload)

    assert response.status_code == 400
    details = response.get_json()["details"]
    assert any(expected_detail in detail for detail in details), details


def test_create_reports_every_problem_at_once(client):
    """A form should be able to show all its errors after one round trip."""
    response = client.post("/api/goals", json={"target_amount": -1, "priority": "urgent"})

    details = response.get_json()["details"]
    assert len(details) >= 4  # name, target_amount, target_date, priority


def test_create_rejects_a_body_that_is_not_an_object(client):
    response = client.post("/api/goals", json=["not", "an", "object"])

    assert response.status_code == 400
    assert "request body must be a JSON object" in response.get_json()["details"]


def test_create_rejects_malformed_json_with_json(client):
    """Even a broken body gets a JSON error, never an HTML error page."""
    response = client.post("/api/goals", data="{not json", content_type="application/json")

    assert response.status_code == 400
    assert response.is_json
    assert "error" in response.get_json()


def test_a_past_target_date_is_allowed_on_a_goal_that_is_not_active(client):
    """The rule exists because an active goal must be plannable, nothing more."""
    response = client.post(
        "/api/goals",
        json={"name": "Historical", "target_amount": 100, "target_date": PAST_DATE, "status": "achieved"},
    )

    assert response.status_code == 201


# ---------------------------------------------------------------------------
# PUT /api/goals/<id>
# ---------------------------------------------------------------------------


def test_update_merges_and_leaves_unmentioned_fields_alone(client):
    before = client.get("/api/goals/2").get_json()

    body = client.put("/api/goals/2", json={"priority": "high"}).get_json()

    assert body["priority"] == "high"
    assert body["name"] == before["name"]
    assert body["target_amount"] == before["target_amount"]
    assert body["target_date"] == before["target_date"]


def test_update_touches_updated_at_but_not_created_at(client):
    before = client.get("/api/goals/2").get_json()

    body = client.put("/api/goals/2", json={"name": "Japan Trip 2027 (revised)"}).get_json()

    assert body["created_at"] == before["created_at"]
    assert body["updated_at"] != before["updated_at"]


def test_update_keeps_steps_and_contributions(client):
    """Editing a goal must not disturb its plan or its payment history."""
    body = client.put("/api/goals/3", json={"target_amount": 3000}).get_json()

    assert body["target_amount"] == 3000.0
    assert len(body["steps"]) == 6
    assert body["saved_to_date"] == 450.0


def test_update_refuses_to_move_a_goal_to_another_user(client):
    response = client.put("/api/goals/2", json={"user_id": 3})

    assert response.status_code == 400
    assert "user_id cannot be changed" in response.get_json()["details"]


def test_update_rejects_an_empty_body(client):
    response = client.put("/api/goals/2", json={})

    assert response.status_code == 400
    assert any("no updatable fields" in detail for detail in response.get_json()["details"])


def test_update_rejects_back_dating_an_active_goal(client):
    response = client.put("/api/goals/2", json={"target_date": PAST_DATE})

    assert response.status_code == 400
    assert any("is in the past" in detail for detail in response.get_json()["details"])


def test_update_allows_back_dating_when_the_goal_is_paused_in_the_same_request(client):
    response = client.put("/api/goals/2", json={"target_date": PAST_DATE, "status": "paused"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "paused"


def test_update_404s_for_a_goal_that_does_not_exist(client):
    response = client.put("/api/goals/9999", json={"name": "Ghost"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/goals/<id>
# ---------------------------------------------------------------------------


def test_delete_returns_204_and_an_empty_body(client):
    response = client.delete("/api/goals/4")

    assert response.status_code == 204
    assert response.data == b""
    assert client.get("/api/goals/4").status_code == 404


def test_delete_cascades_to_steps_and_contributions(client, conn):
    assert conn.execute("SELECT COUNT(*) FROM goal_steps WHERE goal_id = 3").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM contributions WHERE goal_id = 3").fetchone()[0] == 2

    client.delete("/api/goals/3")

    assert conn.execute("SELECT COUNT(*) FROM goal_steps WHERE goal_id = 3").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contributions WHERE goal_id = 3").fetchone()[0] == 0


def test_delete_keeps_the_ai_audit_trail(client, conn):
    """ai_plan_log survives with a NULL goal_id -- it is the report's evidence."""
    before = conn.execute("SELECT COUNT(*) FROM ai_plan_log").fetchone()[0]
    orphans_before = conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE goal_id IS NULL").fetchone()[0]

    client.delete("/api/goals/3")

    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM ai_plan_log WHERE goal_id IS NULL").fetchone()[0] == orphans_before + 3


def test_delete_is_not_idempotent_and_404s_the_second_time(client):
    assert client.delete("/api/goals/5").status_code == 204
    assert client.delete("/api/goals/5").status_code == 404


def test_deleting_a_goal_does_not_disturb_the_others(client):
    client.delete("/api/goals/4")

    assert client.get("/api/goals?user_id=all").get_json()["count"] == 12
    assert client.get("/api/goals/1").status_code == 200


# ---------------------------------------------------------------------------
# Cross-cutting HTTP behaviour
# ---------------------------------------------------------------------------


def test_an_unknown_route_returns_json_not_html(client):
    response = client.get("/api/nonsense")

    assert response.status_code == 404
    assert response.is_json


def test_an_unsupported_method_returns_json(client):
    response = client.patch("/api/goals/1", json={"name": "nope"})

    assert response.status_code == 405
    assert response.is_json


def test_cors_headers_are_returned_for_the_frontend_origin(client):
    response = client.get("/api/goals", headers={"Origin": "http://localhost:8060"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8060"
    assert "Origin" in response.headers["Vary"]


def test_cors_headers_are_withheld_from_an_unlisted_origin(client):
    response = client.get("/api/goals", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_a_preflight_request_is_answered(client):
    """Flask answers OPTIONS itself; the CORS hook decorates that response."""
    response = client.options("/api/goals", headers={"Origin": "http://localhost:8060"})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8060"
    assert "PUT" in response.headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]


# ---------------------------------------------------------------------------
# Database-level guarantees the API depends on
# ---------------------------------------------------------------------------


def test_foreign_keys_are_enforced_on_the_request_connection(app):
    """ON DELETE CASCADE is inert unless every connection sets the pragma."""
    from app.db import get_db

    with app.app_context():
        conn = get_db()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO contributions (goal_id, amount, contribution_date) VALUES (9999, 10, '2026-09-03')"
            )
