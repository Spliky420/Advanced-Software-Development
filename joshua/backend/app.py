import logging
import os
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import ai_mode
import db
import allocation
import drift
import llm
import multi_agent_client
from db import DEFAULT_USER_ID
from validation import ValidationError, validate_holding_payload, validate_targets_payload

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"

# Named so a second create_app() can recognise the handler it already added.
LOG_HANDLER_NAME = "joshua-stdout"


def configure_logging():
    """Send the root logger to stdout at LOG_LEVEL (default INFO).

    stdout, not stderr: it is what `docker compose logs joshua-backend` shows
    alongside gunicorn's own output.

    Idempotent. create_app() runs once per test in the suite and twice over in
    development (module import plus the reloader), and without the name check
    each call would stack another handler and print every line again.
    """
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers:
        if getattr(handler, "name", None) == LOG_HANDLER_NAME:
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.name = LOG_HANDLER_NAME
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)


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


AI_OFF_MESSAGES = {
    "disabled": "AI is disabled on this server, so no summary was generated. "
                "Holdings, allocation and the drift figures still work.",
    "unavailable": "AI is unavailable right now (Ollama could not produce a response), "
                   "so no summary was generated. Holdings, allocation and the drift "
                   "figures still work.",
}


def _ai_off_response(status, detail):
    """503 for an AI-only endpoint that could not use the model.

    error is the message for people; ai_status ("disabled" or "unavailable")
    is for code to branch on; detail keeps the technical reason. Never a
    stack trace.
    """
    return jsonify({
        "error": AI_OFF_MESSAGES[status],
        "ai_enabled": status != "disabled",
        "ai_status": status,
        "detail": detail,
    }), 503


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


MULTI_AGENT_TASK = "Review my portfolio allocation and drift"


def build_workflow_evidence():
    """The evidence object sent to the Multi-Agent Server.

    Every figure is computed in Python before it leaves this backend:
    holdings and allocation by allocation.build_portfolio_report, drift by
    drift.act/observe from that same report. Rounded to 2dp at this output
    layer, as every other response is. The agents only plan, describe and
    review around these figures; none is ever asked to calculate one.
    """
    targets = db.list_targets(DEFAULT_USER_ID)
    report = allocation.build_portfolio_report(db.list_holdings(DEFAULT_USER_ID))
    rounded = _round_report(report)

    plan_result = drift.plan(targets)
    act_result = drift.act(report["portfolio"], plan_result)
    observe_result = drift.observe(act_result, plan_result)

    return {
        "holdings": [
            {
                key: holding[key]
                for key in ("ticker", "asset_name", "asset_class", "units",
                            "market_value", "cost_basis", "gain_loss", "gain_loss_percent")
            }
            for holding in rounded["holdings"]
        ],
        "allocation": rounded["portfolio"],
        "drift": {
            "threshold_percent": _round(observe_result["threshold_percent"]),
            "breaches": [_round_drift_row(row) for row in observe_result["breaches"]],
            "within_threshold": [_round_drift_row(row) for row in observe_result["within_threshold"]],
        },
    }


# Friendly message per failure, for the UI; code is for clients to branch on.
MULTI_AGENT_FAILURES = {
    "disabled": (503, "AI is disabled on this server, so the Multi-Agent Review cannot run."),
    "unreachable": (503, "The Multi-Agent Server is not running. Start it on the host "
                         "(multi-agent-server/run.sh) and try again."),
    "timeout": (504, "The Multi-Agent Server is not responding. It may be busy -- try again "
                     "in a moment."),
    "error": (502, "The Multi-Agent Server sent a response this app could not read."),
    "validation_failed": (400, "The Multi-Agent Server rejected the request."),
    "not_found": (404, "That run does not exist on the Multi-Agent Server (its history may have "
                       "been cleared). Start a new run."),
    "conflict": (409, "This run has already been reviewed (or failed), so it cannot be reviewed again."),
    "agent_unavailable": (503, "The agents could not run. Check Ollama is running on the host, "
                               "or start the Multi-Agent Server with STUB_AGENTS=true."),
}


def _multi_agent_failure(result, own_request=False):
    """Turn a failed multi_agent_client result into (body, status).

    own_request: True when this backend built the whole request body (start
    a workflow), so a 400 from the server is this backend's fault, not the
    user's, and is reported as 502 rather than passed on as 400.
    """
    code = result["status"]
    data = result["data"] if isinstance(result["data"], dict) else {}
    if code == "rejected":
        code = data.get("error") if data.get("error") in MULTI_AGENT_FAILURES else "error"
    http_status, message = MULTI_AGENT_FAILURES[code]
    if code == "validation_failed" and own_request:
        http_status = 502

    body = {"error": message, "code": code, "detail": result["error"]}
    if data.get("fields"):
        body["fields"] = data["fields"]
    if data.get("run_id"):
        body["run_id"] = data["run_id"]
    return jsonify(body), http_status


def create_app():
    configure_logging()
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

        if not ai_mode.is_enabled():
            return _ai_off_response("disabled", ai_mode.DISABLED_MESSAGE)
        try:
            response_text, model_name = llm.generate(figures, system=INSIGHT_SYSTEM_PROMPT)
        except llm.LLMDisabledError as exc:
            return _ai_off_response("disabled", str(exc))
        except llm.LLMUnavailableError as exc:
            return _ai_off_response("unavailable", str(exc))

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
        # CONTEXT (MCP glossary + RAG passages) is optional and never fails the request.
        targets = db.list_targets(DEFAULT_USER_ID)
        report = allocation.build_portfolio_report(db.list_holdings(DEFAULT_USER_ID))

        plan_result = drift.plan(targets)
        act_result = drift.act(report["portfolio"], plan_result)
        observe_result = drift.observe(act_result, plan_result)
        context_result = drift.gather_context(observe_result)

        # Never raises for Ollama: with AI off or unreachable, ADAPT returns
        # the Python-built fallback summary and ai_used=False, so the figures
        # computed above still reach the client.
        adapt_result = drift.adapt(observe_result, context_result=context_result)

        insight_log_id = None
        if adapt_result["llm_called"]:
            entry = db.create_insight_log(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "request_type": "drift-review",
                    "prompt_sent": adapt_result["prompt_sent"],
                    "model_name": adapt_result["model_name"],
                    # What the model actually said, even when the figures
                    # check replaced it -- the log is the evidence trail.
                    "response_text": adapt_result["model_response"],
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
                "run_id": plan_result.get("run_id", "-"),
            },
            "act": {
                "phase": act_result["phase"],
                "description": act_result["description"],
                "total_market_value": _round(act_result["total_market_value"]),
                "drift_by_class": [_round_drift_row(r) for r in act_result["drift_by_class"]],
                "run_id": act_result.get("run_id", "-"),
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
                "run_id": observe_result.get("run_id", "-"),
            },
            "context": {
                "phase": context_result["phase"],
                "description": context_result["description"],
                "mcp_called": context_result["mcp_called"],
                "rag_called": context_result["rag_called"],
                "reason": context_result["reason"],
                "glossary": context_result["glossary"],
                "retrieval": context_result["retrieval"],
                "insufficient_context": context_result["insufficient_context"],
                "insufficient_reason": context_result["insufficient_reason"],
                "run_id": context_result.get("run_id", "-"),
            },
            "adapt": {
                "phase": adapt_result["phase"],
                "description": adapt_result["description"],
                "llm_called": adapt_result["llm_called"],
                "model_name": adapt_result["model_name"],
                "summary": adapt_result["summary"],
                "summary_source": adapt_result["summary_source"],
                "context_status": adapt_result["context_status"],
                "unsupplied_figures": adapt_result["unsupplied_figures"],
                "misattributed": adapt_result["misattributed"],
                "citations": adapt_result["citations"],
                "ai_used": adapt_result["ai_used"],
                "ai_error": adapt_result["ai_error"],
                "run_id": adapt_result.get("run_id", "-"),
            },
            "ai_enabled": ai_mode.is_enabled(),
            "ai_used": adapt_result["ai_used"],
            "insight_log_id": insight_log_id,
            # Same id the four [agentic-loop <run_id>] log lines carry, lifted
            # to the top level so a response and a terminal capture can be
            # matched up without opening a section.
            "run_id": plan_result.get("run_id", "-"),
        }), 200

    @app.post("/api/multi-agent/workflow")
    def start_multi_agent_workflow():
        # Asynchronous: the Multi-Agent Server answers 202 at once with the
        # run at "planning" and runs the agents on its own thread. The
        # client polls GET /api/multi-agent/workflow/<run_id> for progress.
        evidence = build_workflow_evidence()
        result = multi_agent_client.start_workflow(MULTI_AGENT_TASK, evidence)
        if not result["ok"]:
            return _multi_agent_failure(result, own_request=True)
        return jsonify({"task": MULTI_AGENT_TASK, "evidence": evidence, "run": result["data"]}), 202

    @app.get("/api/multi-agent/workflow/<run_id>")
    def get_multi_agent_workflow(run_id):
        # The run's current state, passed through. A run whose agent could
        # not run is a 200 here with status "failed" and an error saying
        # which phase -- the poller decides what to show, not this layer.
        result = multi_agent_client.get_workflow(run_id)
        if not result["ok"]:
            return _multi_agent_failure(result)
        return jsonify({"run": result["data"]}), 200

    @app.post("/api/multi-agent/workflow/<run_id>/review")
    def review_multi_agent_workflow(run_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({
                "error": "The review must be a JSON object with a decision.",
                "code": "validation_failed",
                "fields": {"body": "must be a JSON object"},
            }), 400
        result = multi_agent_client.submit_review(run_id, body)
        if not result["ok"]:
            return _multi_agent_failure(result)
        return jsonify(result["data"]), 200

    return app


app = create_app()

if __name__ == "__main__":
    # Local development server only; the container runs gunicorn, which binds
    # 0.0.0.0 inside the container (see Dockerfile). Loopback by default so a
    # dev run is not exposed to the network; set HOST to override.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
