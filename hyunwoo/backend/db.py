import os
import sqlite3


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


# Return all bills in due-date order.
def list_bills():
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM bills
            ORDER BY next_due_date, name
            """
        ).fetchall()

    return [dict(row) for row in rows]


# Find one bill by its ID.
def get_bill(bill_id):
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM bills WHERE id = ?",
            (bill_id,),
        ).fetchone()

    return dict(row) if row else None


# Add a bill and return the saved record.
def create_bill(data):
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO bills (
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        connection.commit()

        row = connection.execute(
            "SELECT * FROM bills WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


# Replace the details of an existing bill.
def update_bill(bill_id, data):
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
            WHERE id = ?
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
            ),
        )

        if cursor.rowcount == 0:
            return None

        connection.commit()

        row = connection.execute(
            "SELECT * FROM bills WHERE id = ?",
            (bill_id,),
        ).fetchone()

    return dict(row)


# Delete a bill and report whether it was found.
def delete_bill(bill_id):
    with connect() as connection:
        cursor = connection.execute(
            "DELETE FROM bills WHERE id = ?",
            (bill_id,),
        )
        connection.commit()

    return cursor.rowcount > 0
