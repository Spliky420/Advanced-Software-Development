"""AI_MODE_ENABLED: the one switch for every AI-backed call this backend makes.

When it reads false, this backend makes no call to Ollama, the MCP server,
the RAG server or the Multi-Agent Server. Every client checks it itself
(llm, mcp_client, rag_client, multi_agent_client), so no code path can reach
an AI service with the switch off, whichever route asked. CRUD, allocation
and the Python half of the drift review do not depend on it.

Read on every call rather than once at import, so a test (or an operator
restarting with a new environment) never sees a stale value.
"""

import os

FALSE_VALUES = frozenset({"false", "0", "no", "off"})

DISABLED_MESSAGE = "AI mode is disabled (AI_MODE_ENABLED=false)"


def is_enabled():
    """True unless AI_MODE_ENABLED is set to false, 0, no or off.

    Unset or empty means enabled, matching the compose default of "true".
    """
    raw = os.environ.get("AI_MODE_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in FALSE_VALUES
