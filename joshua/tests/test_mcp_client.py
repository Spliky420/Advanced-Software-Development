"""MCP client and the CONTEXT step of the drift loop.

The success and error-payload cases run against a real FastMCP server over
the SDK's in-memory transport, so result parsing is tested against the
serialisation the shared mcp-server actually produces, not a hand-built
CallToolResult. The unreachable case uses the real streamable-HTTP transport
against a port with nothing listening.
"""

import asyncio
import socket
import time
from contextlib import asynccontextmanager

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

import drift
import llm
import mcp_client

# Fixtures and helpers shared with the figure-provenance suite.
from test_no_invented_figures import (  # noqa: F401 -- pytest fixtures
    _calculated_figures,
    _numbers_in,
    client,
    compliant_model,
)

GLOSSARY = {
    "ETF": "An exchange-traded fund, first listed in 1993, trades on an exchange.",
    "Equity": "Ownership in a company, usually held as shares.",
}


def build_fake_server():
    """Stand-in for mcp-server/server.py with the same error convention:
    a backend failure is returned as {"error": ...}, never raised."""
    server = FastMCP("fake-shared-mcp")

    @server.tool()
    def glossary_lookup(term: str):
        if term == "boom":
            raise RuntimeError("tool crashed")
        if term not in GLOSSARY:
            return {"error": f"Backend returned 404: http://maxwell-backend:5000/api/glossary/{term}"}
        return {"term": term, "definition": GLOSSARY[term]}

    return server


@pytest.fixture
def fake_mcp(monkeypatch):
    server = build_fake_server()

    @asynccontextmanager
    async def open_in_memory(url, timeout_seconds):
        async with create_connected_server_and_client_session(server) as session:
            yield session

    monkeypatch.setenv("MCP_SERVER_URL", "http://in-memory.test/mcp")
    monkeypatch.setattr(mcp_client, "_open_session", open_in_memory)
    return server


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --------------------------------------------------------------------------
# Client: the three required cases
# --------------------------------------------------------------------------

def test_tool_call_succeeds_and_returns_the_payload(fake_mcp):
    result = mcp_client.call_tool("glossary_lookup", {"term": "Equity"})

    assert result == {
        "tool": "glossary_lookup",
        "ok": True,
        "data": {"term": "Equity", "definition": GLOSSARY["Equity"]},
        "error": None,
    }


def test_error_payload_is_unavailable_even_though_is_error_is_false(fake_mcp):
    async def raw_call():
        async with create_connected_server_and_client_session(fake_mcp) as session:
            return await session.call_tool("glossary_lookup", {"term": "Unknown"})

    # The trap: the protocol reports success, the failure is only in content.
    raw = asyncio.run(raw_call())
    assert raw.isError is False

    result = mcp_client.call_tool("glossary_lookup", {"term": "Unknown"})

    assert result["ok"] is False
    assert result["data"] is None
    assert "Backend returned 404" in result["error"]


def test_unreachable_server_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{free_port()}/mcp")
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "3")

    started = time.monotonic()
    result = mcp_client.call_tool("glossary_lookup", {"term": "ETF"})
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["data"] is None
    assert "could not reach MCP server" in result["error"] or "did not respond" in result["error"]
    assert elapsed < 6, "the timeout must bound how long a dead server can stall a request"


# --------------------------------------------------------------------------
# Client: the other failure shapes
# --------------------------------------------------------------------------

def test_tool_that_raises_is_unavailable(fake_mcp):
    result = mcp_client.call_tool("glossary_lookup", {"term": "boom"})

    assert result["ok"] is False
    assert "tool raised" in result["error"]


def test_slow_server_is_cut_off_by_the_timeout(monkeypatch):
    class HangingSession:
        async def call_tool(self, name, arguments):
            await asyncio.sleep(30)

    @asynccontextmanager
    async def open_hanging(url, timeout_seconds):
        yield HangingSession()

    monkeypatch.setenv("MCP_SERVER_URL", "http://slow.test/mcp")
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setattr(mcp_client, "_open_session", open_hanging)

    started = time.monotonic()
    result = mcp_client.call_tool("glossary_lookup", {"term": "ETF"})

    assert time.monotonic() - started < 2
    assert result["ok"] is False
    assert "did not respond within 0.2s" in result["error"]


def test_batch_keeps_order_and_isolates_a_failed_call(fake_mcp):
    results = mcp_client.call_tools([
        ("glossary_lookup", {"term": "ETF"}),
        ("glossary_lookup", {"term": "Unknown"}),
        ("glossary_lookup", {"term": "Equity"}),
    ])

    assert [r["ok"] for r in results] == [True, False, True]
    assert results[2]["data"]["term"] == "Equity"


def test_empty_server_url_disables_mcp_without_touching_the_network(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "")

    result = mcp_client.call_tool("glossary_lookup", {"term": "ETF"})

    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_unset_server_url_defaults_to_the_compose_address(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_URL")

    assert mcp_client.get_server_url() == "http://mcp-server:5002/mcp"


def test_portfolio_snapshot_is_refused_because_it_loops_back(fake_mcp):
    with pytest.raises(ValueError, match="portfolio_snapshot"):
        mcp_client.call_tool("portfolio_snapshot")


# --------------------------------------------------------------------------
# CONTEXT step of the drift loop
# --------------------------------------------------------------------------

def make_observe(*asset_classes):
    breaches = [
        {"asset_class": name, "direction": "overweight", "drift_magnitude": 6.0}
        for name in asset_classes
    ]
    return {"run_id": "test", "breach_count": len(breaches), "breaches": breaches}


class RecordingCallTools:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses

    def __call__(self, calls):
        self.calls.append(calls)
        if self.responses is not None:
            return self.responses
        return [
            {"tool": name, "ok": True, "data": {"definition": f"about {args['term']}"}, "error": None}
            for name, args in calls
        ]


def test_context_skips_the_tool_when_nothing_breaches():
    stub = RecordingCallTools()

    result = drift.gather_context(make_observe(), call_tools_fn=stub)

    assert stub.calls == []
    assert result["mcp_called"] is False
    assert result["glossary"] == []


def test_context_looks_up_each_term_once_and_skips_unmapped_classes():
    stub = RecordingCallTools()

    result = drift.gather_context(
        make_observe("Australian equities", "Cash", "International equities", "ETFs"),
        call_tools_fn=stub,
    )

    assert stub.calls == [[
        ("glossary_lookup", {"term": "Equity"}),
        ("glossary_lookup", {"term": "ETF"}),
    ]]
    assert result["glossary"][0]["asset_classes"] == ["Australian equities", "International equities"]
    assert all(entry["status"] == "found" for entry in result["glossary"])


def test_context_with_mcp_down_reports_unavailable_and_does_not_raise():
    down = [{"tool": "glossary_lookup", "ok": False, "data": None, "error": "could not reach MCP server"}]

    result = drift.gather_context(make_observe("ETFs"), call_tools_fn=RecordingCallTools(down))

    assert result["mcp_called"] is True
    assert result["glossary"][0]["status"] == "unavailable"
    assert result["glossary"][0]["definition"] is None
    assert result["glossary"][0]["error"] == "could not reach MCP server"


def test_context_survives_a_call_tools_function_that_raises():
    def exploding(calls):
        raise RuntimeError("unexpected")

    result = drift.gather_context(make_observe("ETFs"), call_tools_fn=exploding)

    assert result["glossary"][0]["status"] == "unavailable"


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------

def test_drift_review_still_succeeds_with_the_mcp_server_unreachable(
    client, compliant_model, monkeypatch
):
    monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{free_port()}/mcp")
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "3")

    response = client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()
    assert body["adapt"]["llm_called"] is True
    assert body["context"]["mcp_called"] is True
    assert body["context"]["glossary"]
    assert all(entry["status"] == "unavailable" for entry in body["context"]["glossary"])


def test_a_number_from_a_glossary_definition_never_becomes_a_portfolio_figure(
    client, fake_mcp, monkeypatch
):
    # Precondition: the definition's year is not a figure the pipeline
    # calculates, so seeing it in the output can only mean it leaked.
    allowed = _calculated_figures()
    assert 1993.0 not in allowed

    prompts = []

    def quotes_the_reference_material(prompt, system=None):
        prompts.append(prompt)
        return "ETFs have been overweight since 1993.", "stub-model"

    monkeypatch.setattr(llm, "generate", quotes_the_reference_material)

    response = client.post("/api/drift-review")

    assert response.status_code == 200
    body = response.get_json()

    # The definition is grounding material now: it is in the prompt, inside
    # the reference block, after the figures.
    assert GLOSSARY["ETF"] in prompts[0]
    assert prompts[0].index(drift.FIGURES_HEADING) < prompts[0].index(drift.REFERENCE_HEADING)

    # The model presented the definition's year as a portfolio fact; the
    # figures check caught it and the summary was rebuilt in Python.
    adapt_section = body["adapt"]
    assert adapt_section["summary_source"] == "fallback"
    assert 1993.0 in adapt_section["unsupplied_figures"]
    assert "1993" not in adapt_section["summary"]
    invented = set(_numbers_in(adapt_section["summary"])) - allowed
    assert not invented, f"adapt.summary contains uncalculated figures: {sorted(invented)}"
