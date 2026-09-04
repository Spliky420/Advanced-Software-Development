#!/bin/sh
# Initialise the SQLite database on first start only.
set -eu

DB_DIR="${DB_DIR:-/data}"
DB_FILE="${DB_FILE:-/data/library.db}"
SQL_DIR="${SQL_DIR:-/sql}"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

mkdir -p "$DB_DIR"

if [ -f "$DB_FILE" ]; then
    echo "[database] $DB_FILE already exists -- skipping init.sql and seed.sql."
else
    echo "[database] no database found at $DB_FILE -- initialising."

    # Build at a temporary path and move into place only once both scripts have
    # succeeded. A crash part-way leaves no library.db, so the next start
    # retries cleanly instead of inheriting a half-seeded database.
    TMP_FILE="$DB_DIR/.library.db.building"
    rm -f "$TMP_FILE"

    sqlite3 "$TMP_FILE" < "$SQL_DIR/init.sql"
    echo "[database] schema created from init.sql"

    sqlite3 "$TMP_FILE" < "$SQL_DIR/seed.sql"
    echo "[database] seed data loaded from seed.sql"

    mv "$TMP_FILE" "$DB_FILE"
    echo "[database] initialised $DB_FILE"
fi

# The backend container runs unprivileged as APP_UID. SQLite writes -journal
# and -wal siblings next to the database, so the directory needs to be group
# writable too, not just the file.
chown -R "$APP_UID:$APP_GID" "$DB_DIR"
chmod 775 "$DB_DIR"
chmod 664 "$DB_FILE"

echo "[database] ready: $(sqlite3 "$DB_FILE" 'SELECT COUNT(*) FROM documents;') documents, $(sqlite3 "$DB_FILE" 'SELECT COUNT(*) FROM document_embeddings;') embedded chunks, $(sqlite3 "$DB_FILE" 'SELECT COUNT(*) FROM document_ai_log;') AI log rows"

# Stay alive so compose reports this as a running, healthchecked service
# rather than an exited container.
exec tail -f /dev/null
