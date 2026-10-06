"""The MCP client and the two evidence endpoints.

What these tests are actually protecting:

  * that this backend speaks the protocol -- `tools/list` and `tools/call`
    with named arguments -- rather than fetching a URL and hoping
  * that a figure a tool returned arrives at the caller byte-identical, since
    the whole value of MCP here is that another backend did the arithmetic
  * that the two ways a tool can fail are both detected. One is MCP's own
    `isError`; the other is mcp-server/tools.py returning an `{"error": ...}`
    payload on a *successful* call, which is what actually happens when a
    teammate's service is down, and which a client checking only `isError`
    would mistake for data
  * that the server being absent is a clean 503 with a message naming the URL
    it tried, not a traceback

No test here opens a socket or starts an event loop. `stub_mcp` replaces the
one transport function and nothing else, so the parsing, error detection,
timing and logging below are the real implementations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import BILL_SUMMARY_PAYLOAD, MCP_TOOL_NAMES, TRANSACTION_SUMMARY_PAYLOAD, mcp_tool_result

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.mcp import client as mcp_client


def _mcp_rows(conn, goal_id=None):
    """Every ai_plan_log row this feature's MCP phase wrote."""
    if goal_id is None:
        return conn.execute(
            "SELECT * FROM ai_plan_log WHERE phase = 'mcp' ORDER BY log_id"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM ai_plan_log WHERE phase = 'mcp' AND goal_id = ? ORDER BY log_id",
        (goal_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


def test_tools_endpoint_lists_what_the_server_advertises(client, stub_mcp):
    calls = stub_mcp()

    response = client.get("/api/mcp/tools")

    assert response.status_code == 200
    body = response.get_json()
    assert [tool["name"] for tool in body["tools"]] == list(MCP_TOOL_NAMES)
    assert body["count"] == 6
    assert body["server_url"] == "http://mcp.invalid:5002/mcp"
    # One protocol operation, and it is the right one.
    assert calls == [{"op": "tools/list"}]


def test_tools_endpoint_reports_each_tool_schema_and_the_round_trip_time(client, stub_mcp):
    stub_mcp()

    body = client.get("/api/mcp/tools").get_json()

    first = body["tools"][0]
    assert first["input_schema"] == {"type": "object", "properties": {}}
    assert first["description"]
    # Timing is part of the evidence: the report quotes it.
    assert isinstance(body["duration_ms"], float)
    assert body["duration_ms"] >= 0


def test_tools_listing_is_written_to_the_audit_trail(client, stub_mcp, conn):
    stub_mcp()

    client.get("/api/mcp/tools")

    rows = _mcp_rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["phase"] == "mcp"
    # No model ran: the MCP server relays figures other backends computed.
    assert row["model_name"] == "mcp"
    # A tools listing belongs to no goal.
    assert row["goal_id"] is None
    assert "tools/list" in row["prompt"]
    assert json.loads(row["response"])["count"] == 6


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


def test_call_passes_the_tool_payload_through_untouched(client, stub_mcp):
    stub_mcp(results={"bill_summary": BILL_SUMMARY_PAYLOAD})

    response = client.post("/api/mcp/call", json={"tool": "bill_summary"})

    assert response.status_code == 200
    body = response.get_json()
    # Byte-for-byte what the owning backend computed. Nothing rounded,
    # renamed, totalled or dropped on the way through.
    assert body["result"] == BILL_SUMMARY_PAYLOAD
    assert body["result"]["summary"]["monthly_cost"] == 620.24
    assert body["is_error"] is False
    assert body["error"] is None
    assert body["tool"] == "bill_summary"


def test_call_sends_named_arguments_over_the_protocol(client, stub_mcp):
    calls = stub_mcp(results={"goal_progress": {"goal_id": 3, "saved_to_date": 1400.0}})

    client.post("/api/mcp/call", json={"tool": "goal_progress", "arguments": {"goal_id": 3}})

    # MCP arguments are named, never positional -- this is the shape the
    # protocol sends and what the server's tool signature expects.
    assert calls == [{"op": "tools/call", "tool": "goal_progress", "arguments": {"goal_id": 3}}]


def test_call_defaults_to_no_arguments(client, stub_mcp):
    calls = stub_mcp(results={"transaction_summary": TRANSACTION_SUMMARY_PAYLOAD})

    body = client.post("/api/mcp/call", json={"tool": "transaction_summary"}).get_json()

    assert calls[0]["arguments"] == {}
    assert body["arguments"] == {}


def test_call_is_written_to_the_audit_trail_with_its_result(client, stub_mcp, conn):
    stub_mcp(results={"bill_summary": BILL_SUMMARY_PAYLOAD})

    body = client.post("/api/mcp/call", json={"tool": "bill_summary"}).get_json()

    rows = _mcp_rows(conn)
    assert len(rows) == 1
    logged = json.loads(rows[0]["response"])
    assert logged["tool"] == "bill_summary"
    assert logged["result"] == BILL_SUMMARY_PAYLOAD
    assert logged["is_error"] is False
    # The response tells the caller which row to look at.
    assert body["log_id"] == rows[0]["log_id"]


def test_call_can_be_attributed_to_a_goal(client, stub_mcp, conn):
    stub_mcp(results={"bill_summary": BILL_SUMMARY_PAYLOAD})

    client.post("/api/mcp/call", json={"tool": "bill_summary", "goal_id": 3})

    rows = _mcp_rows(conn, goal_id=3)
    assert len(rows) == 1
    # And so shows up in the goal's own audit trail, which is what makes the
    # whole exchange behind one plan readable from the API.
    entries = client.get("/api/goals/3/ai-log").get_json()["entries"]
    assert any(entry["phase"] == "mcp" for entry in entries)


def test_call_404s_for_a_goal_that_does_not_exist(client, stub_mcp):
    """Checked before the call, not after: a foreign key violation at logging
    time would be a 500 for what is plainly a bad request."""
    calls = stub_mcp(results={"bill_summary": BILL_SUMMARY_PAYLOAD})

    response = client.post("/api/mcp/call", json={"tool": "bill_summary", "goal_id": 99999})

    assert response.status_code == 404
    assert calls == []


# ---------------------------------------------------------------------------
# A tool that fails -- the two different ways
# ---------------------------------------------------------------------------


def test_a_relayed_error_payload_is_detected_as_an_error(client, stub_mcp):
    """The live failure mode: a teammate's backend is down.

    mcp-server/tools.py catches the connection error and *returns* a dict, so
    the protocol call succeeds and isError stays false. A client that trusted
    isError alone would hand this to the planner as though it were a bill
    total.
    """
    stub_mcp(
        results={
            "bill_summary": {"error": "Could not reach backend at http://hyunwoo-backend:5000/api/bills"}
        }
    )

    response = client.post("/api/mcp/call", json={"tool": "bill_summary"})

    # 200: the MCP exchange itself worked, and what the tool said is the
    # evidence of what went wrong.
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_error"] is True
    assert "Could not reach backend" in body["error"]
    assert body["result"] == {
        "error": "Could not reach backend at http://hyunwoo-backend:5000/api/bills"
    }


def test_a_protocol_level_error_is_detected_as_an_error(client, stub_mcp, mcp_result):
    """The other way: the server marks the call itself as failed."""
    stub_mcp(results={"bill_summary": mcp_result("ValueError: tool raised", is_error=True)})

    body = client.post("/api/mcp/call", json={"tool": "bill_summary"}).get_json()

    assert body["is_error"] is True
    assert body["error"] == "ValueError: tool raised"


def test_an_unknown_tool_name_comes_back_as_an_error_not_a_400(client, stub_mcp):
    """The server is the authority on which tools exist.

    Validating the name against a hardcoded list of today's six would turn a
    teammate adding a tool into a 400 from this backend.
    """
    stub_mcp()

    body = client.post("/api/mcp/call", json={"tool": "not_a_real_tool"}).get_json()

    assert body["is_error"] is True
    assert "Unknown tool" in body["error"]


def test_a_failed_tool_call_is_still_audited(client, stub_mcp, conn):
    stub_mcp(results={"bill_summary": {"error": "Backend timed out: http://hyunwoo-backend:5000"}})

    client.post("/api/mcp/call", json={"tool": "bill_summary"})

    logged = json.loads(_mcp_rows(conn)[0]["response"])
    assert logged["is_error"] is True
    assert "timed out" in logged["error"]


# ---------------------------------------------------------------------------
# The server being absent
# ---------------------------------------------------------------------------


def test_an_unreachable_server_is_a_503_naming_the_url(client, stub_mcp):
    stub_mcp(
        unavailable=mcp_client.MCPUnavailable(
            "could not reach the MCP server at http://mcp.invalid:5002/mcp: Connection refused"
        )
    )

    response = client.post("/api/mcp/call", json={"tool": "bill_summary"})

    assert response.status_code == 503
    assert "http://mcp.invalid:5002/mcp" in response.get_json()["error"]


def test_an_unreachable_server_is_recorded_as_an_attempt(client, stub_mcp, conn):
    """The failure is the interesting row.

    Release 1's claim is that this feature degrades gracefully; a
    demonstration of that needs the attempt to appear in the audit trail
    rather than vanish.
    """
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: Connection refused"))

    client.get("/api/mcp/tools")

    rows = _mcp_rows(conn)
    assert len(rows) == 1
    assert "unavailable" in rows[0]["prompt"]
    assert json.loads(rows[0]["response"])["unavailable"] is True


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/mcp/tools"), ("post", "/api/mcp/call")],
)
def test_disabled_mcp_is_a_503_that_says_so(client, app, stub_mcp, method, path):
    """CI runs with MCP_ENABLED=false, so this is the path it exercises."""
    stub_mcp()
    app.config["MCP_ENABLED"] = False

    response = getattr(client, method)(path, json={"tool": "bill_summary"})

    assert response.status_code == 503
    assert "MCP_ENABLED=false" in response.get_json()["error"]


def test_disabled_mcp_does_not_touch_the_transport(client, app, stub_mcp):
    calls = stub_mcp()
    app.config["MCP_ENABLED"] = False

    client.get("/api/mcp/tools")

    assert calls == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, "tool is required"),
        ({"tool": ""}, "tool must not be empty"),
        ({"tool": 7}, "tool must be a string"),
        ({"tool": "bill_summary", "arguments": []}, "arguments must be a JSON object"),
        ({"tool": "bill_summary", "arguments": "goal_id=3"}, "arguments must be a JSON object"),
        ({"tool": "bill_summary", "goal_id": "3"}, "goal_id must be an integer"),
        ({"tool": "bill_summary", "goal_id": 0}, "goal_id must be a positive integer"),
    ],
)
def test_call_rejects_an_unusable_body(client, stub_mcp, body, expected):
    stub_mcp()

    response = client.post("/api/mcp/call", json=body)

    assert response.status_code == 400
    assert expected in response.get_json()["details"]


def test_call_validates_before_connecting(client, stub_mcp):
    """A 400 must not have cost a round trip to the MCP server."""
    calls = stub_mcp()

    client.post("/api/mcp/call", json={})

    assert calls == []


# ---------------------------------------------------------------------------
# Reading a result -- unit level, no HTTP
# ---------------------------------------------------------------------------


def test_result_parsing_prefers_structured_content():
    """Forward compatibility: none of the six tools declares an output schema
    today, because server.py gives its functions no return annotations. If one
    ever does, the validated dict is the better source."""
    result = mcp_tool_result('{"ignored": true}', structured={"monthly_cost": 620.24})

    parsed = mcp_client.parse_tool_result(result)

    assert parsed["payload"] == {"monthly_cost": 620.24}
    assert parsed["format"] == "structured"


def test_result_parsing_decodes_the_single_json_block_fastmcp_sends():
    result = mcp_tool_result(json.dumps(TRANSACTION_SUMMARY_PAYLOAD))

    parsed = mcp_client.parse_tool_result(result)

    assert parsed["payload"] == TRANSACTION_SUMMARY_PAYLOAD
    assert parsed["format"] == "text"
    assert parsed["is_error"] is False


def test_result_parsing_decodes_several_blocks_as_a_list():
    """FastMCP turns a returned list into one content block per item."""
    result = mcp_tool_result('{"rank": 1}', '{"rank": 2}')

    parsed = mcp_client.parse_tool_result(result)

    assert parsed["payload"] == [{"rank": 1}, {"rank": 2}]


def test_result_parsing_keeps_text_that_is_not_json():
    result = mcp_tool_result("ETF stands for exchange traded fund.")

    parsed = mcp_client.parse_tool_result(result)

    assert parsed["payload"] == "ETF stands for exchange traded fund."
    assert parsed["is_error"] is False


def test_result_parsing_handles_a_tool_that_returned_nothing():
    parsed = mcp_client.parse_tool_result(mcp_tool_result())

    assert parsed["payload"] is None
    assert parsed["format"] == "empty"


def test_result_parsing_never_invents_an_error_for_an_empty_error_string():
    """`{"error": ""}` is not a failure -- it is a field that happens to be
    empty, and treating it as an outage would discard a usable payload."""
    result = mcp_tool_result(json.dumps({"error": "", "monthly_cost": 620.24}))

    parsed = mcp_client.parse_tool_result(result)

    assert parsed["is_error"] is False


# ---------------------------------------------------------------------------
# Turning a transport failure into one readable exception
# ---------------------------------------------------------------------------


def _stub_runner(monkeypatch, exc):
    """Make the event loop seam raise, without starting an event loop.

    _run_coroutine is the only place asyncio appears; replacing it leaves the
    real translation in _invoke under test.
    """

    def _raise(make_coroutine, timeout):
        raise exc

    monkeypatch.setattr(mcp_client, "_run_coroutine", _raise)


def test_a_refused_connection_names_the_server(app, monkeypatch):
    _stub_runner(monkeypatch, ConnectionRefusedError("[Errno 111] Connection refused"))

    with app.app_context():
        with pytest.raises(mcp_client.MCPUnavailable) as caught:
            mcp_client.list_tools()

    assert "http://mcp.invalid:5002/mcp" in str(caught.value)
    assert "Connection refused" in str(caught.value)


def test_an_exception_group_is_flattened_to_the_real_cause(app, monkeypatch):
    """The SDK runs its transport in an anyio task group, so a refused
    connection arrives wrapped. Reporting the group would print "unhandled
    errors in a TaskGroup", which says nothing useful."""
    wrapped = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [ConnectionRefusedError("[Errno 111] Connection refused")],
    )
    _stub_runner(monkeypatch, wrapped)

    with app.app_context():
        with pytest.raises(mcp_client.MCPUnavailable) as caught:
            mcp_client.list_tools()

    assert "Connection refused" in str(caught.value)
    assert "TaskGroup" not in str(caught.value)


def test_a_timeout_says_it_timed_out_and_names_the_limit(app, monkeypatch):
    _stub_runner(monkeypatch, TimeoutError())

    with app.app_context():
        with pytest.raises(mcp_client.MCPUnavailable) as caught:
            mcp_client.list_tools()

    assert "did not answer within 20s" in str(caught.value)


def test_a_missing_sdk_says_which_package_to_install(app, monkeypatch):
    """The container installs backend/requirements.txt, which pins mcp. If an
    image is ever built without it, the message should say so rather than
    blaming the network."""
    _stub_runner(monkeypatch, ImportError("No module named 'mcp'"))

    with app.app_context():
        with pytest.raises(mcp_client.MCPUnavailable) as caught:
            mcp_client.list_tools()

    assert "requirements.txt" in str(caught.value)


# ---------------------------------------------------------------------------
# The status probe behind the header indicator
# ---------------------------------------------------------------------------


def test_health_reports_reachable_with_the_tool_count(client, stub_mcp):
    stub_mcp()

    body = client.get("/api/mcp/health").get_json()

    assert body == {
        "enabled": True,
        "reachable": True,
        "server_url": "http://mcp.invalid:5002/mcp",
        "tool_count": 6,
        "tools": list(MCP_TOOL_NAMES),
        "detail": None,
    }


def test_health_reports_an_unreachable_server_as_200(client, stub_mcp):
    """A status light that cannot report "off" is not a status light."""
    stub_mcp(unavailable=mcp_client.MCPUnavailable("could not reach the MCP server: Connection refused"))

    response = client.get("/api/mcp/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["enabled"] is True
    assert body["reachable"] is False
    assert "Connection refused" in body["detail"]


def test_health_reports_disabled_without_connecting(client, app, stub_mcp):
    calls = stub_mcp()
    app.config["MCP_ENABLED"] = False

    body = client.get("/api/mcp/health").get_json()

    assert body["enabled"] is False
    assert body["reachable"] is False
    assert "MCP_ENABLED=false" in body["detail"]
    assert calls == []


def test_the_probe_uses_its_own_short_timeout(app, monkeypatch):
    """A page load must not block for the full call timeout because a host
    process nobody started is not answering."""
    app.config["MCP_ENABLED"] = True
    seen: list[float | None] = []

    def _record(action, timeout=None):
        seen.append(timeout)
        raise mcp_client.MCPUnavailable("down")

    monkeypatch.setattr(mcp_client, "_invoke", _record)

    with app.app_context():
        mcp_client.probe()
        call_timeout = mcp_client.timeout_seconds()

    assert seen == [mcp_client.HEALTH_TIMEOUT_SECONDS]
    assert mcp_client.HEALTH_TIMEOUT_SECONDS < call_timeout
