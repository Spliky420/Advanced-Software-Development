import re
from datetime import datetime, timezone
from pathlib import Path

from core import database_api, mcp_evidence


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


# ============================================================
# GENERIC-ORCHESTRATOR COLLECTOR -- lets mode="mcp" run through the same
# core/orchestrator.py COLLECTORS registry as db/endpoints/architecture/
# devops, instead of only through the bespoke run_mcp_review flow.
# ============================================================


def build_integration_evidence(app_dir: Path, repo_root: Path) -> str:
    """Shared evidence text for both the generic "mcp" review mode and
    core/mcp_pipeline.py's run_mcp_integration_review: the automated,
    no-model tool validation (mcp_evidence.collect) plus the boundary
    analysis. One place builds this so the two callers can't drift.
    """
    validation_passed, validation_message = mcp_evidence.collect(app_dir, repo_root)
    boundaries = analyse_tool_boundaries(app_dir)

    return f"""Tool validation: {"PASS" if validation_passed else "FAIL"}
{validation_message}

Tool boundary analysis:
- In sync: {', '.join(boundaries['in_sync']) or '(none)'}
- Documented but not implemented: {', '.join(boundaries['documented_only']) or '(none)'}
- Implemented but not documented: {', '.join(boundaries['implemented_only']) or '(none)'}
- Boundaries match: {boundaries['boundaries_match']}"""


def collect(repo_root: Path, student: str) -> str:
    """Matches the (repo_root, student) shape every other mode's collector
    module uses. MCP evidence has no per-student concept -- one tool
    registry spans all six backends -- so `student` is accepted but
    unused, the same as core/collectors.py's collect_architecture does
    for student="all".
    """
    app_dir = repo_root / "ai-services" / "agentic-loop"
    return build_integration_evidence(app_dir, repo_root)
