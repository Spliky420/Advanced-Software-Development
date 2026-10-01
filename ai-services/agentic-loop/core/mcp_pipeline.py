import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core import mcp_collector, mcp_evidence


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


def run_tool_validation(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    """No model call: automates what the boundary analysis leaves out --
    proof that every documented MCP tool is actually implemented AND
    actually runs, not just named consistently in two files. Writes the
    result to reports/mcp-evidence.md on every run.
    """
    passed, message = mcp_evidence.collect(app_dir, repo_root)

    report_path = app_dir / "reports" / "mcp-evidence.md"
    report_path.write_text(
        f"""# MCP Tool Validation

Generated: {_timestamp()}

No model call -- pure Python: checks mcp-server/ has every required file,
tools.py implements every required function, server.py declares every
required tool, and then actually calls all six tools against the live
team backends to confirm they run without raising.

Result: {"PASS" if passed else "FAIL"}

{message}
""",
        encoding="utf-8",
    )

    return passed, message


DEFAULT_INTEGRATION_TASK_PROMPT = (
    "You are reviewing the MCP Tool Integration for the Personal Finance "
    "Assistant. The MCP server exposes six student backends' data "
    "(portfolio, glossary, documents, bills, transactions, goals) as MCP "
    "tools, calling each backend over HTTP rather than touching any "
    "database directly."
)


def build_implementation_prompt(task_prompt: str, evidence: str) -> str:
    return f"""
{task_prompt}

Review Scope:
MCP Tool Integration

Observed Evidence:
{evidence}

Validate that:
1. All 6 MCP tools are defined and callable
2. Tool boundaries are clear (what each tool does and does not do)
3. MCP endpoints exist in routes/mcp_mode.py
4. Prompts exist for tool selection and integration review

Reply in at most 40 words and stay evidence-based.
""".strip()


def build_review_prompt(implementation_output: str, evidence: str) -> str:
    return f"""
Implementation Recommendation:
{implementation_output}

Observed Evidence:
{evidence}

Validate the MCP integration assessment against the evidence.
Identify any gaps or risks in tool definitions or boundaries.

Reply in at most 40 words and stay evidence-based.
""".strip()


def run_mcp_integration_review(
    app_dir: Path,
    repo_root: Path,
    ai,
    task_prompt: str = DEFAULT_INTEGRATION_TASK_PROMPT,
) -> dict:
    """The model-facing half of MCP tool validation: takes the automated,
    no-model evidence from mcp_evidence.collect() and
    mcp_collector.analyse_tool_boundaries(), then runs it through two
    Ollama calls -- an implementation assessment, then a review pass that
    cross-checks that assessment against the same evidence. Neither call
    is asked for a number; both only ever see evidence Python already
    computed.
    """
    print()
    print("======================================")
    print("MCP TOOL INTEGRATION REVIEW")
    print("======================================")

    # =====================================
    # ACT (automated, no model call)
    # =====================================
    print()
    print("[ACT]")

    evidence = mcp_collector.build_integration_evidence(app_dir, repo_root)

    # =====================================
    # OBSERVE
    # =====================================
    print()
    print("[OBSERVE]")

    print("Asking Ollama for an implementation assessment...")
    implementation_output = ai.run(build_implementation_prompt(task_prompt, evidence))

    # =====================================
    # ADAPT
    # =====================================
    print()
    print("[ADAPT]")

    print("Asking Ollama to review that assessment against the evidence...")
    review_output = ai.run(build_review_prompt(implementation_output, evidence))

    result = {
        "evidence": evidence,
        "implementation_output": implementation_output,
        "review_output": review_output,
    }

    report_path = app_dir / "reports" / "mcp-integration-review.md"
    report_path.write_text(
        f"""# MCP Tool Integration Review

Generated: {_timestamp()}

## Evidence (Act -- no model call)
```
{evidence}
```

## Implementation Assessment (Observe)
{implementation_output}

## Review (Adapt)
{review_output}
""",
        encoding="utf-8",
    )

    return result


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
