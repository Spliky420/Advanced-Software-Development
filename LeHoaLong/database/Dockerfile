# Le Hoa Long's database microservice.
#
# Owns the named volume holding goals.db: it creates the schema, loads the
# seed data, verifies both, and hands the file to the backend. No port is
# published -- SQLite is a file, not a server, and the only thing that talks
# to it is lehoalong-backend over the shared volume. (8062 is reserved in the
# port table for a future release that fronts it with a service.)
#
#   docker build -t lehoalong-db LeHoaLong/database
#
# python:3.11-slim rather than alpine+sqlite3 because the initialiser is
# init_db.py: it does the consistency checking the raw sqlite3 CLI cannot,
# and it is the same script a developer runs locally. The image needs no pip
# install -- init_db.py is standard library only.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY schema.sql seed.sql init_db.py ./
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Strip CRLF in case the file was checked out on Windows -- a stray \r makes
# the shebang unusable and the container fails with "no such file or
# directory" on a script that is plainly there.
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

ENV DB_DIR=/data \
    DB_FILE=/data/goals.db \
    APP_UID=10001 \
    APP_GID=10001

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
