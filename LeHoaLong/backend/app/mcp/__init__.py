"""MCP integration -- this backend as a client of the team's shared MCP server.

Two modules, and the split is the architectural point:

    client.py   the protocol. Connects, lists tools, calls one by name.
    context.py  the use. Turns two teammates' tools into the budget context
                a savings plan needs, carrying every figure through unchanged.

This package is named `mcp` and the official SDK it imports is also named
`mcp`. There is no conflict: Python 3 resolves imports absolutely, so
`from mcp import ClientSession` inside client.py finds the installed SDK,
while this package is only ever reachable as `app.mcp`.
"""
