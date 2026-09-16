import os

from mcp.server.fastmcp import FastMCP

from tools import (
    get_portfolio_snapshot,
    get_glossary_definition,
    search_documents,
    get_bill_summary,
    get_transaction_summary,
    get_goal_progress,
)


# Runs as its own process alongside app.py's Flask harness (see Dockerfile),
# on its own port -- streamable-http, not stdio, because a real MCP client
# needs to reach this container over the shared docker-compose network
# rather than spawning it as a local subprocess.
MCP_HTTP_HOST = os.getenv("MCP_HTTP_HOST", "0.0.0.0")
MCP_HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "5002"))

mcp = FastMCP(
    "Personal Finance Assistant MCP",
    host=MCP_HTTP_HOST,
    port=MCP_HTTP_PORT,
    streamable_http_path="/mcp",
)

AVAILABLE_TOOLS = [
    "portfolio_snapshot",
    "glossary_lookup",
    "document_search",
    "bill_summary",
    "transaction_summary",
    "goal_progress",
]


@mcp.tool()
def portfolio_snapshot():
    """Get the user's current portfolio holdings and asset allocation.

    Returns holdings (one row per position) and allocation percentages by
    asset class, both already computed by joshua/backend
    (GET /api/holdings, GET /api/allocation). Use for questions about
    portfolio, holdings, or asset allocation.
    """
    return get_portfolio_snapshot()


@mcp.tool()
def glossary_lookup(
    term: str
):
    """Look up the definition of a financial term.

    Args:
        term: The financial term to define, e.g. "ETF".

    Returns the term's definition text from Maxwell/backend
    (GET /api/glossary/<term>). Use when asked what a financial term means.
    """
    return get_glossary_definition(term)


@mcp.tool()
def document_search(
    query: str,
    top_k: int = 5
):
    """Semantically search the user's saved research documents/notes.

    Args:
        query: Natural-language search query.
        top_k: Maximum number of matching documents to return.

    Returns a ranked list of matching documents with similarity scores,
    each a Python-computed cosine similarity from Enerel/backend
    (POST /api/documents/search) -- never model output. Use when asked to
    find, search, or recall saved research documents or notes.
    """
    return search_documents(query, top_k)


@mcp.tool()
def bill_summary():
    """Get upcoming/recurring bills and total obligations.

    Returns the bill list plus summary totals from hyunwoo/backend
    (GET /api/bills, GET /api/summary). Use for questions about upcoming
    bills, recurring payments, or bill totals.
    """
    return get_bill_summary()


@mcp.tool()
def transaction_summary():
    """Get spending/transaction totals: income, expenses, and potential
    deductions.

    Returns totals already computed by Thomas/backend
    (GET /api/transactions/summary). Use for questions about spending,
    recent transactions, or purchase categories.
    """
    return get_transaction_summary()


@mcp.tool()
def goal_progress(
    goal_id: int
):
    """Get progress toward a savings or budgeting goal.

    Args:
        goal_id: The id of the goal to check.

    Returns the target amount, amount contributed, and remaining
    instalments from LeHoaLong/backend (GET /api/goals/<id>/progress).
    Use when asked how close the user is to a savings goal or budget
    target.
    """
    return get_goal_progress(goal_id)


if __name__ == "__main__":
    print("Starting Personal Finance Assistant MCP Server...")
    print(f"Listening on http://{MCP_HTTP_HOST}:{MCP_HTTP_PORT}/mcp (streamable-http)")
    print("Available tools:")
    for tool in AVAILABLE_TOOLS:
        print(f"- {tool}")
    mcp.run(transport="streamable-http")
