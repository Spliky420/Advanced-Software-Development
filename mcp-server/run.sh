#!/bin/bash
# Runs the shared MCP server on the host -- it is deliberately not a compose
# service. Starts both processes: server.py (the real MCP protocol,
# streamable-http, port 5002) and app.py (the Flask test harness behind
# shared/mcp.html, port 5001). Ctrl-C stops both.
set -e
cd "$(dirname "$0")"

python3 server.py &
MCP_PID=$!
python3 app.py &
APP_PID=$!

trap 'kill "$MCP_PID" "$APP_PID" 2>/dev/null' INT TERM EXIT
wait
