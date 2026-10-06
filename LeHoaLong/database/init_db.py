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

Exit codes: 0 success, 1 failure (missing SQL file, bad SQL, structural
corruption, or a seed-time invariant broken on a *freshly built* database).

A database that already exists is checked more leniently on purpose: see
``check`` for which claims are guarantees and which are only observations
once real activity has touched the data. Getting that distinction wrong made
one drifted goal enough to crash-loop the database container.
"""

from __future__ import annotations

import argparse
import os
import re
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

# Every phase ai_plan_log must accept. Release 0 shipped three; Release 1's MCP
# and RAG integrations add two more, and an existing database file still has
# the old three-phase CHECK constraint -- see migrate_ai_plan_log.
REQUIRED_PHASES = ("plan", "observe", "adapt", "mcp", "rag")


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


# ---------------------------------------------------------------------------
# Migration -- ai_plan_log's phase constraint
# ---------------------------------------------------------------------------


def phase_is_allowed(conn: sqlite3.Connection, phase: str) -> bool:
    """Whether ai_plan_log's CHECK constraint currently accepts `phase`.

    Probed with a real insert that is then rolled back, rather than by
    pattern-matching the DDL in sqlite_master: the constraint is whatever
    SQLite actually enforces, not whatever the stored text looks like.
    """
    try:
        conn.execute(
            "INSERT INTO ai_plan_log (goal_id, phase, model_name, prompt, response, created_at) "
            "VALUES (NULL, ?, 'probe', 'constraint probe', NULL, '1970-01-01T00:00:00')",
            (phase,),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    conn.rollback()
    return True


def _ai_plan_log_ddl() -> tuple[str, list[str]]:
    """The ai_plan_log table and index statements, read out of schema.sql.

    Read rather than duplicated here on purpose. A migrated database and a
    freshly seeded one have to end up with the same table, and the surest way
    to guarantee that is for both to come from the same text.
    """
    text = SCHEMA_FILE.read_text(encoding="utf-8")

    table = re.search(r"^CREATE TABLE ai_plan_log\b.*?;", text, re.DOTALL | re.MULTILINE)
    if table is None:
        raise ValueError(f"could not find the ai_plan_log table definition in {SCHEMA_FILE}")

    indexes = re.findall(r"^CREATE INDEX\s+\w+\s+ON ai_plan_log\b[^;]*;", text, re.MULTILINE)
    return table.group(0), indexes


def migrate_ai_plan_log(conn: sqlite3.Connection) -> str | None:
    """Rebuild ai_plan_log with the current CHECK constraint, preserving rows.

    Returns a one-line description of what it did, or None if the table
    already accepts every phase in REQUIRED_PHASES.

    Why this exists: Release 1 logs MCP tool calls and RAG answers to this
    table, and `phase` is constrained by a CHECK. A database created before
    those phases existed -- which is every goals.db already sitting on the
    lehoalong-db-data volume -- rejects them with an IntegrityError at the
    moment of the first MCP call, i.e. live in front of a marker. The
    alternative was `INIT_DB_FORCE=1`, which fixes the constraint by throwing
    away every goal created since the volume was made.

    SQLite cannot ALTER a CHECK constraint, so this is the table-rebuild
    procedure from the SQLite documentation ("Making Other Kinds Of Table
    Schema Changes"): foreign keys off, copy into a new table, swap the names,
    recreate the indexes, foreign keys back on. log_id values are carried
    across unchanged, so ai-log entries keep the ids any report already cites.
    """
    missing = [phase for phase in REQUIRED_PHASES if not phase_is_allowed(conn, phase)]
    if not missing:
        return None

    table_sql, index_sql = _ai_plan_log_ddl()
    preserved = conn.execute("SELECT COUNT(*) FROM ai_plan_log").fetchone()[0]

    # Explicit transaction control: the pragma below only takes effect outside
    # a transaction, so the implicit one the driver would otherwise open has to
    # be out of the way.
    previous_isolation = conn.isolation_level
    conn.commit()
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        try:
            conn.execute(
                table_sql.replace("CREATE TABLE ai_plan_log", "CREATE TABLE ai_plan_log_migrated", 1)
            )
            conn.execute(
                "INSERT INTO ai_plan_log_migrated "
                "(log_id, goal_id, phase, model_name, prompt, response, created_at) "
                "SELECT log_id, goal_id, phase, model_name, prompt, response, created_at "
                "FROM ai_plan_log"
            )
            conn.execute("DROP TABLE ai_plan_log")
            conn.execute("ALTER TABLE ai_plan_log_migrated RENAME TO ai_plan_log")
            for statement in index_sql:
                conn.execute(statement)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = previous_isolation

    return (
        f"ai_plan_log migrated to accept the {', '.join(missing)} phase(s) "
        f"-- {preserved} existing row(s) preserved"
    )


def check(conn: sqlite3.Connection, *, fresh: bool) -> tuple[list[str], list[str]]:
    """Verify the database. Returns (fatal, advisory).

    Two different kinds of claim live here, and conflating them is what made
    this script able to brick the stack.

    **Fatal, always.** Structural corruption -- orphaned rows that no correct
    write could have produced. A database in this state is broken however it
    got there, so the container should refuse to come up around it.

    **Fatal only on a fresh build.** The invariants the *seed data* claims:
    at least MIN_ROWS_PER_TABLE rows per table, each goal's steps summing to
    its target, achieved goals actually funded. These hold by construction the
    moment seed.sql has run, and CI enforces them that way. They are NOT
    properties of a live database:

      * replan regenerates the pending steps from (target - contributions)
        while completed steps keep the amounts they were planned with, and
        contributions do not have to equal those amounts -- so the steps of a
        replanned goal legitimately stop summing to the target
      * a user may delete goals, taking a table back under ten rows
      * a user may mark a goal achieved before funding it

    None of that is corruption, and none of it should stop the database
    container from starting. On an existing database these are reported as
    advisories and the exit code stays 0.
    """
    fatal: list[str] = []
    seeded: list[str] = []

    # --- structural: always fatal ------------------------------------------
    # SQLite only enforces foreign keys on write, so a file built with the
    # pragma off could still hold orphans.
    for violation in conn.execute("PRAGMA foreign_key_check").fetchall():
        fatal.append(f"foreign key violation in {violation[0]}, rowid {violation[1]}")

    # --- seed-time invariants ----------------------------------------------
    for table in TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count < MIN_ROWS_PER_TABLE:
            seeded.append(f"{table} has {count} rows, fewer than the required {MIN_ROWS_PER_TABLE}")

    # Each goal's steps should sum to its target amount. Goals with no steps
    # yet are excluded -- no plan is not a broken plan.
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
        seeded.append(
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
            seeded.append(
                f"goal {row['goal_id']} ({row['name']}) is marked achieved but only "
                f"{row['saved']:.2f} of {row['target_amount']:.2f} has been contributed"
            )

    if fresh:
        # seed.sql just ran: these are guarantees, not observations.
        return fatal + seeded, []
    return fatal, seeded


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

    fresh = False
    try:
        if args.summary_only:
            if not db_path.exists():
                print(f"[init_db] no database at {db_path}", file=sys.stderr)
                return 1
        else:
            # True only when schema.sql and seed.sql actually just ran. That is
            # what decides whether the seed-time invariants are guarantees to
            # enforce or observations about live data to report.
            fresh = build(db_path, force=args.force)
    except (OSError, sqlite3.Error) as exc:
        print(f"[init_db] failed: {exc}", file=sys.stderr)
        return 1

    conn = connect(db_path)
    try:
        if not (fresh or args.summary_only):
            # A database built before Release 1 still has the three-phase CHECK
            # constraint on ai_plan_log and would reject every MCP and RAG log
            # row. Migrate it in place rather than demanding a destructive
            # re-seed. A freshly built file already has the current schema, and
            # --summary-only promises to touch nothing.
            try:
                migration = migrate_ai_plan_log(conn)
            except (sqlite3.Error, ValueError) as exc:
                print(f"[init_db] failed to migrate ai_plan_log: {exc}", file=sys.stderr)
                return 1
            if migration:
                print(f"[init_db] {migration}")

        fatal, advisory = check(conn, fresh=fresh)
        if not args.quiet:
            summarise(conn)
    finally:
        conn.close()

    if advisory:
        # Not a failure. An existing database drifts from what the seed
        # claimed as soon as anyone replans a goal or deletes one, and the
        # container has to keep starting through that.
        print("[init_db] NOTE -- this database no longer matches the seed's claims:", file=sys.stderr)
        for item in advisory:
            print(f"  - {item}", file=sys.stderr)
        print(
            "[init_db] expected on a database with live activity; "
            "run with --force to rebuild from seed.sql.",
            file=sys.stderr,
        )

    if fatal:
        print("[init_db] CONSISTENCY PROBLEMS:", file=sys.stderr)
        for problem in fatal:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"[init_db] ready: {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
