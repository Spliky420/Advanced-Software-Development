from flask import Flask, render_template, request, Response
import requests
import os

BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "http://localhost:5001"
)

app = Flask(__name__)



@app.route("/")
def index():
    return render_template("index.html")

@app.route(
    "/api/transactions/<int:transaction_id>/edit",
    methods=["GET"]
)
def edit_transaction_form(transaction_id):
    response = requests.get(
        f"{BACKEND_URL}/api/transactions/{transaction_id}/edit"
    )

    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("Content-Type")
    )

@app.route("/api/transactions/summary", methods=["GET"])
def transaction_summary():
    response = requests.get(
        f"{BACKEND_URL}/api/transactions/summary"
    )

    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("Content-Type")
    )

@app.route("/api/transactions", methods=["GET", "POST"])
def transactions():
    if request.method == "GET":
        response = requests.get(
            f"{BACKEND_URL}/api/transactions",
            params=request.args
        )

    else:
        response = requests.post(
            f"{BACKEND_URL}/api/transactions",
            data=request.form,
            files=request.files
        )

    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("Content-Type")
    )


@app.route("/api/transactions/<int:transaction_id>", methods=["PUT", "DELETE"])
def transaction(transaction_id):
    if request.method == "PUT":
        response = requests.put(
            f"{BACKEND_URL}/api/transactions/{transaction_id}",
            data=request.form
        )

    else:
        response = requests.delete(
            f"{BACKEND_URL}/api/transactions/{transaction_id}"
        )

    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("Content-Type")
    )


@app.route("/api/transactions/ai-classify", methods=["POST"])
def ai_classify():
    response = requests.post(
        f"{BACKEND_URL}/api/transactions/ai-classify",
        data=request.form
    )

    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("Content-Type")
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )