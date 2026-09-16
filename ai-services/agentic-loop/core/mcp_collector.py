import re
from datetime import datetime, timezone
from pathlib import Path

from core import database_api


# Single source of truth for which MCP tools this pipeline can actually
# invoke, and what each one needs. Plan (mcp_pipeline.py) validates the
# model's tool choice against this dict's keys before Act ever runs --
# a name the model invents that isn't here is rejected, never called.
MCP_TOOLS = {
    "portfolio_snapshot": {
        "call": lambda params: database_api.get_portfolio_snapshot(),
        "params": [],
    },
    "glossary_lookup": {
        "call": lambda params: database_api.get_glossary_definition(params["term"]),
        "params": ["term"],
    },
    "document_search": {
        "call": lambda params: database_api.search_documents(
            params["query"], int(params.get("top_k", 5) or 5)
        ),
        "params": ["query"],
    },
    "bill_summary": {
        "call": lambda params: database_api.get_bill_summary(),
        "params": [],
    },
    "transaction_summary": {
        "call": lambda params: database_api.get_transaction_summary(),
        "params": [],
    },
    "goal_progress": {
        "call": lambda params: database_api.get_goal_progress(int(params["goal_id"])),
        "params": ["goal_id"],
    },
}


def list_available_tools() -> list[str]:
    return sorted(MCP_TOOLS)


def required_params(tool_name: str) -> list[str]:
    tool = MCP_TOOLS.get(tool_name)
    return list(tool["params"]) if tool else []


def collect_tool_evidence(tool_name: str, params: dict | None = None) -> dict:
    """ACT + OBSERVE evidence for one MCP tool call.

    Every number inside `result` traces back to core/database_api.py,
    which itself only relays what a teammate's backend already computed
    in Python -- this function never computes or adjusts a figure, it
    only records what came back and when.
    """
    params = params or {}
    called_at = datetime.now(timezone.utc).isoformat()

    tool = MCP_TOOLS.get(tool_name)
    if tool is None:
        return {
            "tool": tool_name,
            "input": params,
            "called_at": called_at,
            "invoked": False,
            "error": f"Unknown MCP tool: {tool_name}",
        }

    try:
        result = tool["call"](params)
        return {
            "tool": tool_name,
            "input": params,
            "called_at": called_at,
            "invoked": True,
            "result": result,
        }
    except Exception as exc:
        return {
            "tool": tool_name,
            "input": params,
            "called_at": called_at,
            "invoked": True,
            "error": str(exc),
        }


# ============================================================
# BOUNDARY ANALYSIS -- no model call.
# ============================================================

_TOOL_HEADING_RE = re.compile(r"^\d+\.\s+\*\*(?P<name>[a-z_]+)\*\*", re.MULTILINE)


def documented_tool_names(app_dir: Path) -> set[str]:
    prompt_path = app_dir / "prompts" / "implementation" / "tool_selection_prompt.txt"
    text = prompt_path.read_text(encoding="utf-8")
    return set(_TOOL_HEADING_RE.findall(text))


def analyse_tool_boundaries(app_dir: Path) -> dict:
    """Confirms the tools this pipeline can actually invoke (MCP_TOOLS)
    match, one for one, what tool_selection_prompt.txt tells the model is
    available. Pure Python, no model call -- catches drift in either
    direction (documented but unimplemented, or implemented but
    undocumented) before it reaches a live request.
    """
    documented = documented_tool_names(app_dir)
    implemented = set(MCP_TOOLS)

    return {
        "documented_only": sorted(documented - implemented),
        "implemented_only": sorted(implemented - documented),
        "in_sync": sorted(documented & implemented),
        "boundaries_match": documented == implemented,
    }
