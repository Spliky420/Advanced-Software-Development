import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core import mcp_collector


def _load_prompt_file(app_dir: Path, relative_path: str) -> str:
    return (app_dir / "prompts" / relative_path).read_text(encoding="utf-8")


def _extract_selected_tool(plan_response: str) -> str | None:
    match = re.search(r"Selected Tool:\s*\[?([a-z_]+)\]?", plan_response, re.IGNORECASE)
    if not match:
        return None

    name = match.group(1).strip().lower()
    return name if name in mcp_collector.MCP_TOOLS else None


def run_mcp_review(user_request: str, app_dir: Path, ai, ask_for_param=input) -> dict:
    """The MCP mode's Plan -> Act -> Observe -> Adapt loop for one user
    request.

    PLAN and ADAPT are the only two Ollama calls that reason in prose;
    ACT is pure Python (core/mcp_collector.py calling
    core/database_api.py). No step ever asks the model for a number --
    PLAN only ever returns a tool *name* checked against
    mcp_collector.MCP_TOOLS, and every figure downstream comes from
    whatever that tool's evidence actually contains.
    """
    print()
    print("======================================")
    print("MCP REVIEW")
    print(f"REQUEST: {user_request}")
    print("======================================")

    # =====================================
    # PLAN
    # =====================================
    print()
    print("[PLAN]")

    selection_prompt = _load_prompt_file(
        app_dir, "implementation/tool_selection_prompt.txt"
    ).replace("{{USER_REQUEST}}", user_request)

    print("Asking Ollama to select an MCP tool...")
    plan_response = ai.run(selection_prompt)

    selected_tool = _extract_selected_tool(plan_response)

    if selected_tool is None:
        print()
        print(
            "No tool from the documented list was selected "
            "(hallucinated name, or insufficient context). Stopping."
        )
        result = {
            "user_request": user_request,
            "plan_response": plan_response,
            "selected_tool": None,
        }
        _write_run_report(app_dir, result)
        return result

    print(f"Selected tool: {selected_tool}")

    # =====================================
    # ACT
    # =====================================
    print()
    print("[ACT]")

    params = {}
    for param_name in mcp_collector.required_params(selected_tool):
        params[param_name] = ask_for_param(f"  {param_name}: ").strip()

    print(f"Invoking {selected_tool}({params})...")
    evidence = mcp_collector.collect_tool_evidence(selected_tool, params)

    # =====================================
    # OBSERVE
    # =====================================
    print()
    print("[OBSERVE]")

    observe_prompt = f"""
You are a finance assistant. Answer the user's request using ONLY the JSON
evidence below. Every figure in your answer must come from this evidence --
never invent, adjust, or estimate a number that is not present in it.

USER REQUEST:
{user_request}

TOOL EXECUTION EVIDENCE:
{json.dumps(evidence, indent=2, default=str)}
"""

    print("Asking Ollama to interpret the tool evidence...")
    agent_response = ai.run(observe_prompt)

    # =====================================
    # ADAPT
    # =====================================
    print()
    print("[ADAPT]")

    integration_prompt = (
        _load_prompt_file(app_dir, "review/integration_review_prompt.txt")
        .replace(
            "{{TOOL_EXECUTION_EVIDENCE}}",
            json.dumps(evidence, indent=2, default=str),
        )
        .replace("{{AGENT_RESPONSE}}", agent_response)
        .replace("{{USER_REQUEST}}", user_request)
    )

    print("Asking Ollama to validate the MCP integration...")
    integration_review = ai.run(integration_prompt)

    result = {
        "user_request": user_request,
        "plan_response": plan_response,
        "selected_tool": selected_tool,
        "params": params,
        "evidence": evidence,
        "agent_response": agent_response,
        "integration_review": integration_review,
    }

    _write_run_report(app_dir, result)
    _write_integration_report(app_dir, result)

    return result


def run_boundary_analysis(app_dir: Path) -> dict:
    """No model call: compares prompts/implementation/tool_selection_prompt.txt
    against core/mcp_collector.py's MCP_TOOLS registry and writes the
    result to reports/boundary-analysis.md.
    """
    analysis = mcp_collector.analyse_tool_boundaries(app_dir)

    report_path = app_dir / "reports" / "boundary-analysis.md"
    report_path.write_text(
        f"""# MCP Tool Boundary Analysis

Generated: {_timestamp()}

No model call -- pure Python comparison of
prompts/implementation/tool_selection_prompt.txt against
core/mcp_collector.py's MCP_TOOLS registry.

- In sync: {', '.join(analysis['in_sync']) or '(none)'}
- Documented but not implemented: {', '.join(analysis['documented_only']) or '(none)'}
- Implemented but not documented: {', '.join(analysis['implemented_only']) or '(none)'}

Boundaries match: {analysis['boundaries_match']}
""",
        encoding="utf-8",
    )

    return analysis


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _write_run_report(app_dir: Path, result: dict) -> None:
    report_path = app_dir / "reports" / "run-report.md"

    if result.get("selected_tool") is None:
        report_path.write_text(
            f"""# MCP Run Report

Generated: {_timestamp()}

## Request
{result['user_request']}

## Plan
No tool selected.

```
{result['plan_response']}
```
""",
            encoding="utf-8",
        )
        return

    report_path.write_text(
        f"""# MCP Run Report

Generated: {_timestamp()}

## Request
{result['user_request']}

## Plan
Selected tool: `{result['selected_tool']}`

```
{result['plan_response']}
```

## Act / Observe
Params: `{result.get('params', {})}`

```json
{json.dumps(result.get('evidence', {}), indent=2, default=str)}
```

## Agent response
{result.get('agent_response', '')}
""",
        encoding="utf-8",
    )


def _write_integration_report(app_dir: Path, result: dict) -> None:
    report_path = app_dir / "reports" / "integration-report.md"
    report_path.write_text(
        f"""# MCP Integration Review

Generated: {_timestamp()}
Tool: `{result['selected_tool']}`

{result.get('integration_review', '')}
""",
        encoding="utf-8",
    )
