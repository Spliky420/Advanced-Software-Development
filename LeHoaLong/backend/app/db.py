"""SQLite connection handling.

One connection per request, opened lazily and closed when the app context
tears down. Two pragmas matter and both are per-connection, so they have to be
set here rather than in schema.sql:

    foreign_keys  SQLite defaults this OFF for backwards compatibility. Without
                  it, ON DELETE CASCADE silently does nothing and deleting a
                  goal would orphan its steps and contributions.
    busy_timeout  The database file sits on a volume shared with the database
                  container. Waiting a few seconds for a write lock is far
                  better than failing immediately with "database is locked".
"""

from __future__ import annotations

import sqlite3

from flask import current_app, g


def get_db() -> sqlite3.Connection:
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DB_PATH"],
            timeout=current_app.config["DB_BUSY_TIMEOUT_MS"] / 1000,
            isolation_level="",  # explicit transactions; commit() is ours to call
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(current_app.config['DB_BUSY_TIMEOUT_MS'])}")
        g.db = conn
    return g.db


def close_db(exc: BaseException | None = None) -> None:
    """Close the request's connection, rolling back anything left uncommitted.

    Registered as a teardown handler. A view that raised part-way through a
    multi-statement write must not leave half of it behind.
    """
    conn = g.pop("db", None)
    if conn is None:
        return
    try:
        if exc is not None:
            conn.rollback()
    finally:
        conn.close()


def database_is_reachable() -> tuple[bool, str | None]:
    """Cheap liveness probe for /health.

    Returns (ok, error_message). Queries a real table rather than running
    `SELECT 1`, so a present-but-uninitialised database file reads as a
    failure instead of a pass.
    """
    try:
        get_db().execute("SELECT COUNT(*) FROM goals").fetchone()
        return True, None
    except sqlite3.Error as exc:
        return False, str(exc)
