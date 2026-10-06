import os
import re

import requests

REQUEST_TIMEOUT = 10  # seconds

# The MCP server runs on the host, not in compose, so base URLs default to
# each backend's published host port (see the port table in CLAUDE.md).
# Override via env var, e.g. JOSHUA_BACKEND_URL=http://localhost:8011.
JOSHUA_BACKEND_URL = os.getenv("JOSHUA_BACKEND_URL", "http://localhost:8011")
MAXWELL_BACKEND_URL = os.getenv("MAXWELL_BACKEND_URL", "http://localhost:8021")
ENEREL_BACKEND_URL = os.getenv("ENEREL_BACKEND_URL", "http://localhost:8031")
HYUNWOO_BACKEND_URL = os.getenv("HYUNWOO_BACKEND_URL", "http://localhost:8041")
THOMAS_BACKEND_URL = os.getenv("THOMAS_BACKEND_URL", "http://localhost:8051")
LEHOALONG_BACKEND_URL = os.getenv("LEHOALONG_BACKEND_URL", "http://localhost:8061")


def _request(method: str, base_url: str, path: str, **kwargs):
    """Call a teammate's backend and normalise connection failures.

    Every number a tool returns below is already Python-computed by the
    owning backend (see CLAUDE.md's arithmetic rule) -- this file only
    relays it, it never computes or adjusts a figure itself.
    """
    try:
        response = requests.request(
            method, f"{base_url}{path}", timeout=REQUEST_TIMEOUT, **kwargs
        )
        response.raise_for_status()
        return response
    except requests.exceptions.ConnectionError:
        return {"error": f"Could not reach backend at {base_url}{path}"}
    except requests.exceptions.Timeout:
        return {"error": f"Backend timed out: {base_url}{path}"}
    except requests.exceptions.HTTPError as exc:
        return {
            "error": f"Backend returned {exc.response.status_code}: {base_url}{path}"
        }


def get_portfolio_snapshot():
    """portfolio_snapshot -- joshua/backend GET /api/holdings + /api/allocation."""
    holdings = _request("GET", JOSHUA_BACKEND_URL, "/api/holdings")
    if isinstance(holdings, dict):
        return holdings

    allocation = _request("GET", JOSHUA_BACKEND_URL, "/api/allocation")
    if isinstance(allocation, dict):
        return allocation

    return {
        "holdings": holdings.json(),
        "allocation": allocation.json(),
    }


def get_glossary_definition(term: str):
    """glossary_lookup -- Maxwell/backend GET /api/glossary/<term>."""
    term = (term or "").strip()
    if not term:
        return {"error": "term is required"}

    response = _request("GET", MAXWELL_BACKEND_URL, f"/api/glossary/{term}")
    if isinstance(response, dict):
        return response

    return response.json()


def search_documents(query: str, top_k: int = 5):
    """document_search -- Enerel/backend POST /api/documents/search.

    Every similarity score returned is a Python-computed cosine similarity
    (Enerel/backend/retrieval.py) -- the one model call this endpoint makes
    only embeds the query, it never produces the score.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "query is required"}

    response = _request(
        "POST",
        ENEREL_BACKEND_URL,
        "/api/documents/search",
        json={"query": query, "top_k": top_k},
    )
    if isinstance(response, dict):
        return response

    return response.json()


def get_bill_summary():
    """bill_summary -- hyunwoo/backend GET /api/bills + /api/summary."""
    bills = _request("GET", HYUNWOO_BACKEND_URL, "/api/bills")
    if isinstance(bills, dict):
        return bills

    summary = _request("GET", HYUNWOO_BACKEND_URL, "/api/summary")
    if isinstance(summary, dict):
        return summary

    return {
        "bills": bills.json(),
        "summary": summary.json(),
    }


# Matches the summary cards Thomas's backend renders, e.g.:
#   <span>Total Income</span><strong>$1,234.56</strong>
_SUMMARY_CARD_RE = re.compile(
    r"<span>(?P<label>[^<]+)</span>\s*<strong>\$(?P<amount>[-\d,.]+)</strong>"
)


def get_transaction_summary():
    """transaction_summary -- Thomas/backend GET /api/transactions/summary.

    NOTE: unlike every other teammate's endpoint, Thomas's backend renders
    this as an HTML fragment for direct embedding in his frontend, not
    JSON (see Thomas/backend/app.py) -- there is no JSON summary route to
    call instead. This scrapes the three figures Thomas's backend already
    computed in Python out of that HTML; it does not recompute them. If a
    JSON route is added later, switch to that and delete this workaround.
    """
    response = _request("GET", THOMAS_BACKEND_URL, "/api/transactions/summary")
    if isinstance(response, dict):
        return response

    cards = {
        match.group("label").strip(): float(match.group("amount").replace(",", ""))
        for match in _SUMMARY_CARD_RE.finditer(response.text)
    }

    if not cards:
        return {"error": "Could not parse transaction summary HTML"}

    return {
        "total_income": cards.get("Total Income"),
        "total_expenses": cards.get("Total Expenses"),
        "potential_deductions": cards.get("Potential Deductions"),
    }


def get_goal_progress(goal_id: int):
    """goal_progress -- LeHoaLong/backend GET /api/goals/<id>/progress."""
    if goal_id is None:
        return {"error": "goal_id is required"}

    response = _request(
        "GET", LEHOALONG_BACKEND_URL, f"/api/goals/{goal_id}/progress"
    )
    if isinstance(response, dict):
        return response

    return response.json()


if __name__ == "__main__":
    print(get_portfolio_snapshot())
    print(get_glossary_definition("ETF"))
    print(search_documents("dividend reinvestment"))
    print(get_bill_summary())
    print(get_transaction_summary())
    print(get_goal_progress(1))
