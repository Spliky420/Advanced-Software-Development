import sqlite3

import app as app_module
import db
import llm


def valid_bill():
    return {
        "name": "Test Subscription",
        "provider": "Example Provider",
        "category": "Software",
        "amount": 14.99,
        "billing_frequency": "monthly",
        "next_due_date": "2026-09-25",
        "auto_renew": True,
        "trial_end_date": None,
        "status": "active",
        "notes": "API test",
    }


def test_health_and_seeded_records(client):
    health = client.get("/health")
    bills = client.get("/api/bills")

    assert health.status_code == 200
    assert health.get_json() == {"bill_count": 10, "status": "healthy"}
    assert bills.status_code == 200
    assert len(bills.get_json()) == 10


def test_endpoints_only_return_the_default_users_bills(client):
    with sqlite3.connect(db.DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO bills (
                user_id, name, provider, category, amount,
                billing_frequency, next_due_date, auto_renew,
                trial_end_date, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                "Another User Bill",
                "Private Provider",
                "Other",
                50,
                "monthly",
                "2026-09-20",
                0,
                None,
                "active",
                "Should stay private",
            ),
        )
        connection.commit()

    bills = client.get("/api/bills").get_json()
    health = client.get("/health").get_json()

    assert len(bills) == 10
    assert all(bill["user_id"] == db.DEFAULT_USER_ID for bill in bills)
    assert health["bill_count"] == 10


def test_create_read_update_and_delete_bill(client):
    created = client.post("/api/bills", json=valid_bill())

    assert created.status_code == 201
    bill_id = created.get_json()["id"]

    fetched = client.get(f"/api/bills/{bill_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["name"] == "Test Subscription"

    updated_payload = valid_bill()
    updated_payload.update({"name": "Updated Subscription", "status": "paused"})
    updated = client.put(f"/api/bills/{bill_id}", json=updated_payload)

    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Updated Subscription"
    assert updated.get_json()["status"] == "paused"

    deleted = client.delete(f"/api/bills/{bill_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/bills/{bill_id}").status_code == 404


def test_create_rejects_invalid_and_duplicate_bills(client):
    invalid = valid_bill()
    invalid["amount"] = 0

    invalid_response = client.post("/api/bills", json=invalid)
    duplicate_response = client.post(
        "/api/bills",
        json={
            **valid_bill(),
            "name": "Netflix",
            "provider": "Netflix",
        },
    )

    assert invalid_response.status_code == 400
    assert "amount" in invalid_response.get_json()["errors"]
    assert duplicate_response.status_code == 409


def test_summary_matches_seeded_records(client):
    response = client.get("/api/summary")
    summary = response.get_json()

    assert response.status_code == 200
    assert summary["active_bill_count"] == 10
    assert summary["auto_renew_count"] == 9
    assert summary["monthly_cost"] == 620.24
    assert summary["annual_cost"] == 7442.9


def test_review_endpoint_returns_all_four_real_phases(client, monkeypatch):
    monkeypatch.setattr(app_module.llm, "generate", lambda prompt: "supportive")

    response = client.post(
        "/api/bills/review",
        json={"review_date": "2026-09-01", "window_days": 30},
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["plan"]["priority_order"][0] == "overdue bills"
    assert body["act"]["active_bill_count"] == 10
    assert len(body["observe"]["overdue"]) == 1
    assert len(body["observe"]["due_soon"]) == 6
    assert len(body["observe"]["upcoming_auto_renewals"]) == 8
    assert len(body["observe"]["expiring_trials"]) == 1
    assert body["adapt"]["priority"]["type"] == "overdue"
    assert body["adapt"]["summary_tone"] == "supportive"


def test_review_rejects_invalid_period(client):
    response = client.post(
        "/api/bills/review",
        json={"review_date": "2026-09-01", "window_days": 100},
    )

    assert response.status_code == 400
    assert "between 1 and 90" in response.get_json()["error"]


def test_review_reports_when_ollama_is_unavailable(client, monkeypatch):
    def unavailable(prompt):
        raise llm.LLMError("Could not reach the Ollama service.")

    monkeypatch.setattr(app_module.llm, "generate", unavailable)

    response = client.post(
        "/api/bills/review",
        json={"review_date": "2026-09-01", "window_days": 30},
    )
    body = response.get_json()

    assert response.status_code == 503
    assert body["plan"]["phase"] == "plan"
    assert body["act"]["phase"] == "act"
    assert body["observe"]["phase"] == "observe"
    assert "Could not reach" in body["adapt"]["error"]
