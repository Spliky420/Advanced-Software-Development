# Shared MCP server

One MCP server serves every student's feature. It is **not containerised**:
it runs as a local process pair on the host, and the backends in
`docker-compose.yml` reach it through `host.docker.internal`.

| Port | Process     | Used by                                                    |
| ---- | ----------- | ---------------------------------------------------------- |
| 5002 | `server.py` | Real MCP protocol (streamable-http) at `/mcp` — Joshua, Enerel, HyunWoo, Thomas, LeHoaLong |
| 5001 | `app.py`    | Flask test harness (`/mcp/<tool>`) — `shared/mcp.html`, Maxwell |

## Run

```
cd mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Start it after `docker compose up`: its tools call each backend on its
published host port (`localhost:8011`, `8021`, `8031`, `8041`, `8051`,
`8061`) and AI mode calls Ollama on `localhost:11434`. Override any of these
with the `*_BACKEND_URL` / `OLLAMA_BASE_URL` env vars in `tools.py` and
`routes/ai_mode.py`.

To point every backend at a different MCP server, set `MCP_SERVER_URL`
(protocol endpoint) and `MCP_HARNESS_URL` (harness root) in `.env`.
