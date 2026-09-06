#!/bin/sh


set -e

DB_FILE="${DB_FILE:-/data/transactions.db}"

echo "Using database: $DB_FILE"

mkdir -p "$(dirname "$DB_FILE")"

if [ ! -f "$DB_FILE" ]; then
    echo "Creating Transactions database..."

    sqlite3 "$DB_FILE" < /app/init.sql
    sqlite3 "$DB_FILE" < /app/seed.sql

    echo "Database created and seeded."
else
    echo "Database already exists."

    # Ensure any newer schema changes that use
    # CREATE TABLE IF NOT EXISTS are applied.
    sqlite3 "$DB_FILE" < /app/init.sql
fi

echo "Checking database..."

sqlite3 "$DB_FILE" "SELECT COUNT(*) AS transaction_count FROM transactions;"

echo "Database is ready."


tail -f /dev/null