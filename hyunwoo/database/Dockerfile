# Small base image.
FROM alpine:3.20

# Install SQLite.
RUN apk add --no-cache sqlite

WORKDIR /database

# Copy the table and sample data files.
COPY init.sql seed.sql ./

# Copy the startup script.
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

# Save the database in the shared data folder.
ENV DB_FILE=/data/bills.db

VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
