# Advanced-Software-Development

ASD 2026 Project.

Five students each build a **frontend**, a **backend/API** and a **database**
microservice. All of them are orchestrated together by the single
`docker-compose.yml` at the repo root, and all of them share one **Ollama**
container for LLM access. Each student's services are independent — you can run
the whole stack or just one student's slice.

---

## Running the stack from a clean clone

These steps are the same for every student's services.

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2). Nothing else — Python, Flask
  and SQLite all live inside the containers.
- Roughly 2 GB of free disk for images, plus the size of whichever model you
  pull (400 MB or 4.9 GB, see step 3).

### 1. Clone and configure

```bash
git clone <repo-url>
cd Advanced-Software-Development
cp .env.example .env
```

`.env` is gitignored, so every teammate copies it once. It sets the shared
model tag and a few tunables. The values in `.env.example` are also the
built-in defaults in `docker-compose.yml`, so the stack still comes up if you
forget this step — but copy it anyway, since it is the file you edit to switch
models.

### 2. Build and start

```bash
docker compose up -d --build
```

First run takes a few minutes: it builds every image, and each database service
creates and seeds its own SQLite file on first start only.

### 3. Pull a model into the Ollama container

**This step is required.** A model pulled on your host machine is *not* visible
to the container — Ollama keeps its models in the `ollama-models` Docker
volume.

```bash
docker compose exec ollama ollama pull qwen2.5:0.5b   # default, ~400 MB, fast
docker compose exec ollama ollama pull llama3.1:8b    # demo model, ~4.9 GB
```

`qwen2.5:0.5b` is the default so that a clean clone works quickly. To switch,
pull the other model first, then set `OLLAMA_MODEL=llama3.1:8b` in `.env` and
run `docker compose up -d` to restart the backends with the new value.

If the configured tag has never been pulled, Ollama answers **404** and the LLM
endpoints return a clean **503** naming the missing model and the exact pull
command. Everything that does not involve the LLM keeps working.

### 4. Check it is up

```bash
docker compose ps
```

Every service should be `running`, and the ones with healthchecks `healthy`.
Then open the frontend for the student whose feature you want (see the port map
below).

### Stopping and resetting

```bash
docker compose down            # stop, keep databases and pulled models
docker compose down -v         # also delete all data volumes and models
```

`down -v` discards the seeded databases; the next `up` re-creates and re-seeds
them from scratch. It also deletes pulled models, so you would repeat step 3.

### Port map

Each student owns a block of ten host ports so nothing collides when the whole
stack runs at once. Claim yours in `CLAUDE.md` and in the header comment of
`docker-compose.yml`.

| Range     | Owner      | In use                                             |
| --------- | ---------- | -------------------------------------------------- |
| 8000      | **Shared** | Unified project home page                          |
| 8010–8019 | **Joshua** | 8010 frontend, 8011 backend (database has no port) |
| 8020–8029 | **Maxwell**| 8020 frontend, 8021 backend (database has no port) |
| 8030–8039 | **HyunWoo**| 8030 frontend, 8031 backend (database has no port) |
| 8040–8049 | free       |                                                    |
| 8050–8059 | free       |                                                    |
| 11434     | shared     | `ollama` — one instance serves every backend       |

### A note for the other four students

`docker-compose.yml` has a commented template block at the bottom: copy it,
replace `<name>`, claim a port range, and nothing above your block needs to
change.

Do the same here. Add your own `## <Your name> — <Your feature>` section below
the existing ones, following the same subsection order (*What it does*,
*Services and ports*, *API endpoints*, *How it works*, *Running just these
services*, *Running the tests*, *Known limitations*). Everything above this
line is shared — please change it by pull request.

---

## Joshua — Portfolio Holdings

### What it does

Tracks an investment portfolio and reports on it in plain English.

You record **holdings** — a ticker, an asset class, units held, average cost
and last known price. From those, the backend calculates each position's cost
basis, market value and gain/loss, then rolls them up into a portfolio total
and a breakdown by asset class. You also set **allocation targets**: what
percentage of the portfolio each asset class *should* be.

On top of that sit two LLM-backed features. `/api/insights` describes the
portfolio's composition and concentration in three sentences.
`/api/drift-review` compares the actual allocation against the targets, flags
the asset classes that have drifted past a threshold, and has the model explain
which are overweight and which are underweight.

The architectural rule throughout: **every number is calculated in Python.**
The model is only ever handed finished figures and asked to write sentences
around them — it never does arithmetic and never sees a raw holding. See
[Known limitations](#known-limitations) for why that matters in practice.

### Services and ports

| Service           | Host port | What it is                                               |
| ----------------- | --------- | -------------------------------------------------------- |
| `joshua-frontend` | **8010**  | nginx serving a page and proxying `/api/` to the backend |
| `joshua-backend`  | **8011**  | Python 3 + Flask REST API (gunicorn in the container)    |
| `joshua-database` | —         | SQLite, created and seeded on first start                |

Open <http://localhost:8010> for the page, or call the API directly at
`http://localhost:8011`.

The database service has no host port on purpose: it owns the `joshua-db-data`
volume and is reached only over the compose network. It seeds 16 holdings
across all 10 asset classes, 10 allocation targets summing to 100%, and 10
sample insight-log rows — so every endpoint returns something meaningful the
moment the stack is up.

The frontend is a deliberate placeholder (plain HTML + `fetch`) until the team
settles its framework with the tutor. It can be replaced wholesale without the
container, the nginx proxy or the compose wiring changing.

### API endpoints

Base URL `http://localhost:8011`. All request and response bodies are JSON.

| Method   | Path                 | Description                                                                                                            |
| -------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/health`            | Liveness check; 503 if the database is unreachable.                                                                     |
| `GET`    | `/api/holdings`      | List every holding in the portfolio.                                                                                    |
| `GET`    | `/api/holdings/<id>` | Fetch one holding; 404 if it does not exist.                                                                            |
| `POST`   | `/api/holdings`      | Create a holding; 201 with the stored row, or 400 listing every validation error.                                       |
| `PUT`    | `/api/holdings/<id>` | Replace a holding; 404 if it does not exist.                                                                            |
| `DELETE` | `/api/holdings/<id>` | Delete a holding; 204 on success.                                                                                       |
| `GET`    | `/api/allocation`    | The calculated portfolio report: per-holding metrics, totals, and the breakdown by asset class.                         |
| `GET`    | `/api/targets`       | The target allocation percentage for each asset class.                                                                  |
| `PUT`    | `/api/targets`       | Replace the whole target set at once; rejected unless the percentages sum to 100.                                       |
| `POST`   | `/api/insights`      | Ask the model to describe the portfolio in three sentences; 201 with the logged entry, or 503 if the model is unavailable. |
| `POST`   | `/api/drift-review`  | Run the full Plan → Act → Observe → Adapt loop against the allocation targets.                                          |

Both LLM endpoints write an audit row to `insight_log` recording the exact
prompt sent, the model tag used and the text that came back.

A quick check once the stack is up:

```bash
curl http://localhost:8011/api/allocation
curl -X POST http://localhost:8011/api/drift-review
```

On Windows PowerShell use `curl.exe` — plain `curl` is an alias for
`Invoke-WebRequest` and takes different arguments.

### How it works — the Plan → Act → Observe → Adapt loop

`POST /api/drift-review` implements the agentic loop in
[`joshua/backend/drift.py`](joshua/backend/drift.py). Each phase is one public
function, called in order, and each contributes its own key to the response, so
the loop is visible from the outside rather than hidden inside the service.

**The first three phases are pure Python with no LLM involvement at all.** Only
ADAPT talks to the model, and only ever about breaches OBSERVE has already
found.

| Phase       | Function                          | What happens                                                                                                                                            |
| ----------- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Plan**    | `plan(targets)`                   | Reads the allocation targets and sets the drift threshold — `DRIFT_THRESHOLD_PERCENT`, default 5 percentage points. Decides which asset classes are in scope. |
| **Act**     | `act(portfolio, plan_result)`     | Computes the actual allocation and the drift for each class: `actual % − target %`, in percentage points. Positive is overweight, negative underweight.  |
| **Observe** | `observe(act_result, plan_result)` | Classifies each class as a breach or within tolerance. Anything with `\|drift\| ≥ threshold` is a breach, labelled overweight or underweight, sorted by magnitude. |
| **Adapt**   | `adapt(observe_result)`           | Sends *only* the breaches — as finished figures — to the model, which writes a plain-English paragraph naming what is overweight, what is underweight, and by how much. |

Two details worth knowing:

- **ACT covers the union of targeted and held classes.** A class you hold but
  have set no target for is real drift (target treated as 0%) and would be
  invisible if only the planned list were walked.
- **ADAPT short-circuits.** When nothing has breached, it returns a fixed
  Python sentence saying so and never calls the model at all. The
  `adapt.llm_called` flag in the response tells you which happened.

The response body mirrors the loop:

```json
{
  "plan":    { "phase": "plan",    "threshold_percent": 5.0, "asset_classes_to_examine": [], "target_percent_by_class": {} },
  "act":     { "phase": "act",     "total_market_value": 0.0, "drift_by_class": [] },
  "observe": { "phase": "observe", "breach_count": 0, "breaches": [], "within_threshold": [] },
  "adapt":   { "phase": "adapt",   "llm_called": true, "model_name": "qwen2.5:0.5b", "summary": "..." },
  "insight_log_id": 11
}
```

Each phase also carries a `description` string explaining, in the response
itself, what that step of the loop did.

### Running just these services

```bash
docker compose up -d --build ollama joshua-database joshua-backend joshua-frontend
```

Then pull a model as in step 3 above, if you have not already.

### Running the tests

The tests run on the host, not in a container, and need no running stack and no
database — they build their own temporary SQLite database and stub the model.

```bash
pip install pytest Flask requests
python -m pytest joshua/tests
```

Run that from the repo root. 37 tests, under a second.

Install those three packages directly rather than using
`-r joshua/backend/requirements.txt` — that file also pins `gunicorn`, which is
the container's WSGI server and does not install on Windows.

| File                         | Covers                                                                |
| ---------------------------- | --------------------------------------------------------------------- |
| `test_allocation.py`         | Cost basis, market value, gain/loss and asset-class rollups.           |
| `test_drift.py`              | Each phase of the Plan → Act → Observe → Adapt loop.                   |
| `test_targets_validation.py` | Target payload validation, including the sum-to-100 rule.              |
| `test_llm.py`                | Ollama failure modes: unreachable versus model-not-pulled.             |
| `test_no_invented_figures.py` | That neither LLM endpoint reports a figure Python did not calculate.  |

### Known limitations

**Small models misread correctly-supplied figures.** A small model can get the
*interpretation* of a correct figure wrong even though every number it was
handed is right. Observed with `qwen2.5:0.5b` on `/api/insights`: asked to name
the largest asset class, it named Australian equities at 11.66% when ETFs at
24.30% was plainly larger. Both figures were supplied correctly; the model
simply compared them badly.

This is precisely why all arithmetic happens in Python and the model is given
finished values. The guarantee the architecture provides is that **the model
cannot introduce a figure of its own** — every number in a response traces back
to the calculated portfolio report. It does not, and cannot, guarantee that the
model reasons about those numbers well. `test_no_invented_figures.py` locks in
the guarantee that holds; interpretation quality is a model-choice question,
not a code one.

**`llama3.1:8b` is the demo model for this reason** — it reads the supplied
figures reliably where the 0.5b model does not. Develop against `qwen2.5:0.5b`
for speed, demo on `llama3.1:8b`.

**Model prose is returned verbatim.** Nothing at runtime filters numbers out of
`response_text` on `/api/insights` or `adapt.summary` on `/api/drift-review`.
The test asserts the no-invented-figures property against a compliant stand-in
model, so it catches a regression in what Python computes and sends — not a
misbehaving model in production.

**Release 0 is single-user.** Every query is scoped to one `DEFAULT_USER_ID`
constant defined in `db.py`; the holdings and targets endpoints never take a
`user_id` from the client. `user_id` stays in the schema and every query
function still takes it as a parameter, so multi-user support later means
passing a real value through, not a rewrite.

**The frontend is a placeholder.** Plain HTML and `fetch`, pending the team's
framework decision. It currently renders the asset-class allocation table only.

**The model must be pulled into the container.** Covered in step 3 above — a
host-side `ollama pull` does not count, and the LLM endpoints return 503 until
you do it.

---

## Maxwell — Financial Glossary

### What it does

A financial glossary: look up a term and get its definition. Definitions are
**shared reference data** — a term means the same thing regardless of who is
looking it up, so there is no user scoping (Release 0 specification).

When a requested term is not already in the database, the backend generates a
definition via Ollama (AI-Mode). Terms are validated as financial before that
happens, so non-financial input is rejected with a clear error instead of
being sent to the model.

Full CRUD is supported from the frontend: add a term (with an
Ollama-generated definition where the term is financial), edit an existing
definition, and delete a term.

### Services and ports

| Service            | Host port | Purpose                                     |
| ------------------ | --------- | ------------------------------------------- |
| `maxwell-frontend` | 8020      | Static HTML/JavaScript client               |
| `maxwell-backend`  | 8021      | Python Flask API (SQLite + Ollama)          |
| database           | —         | SQLite file inside the backend service      |

Open <http://localhost:8020> for the glossary UI.

### API endpoints

| Method | Path                     | Purpose                                  |
| ------ | ------------------------ | ---------------------------------------- |
| GET    | `/api/glossary`          | List all glossary terms                  |
| GET    | `/api/glossary/<term>`   | Fetch one term, generating it if missing |

The frontend also drives create, update and delete against these routes.

### Running just these services

```bash
docker compose up --build maxwell-frontend maxwell-backend ollama
```

### Known limitations

- Financial-term validation is a gate in front of the model, not a guarantee
  about the model's output quality.
- All LLM access goes through the shared `ollama` service at
  `http://ollama:11434` — never a hardcoded model name or a host install.

---

## HyunWoo — Bills & Subscriptions

### What it does

Tracks recurring bills and subscriptions in one dashboard. Users can add,
view, edit and delete records, compare monthly and annual recurring costs, and
monitor payment dates, automatic renewals and free trials.

The AI review follows a visible Plan → Act → Observe → Adapt workflow. Python
calculates every amount, date and priority. Ollama receives the completed
findings and selects an appropriate tone for the action summary, while the
recommended actions remain based on validated Python results.

### Services and ports

| Service              | Host port | Purpose                                      |
| -------------------- | --------- | -------------------------------------------- |
| `hyunwoo-frontend`   | **8030**  | nginx serving the bills dashboard            |
| `hyunwoo-backend`    | **8031**  | Flask REST API and agentic review             |
| `hyunwoo-database`   | —         | SQLite database seeded with 10 sample records |

Open <http://localhost:8030> for the dashboard, or call the API directly at
`http://localhost:8031`. The shared project homepage is available at
<http://localhost:8000>.

The database service owns the `hyunwoo-db-data` volume. It creates the bills
table and adds 10 realistic sample bills only when the database is first
started.

### API endpoints

| Method   | Path                    | Purpose                                         |
| -------- | ----------------------- | ----------------------------------------------- |
| `GET`    | `/health`               | Check the API and database connection           |
| `GET`    | `/api/bills`            | List all bills and subscriptions                |
| `GET`    | `/api/bills/<id>`       | Return one saved record                         |
| `POST`   | `/api/bills`            | Add a bill or subscription                      |
| `PUT`    | `/api/bills/<id>`       | Replace an existing record                      |
| `DELETE` | `/api/bills/<id>`       | Delete an existing record                       |
| `GET`    | `/api/summary`          | Return recurring cost and renewal totals        |
| `POST`   | `/api/bills/review`     | Run the Plan → Act → Observe → Adapt review     |

### How it works — the Plan → Act → Observe → Adapt loop

`POST /api/bills/review` accepts a review date and a period from 1 to 90 days.
The response contains a separate result for every phase:

| Phase       | What happens                                                                  |
| ----------- | ----------------------------------------------------------------------------- |
| **Plan**    | Selects the date range, seven-day urgency rule and priority order.             |
| **Act**     | Loads active records, calculates comparable costs and sorts payment dates.     |
| **Observe** | Finds overdue bills, near-term payments, renewals and trials ending soon.      |
| **Adapt**   | Selects the first priority, builds safe next steps and uses Ollama for tone.    |

When no records require attention, Adapt returns a clear Python response and
does not call Ollama. If Ollama returns an unexpected tone, the backend uses a
validated neutral summary instead.

### Running just these services

```bash
docker compose up -d --build ollama shared-frontend hyunwoo-database hyunwoo-backend hyunwoo-frontend
docker compose exec ollama ollama pull qwen2.5:0.5b
```

Then open <http://localhost:8000> or <http://localhost:8030>.

### Running the tests

The tests use a temporary SQLite database and replace the Ollama response, so
they do not require a running model or Docker stack.

```bash
python3 -m pip install -r hyunwoo/backend/requirements.txt -r hyunwoo/tests/requirements.txt
python3 -m pytest hyunwoo/tests -v
```

### Known limitations

- Release 0 scopes every bill to one default local user and does not include
  accounts or login.
- Due dates and trial dates are entered manually; the application does not
  connect to banks, providers or calendars.
- Recommendations are reminders and review prompts only. The application does
  not make payments or cancel subscriptions.
- The model must be pulled into the shared Ollama container before running an
  AI review that contains items needing attention.
