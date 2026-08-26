import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import db
import allocation
import drift
import llm
from db import DEFAULT_USER_ID
from validation import ValidationError, validate_holding_payload, validate_targets_payload

INSIGHT_SYSTEM_PROMPT = (
    "You are a portfolio reporting assistant. You will be given a set of "
    "already-calculated portfolio figures. Using only those figures, write "
    "exactly three sentences in plain English: one sentence describing the "
    "overall composition of the portfolio, one sentence naming the single "
    "largest asset class concentration, and one sentence commenting on how "
    "diversified the portfolio is. Describe only -- never give advice, "
    "recommendations, or predictions. Never perform arithmetic yourself and "
    "never restate, recalculate, or invent any figure that is not given to "
    "you exactly as given below."
)


def _build_insight_prompt(portfolio):
    lines = [
        f"Total market value: ${portfolio['total_market_value']:.2f}",
        f"Total gain/loss: ${portfolio['total_gain_loss']:.2f}",
        "Asset class breakdown:",
    ]
    for item in portfolio["asset_class_allocation"]:
        lines.append(
            f"- {item['asset_class']}: ${item['market_value']:.2f} "
            f"({item['percent_of_total']:.2f}% of total market value)"
        )
    return "\n".join(lines)


def _round(value):
    return round(value, 2) if isinstance(value, float) else value


def _round_drift_row(row):
    rounded = dict(row)
    for key in ("target_percent", "actual_percent", "market_value",
                "drift_percentage_points", "drift_magnitude"):
        if key in rounded:
            rounded[key] = _round(rounded[key])
    return rounded


def _round_report(report):
    holdings = []
    for holding in report["holdings"]:
        rounded = dict(holding)
        for key in ("market_value", "cost_basis", "gain_loss", "gain_loss_percent"):
            rounded[key] = _round(rounded[key])
        holdings.append(rounded)

    portfolio = report["portfolio"]
    return {
        "holdings": holdings,
        "portfolio": {
            "total_market_value": _round(portfolio["total_market_value"]),
            "total_cost": _round(portfolio["total_cost"]),
            "total_gain_loss": _round(portfolio["total_gain_loss"]),
            "asset_class_allocation": [
                {
                    "asset_class": item["asset_class"],
                    "market_value": _round(item["market_value"]),
                    "percent_of_total": _round(item["percent_of_total"]),
                }
                for item in portfolio["asset_class_allocation"]
            ],
        },
    }


def create_app():
    app = Flask(__name__)

    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception as exc:
            return jsonify({"status": "error", "database": "unreachable", "detail": str(exc)}), 503
        return jsonify({"status": "ok", "database": "reachable"}), 200

    @app.get("/api/holdings")
    def list_holdings():
        return jsonify(db.list_holdings(DEFAULT_USER_ID)), 200

    @app.get("/api/holdings/<int:holding_id>")
    def get_holding(holding_id):
        holding = db.get_holding(holding_id, DEFAULT_USER_ID)
        if holding is None:
            return jsonify({"error": f"holding {holding_id} not found"}), 404
        return jsonify(holding), 200

    @app.post("/api/holdings")
    def create_holding():
        try:
            clean = validate_holding_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400
        return jsonify(db.create_holding(clean, DEFAULT_USER_ID)), 201

    @app.put("/api/holdings/<int:holding_id>")
    def update_holding(holding_id):
        try:
            clean = validate_holding_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400
        holding = db.update_holding(holding_id, clean, DEFAULT_USER_ID)
        if holding is None:
            return jsonify({"error": f"holding {holding_id} not found"}), 404
        return jsonify(holding), 200

    @app.delete("/api/holdings/<int:holding_id>")
    def delete_holding(holding_id):
        if not db.delete_holding(holding_id, DEFAULT_USER_ID):
            return jsonify({"error": f"holding {holding_id} not found"}), 404
        return "", 204

    @app.get("/api/allocation")
    def get_allocation():
        report = allocation.build_portfolio_report(db.list_holdings(DEFAULT_USER_ID))
        return jsonify(_round_report(report)), 200

    @app.get("/api/targets")
    def get_targets():
        return jsonify(db.list_targets(DEFAULT_USER_ID)), 200

    @app.put("/api/targets")
    def put_targets():
        try:
            clean_targets = validate_targets_payload(request.get_json(silent=True))
        except ValidationError as exc:
            return jsonify({"error": str(exc), "errors": exc.errors}), 400
        return jsonify(db.replace_targets(clean_targets, DEFAULT_USER_ID)), 200

    @app.post("/api/insights")
    def create_insight():
        report = allocation.build_portfolio_report(db.list_holdings(DEFAULT_USER_ID))
        portfolio = _round_report(report)["portfolio"]
        figures = _build_insight_prompt(portfolio)
        prompt_sent = INSIGHT_SYSTEM_PROMPT + "\n\n" + figures

        try:
            response_text, model_name = llm.generate(figures, system=INSIGHT_SYSTEM_PROMPT)
        except llm.LLMUnavailableError as exc:
            return jsonify({"error": f"insight generation is unavailable: {exc}"}), 503

        entry = db.create_insight_log(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request_type": "insights",
                "prompt_sent": prompt_sent,
                "model_name": model_name,
                "response_text": response_text,
            },
            DEFAULT_USER_ID,
        )
        return jsonify(entry), 201

    @app.post("/api/drift-review")
    def create_drift_review():
        # PLAN -> ACT -> OBSERVE are deterministic Python; only ADAPT calls the LLM.
        targets = db.list_targets(DEFAULT_USER_ID)
        report = allocation.build_portfolio_report(db.list_holdings(DEFAULT_USER_ID))

        plan_result = drift.plan(targets)
        act_result = drift.act(report["portfolio"], plan_result)
        observe_result = drift.observe(act_result, plan_result)

        try:
            adapt_result = drift.adapt(observe_result)
        except llm.LLMUnavailableError as exc:
            return jsonify({"error": f"drift review is unavailable: {exc}"}), 503

        insight_log_id = None
        if adapt_result["llm_called"]:
            entry = db.create_insight_log(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "request_type": "drift-review",
                    "prompt_sent": adapt_result["prompt_sent"],
                    "model_name": adapt_result["model_name"],
                    "response_text": adapt_result["summary"],
                },
                DEFAULT_USER_ID,
            )
            insight_log_id = entry["id"]

        return jsonify({
            "plan": {
                "phase": plan_result["phase"],
                "description": plan_result["description"],
                "threshold_percent": _round(plan_result["threshold_percent"]),
                "asset_classes_to_examine": plan_result["asset_classes_to_examine"],
                "target_percent_by_class": {
                    k: _round(v) for k, v in plan_result["target_percent_by_class"].items()
                },
            },
            "act": {
                "phase": act_result["phase"],
                "description": act_result["description"],
                "total_market_value": _round(act_result["total_market_value"]),
                "drift_by_class": [_round_drift_row(r) for r in act_result["drift_by_class"]],
            },
            "observe": {
                "phase": observe_result["phase"],
                "description": observe_result["description"],
                "threshold_percent": _round(observe_result["threshold_percent"]),
                "breach_count": observe_result["breach_count"],
                "breaches": [_round_drift_row(r) for r in observe_result["breaches"]],
                "within_threshold": [
                    _round_drift_row(r) for r in observe_result["within_threshold"]
                ],
            },
            "adapt": {
                "phase": adapt_result["phase"],
                "description": adapt_result["description"],
                "llm_called": adapt_result["llm_called"],
                "model_name": adapt_result["model_name"],
                "summary": adapt_result["summary"],
            },
            "insight_log_id": insight_log_id,
        }), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
