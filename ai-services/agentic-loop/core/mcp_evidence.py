import importlib.util
from pathlib import Path


# Mirrors AVAILABLE_TOOLS in mcp-server/server.py -- the six tools the real
# deployed MCP server exposes, not core/database_api.py's local copy.
REQUIRED_MCP_TOOLS = [
    "portfolio_snapshot",
    "glossary_lookup",
    "document_search",
    "bill_summary",
    "transaction_summary",
    "goal_progress",
]

# Mirrors mcp-server/tools.py's public function names.
REQUIRED_FUNCTIONS = {
    "portfolio_snapshot": "get_portfolio_snapshot",
    "glossary_lookup": "get_glossary_definition",
    "document_search": "search_documents",
    "bill_summary": "get_bill_summary",
    "transaction_summary": "get_transaction_summary",
    "goal_progress": "get_goal_progress",
}


def _load_tools_module(mcp_server_dir: Path):
    spec = importlib.util.spec_from_file_location("mcp_tools_check", mcp_server_dir / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(app_dir: Path, repo_root: Path) -> tuple[bool, str]:
    """No model call: proves mcp-server/ actually implements and can run
    every documented tool, rather than trusting that the code looks right.

    Loads the real mcp-server/tools.py (the deployed artifact), not
    core/database_api.py's copy, so this catches drift between the two.
    A tool call "succeeding" here means it didn't raise -- tools.py never
    raises on an unreachable backend, it returns {"error": ...} instead
    (see mcp-server/tools.py's _request), so this checks that the tool
    is callable and well-formed, not that every backend answered live.
    """
    mcp_server_dir = repo_root / "mcp-server"

    required_paths = [
        mcp_server_dir / "tools.py",
        mcp_server_dir / "server.py",
        mcp_server_dir / "requirements.txt",
        mcp_server_dir / "routes" / "mcp_mode.py",
        app_dir / "prompts" / "implementation" / "tool_selection_prompt.txt",
        app_dir / "prompts" / "review" / "integration_review_prompt.txt",
    ]

    missing = [str(path.relative_to(repo_root)) for path in required_paths if not path.exists()]
    if missing:
        return False, "MCP evidence incomplete. Missing: " + ", ".join(missing)

    tools_text = (mcp_server_dir / "tools.py").read_text(encoding="utf-8")
    server_text = (mcp_server_dir / "server.py").read_text(encoding="utf-8")

    missing_tools = [tool for tool in REQUIRED_MCP_TOOLS if tool not in server_text]
    if missing_tools:
        return False, "MCP server missing required tools: " + ", ".join(missing_tools)

    missing_functions = [
        func_name for func_name in REQUIRED_FUNCTIONS.values() if f"def {func_name}" not in tools_text
    ]
    if missing_functions:
        return False, "tools.py missing required function implementations: " + ", ".join(missing_functions)

    # Execute all six MCP tools against the live team backends.
    try:
        tools_module = _load_tools_module(mcp_server_dir)
        tools_module.get_portfolio_snapshot()
        tools_module.get_glossary_definition("ETF")
        tools_module.search_documents("dividend reinvestment", 5)
        tools_module.get_bill_summary()
        tools_module.get_transaction_summary()
        tools_module.get_goal_progress(1)
    except Exception as exc:
        return False, f"MCP tool execution failed: {exc}"

    return True, (
        "MCP evidence: mcp-server/ contains tools.py and server.py; "
        f"server defines {len(REQUIRED_MCP_TOOLS)} tools (portfolio_snapshot, glossary_lookup, "
        "document_search, bill_summary, transaction_summary, goal_progress); all 6 tools executed "
        "without raising; routes/mcp_mode.py and implementation/review prompts exist."
    )
