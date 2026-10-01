#!/bin/bash
# Runs both processes this image serves: app.py (the Flask test harness /
# htmx UI backend, port 5001) and server.py (the real MCP-protocol server,
# streamable-http, port 5002). If either exits, the container exits so
# Docker's restart policy/healthcheck can react instead of silently running
# on one leg.
set -e

python server.py &
MCP_PID=$!

python app.py &
APP_PID=$!

wait -n "$MCP_PID" "$APP_PID"
exit $?
