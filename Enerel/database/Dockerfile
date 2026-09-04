# Enerel's database microservice.
# Owns the named volume holding library.db and initialises it once.
FROM alpine:3.20

RUN apk add --no-cache sqlite

COPY init.sql seed.sql /sql/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Strip CRLF in case the file was checked out on Windows -- a stray \r makes
# the shebang unusable and the container fails with "no such file".
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

ENV DB_DIR=/data \
    DB_FILE=/data/library.db \
    APP_UID=10001 \
    APP_GID=10001

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
