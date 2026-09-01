# CLAUDE.md

Guidance for Claude Code (and any contributor) working in this repository.

## Project

University team project (ASD 2026). Five students, each building a **frontend**,
a **backend/API**, and a **database** microservice, all integrated into a single
Agentic AI application.

## Stack

- **Backend**: Python 3 + Flask, serving JSON over REST. The backend is
  frontend-agnostic — do not assume or couple to any specific frontend framework.
- **Frontend**: framework not yet finalised (being confirmed with the tutor).
  Build backends so they don't care what consumes them.
- **Database**: SQLite, one per microservice.
- **Containerisation**: Docker. All services are orchestrated together through a
  single shared `docker-compose.yml` at the repo root.

## Repository layout

- Each team member works **only** inside their own top-level directory, named
  after them. Do not edit another member's directory.
- Shared files — touched by everyone, so treat them as high-coordination-cost:
  - `index.html`
  - the shared CSS
  - `docker-compose.yml`
  - Changes to shared files must go through a **pull request**, never a direct
    commit to the shared file. Never edit `docker-compose.yml` and other shared
    files directly on main.

## LLM access — hard rules

- The **only** way to reach an LLM is via **Ollama**, reachable on the Docker
  Compose network at `http://ollama:11434`. There is no other approved path.
- **Never call a commercial/external AI API at runtime** (OpenAI, Anthropic,
  Google, etc.). This is a hard constraint, not a style preference.
- The model tag must always be read from the `OLLAMA_MODEL` environment
  variable — never hardcode a model name.
  - Default: `qwen2.5:0.5b` (~400MB) — fast local development, and the
    fallback baked into `docker-compose.yml`, `llm.py` and the backend
    Dockerfile so a fresh clone with no `.env` still comes up working.
  - Demo model: `llama3.1:8b` (~4.9GB) — higher quality, and the model to run
    the demo on. Pull it into the container before switching to it.

## Arithmetic — hard architectural rule

- **All numeric calculation happens in Python**, not in the LLM.
- The LLM only ever receives already-computed, finished figures and produces
  text/explanation around them — it must never be asked to perform arithmetic
  itself. When implementing any "agentic" feature, compute the numbers in
  Python first, then hand the results to the LLM as input.

### Known limitation — small models misread correctly-supplied figures

A small model can get the *interpretation* of a correct figure wrong even
though every number it was handed is right. Observed with `qwen2.5:0.5b` on
`/api/insights`: asked to name the largest asset class, it named Australian
equities at 11.66% when ETFs at 24.30% was plainly larger. Both figures were
supplied correctly; the model simply compared them badly.

This is precisely why all arithmetic happens in Python and the LLM is given
finished values. The guarantee the architecture provides is that **the model
cannot introduce a figure of its own** — every number in a response traces back
to `allocation.build_portfolio_report` or to the drift pipeline built on it.
It does not, and cannot, guarantee the model reasons about those numbers well.
`joshua/tests/test_no_invented_figures.py` locks in the guarantee that holds;
interpretation quality is a model-choice question, not a code one.

`llama3.1:8b` is the demo model for this reason — it reads the supplied figures
reliably where the 0.5b model does not. Develop against `qwen2.5:0.5b` for
speed, demo on `llama3.1:8b`.

One caveat on that test: the model's prose is returned to clients verbatim
(`response_text` on `/api/insights`, `adapt.summary` on `/api/drift-review`)
and nothing at runtime filters a number out of it. The test asserts the
property against a compliant stand-in model, so it catches a regression in
what Python sends and reports — not a misbehaving model in production.

## Host port ranges — one block per student

Each student claims a block of ten host ports so nothing collides when all
five stacks run under the shared `docker-compose.yml`. Claim yours by editing
this table and the header comment in `docker-compose.yml`.

| Range       | Owner       | In use                                              |
| ----------- | ----------- | --------------------------------------------------- |
| 8000        | **Shared**  | Unified project home page                            |
| 8010–8019   | **Joshua**  | 8010 frontend, 8011 backend (database has no port)   |
| 8020–8029   | **Maxwell** | 8020 frontend, 8021 backend (database has no port)   |
| 8030–8039   | free        |                                                       |
| 8040–8049   | **HyunWoo** | 8040 frontend, 8041 backend (database has no port)   |
| 8050–8059   | free        |                                                       |
| 11434       | shared      | `ollama` (one instance serves every backend)          |

Container-internal ports are not shared state — every backend can listen on
5000 inside its own container. Only the left-hand side of a compose `ports:`
mapping needs to be unique.

### Ollama models live in a container volume

The `ollama` service keeps models in the `ollama-models` named volume. A model
pulled on the host is **not** visible to the container; pull it into the
container instead:

```
docker compose exec ollama ollama pull qwen2.5:0.5b   # default, fast
docker compose exec ollama ollama pull llama3.1:8b    # demo model
```

A tag that has never been pulled into the container makes Ollama answer 404,
and the endpoint returns 503 naming the missing model and the pull command
— distinct from the "could not reach Ollama" message, which means the
container is genuinely unreachable.

Set `OLLAMA_MODEL` in `.env` (copy from `.env.example`) to switch the model for
every service at once.

## Scoping — Release 0 is single-user

- Features with an ownership concept (a user's own holdings, settings, etc.)
  should scope every query to one `DEFAULT_USER_ID` constant for this release,
  keep `user_id` in the schema, and pass it explicitly through the query layer
  — multi-user support later means passing a real `user_id` through instead
  of the constant, not a rewrite.
- Features with no ownership concept — shared reference data that means the
  same thing regardless of who's looking it up — don't need `user_id` at all.

### Joshua's backend (`joshua/backend/`) — Portfolio Holdings

- Deliberately single-user for this release: every query is scoped to one
  `DEFAULT_USER_ID` constant (defined once in `db.py`), holdings and targets
  endpoints never take a `user_id` from the client, and created/updated rows
  are stamped with it server-side.
- `user_id` stays in the schema and every query layer function still takes it
  as an explicit parameter.
- The seed data's `user_id = 1` matches `DEFAULT_USER_ID`; keep them in sync
  if either changes.

### Maxwell's backend (`Maxwell/backend/`) — Financial Glossary

- Shared reference data, not personal to any user: a term's definition
  doesn't change depending on who's looking it up, so the `terms` table has
  no `user_id` column and no per-user scoping.
- AI-Mode is used to generate or refine a definition when a requested term
  isn't already in the database — always via Ollama, never a hardcoded model
  name (see LLM access rules above).

## Working conventions

- Stay inside your own top-level directory unless the task explicitly touches
  a shared file, in which case open a pull request instead of committing
  directly.
- When adding a new microservice, follow the existing pattern of the other
  members' services (Flask app + SQLite db + Dockerfile) and wire it into the
  root `docker-compose.yml` via PR.
