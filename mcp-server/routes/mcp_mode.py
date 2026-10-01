import json
import os

from flask import Blueprint, request

from tools import (
    get_portfolio_snapshot,
    get_glossary_definition,
    search_documents,
    get_bill_summary,
    get_transaction_summary,
    get_goal_progress,
)


mcp_bp = Blueprint("mcp_mode", __name__)


def mcp_mode_is_enabled(req) -> bool:
    enabled = os.getenv("MCP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return False

    mode_header = req.headers.get("X-MCP-Mode", "on").strip().lower()
    return mode_header in ("1", "true", "yes", "on")


def mcp_disabled_response():
    return "<p>MCP Mode is disabled.</p>", 403


def mcp_render_json(title: str, payload):
    return f"<h3>{title}</h3><pre>{json.dumps(payload, indent=2)}</pre>"


def _status_for(result) -> int:
    # tools.py never raises on a backend failure -- it returns {"error": ...}
    # instead, so the HTTP status here is derived from the payload rather
    # than from a caught exception.
    return 503 if isinstance(result, dict) and "error" in result else 200


@mcp_bp.post("/mcp/portfolio-snapshot")
def mcp_portfolio_snapshot():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    result = get_portfolio_snapshot()
    return mcp_render_json("MCP Tool: portfolio_snapshot", result), _status_for(result)


@mcp_bp.post("/mcp/glossary-lookup")
def mcp_glossary_lookup():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    term = request.form.get("term", "").strip()
    if not term:
        return "<p>term is required.</p>", 400

    result = get_glossary_definition(term)
    return mcp_render_json("MCP Tool: glossary_lookup", result), _status_for(result)


@mcp_bp.post("/mcp/document-search")
def mcp_document_search():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    query = request.form.get("query", "").strip()
    if not query:
        return "<p>query is required.</p>", 400

    try:
        top_k = int(request.form.get("top_k", "5"))
    except ValueError:
        top_k = 5

    result = search_documents(query, top_k)
    return mcp_render_json("MCP Tool: document_search", result), _status_for(result)


@mcp_bp.post("/mcp/bill-summary")
def mcp_bill_summary():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    result = get_bill_summary()
    return mcp_render_json("MCP Tool: bill_summary", result), _status_for(result)


@mcp_bp.post("/mcp/transaction-summary")
def mcp_transaction_summary():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    result = get_transaction_summary()
    return mcp_render_json("MCP Tool: transaction_summary", result), _status_for(result)


@mcp_bp.post("/mcp/goal-progress")
def mcp_goal_progress():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    goal_id = request.form.get("goal_id", "").strip()
    if not goal_id.isdigit():
        return "<p>goal_id is required and must be an integer.</p>", 400

    result = get_goal_progress(int(goal_id))
    return mcp_render_json("MCP Tool: goal_progress", result), _status_for(result)
