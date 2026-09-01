import sqlite3
from datetime import date

from flask import Flask, jsonify, request

import calculations
import db
import review

app = Flask(__name__)

# Values accepted by the bill form and API.
FREQUENCIES = {
    "weekly",
    "fortnightly",
    "monthly",
    "quarterly",
    "yearly",
}

STATUSES = {
    "active",
    "paused",
    "cancelled",
}


# Allow the frontend container to call this API.
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


# Check dates and keep them in YYYY-MM-DD format.
def validate_date(value, field_name, errors, required=True):
    if value in (None, ""):
        if required:
            errors[field_name] = "This field is required."
        return None

    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        errors[field_name] = "Use YYYY-MM-DD format."
        return None


# Clean and check data before saving it.
def validate_bill(data):
    if not isinstance(data, dict):
        return None, {"request": "A JSON object is required."}

    errors = {}
    cleaned = {}

    for field in ("name", "provider", "category"):
        value = data.get(field)

        if not isinstance(value, str) or not value.strip():
            errors[field] = "This field is required."
        else:
            cleaned[field] = value.strip()

    amount = data.get("amount")

    try:
        if isinstance(amount, bool):
            raise ValueError

        amount = float(amount)

        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors["amount"] = "Amount must be greater than zero."
    else:
        cleaned["amount"] = round(amount, 2)

    frequency = data.get("billing_frequency")

    if frequency not in FREQUENCIES:
        errors["billing_frequency"] = (
            "Use weekly, fortnightly, monthly, quarterly or yearly."
        )
    else:
        cleaned["billing_frequency"] = frequency

    cleaned["next_due_date"] = validate_date(
        data.get("next_due_date"),
        "next_due_date",
        errors,
    )

    cleaned["trial_end_date"] = validate_date(
        data.get("trial_end_date"),
        "trial_end_date",
        errors,
        required=False,
    )

    auto_renew = data.get("auto_renew", False)

    if auto_renew not in (True, False, 0, 1):
        errors["auto_renew"] = "Use true or false."
    else:
        cleaned["auto_renew"] = int(bool(auto_renew))

    status = data.get("status", "active")

    if status not in STATUSES:
        errors["status"] = "Use active, paused or cancelled."
    else:
        cleaned["status"] = status

    notes = data.get("notes", "")

    if notes is None:
        notes = ""

    if not isinstance(notes, str):
        errors["notes"] = "Notes must be text."
    else:
        cleaned["notes"] = notes.strip()

    if errors:
        return None, errors

    return cleaned, None


# Confirm that the database can be reached.
@app.get("/health")
def health():
    try:
        with db.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM bills"
            ).fetchone()[0]

        return jsonify({
            "status": "healthy",
            "bill_count": count,
        })
    except Exception as error:
        return jsonify({
            "status": "unhealthy",
            "error": str(error),
        }), 503


# Return every saved bill.
@app.get("/api/bills")
def get_bills():
    return jsonify(db.list_bills())


# Return one bill or a not-found response.
@app.get("/api/bills/<int:bill_id>")
def get_bill(bill_id):
    bill = db.get_bill(bill_id)

    if bill is None:
        return jsonify({"error": "Bill not found"}), 404

    return jsonify(bill)


# Validate and create a new bill.
@app.post("/api/bills")
def create_bill():
    cleaned, errors = validate_bill(request.get_json(silent=True))

    if errors:
        return jsonify({"errors": errors}), 400

    try:
        bill = db.create_bill(cleaned)
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "A bill with this name and provider already exists."
        }), 409

    return jsonify(bill), 201


# Validate and update an existing bill.
@app.put("/api/bills/<int:bill_id>")
def update_bill(bill_id):
    cleaned, errors = validate_bill(request.get_json(silent=True))

    if errors:
        return jsonify({"errors": errors}), 400

    try:
        bill = db.update_bill(bill_id, cleaned)
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "A bill with this name and provider already exists."
        }), 409

    if bill is None:
        return jsonify({"error": "Bill not found"}), 404

    return jsonify(bill)


# Delete an existing bill.
@app.delete("/api/bills/<int:bill_id>")
def delete_bill(bill_id):
    if not db.delete_bill(bill_id):
        return jsonify({"error": "Bill not found"}), 404

    return "", 204


# Return the combined cost of all active bills.
@app.get("/api/summary")
def get_summary():
    bills = db.list_bills()
    return jsonify(calculations.build_cost_summary(bills))


# Run the first three agentic review phases.
@app.post("/api/bills/review")
def review_bills():
    data = request.get_json(silent=True) or {}

    try:
        plan_result = review.plan(
            review_date=data.get("review_date"),
            window_days=data.get("window_days", review.DEFAULT_WINDOW_DAYS),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    bills = db.list_bills()
    act_result = review.act(bills, plan_result)
    observe_result = review.observe(act_result, plan_result)

    return jsonify({
        "plan": plan_result,
        "act": act_result,
        "observe": observe_result,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
