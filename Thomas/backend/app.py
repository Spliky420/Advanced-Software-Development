from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
import json
import requests
from werkzeug.utils import secure_filename

app = Flask(__name__)

DATABASE = os.getenv("DATABASE_PATH", "transactions.db")

UPLOAD_FOLDER = "uploads/receipts"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def load_prompt(filename):
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", filename)

    with open(prompt_path, "r", encoding="utf-8") as file:
        return file.read()


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
    return jsonify({"status": "ok", "service": "transactions-backend"})


@app.route("/api/transactions/ai-classify", methods=["POST"])
def ai_classify_transaction():
    merchant = request.form.get("merchant", "").strip()
    description = request.form.get("description", "").strip()
    amount = request.form.get("amount", "").strip()
    transaction_type = request.form.get("transaction_type", "expense").strip()

    if not merchant and not description:
        return (
            """
            <div class="ai-suggestion error">
                Please enter a merchant or description first.
            </div>
        """,
            400,
        )

    try:
        prompt_template = load_prompt("transaction_classification.txt")

        prompt = prompt_template.format(
            merchant=merchant,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
        )

        ollama_response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "qwen2.5:0.5b",
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=60,
        )

        ollama_response.raise_for_status()

        ollama_data = ollama_response.json()

        ai_response = ollama_data.get("response", "{}")

        classification = json.loads(ai_response)

        category = classification.get("category", "uncategorised")

        deduction_status = classification.get("deduction_status", "needs_review")

        reason = classification.get("reason", "No explanation provided.")

        return f"""
            <div class="ai-suggestion">

                <h4>AI Suggestion</h4>

                <p>
                    <strong>Category:</strong>
                    {category}
                </p>

                <p>
                    <strong>Deduction status:</strong>
                    {deduction_status}
                </p>

                <p>
                    <strong>Reason:</strong>
                    {reason}
                </p>

                <p class="ai-warning">
                    This is an AI-generated suggestion.
                    Review the classification before saving the transaction.
                </p>

            </div>
        """

    except FileNotFoundError:
        return (
            """
            <div class="ai-suggestion error">
                AI prompt file could not be found.
            </div>
        """,
            500,
        )

    except requests.exceptions.ConnectionError:
        return (
            """
            <div class="ai-suggestion error">
                Could not connect to Ollama.
                Make sure Ollama is running.
            </div>
        """,
            503,
        )

    except requests.exceptions.Timeout:
        return (
            """
            <div class="ai-suggestion error">
                Ollama took too long to respond.
            </div>
        """,
            504,
        )

    except requests.exceptions.HTTPError as error:
        print("Ollama HTTP error:", error)

        return (
            """
            <div class="ai-suggestion error">
                Ollama returned an error.
            </div>
        """,
            502,
        )

    except json.JSONDecodeError:
        print("Invalid AI JSON response:", ai_response)

        return (
            """
            <div class="ai-suggestion error">
                The AI returned an invalid response.
                Please try again.
            </div>
        """,
            500,
        )

    except Exception as error:
        print("AI classification error:", error)

        return (
            """
            <div class="ai-suggestion error">
                AI classification failed.
            </div>
        """,
            500,
        )


@app.route("/api/transactions/summary", methods=["GET"])
def transaction_summary():
    connection = get_db()

    total_income = connection.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE transaction_type = 'income'
    """).fetchone()[0]

    total_expenses = connection.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE transaction_type = 'expense'
    """).fetchone()[0]

    potential_deductions = connection.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE transaction_type = 'expense'
        AND deduction_status = 'potentially_deductible'
    """).fetchone()[0]

    connection.close()

    return f"""
        <div class="summary-card">
            <span>Total Income</span>
            <strong>${total_income:,.2f}</strong>
        </div>

        <div class="summary-card">
            <span>Total Expenses</span>
            <strong>${total_expenses:,.2f}</strong>
        </div>

        <div class="summary-card">
            <span>Potential Deductions</span>
            <strong>${potential_deductions:,.2f}</strong>
        </div>
    """


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
        "merchant_desc": "merchant DESC",
    }

    order_by = sort_options.get(sort, "transaction_date DESC")

    query += f" ORDER BY {order_by}"

    connection = get_db()

    transactions = connection.execute(query, params).fetchall()

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
    deduction_status = request.form.get("deduction_status", "not_reviewed")

    receipt_filename = None

    if "receipt" in request.files:
        receipt = request.files["receipt"]

        if receipt and receipt.filename:
            filename = secure_filename(receipt.filename)

            receipt.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

            receipt_filename = filename

    connection = get_db()

    cursor = connection.execute(
        """
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
    """,
        (
            transaction_date,
            merchant,
            description,
            amount,
            transaction_type,
            category,
            deduction_status,
            receipt_filename,
        ),
    )

    connection.commit()

    transaction_id = cursor.lastrowid

    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()

    connection.close()

    return render_transaction_row(transaction)


@app.route("/api/transactions/<int:transaction_id>/edit", methods=["GET"])
def edit_transaction_form(transaction_id):
    connection = get_db()

    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()

    connection.close()

    if transaction is None:
        return "Transaction not found", 404

    return f"""
        <tr id="transaction-{transaction['id']}">
            <td colspan="9">

                <form
    hx-put="/api/transactions/{transaction['id']}"
    hx-target="#transaction-{transaction['id']}"
    hx-swap="outerHTML"
    hx-on::after-request="
        htmx.ajax('GET', '/api/transactions/summary', {{
            target: '#summary-grid',
            swap: 'innerHTML'
        }})
    "
    class="edit-form"
>

                    <div class="edit-grid">

                        <input
                            type="date"
                            name="transaction_date"
                            value="{transaction['transaction_date']}"
                            required
                        >

                        <input
                            type="text"
                            name="merchant"
                            value="{transaction['merchant']}"
                            required
                        >

                        <input
                            type="text"
                            name="description"
                            value="{transaction['description']}"
                            required
                        >

                        <input
                            type="number"
                            name="amount"
                            step="0.01"
                            min="0"
                            value="{transaction['amount']}"
                            required
                        >

                        <select name="transaction_type">
                            <option
                                value="expense"
                                {"selected" if transaction['transaction_type'] == 'expense' else ""}
                            >
                                Expense
                            </option>

                            <option
                                value="income"
                                {"selected" if transaction['transaction_type'] == 'income' else ""}
                            >
                                Income
                            </option>
                        </select>

                        <select name="category">
                            {category_options(transaction['category'])}
                        </select>

                        <select name="deduction_status">
                            {deduction_options(transaction['deduction_status'])}
                        </select>

                    </div>

                    <div class="button-row">

                        <button
                            type="submit"
                            class="button button-primary"
                        >
                            Save
                        </button>

                        <button
                            type="button"
                            class="button button-secondary"
                            hx-get="/api/transactions"
                            hx-target="#transaction-table-body"
                        >
                            Cancel
                        </button>

                    </div>

                </form>

            </td>
        </tr>
    """


@app.route("/api/transactions/<int:transaction_id>", methods=["PUT"])
def update_transaction(transaction_id):
    data = request.form

    connection = get_db()

    existing = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()

    if existing is None:
        connection.close()

        return jsonify({"error": "Transaction not found"}), 404

    transaction_date = data.get("transaction_date", existing["transaction_date"])

    merchant = data.get("merchant", existing["merchant"])

    description = data.get("description", existing["description"])

    amount = data.get("amount", existing["amount"])

    transaction_type = data.get("transaction_type", existing["transaction_type"])

    category = data.get("category", existing["category"])

    deduction_status = data.get("deduction_status", existing["deduction_status"])

    connection.execute(
        """
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
    """,
        (
            transaction_date,
            merchant,
            description,
            amount,
            transaction_type,
            category,
            deduction_status,
            transaction_id,
        ),
    )

    connection.commit()

    updated = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()

    connection.close()

    return render_transaction_row(updated)


@app.route("/api/transactions/<int:transaction_id>", methods=["DELETE"])
def delete_transaction(transaction_id):
    connection = get_db()

    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()

    if transaction is None:
        connection.close()

        return jsonify({"error": "Transaction not found"}), 404

    connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    connection.commit()
    connection.close()

    return "", 204


@app.route("/receipts/<filename>")
def receipt(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def render_transaction_rows(transactions):
    if not transactions:
        return """
        <tr>
            <td colspan="9" class="loading">
                No transactions found.
            </td>
        </tr>
        """

    return "".join(render_transaction_row(transaction) for transaction in transactions)


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
        class="action-button edit-button"
        hx-get="/api/transactions/{transaction['id']}/edit"
        hx-target="#transaction-{transaction['id']}"
        hx-swap="outerHTML"
    >
        Edit
    </button>

<button
    class="action-button delete-button"
    hx-delete="/api/transactions/{transaction['id']}"
    hx-target="#transaction-{transaction['id']}"
    hx-swap="outerHTML"
    hx-confirm="Delete this transaction?"
    hx-on::after-request="
        htmx.ajax('GET', '/api/transactions', {{
            target: '#transaction-table-body',
            swap: 'innerHTML'
        }});

        htmx.ajax('GET', '/api/transactions/summary', {{
            target: '#summary-grid',
            swap: 'innerHTML'
        }});
    "
>
    Delete
</button>
</td>

        </tr>
    """


def category_options(selected_category):
    categories = [
        ("uncategorised", "Uncategorised"),
        ("groceries", "Groceries"),
        ("transport", "Transport"),
        ("utilities", "Utilities"),
        ("entertainment", "Entertainment"),
        ("work", "Work Expenses"),
        ("health", "Health"),
        ("education", "Education"),
        ("income", "Income"),
        ("other", "Other"),
    ]

    return "".join(f"""
        <option
            value="{value}"
            {"selected" if value == selected_category else ""}
        >
            {label}
        </option>
        """ for value, label in categories)


def deduction_options(selected_status):
    statuses = [
        ("not_reviewed", "Not Reviewed"),
        ("potentially_deductible", "Potentially Deductible"),
        ("not_deductible", "Not Deductible"),
        ("needs_review", "Needs Review"),
    ]

    return "".join(f"""
        <option
            value="{value}"
            {"selected" if value == selected_status else ""}
        >
            {label}
        </option>
        """ for value, label in statuses)


def seed_db():
    connection = get_db()

    count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    if count > 0:
        connection.close()
        return

    sample_transactions = [
        (
            "2026-08-01",
            "Employer Payroll",
            "Monthly salary",
            3200.00,
            "income",
            "income",
            "not_reviewed",
            None,
            "Monthly salary payment",
        ),
        (
            "2026-08-02",
            "Woolworths",
            "Weekly groceries",
            86.45,
            "expense",
            "groceries",
            "not_deductible",
            None,
            "Food and household items",
        ),
        (
            "2026-08-03",
            "Shell",
            "Fuel",
            72.30,
            "expense",
            "transport",
            "needs_review",
            None,
            "Fuel purchase",
        ),
        (
            "2026-08-04",
            "Officeworks",
            "Printer ink",
            89.95,
            "expense",
            "work",
            "potentially_deductible",
            None,
            "Printer ink for home office",
        ),
        (
            "2026-08-05",
            "Netflix",
            "Monthly subscription",
            22.99,
            "expense",
            "entertainment",
            "not_deductible",
            None,
            "Streaming subscription",
        ),
        (
            "2026-08-06",
            "Sydney Trains",
            "Opal travel",
            42.50,
            "expense",
            "transport",
            "not_deductible",
            None,
            "Public transport",
        ),
        (
            "2026-08-07",
            "Chemist Warehouse",
            "Pharmacy purchase",
            38.75,
            "expense",
            "health",
            "not_deductible",
            None,
            "Personal health products",
        ),
        (
            "2026-08-08",
            "University Bookshop",
            "Software engineering textbook",
            74.99,
            "expense",
            "education",
            "potentially_deductible",
            None,
            "Study-related textbook",
        ),
        (
            "2026-08-09",
            "Origin Energy",
            "Electricity bill",
            145.60,
            "expense",
            "utilities",
            "needs_review",
            None,
            "Monthly electricity bill",
        ),
        (
            "2026-08-10",
            "Freelance Client",
            "Website development payment",
            550.00,
            "income",
            "income",
            "not_reviewed",
            None,
            "Freelance income",
        ),
        (
            "2026-08-11",
            "JB Hi-Fi",
            "USB-C hub",
            59.00,
            "expense",
            "work",
            "potentially_deductible",
            None,
            "Accessory used for study and work",
        ),
        (
            "2026-08-12",
            "McDonald's",
            "Lunch",
            16.85,
            "expense",
            "other",
            "not_deductible",
            None,
            "Personal meal",
        ),
    ]

    connection.executemany(
        """
        INSERT INTO transactions (
            transaction_date,
            merchant,
            description,
            amount,
            transaction_type,
            category,
            deduction_status,
            receipt_filename,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        sample_transactions,
    )

    connection.commit()
    connection.close()


if __name__ == "__main__":
    init_db()
    seed_db()

    app.run(host="0.0.0.0", port=5001, debug=True)
