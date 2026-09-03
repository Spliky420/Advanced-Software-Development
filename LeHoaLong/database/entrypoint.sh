#!/bin/sh
# Initialise the Goals and Budgeting database on first start only, then stay
# alive so compose reports a running, healthchecked service.
#
# The real work is init_db.py, which is the same script a developer runs on a
# laptop -- schema, seed, and the consistency checks (>=10 rows per table, no
# foreign key violations, steps summing to their goal's target). Running it
# here means the container cannot come up healthy around a database the
# checks would have rejected.
set -eu

DB_DIR="${DB_DIR:-/data}"
DB_FILE="${DB_FILE:-/data/goals.db}"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

mkdir -p "$DB_DIR"

# init_db.py is a no-op when the file already exists (it prints and skips), so
# a restart re-verifies rather than re-seeding. INIT_DB_FORCE=1 rebuilds from
# scratch -- useful for a demo reset, destructive otherwise.
if [ "${INIT_DB_FORCE:-0}" = "1" ]; then
    echo "[database] INIT_DB_FORCE=1 -- rebuilding $DB_FILE from scratch."
    python /app/init_db.py --db "$DB_FILE" --force
else
    python /app/init_db.py --db "$DB_FILE"
fi

# The backend container runs unprivileged as APP_UID. SQLite writes -journal
# and -wal siblings next to the database, so the directory has to be writable
# too, not just the file itself.
chown -R "$APP_UID:$APP_GID" "$DB_DIR"
chmod 775 "$DB_DIR"
chmod 664 "$DB_FILE"

echo "[database] ready: $DB_FILE"

# Stay alive so compose sees a running service rather than an exited
# container, and so the healthcheck has something to run against.
exec tail -f /dev/null
