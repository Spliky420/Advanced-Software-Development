"""The MCP protocol client.

Release 1 gives this backend a second kind of outbound call alongside Ollama:
the Model Context Protocol, over streamable-http, to the team's one shared MCP
server (`mcp-server/server.py`). That server advertises six tools, each of
which relays figures a teammate's backend already computed in Python.

Four things here are deliberate.

**It speaks the protocol.** The transport is the MCP SDK's own streamable-http
client against the server's `/mcp` endpoint, with a real `initialize`
handshake and real `tools/list` and `tools/call` requests. The same server
also runs a Flask harness on port 5001 that renders tool output as HTML for
its author's demo UI. Scraping that would have been fewer lines and would not
have been MCP at all -- there would be no protocol evidence to put in the
report, and the HTML would break the moment its author restyled a page.

**Nothing in this module computes.** A result is parsed and labelled, never
adjusted. Every figure that comes back was calculated by the backend that owns
the data (CLAUDE.md's arithmetic rule), and this file's job is to stay out of
the way of that.

**A failed tool is data, not an exception.** `mcp-server/tools.py` returns an
`{"error": ...}` payload when a teammate's service is down, which arrives as a
*successful* tool call -- MCP's own `isError` flag stays false. A client that
only checked `isError` would hand that dict to the planner as though it were a
bill total. So both are checked, and `is_error` in the returned dict means
either.

**Infrastructure failure is one exception type.** Anything that stops this
backend reaching the server raises `MCPUnavailable`: the planner catches it to
fall back to Release 0 behaviour, and the `/api/mcp/*` routes turn it into a
clean 503.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from flask import current_app

from ..errors import ServiceUnavailable

# Reachability probes must answer quickly even when the MCP server is not
# running at all, so they override the generous timeout a real tool call gets.
#
# 8s rather than the 2s the Ollama probe uses, because an MCP round trip is
# not one HTTP request: it is connect, initialize, the operation, then session
# teardown. Measured against the shared server running on the development
# laptop, tools/list takes ~1.3s warm and ~2.0s on the first call after the
# server starts. A 3s budget left barely any headroom and would have shown a
# running server as unreachable in the page header, which is a worse failure
# than a slow status light.
HEALTH_TIMEOUT_SECONDS = 8.0

# The SSE read timeout handed to the transport. The server-initiated GET
# stream is long-lived and carries nothing this client needs, so a read
# timeout as short as the call timeout would only make the SDK reconnect for
# no reason. The real bound on a call is the deadline in _invoke, which does
# not depend on which timeout arguments the installed SDK happens to accept.
STREAM_READ_TIMEOUT_SECONDS = 300.0


class MCPUnavailable(ServiceUnavailable):
    """The MCP server could not be reached, or did not answer in time.

    A ServiceUnavailable subclass, so letting it propagate out of a route
    produces the 503 the API contract promises. This is infrastructure being
    absent. A *tool* failing is not this, and does not raise.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    return bool(current_app.config["MCP_ENABLED"])


def server_url() -> str:
    return str(current_app.config["MCP_SERVER_URL"])


def timeout_seconds() -> float:
    return float(current_app.config["MCP_TIMEOUT_SECONDS"])


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _open_streams(url: str, timeout: float):
    """Open the streamable-http transport, whichever SDK version is installed.

    `streamable_http_client` is the current entry point and takes a prepared
    httpx client; `streamablehttp_client` is the older name and takes the
    timeouts directly. Feature detection rather than pinning one version keeps
    this working if the shared `mcp` pin moves -- a live risk when the server
    and this client are maintained by two different people.
    """
    import httpx  # a dependency of the mcp SDK, never a direct one of ours
    from mcp.client import streamable_http as transport

    if hasattr(transport, "streamable_http_client"):
        timeouts = httpx.Timeout(timeout, read=STREAM_READ_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeouts) as http_client:
            async with transport.streamable_http_client(url, http_client=http_client) as streams:
                yield streams
    else:  # pragma: no cover -- older SDK, reached only if the shared pin moves back
        async with transport.streamablehttp_client(
            url, timeout=timeout, sse_read_timeout=STREAM_READ_TIMEOUT_SECONDS
        ) as streams:
            yield streams


@asynccontextmanager
async def _open_session(url: str, timeout: float):
    """An initialised MCP session. The handshake is part of the protocol."""
    from mcp import ClientSession

    async with _open_streams(url, timeout) as (read_stream, write_stream, *_):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _describe_failure(exc: BaseException) -> str:
    """A one-line cause, reaching inside an ExceptionGroup for the real one.

    The SDK runs its transport inside an anyio task group, so a refused
    connection surfaces as a group wrapping the actual error. Reporting the
    group itself would print "unhandled errors in a TaskGroup", which tells
    the reader nothing about what went wrong.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return str(exc).strip() or exc.__class__.__name__


def _run_coroutine(make_coroutine: Callable[[], Awaitable[Any]], timeout: float) -> Any:
    """Drive one coroutine to completion under a hard deadline.

    The only place asyncio appears in this feature, and a seam of its own for
    one practical reason: creating an event loop opens a socketpair, and on
    Windows that goes through socket.connect, which the test suite's
    no_network fixture refuses outright (correctly -- it cannot tell a self
    pipe from a real connection). Keeping the loop behind this function lets
    the tests exercise the failure translation in _invoke without starting
    one, and keeps that fixture as strict as it was in Release 0.

    Takes a factory rather than a coroutine so that a stubbed version which
    raises never leaves an un-awaited coroutine behind.
    """
    return asyncio.run(asyncio.wait_for(make_coroutine(), timeout=timeout))


def _invoke(action: Callable[[Any], Awaitable[Any]], timeout: float | None = None) -> Any:
    """Run `action(session)` against a live MCP session and return its result.

    The one seam the tests replace. Everything above this line is transport;
    everything below it -- which tools are called, how a result is read, what
    counts as an error -- is logic, and the suite exercises it for real
    without opening a socket anywhere.

    The deadline is enforced here rather than left to the transport, so that it
    holds whatever timeout arguments the installed SDK accepts.
    """
    url = server_url()
    limit = timeout_seconds() if timeout is None else timeout

    async def _run() -> Any:
        async with _open_session(url, limit) as session:
            return await action(session)

    try:
        return _run_coroutine(_run, limit)
    except ImportError as exc:
        raise MCPUnavailable(
            f"the MCP client library is not installed in this backend: {exc}. "
            "Add mcp to LeHoaLong/backend/requirements.txt and rebuild the image."
        ) from exc
    except TimeoutError as exc:
        raise MCPUnavailable(
            f"the MCP server at {url} did not answer within {limit:.0f}s. It runs as a host "
            "process, not a container -- check that it is running, and that MCP_SERVER_URL "
            "names a host this backend can reach."
        ) from exc
    except Exception as exc:
        raise MCPUnavailable(f"could not reach the MCP server at {url}: {_describe_failure(exc)}") from exc


# ---------------------------------------------------------------------------
# Reading a result
# ---------------------------------------------------------------------------


def _text_blocks(result: Any) -> list[str]:
    """The text content blocks of a tool result, in order.

    Duck-typed rather than isinstance-checked against the SDK's TextContent,
    so a test can hand this a plain stand-in and still exercise the real
    parsing. Non-text blocks are ignored; no tool on this server returns one.
    """
    blocks: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            blocks.append(text)
    return blocks


def _maybe_json(text: str) -> Any:
    """Parse a content block as JSON, or keep it as the string it is."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _relayed_error(payload: Any) -> str | None:
    """The error message a tool returned inside its own payload, if it did.

    This is `mcp-server/tools.py`'s convention for a teammate's backend being
    unreachable, timing out, or answering non-2xx. The call succeeded at the
    protocol level, so the payload is the only thing that says otherwise.
    """
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"]).strip() or None
    return None


def parse_tool_result(result: Any) -> dict:
    """Normalise a CallToolResult into {payload, is_error, error, format}.

    Where the payload comes from, in order of preference:

      structuredContent  a dict the server validated against the tool's own
                         output schema. None of the six tools declares one
                         today -- `server.py` gives its functions no return
                         annotations -- so this branch is forward
                         compatibility rather than the live path.
      text blocks        FastMCP serialises a returned dict to one JSON text
                         block, which *is* the live path. Several blocks means
                         the tool returned a list, and each is decoded in
                         place.
      neither            a tool that returned None.
    """
    structured = getattr(result, "structuredContent", None)
    blocks = _text_blocks(result)

    if isinstance(structured, dict):
        payload: Any = structured
        result_format = "structured"
    elif not blocks:
        payload = None
        result_format = "empty"
    else:
        decoded = [_maybe_json(text) for text in blocks]
        payload = decoded[0] if len(decoded) == 1 else decoded
        result_format = "text"

    if getattr(result, "isError", False):
        # The protocol says the call itself failed. The payload is then
        # whatever the server could say about why, which may be a bare string.
        reported = _relayed_error(payload) or (payload if isinstance(payload, str) else None)
        return {
            "payload": payload,
            "is_error": True,
            "error": (reported or "the MCP server reported the tool call as failed").strip(),
            "format": result_format,
        }

    relayed = _relayed_error(payload)
    return {
        "payload": payload,
        "is_error": relayed is not None,
        "error": relayed,
        "format": result_format,
    }


# ---------------------------------------------------------------------------
# The two protocol operations this backend needs
# ---------------------------------------------------------------------------


def list_tools(timeout: float | None = None) -> dict:
    """`tools/list` -- what the server advertises.

    Serves two purposes: the frontend's status indicator, and the report's
    evidence that this backend really is an MCP client rather than an HTTP
    client pointed at an MCP-shaped URL.
    """
    started = time.perf_counter()
    result = _invoke(lambda session: session.list_tools(), timeout=timeout)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    tools = [
        {
            "name": getattr(tool, "name", None),
            "description": (getattr(tool, "description", None) or "").strip() or None,
            "input_schema": getattr(tool, "inputSchema", None),
        }
        for tool in getattr(result, "tools", None) or []
    ]
    return {
        "server_url": server_url(),
        "tools": tools,
        "count": len(tools),
        "duration_ms": duration_ms,
    }


def _as_call(name: str, arguments: dict, raw: Any, duration_ms: float) -> dict:
    """The shape every tool call reports, however many shared a session."""
    parsed = parse_tool_result(raw)
    return {
        "tool": name,
        "arguments": arguments,
        "result": parsed["payload"],
        "result_format": parsed["format"],
        "is_error": parsed["is_error"],
        "error": parsed["error"],
        "duration_ms": duration_ms,
        "server_url": server_url(),
    }


def call_tool(name: str, arguments: dict | None = None, timeout: float | None = None) -> dict:
    """`tools/call` -- call one tool by name, returning its result and timing.

    `is_error` true with a readable `error` covers both a protocol-level
    failure and a tool that relayed its own error payload. `result` is
    included either way, because what a failing tool said is itself the
    evidence of how it failed.
    """
    sent = dict(arguments or {})
    started = time.perf_counter()
    raw = _invoke(lambda session: session.call_tool(name, arguments=sent), timeout=timeout)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return _as_call(name, sent, raw, duration_ms)


def call_tools(specs: list[tuple[str, dict]], timeout: float | None = None) -> list[dict]:
    """Call several tools over ONE session, in order.

    A session is not one request: it is connect, initialize, the operations,
    then teardown, measured at ~1.3s against the shared server on the
    development laptop. Building the budget context needs two tools, and
    calling them separately would spend that twice before the model is even
    prompted -- on a feature whose demo slot is 100 seconds.

    The protocol imposes no such cost: a session is reusable, so this reuses
    it. Each tool is still timed individually, because which teammate's
    backend is slow is the useful thing to know.

    One failure applies to all of them. If the server cannot be reached there
    is no result for any tool, which is exactly the all-or-nothing the caller
    wants -- a partially assembled budget context would be worse than none.
    """
    requests = [(name, dict(arguments or {})) for name, arguments in specs]

    async def _action(session: Any) -> list[tuple[str, dict, Any, float]]:
        collected: list[tuple[str, dict, Any, float]] = []
        for name, arguments in requests:
            started = time.perf_counter()
            raw = await session.call_tool(name, arguments=arguments)
            collected.append((name, arguments, raw, round((time.perf_counter() - started) * 1000, 1)))
        return collected

    return [_as_call(*item) for item in _invoke(_action, timeout=timeout)]


def probe() -> dict:
    """Reachability, for the frontend's status indicator. Never raises.

    Uses its own short timeout: a page load must not sit for twenty seconds
    because a host process nobody started is not answering.
    """
    status: dict = {
        "enabled": False,
        "reachable": False,
        "server_url": server_url(),
        "tool_count": None,
        "tools": [],
        "detail": None,
    }

    if not is_enabled():
        status["detail"] = "MCP is disabled by configuration (MCP_ENABLED=false)."
        return status

    status["enabled"] = True
    try:
        listing = list_tools(timeout=HEALTH_TIMEOUT_SECONDS)
    except MCPUnavailable as exc:
        status["detail"] = str(exc)
        return status

    status["reachable"] = True
    status["tool_count"] = listing["count"]
    status["tools"] = [tool["name"] for tool in listing["tools"]]
    return status
