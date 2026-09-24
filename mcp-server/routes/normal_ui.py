from flask import Blueprint, jsonify


normal_ui_bp = Blueprint("normal_ui", __name__)


@normal_ui_bp.get("/")
def index():
    """Human-readable index -- lists the MCP tool endpoints for manual testing."""
    return jsonify({
        "service": "Personal Finance Assistant MCP Server",
        "mcp_mode_endpoints": [
            "/mcp/portfolio-snapshot",
            "/mcp/glossary-lookup",
            "/mcp/document-search",
            "/mcp/bill-summary",
            "/mcp/transaction-summary",
            "/mcp/goal-progress",
        ],
    })


@normal_ui_bp.get("/health")
def health():
    return jsonify({"status": "ok"})
