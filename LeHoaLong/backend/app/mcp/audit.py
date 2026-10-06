"""ai_plan_log writes for the MCP phase.

Every MCP call this backend makes leaves a row in `ai_plan_log` with
`phase = 'mcp'`, for the same reason the Release 0 phases do: the table is the
evidence trail the technical report cites, and an integration that cannot be
shown to have happened may as well not have.

The two text columns keep their Release 0 meaning, generalised one step:

    prompt    what this backend sent -- here, the tool name, the arguments and
              the server it went to. There is no prompt in an MCP exchange,
              and inventing one would be worse than describing the request.
    response  what came back, verbatim, as JSON: the tool's own payload plus
              the timing and the error flag this backend derived from it.

`model_name` is the literal `'mcp'` (see models/ai_log.py). No model runs in
this phase at all -- the server relays figures other backends computed in
Python -- so naming a model tag here would be a fiction.

`goal_id` is nullable, so the standalone `/api/mcp/*` endpoints log with None:
they belong to no goal. Calls made while planning a specific goal are
attributed to it, which is what makes `GET /api/goals/<id>/ai-log` able to
show the whole exchange behind one plan.
"""

from __future__ import annotations

import json
import sqlite3

from ..models import ai_log as ai_log_model
from ..services import dates

PHASE = "mcp"

# Enough of a tool result to prove what was relayed without turning the audit
# table into a copy of every teammate's database. A bill list or a transaction
# summary is a few hundred bytes; a future tool returning something much
# larger gets truncated rather than bloating every row, and the row says so.
MAX_RESPONSE_CHARS = 8000


def _json(payload: dict) -> str:
    """Compact, stable JSON. `default=str` so an odd value cannot lose a row."""
    text = json.dumps(payload, sort_keys=True, default=str)
    if len(text) <= MAX_RESPONSE_CHARS:
        return text
    kept = text[:MAX_RESPONSE_CHARS]
    return json.dumps(
        {"truncated": True, "original_length": len(text), "head": kept},
        sort_keys=True,
    )


def record_tool_call(conn: sqlite3.Connection, *, goal_id: int | None, call: dict) -> int:
    """Log one `tools/call`. `call` is what client.call_tool returned."""
    arguments = json.dumps(call.get("arguments") or {}, sort_keys=True, default=str)
    outcome = "error" if call.get("is_error") else "ok"
    prompt = (
        f"MCP tools/call {call.get('tool')} at {call.get('server_url')} "
        f"with arguments {arguments} -- {outcome} in {call.get('duration_ms')}ms"
    )

    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=ai_log_model.MCP,
        prompt=prompt,
        response=_json(
            {
                "tool": call.get("tool"),
                "arguments": call.get("arguments") or {},
                "result": call.get("result"),
                "result_format": call.get("result_format"),
                "is_error": bool(call.get("is_error")),
                "error": call.get("error"),
                "duration_ms": call.get("duration_ms"),
            }
        ),
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id


def record_listing(conn: sqlite3.Connection, *, goal_id: int | None, listing: dict) -> int:
    """Log one `tools/list`.

    Worth a row of its own: it is the exchange that proves the connection, and
    which tools the server advertised on a given day is exactly the thing that
    changes under this backend without warning.
    """
    names = [tool.get("name") for tool in listing.get("tools") or []]
    prompt = (
        f"MCP tools/list at {listing.get('server_url')} -- "
        f"{listing.get('count')} tool(s) advertised in {listing.get('duration_ms')}ms"
    )

    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=ai_log_model.MCP,
        prompt=prompt,
        response=_json({"tools": names, "count": listing.get("count")}),
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id


def record_unavailable(conn: sqlite3.Connection, *, goal_id: int | None, detail: str, attempted: str) -> int:
    """Log the MCP server being unreachable.

    The failure is the interesting row, not the uninteresting one. Release 1's
    whole claim is that this feature degrades gracefully when a teammate's
    service is down, and a demonstration of that claim needs the attempt to
    appear in the audit trail rather than vanishing.
    """
    log_id = ai_log_model.insert_log(
        conn,
        goal_id=goal_id,
        phase=PHASE,
        model_name=ai_log_model.MCP,
        prompt=f"MCP {attempted} -- unavailable",
        response=_json({"unavailable": True, "detail": detail}),
        created_at=dates.now_iso(),
    )
    conn.commit()
    return log_id
