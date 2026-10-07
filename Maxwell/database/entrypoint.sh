#!/bin/sh
# Initialise the SQLite database on first start only (or always in CI).
set -eu

DB_DIR="${DB_DIR:-/data}"
DB_FILE="${DB_FILE:-/data/glossary.sqlite}"
SQL_DIR="${SQL_DIR:-/sql}"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

# Check if we're in a CI environment
is_ci=false
if [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ] || [ "${GITLAB_CI:-false}" = "true" ] || [ "${TRAVIS:-false}" = "true" ] || [ "${CIRCLECI:-false}" = "true" ]; then
    is_ci=true
fi

# Ensure database directory exists
mkdir -p "$DB_DIR"

if [ "$is_ci" = "true" ]; then
    echo "[database] CI environment detected -- (re)seeding glossary at $DB_FILE"
    # In CI: always re-seed (wipe existing database)
    rm -f "$DB_FILE"
    "$SQL_DIR/seed_glossary.sh"
elif [ -f "$DB_FILE" ]; then
    echo "[database] $DB_FILE already exists -- skipping seeding."
else
    echo "[database] no database found at $DB_FILE -- waiting for backend..."
    # Wait for the Maxwell backend to be ready (max 30 seconds)
    timeout=30
    while [ $timeout -gt 0 ]; do
        if curl -s -f "http://maxwell-backend:5000/health" >/dev/null 2>&1; then
            break
        fi
        sleep 1
        timeout=$((timeout - 1))
    done
    if [ $timeout -le 0 ]; then
        echo "[database] WARNING: backend did not become ready in time; proceeding anyway."
    fi
    echo "[database] seeding glossary..."
    "$SQL_DIR/seed_glossary.sh"
fi

# The backend container runs unprivileged as APP_UID. SQLite writes -journal
# and -wal siblings next to the database, so the directory needs to be group
# writable too, not just the file.
chown -R "$APP_UID:$APP_GID" "$DB_DIR"
chmod 775 "$DB_DIR"
chmod 664 "$DB_FILE"

echo "[database] ready: $(sqlite3 "$DB_FILE" 'SELECT COUNT(*) FROM terms;') glossary terms"

# Stay alive so compose reports this as a running, healthchecked service
# rather than an exited container.
exec tail -f /dev/null