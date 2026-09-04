#!/bin/sh
# Seed the glossary database with initial terms.
# Called by entrypoint.sh on container start.

set -eu

# Defaults (can be overridden by environment)
DB_DIR="${DB_DIR:-/data}"
DB_FILE="${DB_FILE:-/data/glossary.sqlite}"
SQL_DIR="${SQL_DIR:-/sql}"

mkdir -p "$DB_DIR"

echo "[database] (re)seeding glossary at $DB_FILE"

# Remove any existing database to start clean
rm -f "$DB_FILE"

# Initialize schema
sqlite3 "$DB_FILE" < "$SQL_DIR/init.sql"
echo "[database] schema created from init.sql"

# Load seed data
sqlite3 "$DB_FILE" < "$SQL_DIR/seed.sql"
echo "[database] seed data loaded from seed.sql"

# Ensure proper permissions
chmod 664 "$DB_FILE"

echo "[database] seeding complete: $(sqlite3 "$DB_FILE" 'SELECT COUNT(*) FROM terms;') terms"