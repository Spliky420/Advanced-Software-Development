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

# Keep the database container running.
exec tail -f /dev/null
