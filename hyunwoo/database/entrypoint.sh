#!/bin/sh

# Stop if a command fails.
set -eu

# Database file location.
DB_FILE="${DB_FILE:-/data/bills.db}"
TEMP_FILE="${DB_FILE}.initialising"

# Create the data folder if needed.
mkdir -p "$(dirname "$DB_FILE")"

# Only create and seed the database the first time.
if [ ! -f "$DB_FILE" ]; then
    # Clear an unfinished setup from an earlier attempt.
    rm -f "$TEMP_FILE"

    # Create the table and add the sample records.
    sqlite3 "$TEMP_FILE" < /database/init.sql
    sqlite3 "$TEMP_FILE" < /database/seed.sql

    mv "$TEMP_FILE" "$DB_FILE"
    echo "Bills database created with seeded records."
else
    echo "Existing bills database found."
fi

# Add Release 0 user scoping to older databases.
if ! sqlite3 "$DB_FILE" "PRAGMA table_info(bills);" | grep -q '|user_id|'; then
    sqlite3 "$DB_FILE" \
        "ALTER TABLE bills ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1;"
    echo "Existing bills assigned to the default user."
fi

# Keep the main bill list fast.
sqlite3 "$DB_FILE" \
    "CREATE INDEX IF NOT EXISTS idx_bills_user_due ON bills (user_id, next_due_date, name); PRAGMA optimize;"

# Keep the database container running.
exec tail -f /dev/null
