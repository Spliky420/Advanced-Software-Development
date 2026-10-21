#!/bin/bash
# Runs the shared Multi-Agent Server on the host -- it is deliberately not a
# compose service (Release 2 brief). Backends reach it at
# http://host.docker.internal:5004.
#
#   ./run.sh                     real agents, needs Ollama on the host
#   STUB_AGENTS=true ./run.sh    canned agents, no Ollama needed
#
# gunicorn settings, each one load-bearing:
#   --timeout 180  one POST /workflow runs three Ollama calls in sequence
#                  (15-40s warm on CPU, far more cold). gunicorn's default
#                  30s kills the worker silently, usually as the Reviewer
#                  starts, and the caller just sees a dropped connection.
#   --workers 1    runs are held in this process's memory, so every request
#                  for a run must reach the same process.
#   --threads 8    lets GET /workflow/<id> poll progress while a POST is
#                  still blocked running the agents.
#
# gunicorn does not install on Windows; there this falls back to Flask's
# threaded server, which has no worker timeout at all.
set -e
cd "$(dirname "$0")"

PORT="${MULTI_AGENT_PORT:-5004}"

if command -v gunicorn >/dev/null 2>&1; then
    exec gunicorn server:app \
        --bind "0.0.0.0:${PORT}" \
        --workers 1 \
        --threads 8 \
        --timeout 180
else
    echo "gunicorn not found -- falling back to Flask's threaded server"
    exec python3 server.py
fi
