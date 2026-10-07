"""MCP endpoints -- /api/mcp.

The browser never talks to the MCP server. It cannot: the server is a host
process on port 5002 and the frontend is served from port 8060, so a direct
call would be cross-origin against a service that sets no CORS headers. More
to the point, it should not -- routing MCP through this API is what makes the
audit trail, the single timeout policy and the graceful degradation apply to
every caller rather than to whichever caller remembered.

Four routes, and they divide by audience:

    GET  /api/mcp/tools              evidence. What the server advertises.
    POST /api/mcp/call               evidence. One tool call, raw plus timing.
    GET  /api/mcp/health             the status indicator. Fast, never 503.
    GET  /api/goals/<id>/mcp-context the useful one: the assembled budget
                                     context behind a plan.

The last lives on a second blueprint because its path belongs to the goals
namespace while its subject is MCP. Keeping it in this file means every MCP
route is in one place; registering it under /api/goals means the URL reads the
way the resource is nested.

Routes stay thin, as in Release 0: parse, call, choose a status code.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..errors import ServiceUnavailable
from ..mcp import audit
from ..mcp import client as mcp_client
from ..mcp import context as mcp_context
from ..services import budget as budget_service
from ..services import goals as goals_service
from ..services import validation

bp = Blueprint("mcp", __name__, url_prefix="/api/mcp")

# The goal-scoped MCP route. Same module, different namespace -- see above.
goal_bp = Blueprint("mcp_goals", __name__, url_prefix="/api/goals")


def _require_enabled() -> None:
    """503 when MCP is switched off.

    These two routes exist only to exercise MCP, so there is nothing useful to
    degrade to -- unlike planning, which falls back to Release 0 behaviour and
    still returns a real plan. CI runs with MCP_ENABLED=false, so this is the
    path the suite exercises there.
    """
    if not mcp_client.is_enabled():
        raise ServiceUnavailable(
            "MCP is disabled by configuration (MCP_ENABLED=false). "
            "Planning and the rest of this API are unaffected."
        )


@bp.get("/tools")
def tools():
    """GET /api/mcp/tools -- the tools the shared server advertises.

    Proves the connection for the report: a real `initialize` handshake
    followed by a real `tools/list`, with the round-trip time measured.
    """
    _require_enabled()
    conn = get_db()
    try:
        listing = mcp_client.list_tools()
    except mcp_client.MCPUnavailable as exc:
        audit.record_unavailable(conn, goal_id=None, detail=str(exc), attempted="tools/list")
        raise

    audit.record_listing(conn, goal_id=None, listing=listing)
    return jsonify(listing), 200


@bp.post("/call")
def call():
    """POST /api/mcp/call -- call one tool by name.

    200 even when the tool itself failed, with `is_error` and `error` set. The
    protocol exchange succeeded; a teammate's backend being down is the
    result, not a failure of this request, and the payload a failing tool
    returned is exactly the evidence worth keeping. Only the MCP server being
    unreachable is a 503.

    Body: {"tool": "bill_summary", "arguments": {}, "goal_id": 3}
    `arguments` and `goal_id` are both optional; `goal_id` only attributes the
    audit row to a goal.
    """
    clean = validation.validate_mcp_call(request.get_json(silent=True))
    _require_enabled()

    conn = get_db()
    if clean["goal_id"] is not None:
        # 404 now rather than a foreign key violation at the moment of logging.
        goals_service.get_goal_or_404(conn, clean["goal_id"])

    try:
        result = mcp_client.call_tool(clean["tool"], clean["arguments"])
    except mcp_client.MCPUnavailable as exc:
        audit.record_unavailable(
            conn,
            goal_id=clean["goal_id"],
            detail=str(exc),
            attempted=f"tools/call {clean['tool']}",
        )
        raise

    result["log_id"] = audit.record_tool_call(conn, goal_id=clean["goal_id"], call=result)
    return jsonify(result), 200


@bp.get("/health")
def health():
    """GET /api/mcp/health -- is the MCP server reachable?

    Always 200, including when the answer is no: this drives a status light in
    the page header, and a light that cannot report "off" is not a status
    light. Uses its own short timeout so a page load does not block on a host
    process nobody started.

    Not folded into the service-level /health on purpose. That endpoint is the
    container's healthcheck, and MCP is not a dependency of this service --
    making an absent host process able to mark the backend unhealthy would
    take the feature down to report that an optional integration was off.
    """
    return jsonify(mcp_client.probe()), 200


@goal_bp.get("/<int:goal_id>/mcp-context")
def mcp_context_for_goal(goal_id: int):
    """GET /api/goals/<id>/mcp-context -- the budget context behind a plan.

    200 whether or not MCP answered. A context that had to fall back to
    budget settings alone is still a context, and the `mcp` block says which
    happened and why -- the frontend renders that as the "MCP unavailable,
    using budget settings" state rather than an error.

    `?use_mcp=false` forces the fallback path, which is how the Release 0
    behaviour is demonstrated side by side with the Release 1 one without
    restarting anything.
    """
    conn = get_db()
    goal = goals_service.get_goal_or_404(conn, goal_id)
    use_mcp = validation.flag_arg(request.args, "use_mcp", default=True)

    budget = budget_service.available_monthly(conn, goal["user_id"], exclude_goal_id=goal_id)
    context = mcp_context.assemble(conn, goal_id=goal_id, budget=budget, use_mcp=use_mcp)
    return jsonify(context), 200
