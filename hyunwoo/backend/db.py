import json
import os
import sqlite3


DEFAULT_USER_ID = 1


# Database file shared with the database container.
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "database",
        "bills.db",
    ),
)


# Open the database and return rows by column name.
def connect():
    connection = sqlite3.connect(
        f"file:{DB_PATH}?mode=rw",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


# Return one user's bills in due-date order.
def list_bills(user_id):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM bills
            WHERE user_id = ?
            ORDER BY next_due_date, name
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


# Find one bill owned by the user.
def get_bill(bill_id, user_id):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM bills WHERE id = ? AND user_id = ?",
            (bill_id, user_id),
        ).fetchone()

    return dict(row) if row else None


# Add a bill for the user.
def create_bill(data, user_id):
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bills (
                user_id,
                name,
                provider,
                category,
                amount,
                billing_frequency,
                next_due_date,
                auto_renew,
                trial_end_date,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                data["name"],
                data["provider"],
                data["category"],
                data["amount"],
                data["billing_frequency"],
                data["next_due_date"],
                data["auto_renew"],
                data["trial_end_date"],
                data["status"],
                data["notes"],
            ),
        )
        connection.commit()

        row = connection.execute(
            "SELECT * FROM bills WHERE id = ? AND user_id = ?",
            (cursor.lastrowid, user_id),
        ).fetchone()

    return dict(row)


# Replace one of the user's bills.
def update_bill(bill_id, data, user_id):
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE bills
            SET name = ?,
                provider = ?,
                category = ?,
                amount = ?,
                billing_frequency = ?,
                next_due_date = ?,
                auto_renew = ?,
                trial_end_date = ?,
                status = ?,
                notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                data["name"],
                data["provider"],
                data["category"],
                data["amount"],
                data["billing_frequency"],
                data["next_due_date"],
                data["auto_renew"],
                data["trial_end_date"],
                data["status"],
                data["notes"],
                bill_id,
                user_id,
            ),
        )

        if cursor.rowcount == 0:
            return None

        connection.commit()

        row = connection.execute(
            "SELECT * FROM bills WHERE id = ? AND user_id = ?",
            (bill_id, user_id),
        ).fetchone()

    return dict(row)


# Delete one of the user's bills.
def delete_bill(bill_id, user_id):
    with connect() as connection:
        cursor = connection.execute(
            "DELETE FROM bills WHERE id = ? AND user_id = ?",
            (bill_id, user_id),
        )
        connection.commit()

    return cursor.rowcount > 0


# Add review links to existing databases without resetting bills.
def _workflow_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bill_workflows (
            run_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def save_workflow(run_id, user_id, evidence):
    with connect() as connection:
        _workflow_table(connection)
        connection.execute(
            "INSERT INTO bill_workflows (run_id, user_id, evidence_json) VALUES (?, ?, ?)",
            (run_id, user_id, json.dumps(evidence)),
        )
        connection.commit()


def get_workflow(run_id, user_id):
    with connect() as connection:
        _workflow_table(connection)
        row = connection.execute(
            "SELECT * FROM bill_workflows WHERE run_id = ? AND user_id = ?",
            (run_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "evidence": json.loads(row["evidence_json"]),
        "created_at": row["created_at"],
    }


def list_workflows(user_id):
    with connect() as connection:
        _workflow_table(connection)
        rows = connection.execute(
            """SELECT run_id, evidence_json, created_at FROM bill_workflows
               WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 20""",
            (user_id,),
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "review_date": json.loads(row["evidence_json"])["review_scope"]["review_date"],
        }
        for row in rows
    ]
