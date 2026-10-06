"""Client for the team's shared, non-containerised MCP server.

The Research Library is an MCP *client* here: it calls a tool registered on
the shared server (mcp-server/server.py) over the real MCP protocol
(streamable-http), the same transport Thomas/backend uses -- not the
server's htmx test harness on port 5001.

Tool boundary: this feature is only allowed to call the tools listed in
ALLOWED_TOOLS. The shared server exposes six tools for the whole team, but
the Research Library only has a reason to use one of them (looking up a
financial term found in a document), so anything else is refused here
before a connection is ever opened.

MCP is switched off with MCP_ENABLED=false (CI does this), which makes every
call raise MCPDisabledError instead of trying to reach a server that is not
running there.
"""

import asyncio
import json
import os

DEFAULT_MCP_SERVER_URL = "http://host.docker.internal:5002/mcp"
MCP_TIMEOUT_SECONDS = 20

ALLOWED_TOOLS = ("glossary_lookup",)


class MCPDisabledError(Exception):
    """MCP mode is switched off by configuration (MCP_ENABLED=false)."""


class MCPUnavailableError(Exception):
    """The MCP server could not be reached, timed out, or returned nothing usable."""


class MCPToolNotAllowedError(Exception):
    """The requested tool is outside this feature's MCP tool boundary."""


def mcp_enabled():
    return os.environ.get("MCP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def server_url():
    return os.environ.get("MCP_SERVER_URL", DEFAULT_MCP_SERVER_URL)


async def _call_tool_async(url, tool_name, arguments):
    # Imported here rather than at module top so the rest of the backend (and
    # its tests) never depends on the MCP SDK's import side effects.
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments=arguments)


def _run(url, tool_name, arguments):
    """Run one MCP round trip synchronously, bounded by MCP_TIMEOUT_SECONDS.

    Split out from call_tool so tests can replace the network leg without
    touching the boundary and parsing logic around it.
    """
    return asyncio.run(
        asyncio.wait_for(_call_tool_async(url, tool_name, arguments), MCP_TIMEOUT_SECONDS)
    )


def parse_tool_result(result):
    """Turn a CallToolResult into the plain dict the tool returned.

    FastMCP serialises a tool's dict return value as JSON text content, and
    may also attach it as structuredContent (wrapped in {"result": ...} when
    the tool has no declared output schema).
    """
    if getattr(result, "isError", False):
        text = " ".join(getattr(block, "text", "") for block in (result.content or []))
        raise MCPUnavailableError(f"MCP tool returned an error: {text.strip() or 'no detail'}")

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result", structured)
        if isinstance(inner, dict):
            return inner

    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            try:
                payload = json.loads(text)
            except ValueError as exc:
                raise MCPUnavailableError(f"MCP tool returned non-JSON content: {exc}") from exc
            if isinstance(payload, dict):
                return payload

    raise MCPUnavailableError("MCP tool returned no usable content")


def call_tool(tool_name, arguments):
    """Call one allowed tool on the shared MCP server and return its dict result."""
    if not mcp_enabled():
        raise MCPDisabledError("MCP mode is disabled (MCP_ENABLED=false)")
    if tool_name not in ALLOWED_TOOLS:
        raise MCPToolNotAllowedError(
            f"tool '{tool_name}' is outside the Research Library's MCP boundary "
            f"(allowed: {', '.join(ALLOWED_TOOLS)})"
        )

    url = server_url()
    try:
        result = _run(url, tool_name, arguments)
    except (MCPUnavailableError, MCPDisabledError):
        raise
    except Exception as exc:  # noqa: BLE001 -- connection failures surface as ExceptionGroups, timeouts, OSErrors
        raise MCPUnavailableError(f"could not reach the MCP server at {url}: {exc!r}") from exc

    return parse_tool_result(result)
