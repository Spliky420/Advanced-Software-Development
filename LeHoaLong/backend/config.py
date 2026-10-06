"""Configuration for the Goals & Budgeting backend.

Everything that differs between a laptop and a container is an environment
variable with a sensible default, so a fresh clone runs without a .env file.

Nothing here hardcodes a model name: OLLAMA_MODEL is read from the
environment, per the team rule in CLAUDE.md. The default matches the team
default (qwen2.5:0.5b, small and fast); the demo runs on llama3.1:8b by
setting the variable, not by editing code.
"""

from __future__ import annotations

import os

# Release 0 is single-user. Every query still takes user_id as an explicit
# parameter, so multi-user support later means passing a real value through
# rather than a rewrite. This constant is only the fallback used when the
# client does not name a user.
#
# Must match the user_id the seed data uses for the primary demo user.
DEFAULT_USER_ID = 1


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on anything unusable."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# Anything other than these reads as false, so a typo disables a feature
# loudly rather than enabling it by accident.
_TRUTHY = ("1", "true", "yes", "on")


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean environment variable. Absent or unparseable -> default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUTHY


class Config:
    """Base configuration. Read once at app creation."""

    # --- Database ---------------------------------------------------------
    # DB_PATH is the name the compose file uses; the database container calls
    # the same file DB_FILE. Accept either so neither service has to be
    # renamed to match the other.
    DB_PATH = os.environ.get("DB_PATH") or os.environ.get("DB_FILE") or "/data/goals.db"

    # How long SQLite waits for a write lock before giving up. The database
    # file lives on a volume shared with the database container, so a brief
    # wait is far better than an immediate "database is locked".
    DB_BUSY_TIMEOUT_MS = _int_env("DB_BUSY_TIMEOUT_MS", 5000)

    # --- Ollama -----------------------------------------------------------
    # The only approved path to an LLM (CLAUDE.md). Never a commercial API.
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST") or "http://ollama:11434"
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
    OLLAMA_TIMEOUT_SECONDS = _float_env("OLLAMA_TIMEOUT_SECONDS", 120.0)
    # Low but non-zero: descriptions should read naturally without the model
    # drifting away from the instructions.
    OLLAMA_TEMPERATURE = _float_env("OLLAMA_TEMPERATURE", 0.2)

    # --- Progress ---------------------------------------------------------
    # How far a goal may sit either side of its plan before the observe phase
    # calls it behind or ahead, as a percentage of the amount the plan
    # expected by now. A dollar or two out on a four-thousand-dollar plan is
    # noise, not a trend. Floored at $1 so a tiny plan is not hair-triggered.
    PROGRESS_TOLERANCE_PERCENT = _float_env("PROGRESS_TOLERANCE_PERCENT", 1.0)
    PROGRESS_TOLERANCE_FLOOR = _float_env("PROGRESS_TOLERANCE_FLOOR", 1.0)

    # --- MCP (Release 1) --------------------------------------------------
    # The shared MCP server is a HOST process, not a container (see the brief
    # and the README's "Two conflicts" note), so a containerised backend
    # cannot reach it on a compose service name. On Docker Desktop the host is
    # host.docker.internal; `extra_hosts: ["host.docker.internal:host-gateway"]`
    # in the compose snippet makes the same name work on Linux. Running the
    # backend outside Docker, point this at localhost instead.
    #
    # The path matters: /mcp is the streamable-http endpoint FastMCP serves
    # (mcp-server/server.py). Port 5001 is a Flask harness that renders HTML
    # for its author's own UI and is not an MCP endpoint at all.
    MCP_ENABLED = _bool_env("MCP_ENABLED", True)
    MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL") or "http://host.docker.internal:5002/mcp"
    # Bounds one whole MCP operation, connect to result, however many tools
    # share the session. Measured against the shared server on the development
    # laptop, assembling the budget context (two tools, one session):
    #
    #   both teammate backends healthy      2.8s
    #   both refusing connections           6.8s   -> falls back, 2 error rows
    #
    # 15s is a bit over twice the worst measured case. Sizing it higher buys
    # nothing: mcp-server/tools.py gives each teammate request its own 10s
    # timeout and bill_summary makes two of them, so a single *hung* backend
    # can burn 20s inside the tool alone. No deadline this side of the
    # protocol can wait that out, so the deadline is sized for the cases it
    # can actually distinguish, and a hung backend lands on the same clean
    # fallback as a refused one.
    MCP_TIMEOUT_SECONDS = _float_env("MCP_TIMEOUT_SECONDS", 15.0)

    # --- RAG (Release 1) --------------------------------------------------
    # The shared RAG server, also a host process (rag-server/rag_http_server.py
    # on port 5003). Same host.docker.internal reasoning as MCP above.
    #
    # No path suffix: the server routes on /health, /retrieve, /answer and
    # /refresh from the root.
    RAG_ENABLED = _bool_env("RAG_ENABLED", True)
    RAG_SERVER_URL = os.environ.get("RAG_SERVER_URL") or "http://host.docker.internal:5003"

    # A grounded answer is a retrieval plus a full LLM generation inside the
    # RAG server, which runs its own Ollama call with a 120s timeout of its
    # own. This has to be generous enough not to abandon a request that is
    # still working on a cold model, while staying under gunicorn's 180s.
    RAG_TIMEOUT_SECONDS = _float_env("RAG_TIMEOUT_SECONDS", 150.0)

    # How many chunks to retrieve. The shared server defaults to 5 and derives
    # its confidence category from how many come back (>=3 reads as High), so
    # lowering this below 3 would cap every answer at Medium -- see the
    # README's known issues.
    RAG_TOP_K = _int_env("RAG_TOP_K", 5)

    # Identifies this backend in the RAG server's own audit log
    # (rag-server/rag-audit.jsonl), which records a `caller` per request.
    RAG_CALLER = os.environ.get("RAG_CALLER") or "lehoalong-goals-budgeting"

    # --- CORS -------------------------------------------------------------
    # The Vite dev server and the containerised frontend both live on 8060.
    # In the container the nginx proxy makes /api same-origin, so CORS only
    # actually matters when running `npm run dev` against a local backend.
    CORS_ORIGINS = tuple(
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:8060,http://127.0.0.1:8060",
        ).split(",")
        if origin.strip()
    )

    # --- Misc -------------------------------------------------------------
    JSON_SORT_KEYS = False
    TESTING = False
