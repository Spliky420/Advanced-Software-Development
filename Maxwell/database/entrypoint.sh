#!/bin/sh
# Initialise (or re-seed) the SQLite database on every start.
set -eu

DB_DIR="${DB_DIR:-/data}"
DB_FILE="${DB_FILE:-/data/glossary.sqlite}"
SQL_DIR="${SQL_DIR:-/sql}"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

# Ensure database directory exists
mkdir -p "$DB_DIR"

# Seed (or re-seed) the glossary database
# The seed script will remove any existing file, create schema, and load seed data.
"$SQL_DIR/seed_glossary.sh"

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