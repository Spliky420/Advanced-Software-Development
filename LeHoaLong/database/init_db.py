#!/usr/bin/env python3
"""Create and seed the Goals & Budgeting SQLite database.

Runs both inside the database container (as the entrypoint) and on a
developer's machine. It is deliberately dependency-free -- standard library
only -- so it works in a `python:3.11-slim` image with nothing pip-installed.

Usage
-----
    python init_db.py                       # create if missing, then summarise
    python init_db.py --force               # drop and rebuild from scratch
    python init_db.py --db ./goals.db       # explicit path, overrides $DB_FILE
    python init_db.py --summary-only        # just print what is already there

The database path is taken from, in order of precedence: ``--db``, the
``DB_FILE`` environment variable, then ``DB_PATH`` (which is the name the
backend container uses for the same file), then ``/data/goals.db``.

Exit codes: 0 success, 1 failure (missing SQL file, bad SQL, failed check).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / "schema.sql"
SEED_FILE = HERE / "seed.sql"

DEFAULT_DB_PATH = "/data/goals.db"

# Every table the schema defines, child-first, which is also a sensible order
# to report counts in.
TABLES = ("goals", "goal_steps", "contributions", "ai_plan_log", "budget_settings")

# The marking requirement: every table carries at least this many rows.
MIN_ROWS_PER_TABLE = 10


def resolve_db_path(cli_value: str | None) -> Path:
    """Pick the database path from the CLI, then the environment, then default."""
    chosen = cli_value or os.environ.get("DB_FILE") or os.environ.get("DB_PATH") or DEFAULT_DB_PATH
    return Path(chosen)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced.

    SQLite defaults foreign keys OFF for backwards compatibility, and the
    PRAGMA is per-connection -- setting it in schema.sql does not make it
    stick. Every connection that writes has to turn it on, here and in the
    backend's db layer.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def run_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    """Execute one .sql file as a script."""
    if not path.is_file():
        raise FileNotFoundError(f"required SQL file not found: {path}")
    conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()


def build(db_path: Path, force: bool) -> bool:
    """Create and seed the database. Returns True if it did any work.

    The database is built at a temporary path and moved into place only once
    both scripts have succeeded, so a crash part-way leaves no half-seeded
    file for the next start to inherit.
    """
    if db_path.exists() and not force:
        print(f"[init_db] {db_path} already exists -- skipping schema and seed (use --force to rebuild).")
        return False

    db_path.parent.mkdir(parents=True, exist_ok=True)

    building = db_path.with_name(f".{db_path.name}.building")
    for leftover in (building, building.with_name(building.name + "-journal")):
        leftover.unlink(missing_ok=True)

    conn = connect(building)
    try:
        run_sql_file(conn, SCHEMA_FILE)
        print(f"[init_db] schema created from {SCHEMA_FILE.name}")
        run_sql_file(conn, SEED_FILE)
        print(f"[init_db] seed data loaded from {SEED_FILE.name}")
    finally:
        conn.close()

    db_path.unlink(missing_ok=True)
    building.replace(db_path)
    print(f"[init_db] initialised {db_path}")
    return True


def check(conn: sqlite3.Connection) -> list[str]:
    """Verify the invariants the seed data claims. Returns a list of problems."""
    problems: list[str] = []

    for table in TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count < MIN_ROWS_PER_TABLE:
            problems.append(f"{table} has {count} rows, fewer than the required {MIN_ROWS_PER_TABLE}")

    # Foreign keys: SQLite only enforces them on write, so an existing file
    # built with the pragma off could still hold orphans.
    for violation in conn.execute("PRAGMA foreign_key_check").fetchall():
        problems.append(f"foreign key violation in {violation[0]}, rowid {violation[1]}")

    # Each goal's steps should sum to its target amount. Goals with no steps
    # yet (7 and 13) are excluded -- no plan is not a broken plan.
    mismatches = conn.execute(
        """
        SELECT g.goal_id, g.name, g.target_amount, SUM(s.step_amount) AS step_total
          FROM goals g
          JOIN goal_steps s ON s.goal_id = g.goal_id
         GROUP BY g.goal_id
        HAVING ABS(SUM(s.step_amount) - g.target_amount) > 0.005
        """
    ).fetchall()
    for row in mismatches:
        problems.append(
            f"goal {row['goal_id']} ({row['name']}): steps sum to {row['step_total']:.2f} "
            f"but the target is {row['target_amount']:.2f}"
        )

    # An 'achieved' goal should actually be funded.
    underfunded = conn.execute(
        """
        SELECT g.goal_id, g.name, g.target_amount,
               COALESCE((SELECT SUM(c.amount) FROM contributions c WHERE c.goal_id = g.goal_id), 0) AS saved
          FROM goals g
         WHERE g.status = 'achieved'
        """
    ).fetchall()
    for row in underfunded:
        if row["saved"] + 0.005 < row["target_amount"]:
            problems.append(
                f"goal {row['goal_id']} ({row['name']}) is marked achieved but only "
                f"{row['saved']:.2f} of {row['target_amount']:.2f} has been contributed"
            )

    return problems


def summarise(conn: sqlite3.Connection) -> None:
    """Print the seeded data -- row counts, then a per-goal roll-up."""
    print()
    print("Row counts")
    print("-" * 78)
    for table in TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        flag = "ok" if count >= MIN_ROWS_PER_TABLE else "TOO FEW"
        print(f"  {table:<16} {count:>4}   {flag}")

    print()
    print("Goals")
    print("-" * 78)
    header = f"  {'id':>2}  {'usr':>3}  {'name':<28} {'target':>9} {'saved':>9} {'steps':>5}  {'status':<9} pri"
    print(header)
    rows = conn.execute(
        """
        SELECT g.goal_id, g.user_id, g.name, g.target_amount, g.priority, g.status, g.target_date,
               COALESCE((SELECT SUM(c.amount) FROM contributions c WHERE c.goal_id = g.goal_id), 0) AS saved,
               (SELECT COUNT(*) FROM goal_steps s WHERE s.goal_id = g.goal_id) AS step_count
          FROM goals g
         ORDER BY g.user_id, g.goal_id
        """
    ).fetchall()
    for row in rows:
        print(
            f"  {row['goal_id']:>2}  {row['user_id']:>3}  {row['name'][:28]:<28} "
            f"{row['target_amount']:>9,.2f} {row['saved']:>9,.2f} {row['step_count']:>5}  "
            f"{row['status']:<9} {row['priority']}"
        )

    print()
    print("Budget settings")
    print("-" * 78)
    for row in conn.execute("SELECT user_id, monthly_budget, currency FROM budget_settings ORDER BY user_id"):
        goals_owned = conn.execute(
            "SELECT COUNT(*) FROM goals WHERE user_id = ? AND status = 'active'", (row["user_id"],)
        ).fetchone()[0]
        print(
            f"  user {row['user_id']:>2}   {row['monthly_budget']:>9,.2f} {row['currency']}"
            f"   {goals_owned} active goal(s)"
        )

    print()
    print("ai_plan_log by phase and model")
    print("-" * 78)
    for row in conn.execute(
        "SELECT phase, model_name, COUNT(*) AS n FROM ai_plan_log GROUP BY phase, model_name ORDER BY phase, model_name"
    ):
        print(f"  {row['phase']:<9} {row['model_name']:<14} {row['n']:>3}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and seed the Goals & Budgeting database.")
    parser.add_argument("--db", help="path to the SQLite file (overrides $DB_FILE / $DB_PATH)")
    parser.add_argument("--force", action="store_true", help="rebuild even if the database already exists")
    parser.add_argument("--summary-only", action="store_true", help="do not build, just report on the existing file")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary tables")
    args = parser.parse_args(argv)

    db_path = resolve_db_path(args.db)

    try:
        if args.summary_only:
            if not db_path.exists():
                print(f"[init_db] no database at {db_path}", file=sys.stderr)
                return 1
        else:
            build(db_path, force=args.force)
    except (OSError, sqlite3.Error) as exc:
        print(f"[init_db] failed: {exc}", file=sys.stderr)
        return 1

    conn = connect(db_path)
    try:
        problems = check(conn)
        if not args.quiet:
            summarise(conn)
    finally:
        conn.close()

    if problems:
        print("[init_db] CONSISTENCY PROBLEMS:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"[init_db] ready: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
