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
