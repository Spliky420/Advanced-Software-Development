import os
import sqlite3

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "portfolio.db"),
)

# Release 0 is single-user. user_id stays in the schema and every query below
# is still scoped by it, so adding real multi-user support later is a matter
# of passing a real user_id through instead of this constant, not a rewrite.
DEFAULT_USER_ID = 1

HOLDING_COLUMNS = (
    "user_id", "ticker", "asset_name", "asset_class", "units", "average_cost",
    "currency", "last_price", "price_as_at", "purchase_date", "notes",
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ping():
    conn = get_connection()
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()


def list_holdings(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM holdings WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_holding(holding_id, user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def create_holding(data, user_id):
    payload = dict(data)
    payload["user_id"] = user_id
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO holdings
                (user_id, ticker, asset_name, asset_class, units, average_cost,
                 currency, last_price, price_as_at, purchase_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(payload[col] for col in HOLDING_COLUMNS),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM holdings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_holding(holding_id, data, user_id):
    payload = dict(data)
    payload["user_id"] = user_id
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE holdings SET
                user_id = ?, ticker = ?, asset_name = ?, asset_class = ?, units = ?,
                average_cost = ?, currency = ?, last_price = ?, price_as_at = ?,
                purchase_date = ?, notes = ?
            WHERE id = ? AND user_id = ?
            """,
            tuple(payload[col] for col in HOLDING_COLUMNS) + (holding_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_holding(holding_id, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_targets(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM allocation_targets WHERE user_id = ? ORDER BY asset_class",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_insight_log(entry, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO insight_log
                (user_id, created_at, request_type, prompt_sent, model_name, response_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                entry["created_at"],
                entry["request_type"],
                entry["prompt_sent"],
                entry["model_name"],
                entry["response_text"],
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM insight_log WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def replace_targets(targets, user_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM allocation_targets WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO allocation_targets (user_id, asset_class, target_percent) VALUES (?, ?, ?)",
            [(user_id, t["asset_class"], t["target_percent"]) for t in targets],
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM allocation_targets WHERE user_id = ? ORDER BY asset_class",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
