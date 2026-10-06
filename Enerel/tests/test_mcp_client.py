import json
from types import SimpleNamespace

import pytest

import mcp_client


def text_result(payload, is_error=False, structured=None):
    return SimpleNamespace(
        isError=is_error,
        structuredContent=structured,
        content=[SimpleNamespace(type="text", text=json.dumps(payload) if not isinstance(payload, str) else payload)],
    )


@pytest.fixture(autouse=True)
def mcp_on(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp.test:5002/mcp")


def test_call_tool_returns_the_tools_dict(monkeypatch):
    calls = []

    def fake_run(url, tool, arguments):
        calls.append((url, tool, arguments))
        return text_result({"term": "ETF", "definition": "Exchange-Traded Fund"})

    monkeypatch.setattr(mcp_client, "_run", fake_run)

    result = mcp_client.call_tool("glossary_lookup", {"term": "ETF"})

    assert result == {"term": "ETF", "definition": "Exchange-Traded Fund"}
    assert calls == [("http://mcp.test:5002/mcp", "glossary_lookup", {"term": "ETF"})]


def test_disabled_mode_never_opens_a_connection(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(mcp_client, "_run", lambda *a: pytest.fail("MCP must not be called when disabled"))

    with pytest.raises(mcp_client.MCPDisabledError):
        mcp_client.call_tool("glossary_lookup", {"term": "ETF"})


@pytest.mark.parametrize("tool", ["portfolio_snapshot", "transaction_summary", "document_search", "anything"])
def test_tools_outside_the_boundary_are_refused_before_connecting(monkeypatch, tool):
    monkeypatch.setattr(mcp_client, "_run", lambda *a: pytest.fail("out-of-boundary tool reached the server"))

    with pytest.raises(mcp_client.MCPToolNotAllowedError):
        mcp_client.call_tool(tool, {})


def test_connection_failure_becomes_unavailable(monkeypatch):
    def boom(*args):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(mcp_client, "_run", boom)

    with pytest.raises(mcp_client.MCPUnavailableError, match="could not reach the MCP server"):
        mcp_client.call_tool("glossary_lookup", {"term": "ETF"})


def test_unreachable_server_fails_fast_against_a_closed_port(monkeypatch):
    """Real SDK, no mocks: a port nothing listens on must surface as
    MCPUnavailableError rather than hang or leak an ExceptionGroup."""
    pytest.importorskip("mcp")
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:1/mcp")

    with pytest.raises(mcp_client.MCPUnavailableError):
        mcp_client.call_tool("glossary_lookup", {"term": "ETF"})


def test_parse_prefers_structured_content_and_unwraps_result():
    result = text_result("ignored", structured={"result": {"term": "ETF", "definition": "x"}})
    assert mcp_client.parse_tool_result(result) == {"term": "ETF", "definition": "x"}


def test_parse_tool_error_raises():
    with pytest.raises(mcp_client.MCPUnavailableError, match="tool returned an error"):
        mcp_client.parse_tool_result(text_result("boom", is_error=True))


def test_parse_non_json_text_raises():
    with pytest.raises(mcp_client.MCPUnavailableError, match="non-JSON"):
        mcp_client.parse_tool_result(text_result("not json"))


def test_parse_empty_content_raises():
    empty = SimpleNamespace(isError=False, structuredContent=None, content=[])
    with pytest.raises(mcp_client.MCPUnavailableError, match="no usable content"):
        mcp_client.parse_tool_result(empty)
