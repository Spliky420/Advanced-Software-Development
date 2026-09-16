import json
import os
import re

import requests


MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:5001")

REQUEST_TIMEOUT = 15  # seconds

# mcp-server's /mcp/* routes (routes/mcp_mode.py) render an HTML fragment
# for browser/HTMX display -- <h3>title</h3><pre>{json}</pre> -- not raw
# JSON. This pulls the JSON back out of that wrapper so mcp_collector.py
# gets a plain dict/list, same as every other collector in this file's
# sibling core/collectors.py. If mcp_mode.py grows a JSON-only mode
# (e.g. an Accept: application/json branch) switch to that instead.
_PRE_BLOCK_RE = re.compile(r"<pre>(?P<body>.*)</pre>", re.DOTALL)


def _unwrap_json(response: requests.Response):
    match = _PRE_BLOCK_RE.search(response.text)
    if not match:
        raise ValueError(f"No JSON payload found in response: {response.text[:200]}")
    return json.loads(match.group("body"))


def get_portfolio_snapshot_response():
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/portfolio-snapshot",
        timeout=REQUEST_TIMEOUT,
    )


def get_glossary_definition_response(term):
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/glossary-lookup",
        data={"term": term},
        timeout=REQUEST_TIMEOUT,
    )


def search_documents_response(query, top_k=5):
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/document-search",
        data={"query": query, "top_k": top_k},
        timeout=REQUEST_TIMEOUT,
    )


def get_bill_summary_response():
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/bill-summary",
        timeout=REQUEST_TIMEOUT,
    )


def get_transaction_summary_response():
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/transaction-summary",
        timeout=REQUEST_TIMEOUT,
    )


def get_goal_progress_response(goal_id):
    return requests.post(
        f"{MCP_SERVER_URL}/mcp/goal-progress",
        data={"goal_id": goal_id},
        timeout=REQUEST_TIMEOUT,
    )


# Convenience wrappers that raise on a non-2xx and return the unwrapped
# JSON payload directly, mirroring collectors.py's read_file() -- callers
# that need to branch on status code (e.g. a 400/503 from the tool) should
# call the *_response() functions above instead.

def get_portfolio_snapshot():
    response = get_portfolio_snapshot_response()
    response.raise_for_status()
    return _unwrap_json(response)


def get_glossary_definition(term):
    response = get_glossary_definition_response(term)
    response.raise_for_status()
    return _unwrap_json(response)


def search_documents(query, top_k=5):
    response = search_documents_response(query, top_k)
    response.raise_for_status()
    return _unwrap_json(response)


def get_bill_summary():
    response = get_bill_summary_response()
    response.raise_for_status()
    return _unwrap_json(response)


def get_transaction_summary():
    response = get_transaction_summary_response()
    response.raise_for_status()
    return _unwrap_json(response)


def get_goal_progress(goal_id):
    response = get_goal_progress_response(goal_id)
    response.raise_for_status()
    return _unwrap_json(response)
