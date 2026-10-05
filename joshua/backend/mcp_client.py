"""Thin client for the team's shared MCP server (mcp-server/ on main).

Speaks the real MCP protocol over streamable-HTTP, the same transport
mcp-server/server.py serves on its container port 5002. Every public call
returns a plain dict and never raises for a server-side problem: the MCP
server is optional to this backend (compose cannot make joshua-backend depend
on it -- mcp-server already depends on joshua-backend), so an unreachable,
slow or failing server has to degrade to "unavailable", not to a 500.

Two ways a tool call can fail, and both are handled explicitly:

- Protocol-level: the tool raised, so the result has isError set.
- Payload-level: mcp-server/tools.py never raises on a backend failure. It
  returns {"error": "..."} as ordinary content, so isError stays False and the
  error is only visible by reading the payload.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

DEFAULT_MCP_SERVER_URL = "http://mcp-server:5002/mcp"
DEFAULT_TIMEOUT_SECONDS = 5.0

# portfolio_snapshot reads this backend's own /api/holdings and
# /api/allocation, so calling it from here would loop straight back in.
FORBIDDEN_TOOLS = frozenset({"portfolio_snapshot"})


def get_server_url():
    """The MCP endpoint from MCP_SERVER_URL, or None when MCP is switched off.

    Unset means the compose default. Set-but-empty is the off switch -- it is
    also how the test suite keeps every test off the network by default.
    """
    raw = os.environ.get("MCP_SERVER_URL")
    if raw is None:
        return DEFAULT_MCP_SERVER_URL
    raw = raw.strip()
    return raw or None


def get_timeout_seconds():
    """Overall budget for one batch of tool calls, from MCP_TIMEOUT_SECONDS.

    Covers connecting, the MCP handshake and every call in the batch.
    Unparseable or non-positive values fall back to the default.
    """
    raw = os.environ.get("MCP_TIMEOUT_SECONDS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return value


def _ok(tool, data):
    return {"tool": tool, "ok": True, "data": data, "error": None}


def _unavailable(tool, reason):
    return {"tool": tool, "ok": False, "data": None, "error": reason}


def _first_text(result):
    for block in result.content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    return None


def parse_result(tool, result):
    """Turn a CallToolResult into the ok/data/error dict this module returns."""
    if result.isError:
        return _unavailable(tool, f"tool raised: {_first_text(result) or 'no detail'}")

    payload = result.structuredContent
    if payload is None:
        text = _first_text(result)
        if text is None:
            return _unavailable(tool, "tool returned no content")
        try:
            payload = json.loads(text)
        except ValueError:
            return _unavailable(tool, "tool returned non-JSON content")

    # FastMCP wraps a non-object return value as {"result": ...}.
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]

    # The payload-level error: isError is False, but the backend behind the
    # tool failed and said so in the content.
    if isinstance(payload, dict) and "error" in payload:
        return _unavailable(tool, str(payload["error"]))

    return _ok(tool, payload)


def _describe(exc):
    """The innermost useful message, unwrapping anyio's exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


@asynccontextmanager
async def _open_session(url, timeout_seconds):
    """An initialised ClientSession on url. The seam tests replace."""
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=timeout_seconds)
            ) as session:
                await session.initialize()
                yield session


async def _call_tools_async(url, calls, timeout_seconds):
    # Every slot starts as a timeout, so whatever the deadline cuts off is
    # already reported correctly; completed calls overwrite their slot.
    results = [
        _unavailable(name, f"MCP server did not respond within {timeout_seconds:g}s")
        for name, _ in calls
    ]
    done = 0
    try:
        with anyio.move_on_after(timeout_seconds):
            async with _open_session(url, timeout_seconds) as session:
                for index, (name, arguments) in enumerate(calls):
                    result = await session.call_tool(name, arguments)
                    results[index] = parse_result(name, result)
                    done = index + 1
    except Exception as exc:  # noqa: BLE001 -- any transport failure degrades
        reason = f"could not reach MCP server at {url}: {_describe(exc)}"
        for index in range(done, len(calls)):
            results[index] = _unavailable(calls[index][0], reason)
    return results


def call_tools(calls):
    """Run [(tool_name, arguments), ...] over one MCP session, in order.

    Returns one {"tool", "ok", "data", "error"} dict per call, in the same
    order. Never raises for a server problem; raises ValueError only for a
    forbidden tool, which is a bug in the caller rather than a runtime fault.
    """
    calls = [(name, dict(arguments or {})) for name, arguments in calls]
    forbidden = sorted({name for name, _ in calls} & FORBIDDEN_TOOLS)
    if forbidden:
        raise ValueError(f"refusing to call {', '.join(forbidden)}: it calls back into this backend")
    if not calls:
        return []

    url = get_server_url()
    if url is None:
        return [_unavailable(name, "MCP is disabled (MCP_SERVER_URL is empty)") for name, _ in calls]

    try:
        results = asyncio.run(_call_tools_async(url, calls, get_timeout_seconds()))
    except Exception as exc:  # noqa: BLE001 -- e.g. called from a running loop
        reason = f"MCP call failed: {_describe(exc)}"
        results = [_unavailable(name, reason) for name, _ in calls]

    for result in results:
        if not result["ok"]:
            logger.warning("MCP %s unavailable: %s", result["tool"], result["error"])
    return results


def call_tool(name, arguments=None):
    """Single-call convenience wrapper around call_tools."""
    return call_tools([(name, arguments)])[0]
