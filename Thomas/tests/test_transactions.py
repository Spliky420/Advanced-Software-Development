import os
import sqlite3
import tempfile

import pytest

from Thomas.backend.app import app


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp()

    app.config["TESTING"] = True

    import Thomas.backend.app as backend_app

    backend_app.DATABASE = db_path

    connection = sqlite3.connect(db_path)

    connection.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            merchant TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'uncategorised',
            deduction_status TEXT NOT NULL DEFAULT 'not_reviewed',
            receipt_filename TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

    with app.test_client() as test_client:
        yield test_client

    os.close(db_fd)
    os.unlink(db_path)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200


def test_create_transaction(client):
    response = client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Officeworks",
            "description": "Printer ink",
            "amount": "89.95",
            "transaction_type": "expense",
            "category": "work",
            "deduction_status": "potentially_deductible"
        }
    )

    assert response.status_code == 200
    assert b"Officeworks" in response.data
    assert b"Printer ink" in response.data


def test_get_transactions(client):
    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Woolworths",
            "description": "Groceries",
            "amount": "75.50",
            "transaction_type": "expense",
            "category": "groceries",
            "deduction_status": "not_deductible"
        }
    )

    response = client.get("/api/transactions")

    assert response.status_code == 200
    assert b"Woolworths" in response.data


def test_update_transaction(client):
    create_response = client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "JB Hi-Fi",
            "description": "USB hub",
            "amount": "59.00",
            "transaction_type": "expense",
            "category": "other",
            "deduction_status": "not_reviewed"
        }
    )

    response = client.put(
        "/api/transactions/1",
        data={
            "merchant": "JB Hi-Fi",
            "description": "USB-C hub",
            "amount": "65.00",
            "category": "work",
            "deduction_status": "potentially_deductible"
        }
    )

    assert response.status_code == 200
    assert b"USB-C hub" in response.data
    assert b"work" in response.data


def test_delete_transaction(client):
    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Netflix",
            "description": "Subscription",
            "amount": "22.99",
            "transaction_type": "expense",
            "category": "entertainment",
            "deduction_status": "not_deductible"
        }
    )

    response = client.delete("/api/transactions/1")

    assert response.status_code == 204

    get_response = client.get("/api/transactions")

    assert b"Netflix" not in get_response.data


def test_filter_transactions(client):
    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Officeworks",
            "description": "Printer ink",
            "amount": "89.95",
            "transaction_type": "expense",
            "category": "work",
            "deduction_status": "potentially_deductible"
        }
    )

    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Woolworths",
            "description": "Groceries",
            "amount": "80.00",
            "transaction_type": "expense",
            "category": "groceries",
            "deduction_status": "not_deductible"
        }
    )

    response = client.get(
        "/api/transactions?category=work"
    )

    assert response.status_code == 200
    assert b"Officeworks" in response.data
    assert b"Woolworths" not in response.data


def test_summary(client):
    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Employer",
            "description": "Salary",
            "amount": "3000.00",
            "transaction_type": "income",
            "category": "income",
            "deduction_status": "not_reviewed"
        }
    )

    client.post(
        "/api/transactions",
        data={
            "transaction_date": "2026-09-06",
            "merchant": "Officeworks",
            "description": "Printer ink",
            "amount": "100.00",
            "transaction_type": "expense",
            "category": "work",
            "deduction_status": "potentially_deductible"
        }
    )

    response = client.get("/api/transactions/summary")

    assert response.status_code == 200

    assert b"$3,000.00" in response.data
    assert b"$100.00" in response.data


def test_ai_classify_missing_input(client):
    response = client.post(
        "/api/transactions/ai-classify",
        data={}
    )

    assert response.status_code == 400


def test_edit_form_not_found(client):
    response = client.get(
        "/api/transactions/999/edit"
    )

    assert response.status_code == 404