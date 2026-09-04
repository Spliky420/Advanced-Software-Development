# Goals and Budgeting — Le Hoa Long

My three microservices for the group Personal Finance Assistant (ASD 2026,
Release 0). A user sets a savings goal, an agentic loop turns it into a dated
plan, contributions are logged against it, and the service observes whether the
goal is on track and re-plans the remaining steps when it drifts.

Ports **8060–8069** are mine. 8063–8069 are held for later releases.

| Service              | Directory   | Host port | Container port  |
| -------------------- | ----------- | --------- | --------------- |
| `lehoalong-frontend` | `frontend/` | 8060      | 80 (nginx)      |
| `lehoalong-backend`  | `backend/`  | 8061      | 5000 (gunicorn) |
| `lehoalong-database` | `database/` | *(none)*  | —               |

The database publishes no port. SQLite is a file, not a server: the database
container creates, seeds and verifies `goals.db` on the `lehoalong-db-data`
volume, and the backend opens that same file over the volume. **8062 is
reserved** in the team port table for a later release that fronts it with a
service.

---

## Running it

### With the team stack (the normal way)

The three service blocks are not yet in the root `docker-compose.yml` — that is
a shared file, so they go in by pull request. The blocks to paste, plus the
one-line volume entry, are in [`docs/compose-snippet.md`](docs/compose-snippet.md).

Once they are in:

```bash
docker compose up -d lehoalong-database lehoalong-backend lehoalong-frontend
docker compose exec ollama ollama pull qwen2.5:0.5b   # models live in the container
```

Then open <http://localhost:8060>, or reach it from the team home page at
<http://localhost:8000>.

`GET http://localhost:8061/health` reports the database and whether Ollama is
reachable with the configured model pulled.

### On a laptop, without Docker

Two terminals. The backend first:

```bash
python LeHoaLong/database/init_db.py --db LeHoaLong/database/goals.db
pip install -r LeHoaLong/tests/requirements.txt      # Flask + requests + pytest
cd LeHoaLong/backend
DB_PATH=../database/goals.db OLLAMA_BASE_URL=http://localhost:11434 python wsgi.py
```

`wsgi.py` listens on **8061** so it matches what the Vite dev server proxies to.
Use `backend/requirements.txt` instead if you are on Linux or macOS — it also
pins gunicorn, which does not install on Windows and which only the container
needs.

Then the frontend:

```bash
cd LeHoaLong/frontend
npm install
npm run dev        # http://localhost:8060, proxies /api and /health to 8061
```

---

## API

Base path `/api`, all lowercase. JSON in, JSON out. `201` on create, `204` on
delete, `400` on validation failure, `404` on a missing resource, `503` when
Ollama is unreachable or the configured model has not been pulled.

### Goals

| Method   | Path              | Notes                                          |
| -------- | ----------------- | ---------------------------------------------- |
| `GET`    | `/api/goals`      | Optional `?status=`, `?priority=`, `?user_id=` |
| `GET`    | `/api/goals/<id>` | Includes its steps and contribution total      |
| `POST`   | `/api/goals`      | 201                                            |
| `PUT`    | `/api/goals/<id>` |                                                |
| `DELETE` | `/api/goals/<id>` | 204; cascades to steps and contributions       |

### Steps and contributions

| Method   | Path                              |
| -------- | --------------------------------- |
| `GET`    | `/api/goals/<id>/steps`           |
| `PUT`    | `/api/goals/<id>/steps/<step_id>` |
| `DELETE` | `/api/goals/<id>/steps/<step_id>` |
| `GET`    | `/api/goals/<id>/contributions`   |
| `POST`   | `/api/goals/<id>/contributions`   |

### Budget

| Method | Path                           | Notes                                    |
| ------ | ------------------------------ | ---------------------------------------- |
| `GET`  | `/api/budget/summary?user_id=` | Monthly commitment vs budget, over/under |
| `GET`  | `/api/budget/settings`         |                                          |
| `PUT`  | `/api/budget/settings`         |                                          |

### The agentic loop

The four assessed endpoints, one per phase:

| Phase       | Endpoint                             | What it does                                                                                                                      |
| ----------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| **Plan**    | `POST /api/goals/<id>/plan`          | Python builds the dated instalment schedule; the model writes a description for each. Persisted to `goal_steps` with `source='ai'`. |
| **Act**     | `POST /api/goals/<id>/contributions` | Recording money against the goal is the act.                                                                                      |
| **Observe** | `GET /api/goals/<id>/progress`       | Saved-to-date vs required-to-date → `on_track` / `behind` / `ahead`, the variance, and a projected completion date.                |
| **Adapt**   | `POST /api/goals/<id>/replan`        | Re-prompts with the observed variance and regenerates **only the pending steps**; completed ones are preserved.                    |

Every one of them writes to `ai_plan_log` — full prompt, raw response, model
name, phase. `GET /api/goals/<id>/ai-log` reads that trail back out, which is
the evidence for the report.

`GET /health` reports service status and Ollama reachability.

---

## How the AI is wired

- **All arithmetic is Python.** Totals, variances, required-per-month figures,
  instalment amounts and projected dates are computed in `app/services/`; the
  model is handed finished numbers and writes prose around them. It is never
  asked to add anything up.
- **Ollama only**, at `OLLAMA_BASE_URL` (default `http://ollama:11434`), with
  the tag read from `OLLAMA_MODEL`. No model name is hardcoded anywhere in the
  code, and no commercial API is called at runtime.
- Calls go to `/api/generate` with `format: "json"` and a schema stated in the
  prompt. The response is parsed and validated before anything is persisted.
- **Malformed JSON never breaks the feature.** One retry, then a deterministic
  even-split plan (target ÷ months remaining) stands in, flagged
  `fallback: true` with the reason in the response and a `note: "fallback"` row
  in `ai_plan_log`. Ollama being *unreachable* is a different case and returns a
  clean 503 rather than a silent fallback.

### Model choice

The feature brief named `qwen2.5:7b`. The team default is `qwen2.5:0.5b` (fast)
with `llama3.1:8b` for the demo. Because the tag is an environment variable, any
of the three is a `.env` change and not a code change:

```bash
docker compose exec ollama ollama pull llama3.1:8b
# then set OLLAMA_MODEL=llama3.1:8b in .env
```

---

## Database

`database/schema.sql` defines five tables, foreign keys enforced
(`PRAGMA foreign_keys = ON` on every connection — it is per-connection, so
setting it in the schema alone would not stick):

| Table             | Purpose                                                    |
| ----------------- | ---------------------------------------------------------- |
| `goals`           | Name, target amount, target date, priority, status         |
| `goal_steps`      | Ordered dated instalments; `ON DELETE CASCADE` from goals  |
| `contributions`   | Money recorded against a goal; also cascades               |
| `ai_plan_log`     | One row per model exchange: phase, model, prompt, response |
| `budget_settings` | Monthly budget and currency, per user                      |

`init_db.py` creates, seeds and then **verifies** the result — at least 10 rows
in every table, no foreign key violations, step amounts summing to their goal's
target. It exits non-zero if any check fails, so neither the container nor CI
can come up around a database the checks would have rejected.

```bash
python LeHoaLong/database/init_db.py --summary-only    # what is in there now
python LeHoaLong/database/init_db.py --force           # drop and rebuild
```

Seed data spans several `user_id` values so the filters are demonstrable, and
covers the states the UI has to render: a goal on track, one behind, one with no
plan at all, and one already achieved.

### Documented addition — `budget_settings`

**This table is not on my registration form.** The feature spec requires a
budget summary panel (monthly commitment vs monthly budget, with a warning when
goals exceed it) and the original four-table design has nowhere to store the
budget. `budget_settings` is that missing table. Flagging it here as a
deliberate, documented addition rather than scope creep.

The same applies to two smaller corrections: the registration form's
`/API/Goals` casing is standardised to `/api/goals` throughout, and
`GET /api/goals/<id>/ai-log` was added so the `ai_plan_log` trail is readable
without opening the database by hand.

---

## Configuration

Every setting is an environment variable with a working default, so a fresh
clone runs with no `.env`. Defined in `backend/config.py`.

| Variable                     | Default                   | Meaning                                       |
| ---------------------------- | ------------------------- | --------------------------------------------- |
| `DB_PATH` / `DB_FILE`        | `/data/goals.db`          | SQLite file (either name is accepted)         |
| `DB_BUSY_TIMEOUT_MS`         | `5000`                    | How long to wait for a write lock             |
| `OLLAMA_BASE_URL`            | `http://ollama:11434`     | The only approved LLM path                    |
| `OLLAMA_MODEL`               | `qwen2.5:0.5b`            | Model tag — never hardcoded                   |
| `OLLAMA_TIMEOUT_SECONDS`     | `120`                     | Below gunicorn's 180s and nginx's 180s        |
| `OLLAMA_TEMPERATURE`         | `0.2`                     | Low, so descriptions stay on instruction      |
| `PROGRESS_TOLERANCE_PERCENT` | `1.0`                     | Dead band before observe says behind/ahead    |
| `PROGRESS_TOLERANCE_FLOOR`   | `1.0`                     | Minimum dead band, in dollars                 |
| `CORS_ORIGINS`               | `http://localhost:8060,…` | Only fires under `npm run dev`                |
| `INIT_DB_FORCE`              | `0`                       | Database container: `1` re-seeds from scratch |

---

## Frontend

React 19 + Vite, React Router, no component library. Every network call goes
through the single module `src/api/client.js` — no `fetch` is scattered through
components.

Styling imports the team's shared theme from `shared/styles.css` at the
repository root, so this feature matches the other five. That is also why the
frontend image builds from the **repository root** context rather than from
`frontend/`: the stylesheet sits outside the frontend directory and cannot be
reached from a narrower context.

Screens: goal dashboard (cards with progress bar, priority badge, live on-track
status), create/edit form with client-side validation, delete with confirmation,
goal detail with individually editable steps, generate/regenerate plan with a
loading state and a clear error state when the AI service is down, a
contribution form, and the budget summary panel with its over-budget warning.

---

## Tests

```bash
pip install -r LeHoaLong/tests/requirements.txt
pytest LeHoaLong/tests -v
```

238 tests, and **none of them touches the network**. Every test gets its own
copy of a database built from the real `schema.sql` and `seed.sql`, so the suite
exercises the same constraints the container enforces. An autouse `no_network`
fixture monkeypatches `socket.connect`, so a test that tries to open a socket
fails loudly naming itself rather than hanging; Ollama is replaced by the
`fake_model` and `stub_ollama` fixtures in `conftest.py`.

Coverage: goals CRUD happy paths and validation failures, cascade deletion, the
progress calculation including zero contributions / overdue / already achieved,
the budget summary maths, and the AI response parser against both valid and
malformed JSON.

---

## CI

[`.github/workflows/LeHoaLong.yml`](../.github/workflows/LeHoaLong.yml) runs on
pushes to `main` and any `LeHoaLong-**` branch, and on pull requests to `main`,
filtered to `LeHoaLong/**` and the workflow file itself — so it never runs on
another student's work and never reports on it. Three parallel jobs:

| Job        | Steps                                                                           |
| ---------- | ------------------------------------------------------------------------------- |
| `backend`  | `ruff check LeHoaLong` → seed and verify the database → `pytest LeHoaLong/tests` |
| `frontend` | `npm ci` → `npm run lint` (eslint) → `npm run build` (vite)                      |
| `images`   | Build all three Dockerfiles, then run the database initialiser in its image      |

**No Ollama runs in CI and none is needed** — the suite is fully mocked, and
`OLLAMA_BASE_URL` is pointed at a dead port as a second line of defence.

Two of the gates are doing more than they look:

- The **seed step is the marking requirement in executable form**. `init_db.py`
  exits non-zero unless every table carries at least 10 rows, so a seed file
  that regresses fails the build rather than being noticed at demo time.
- The **frontend build catches integration drift**. `src/styles/app.css` imports
  the shared theme by a path relative to the repository root, so if that
  stylesheet is moved or renamed, this job goes red instead of the feature
  quietly losing its styling.

Lint configuration is `LeHoaLong/ruff.toml` (deliberately scoped to this
directory, so it imposes no style on anyone else's Python) and
`frontend/eslint.config.js`.

To reproduce a CI run locally:

```bash
pip install ruff==0.16.6 && ruff check LeHoaLong
pytest LeHoaLong/tests -v
cd LeHoaLong/frontend && npm ci && npm run lint && npm run build && cd ../..
docker build -t lehoalong-db:ci LeHoaLong/database
docker build -t lehoalong-backend:ci LeHoaLong/backend
docker build -f LeHoaLong/frontend/Dockerfile -t lehoalong-frontend:ci .
```

---

## Scope

Release 0. **No MCP, no RAG, no multi-agent** — those are Releases 1 and 2. The
code is arranged so they can be added without a rewrite: routes are thin, all
business logic and arithmetic sits in `app/services/`, and the Ollama client is
one module behind a small interface.

Release 0 is also single-user in the same sense as the rest of the team's
backends: a `DEFAULT_USER_ID` constant supplies the user when the client does
not name one, but `user_id` is in the schema and is an explicit parameter on
every query-layer function, so multi-user support later means passing a real
value through rather than restructuring.
