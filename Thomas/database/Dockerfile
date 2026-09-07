# Thomas/database/Dockerfile

FROM alpine:3.20

RUN apk add --no-cache sqlite

WORKDIR /app

COPY init.sql /app/init.sql
COPY seed.sql /app/seed.sql
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]