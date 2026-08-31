from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

DATABASE = "transactions.db"
UPLOAD_FOLDER = "uploads/receipts"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
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


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "transactions-backend"
    })


@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    transaction_type = request.args.get("transaction_type", "")
    deduction_status = request.args.get("deduction_status", "")
    sort = request.args.get("sort", "date_desc")

    query = """
        SELECT *
        FROM transactions
        WHERE 1 = 1
    """

    params = []

    if search:
        query += """
            AND (
                merchant LIKE ?
                OR description LIKE ?
            )
        """

        search_term = f"%{search}%"
        params.extend([search_term, search_term])

    if category:
        query += " AND category = ?"
        params.append(category)

    if transaction_type:
        query += " AND transaction_type = ?"
        params.append(transaction_type)

    if deduction_status:
        query += " AND deduction_status = ?"
        params.append(deduction_status)

    sort_options = {
        "date_desc": "transaction_date DESC",
        "date_asc": "transaction_date ASC",
        "amount_desc": "amount DESC",
        "amount_asc": "amount ASC",
        "merchant_asc": "merchant ASC",
        "merchant_desc": "merchant DESC"
    }

    order_by = sort_options.get(sort, "transaction_date DESC")

    query += f" ORDER BY {order_by}"

    connection = get_db()

    transactions = connection.execute(
        query,
        params
    ).fetchall()

    connection.close()

    return render_transaction_rows(transactions)


@app.route("/api/transactions", methods=["POST"])
def create_transaction():
    transaction_date = request.form.get("transaction_date")
    merchant = request.form.get("merchant")
    description = request.form.get("description")
    amount = request.form.get("amount")
    transaction_type = request.form.get("transaction_type")
    category = request.form.get("category", "uncategorised")
    deduction_status = request.form.get(
        "deduction_status",
        "not_reviewed"
    )

    receipt_filename = None

    if "receipt" in request.files:
        receipt = request.files["receipt"]

        if receipt and receipt.filename:
            filename = secure_filename(receipt.filename)

            receipt.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )

            receipt_filename = filename

    connection = get_db()

    cursor = connection.execute("""
        INSERT INTO transactions (
            transaction_date,
            merchant,
            description,
            amount,
            transaction_type,
            category,
            deduction_status,
            receipt_filename
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        transaction_date,
        merchant,
        description,
        amount,
        transaction_type,
        category,
        deduction_status,
        receipt_filename
    ))

    connection.commit()

    transaction_id = cursor.lastrowid

    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,)
    ).fetchone()

    connection.close()

    return render_transaction_row(transaction)


@app.route(
    "/api/transactions/<int:transaction_id>",
    methods=["PUT"]
)
def update_transaction(transaction_id):
    data = request.form

    connection = get_db()

    existing = connection.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,)
    ).fetchone()

    if existing is None:
        connection.close()

        return jsonify({
            "error": "Transaction not found"
        }), 404

    transaction_date = data.get(
        "transaction_date",
        existing["transaction_date"]
    )

    merchant = data.get(
        "merchant",
        existing["merchant"]
    )

    description = data.get(
        "description",
        existing["description"]
    )

    amount = data.get(
        "amount",
        existing["amount"]
    )

    transaction_type = data.get(
        "transaction_type",
        existing["transaction_type"]
    )

    category = data.get(
        "category",
        existing["category"]
    )

    deduction_status = data.get(
        "deduction_status",
        existing["deduction_status"]
    )

    connection.execute("""
        UPDATE transactions
        SET
            transaction_date = ?,
            merchant = ?,
            description = ?,
            amount = ?,
            transaction_type = ?,
            category = ?,
            deduction_status = ?
        WHERE id = ?
    """, (
        transaction_date,
        merchant,
        description,
        amount,
        transaction_type,
        category,
        deduction_status,
        transaction_id
    ))

    connection.commit()

    updated = connection.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,)
    ).fetchone()

    connection.close()

    return render_transaction_row(updated)


@app.route(
    "/api/transactions/<int:transaction_id>",
    methods=["DELETE"]
)
def delete_transaction(transaction_id):
    connection = get_db()

    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,)
    ).fetchone()

    if transaction is None:
        connection.close()

        return jsonify({
            "error": "Transaction not found"
        }), 404

    connection.execute(
        "DELETE FROM transactions WHERE id = ?",
        (transaction_id,)
    )

    connection.commit()
    connection.close()

    return "", 204


@app.route("/receipts/<filename>")
def receipt(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


def render_transaction_rows(transactions):
    if not transactions:
        return """
        <tr>
            <td colspan="9" class="loading">
                No transactions found.
            </td>
        </tr>
        """

    return "".join(
        render_transaction_row(transaction)
        for transaction in transactions
    )


def render_transaction_row(transaction):
    receipt_html = "—"

    if transaction["receipt_filename"]:
        receipt_html = f"""
            <a
                class="receipt-link"
                href="/receipts/{transaction['receipt_filename']}"
                target="_blank"
            >
                View
            </a>
        """

    return f"""
        <tr id="transaction-{transaction['id']}">

            <td>
                {transaction['transaction_date']}
            </td>

            <td>
                {transaction['merchant']}
            </td>

            <td>
                {transaction['description']}
            </td>

            <td>
                <span class="badge">
                    {transaction['category']}
                </span>
            </td>

            <td>
                {transaction['transaction_type']}
            </td>

            <td>
                ${transaction['amount']:.2f}
            </td>

            <td>
                <span class="badge">
                    {transaction['deduction_status']}
                </span>
            </td>

            <td>
                {receipt_html}
            </td>

            <td>
                <button
                    class="action-button delete-button"
                    hx-delete="/api/transactions/{transaction['id']}"
                    hx-target="#transaction-{transaction['id']}"
                    hx-swap="outerHTML"
                    hx-confirm="Delete this transaction?"
                >
                    Delete
                </button>
            </td>

        </tr>
    """


if __name__ == "__main__":
    init_db()

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )