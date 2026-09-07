# docker-compose.yml — Le Hoa Long's service blocks

`docker-compose.yml` is a shared file: this snippet exists so the three blocks
can go in via pull request rather than a direct commit (CLAUDE.md). Nothing
above the block needs to change; the two edits are the `services:` block below
and one line in `volumes:`.

## 1. Port table (header comment, near the top of the file)

The header lists the claimed ranges. Add the one line:

```
#   LeHoaLong  8060-8069   CLAIMED
```

## 2. Service blocks

Paste immediately before the `# TEMPLATE` block at the end of `services:`.

```yaml
  # =========================================================================
  # LE HOA LONG -- ports 8060-8069 -- Goals and Budgeting
  # =========================================================================
  lehoalong-database:
    build: ./LeHoaLong/database
    container_name: lehoalong-database
    restart: unless-stopped
    volumes:
      - lehoalong-db-data:/data
    environment:
      DB_FILE: /data/goals.db
      # Set to 1 for one run to drop and re-seed the database -- a clean slate
      # before a demo. Destructive: it discards every goal created live.
      INIT_DB_FORCE: ${LEHOALONG_INIT_DB_FORCE:-0}
    healthcheck:
      # Queries a real table, so a present-but-unseeded file reads as
      # unhealthy rather than passing. python:3.11-slim has no sqlite3 CLI,
      # so this goes through the stdlib module instead.
      test: ["CMD", "python", "-c",
             "import sqlite3; sqlite3.connect('/data/goals.db').execute('SELECT COUNT(*) FROM goals')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s

  lehoalong-backend:
    build: ./LeHoaLong/backend
    container_name: lehoalong-backend
    restart: unless-stopped
    ports:
      - "8061:5000"
    environment:
      DB_PATH: /data/goals.db
      OLLAMA_BASE_URL: http://ollama:11434
      OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:0.5b}
      # Only used by `npm run dev`; in the container nginx makes /api
      # same-origin and this layer never fires.
      CORS_ORIGINS: http://localhost:8060,http://127.0.0.1:8060
    volumes:
      # Same volume as lehoalong-database: that service creates and seeds
      # goals.db, this one reads and writes it.
      - lehoalong-db-data:/data
    depends_on:
      lehoalong-database:
        condition: service_healthy
      ollama:
        # service_started, not service_healthy: goals CRUD, progress and the
        # budget summary are all useful before a model has been pulled, and
        # /plan and /replan return a clean 503 until one is.
        condition: service_started
    healthcheck:
      # /health returns 503 when the database is unreachable; urlopen raises
      # on a non-2xx status, so this fails exactly when it should.
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=5)"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 15s

  lehoalong-frontend:
    # Context is the repo root, not ./LeHoaLong/frontend: the app imports the
    # team's shared stylesheet from shared/styles.css, which is outside the
    # frontend directory. Same arrangement as maxwell-frontend.
    build:
      context: .
      dockerfile: LeHoaLong/frontend/Dockerfile
    container_name: lehoalong-frontend
    restart: unless-stopped
    ports:
      - "8060:80"
    depends_on:
      lehoalong-backend:
        condition: service_started
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--spider", "http://127.0.0.1/"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
```

## 3. Volume

In the `volumes:` block at the bottom of the file:

```yaml
  # Le Hoa Long
  lehoalong-db-data:
```

## 4. Shared home page (separate, optional PR)

`shared/index.html` links each feature by host port. Goals and Budgeting is
reachable from it only once a card pointing at `http://localhost:8060` is
added alongside the existing 8010/8020/8040/8050 cards. That is a second
shared file, so it belongs in its own pull request.

## Notes

- **No published port for the database.** SQLite is a file, not a server; the
  backend reaches it over the `lehoalong-db-data` volume, so there is nothing
  to map. 8062 stays reserved in the port table for a later release that
  fronts it with a service.
- **Model tag.** `${OLLAMA_MODEL:-qwen2.5:0.5b}` follows the team convention:
  one `.env` switches every backend at once, and the default matches the rest
  of the compose file. The original feature brief named `qwen2.5:7b`; setting
  `OLLAMA_MODEL` in `.env` selects it without a code change, and the model is
  never hardcoded anywhere.
- **Pull the model into the container**, not onto the host — a host pull is
  invisible to the `ollama` service:

  ```
  docker compose exec ollama ollama pull qwen2.5:0.5b
  ```
