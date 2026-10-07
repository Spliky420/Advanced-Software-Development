"""Data access for ai_plan_log -- the agentic loop's audit trail.

Every phase writes here: the exact prompt sent, the model tag used, and the
raw text that came back before anything parsed it. model_name holds the
literal 'python' for work that involved no model at all (the observe phase,
and the deterministic fallback plan), which is how you tell the two apart
when reading the table.

These rows are the evidence for the technical report, which is why they
survive their goal being deleted (ON DELETE SET NULL, see schema.sql).
"""

from __future__ import annotations

import sqlite3

PHASES = ("plan", "observe", "adapt", "mcp", "rag")

# The model_name written when Python did the work itself.
PYTHON = "python"

# Release 1 writes two more kinds of row, and neither can honestly claim a
# model tag of its own:
#
#   MCP         an MCP tool call runs no model at all. The MCP server relays
#               figures the owning backend already computed in Python.
#   RAG_SERVER  a grounded answer did involve a model, but it ran inside the
#               shared RAG server, which does not report its tag in the
#               response. Recording the tag this service happens to have
#               configured would be a guess, and a wrong one whenever the two
#               differ. See the README's known issues -- the pull request that
#               makes rag_pipeline.py read OLLAMA_MODEL from the environment
#               would also let it report what it used.
MCP = "mcp"
RAG_SERVER = "rag-server"

COLUMNS = ("log_id", "goal_id", "phase", "model_name", "prompt", "response", "created_at")

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM ai_plan_log"


def insert_log(
    conn: sqlite3.Connection,
    *,
    goal_id: int | None,
    phase: str,
    model_name: str,
    prompt: str,
    response: str | None,
    created_at: str,
) -> int:
    """Write one audit row and return its id."""
    cursor = conn.execute(
        """
        INSERT INTO ai_plan_log (goal_id, phase, model_name, prompt, response, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (goal_id, phase, model_name, prompt, response, created_at),
    )
    return int(cursor.lastrowid)


def list_for_goal(conn: sqlite3.Connection, goal_id: int, *, phase: str | None = None) -> list[sqlite3.Row]:
    """This goal's audit trail, newest first."""
    sql = f"{_SELECT} WHERE goal_id = ?"
    params: list = [goal_id]
    if phase is not None:
        sql += " AND phase = ?"
        params.append(phase)
    sql += " ORDER BY created_at DESC, log_id DESC"
    return conn.execute(sql, params).fetchall()


def latest_for_goal(conn: sqlite3.Connection, goal_id: int, phase: str) -> sqlite3.Row | None:
    """The most recent row for one goal and phase, or None."""
    return conn.execute(
        f"{_SELECT} WHERE goal_id = ? AND phase = ? ORDER BY log_id DESC LIMIT 1",
        (goal_id, phase),
    ).fetchone()
