# Project-level agentic review

`agentic_review.py` runs a Plan → Act → Observe → Adapt loop over **the
repository itself** — its database seeding, its implementation layout, its
microservices architecture and its DevOps pipeline.

It is deliberately not the same thing as `joshua/backend/drift.py`. That loop
reviews *portfolio data*: it is a product feature that reviews a user's
holdings against their targets. This one reviews *the project*. The two share
a shape, a logging format and an Ollama client, nothing else.

## Running it

From the repository root:

```bash
python scripts/review/agentic_review.py            # four phases, then a review record
python scripts/review/agentic_review.py --no-llm   # stop after Observe; never contacts Ollama
python scripts/review/agentic_review.py --json      # full four-phase result as JSON
```

`--no-llm` is the form to use in CI or on a machine with no Ollama running:
Plan, Act and Observe need nothing but the filesystem.

In `--json` mode the four log lines go to **stderr** so that stdout stays
parseable; in every other mode they go to stdout.

`LOG_LEVEL=DEBUG` additionally logs the full result list from Act and the full
prompt and response from Adapt.

**Exit status is 0 whenever the review completes, findings or not.** This is a
review tool, not a gate — a non-zero exit means the script itself failed.

### Requirements

- Python 3.11+
- PyYAML, to parse `docker-compose.yml`. Without it the architecture checks
  report `unknown` rather than failing.
- Ollama only for the Adapt phase. `--no-llm` skips it entirely.

## What it checks

25 checks in four categories.

| Category | Check id | What it asserts |
|---|---|---|
| implementation | `structure.<student>` | the student directory exists and contains `backend/`, `frontend/`, `database/` |
| architecture | `compose.<student>` | `docker-compose.yml` defines at least one `<student>-*` service block |
| architecture | `layout.<dir>` | the spec 7.1 root directories exist: `docs/`, `shared/`, `ai-services/`, `scripts/`, `.github/workflows/` |
| devops | `ci.<student>` | `.github/workflows/` holds a workflow file naming that student |
| database | `seed.<student>` | every table declared in `database/init.sql` is seeded with **≥ 10 rows** by `database/seed.sql` |

Each result carries a `check_id`, a `category`, a `status` and a short factual
`detail` string.

### Status values

- **pass** — the check held.
- **fail** — the check did not hold.
- **unknown** — the check could not be determined, because a file is absent or
  unparseable. `unknown` is a first-class outcome, not an error: the script
  reports what it could not establish rather than guessing or raising. Both
  `fail` and `unknown` become findings.

### How the row counts are obtained

`init.sql` and `seed.sql` are read **as text**. No `.db` file is opened, no
database connection is made, no SQL is executed, and no student Python module
is imported for the checks.

Counting is by **value tuple**, not by `INSERT` statement: a single
`INSERT INTO holdings ... VALUES (...), (...), ...` seeds 16 rows, and counting
statements would report 1. String literals and `--` comments are masked out
first so that parentheses and commas inside them cannot be miscounted, and the
column list in `INSERT INTO t (a, b, c) VALUES ...` is excluded because
counting starts after the `VALUES` keyword.

A table declared by `CREATE TABLE` with no matching `INSERT` counts as 0 rows.
Note this measures **what the seed files populate**, which is not the same as
what a table holds at runtime — a table filled by the application after start-up
reads as 0 here.

## Read-only guarantee

The script never writes a file, never opens or connects to a database, never
executes SQL, and never touches a container. Every check is a filesystem read
or a text parse. The only network call it can make is the optional Ollama
request in Adapt.

## The four phases

The phase functions are the four public functions in the module, in order.
**Plan, Act and Observe are pure Python and involve no LLM at all; only Adapt
talks to the model**, and only ever about findings Observe already produced.

### `plan(repo_root)`

Decides *what* to check and returns the check list. Resolves paths and performs
no I/O — it does not stat a single file. Mints the run's correlation id
(`uuid4().hex[:8]`), which the other three phases carry forward.

```
[agentic-loop <run_id>] PLAN    | checks_planned=25 | categories=database,implementation,architecture,devops
```

### `act(plan_result)`

Performs the checks: walks the tree for directory and file existence, parses
`docker-compose.yml` with PyYAML, and counts seeded rows from SQL text. Returns
one result per check plus a pass/fail/unknown tally.

```
[agentic-loop <run_id>] ACT     | checks_run=25 | pass=21 | fail=3 | unknown=1
```

### `observe(act_result)`

Classifies. Groups every result by category, counts pass/fail/unknown per
category, and produces the findings list — the `fail` and `unknown` results
only — sorted by category.

```
[agentic-loop <run_id>] OBSERVE | findings=4 | passed=21 | by_category=database 1f/1u/5; ...
```

### `adapt(observe_result, generate_fn=None)`

Has the model describe the findings in plain English. **Only the findings are
sent** — never the passing checks, never the repository contents. When there
are zero findings it returns a Python-formatted string saying so and never
calls the LLM:

```
[agentic-loop <run_id>] ADAPT   | llm_called=True | model=qwen2.5:0.5b | prompt_chars=1051 | response_chars=455
[agentic-loop <run_id>] ADAPT   | llm_called=False | reason=no findings, LLM skipped
```

That conditional is the part that makes the loop agentic rather than a fixed
pipeline, which is why the skip is logged as explicitly as a call.

`generate_fn` is an injection seam for tests, exactly as in `drift.adapt`. Left
unset, the phase reuses `joshua/backend/llm.py`'s `generate()` — the team's one
approved Ollama client. If that module cannot be imported, it falls back to a
local twin calling the same `/api/generate` endpoint with the same
`OLLAMA_BASE_URL` / `OLLAMA_MODEL` environment variables and the same
`LLMUnavailableError` handling. The record reports which client was used.

If Ollama is unreachable, the findings are still printed and the exit status is
still 0; the record notes that Adapt was skipped.

### System prompt

The model is given already-established facts and told to describe them only:

> You are a software project review assistant. You will be given a list of
> factual findings from an automated check of a student software project
> repository. Each finding states a category, a check identifier, a status, and
> a short factual detail. Using only those findings, write a short plain-English
> paragraph grouping the issues by category and stating what was found. Describe
> only -- never invent findings, never speculate about causes, never suggest
> fixes, and never restate or introduce any fact that is not given to you exactly
> as provided below.

This follows the team's architectural rule that all determination happens in
Python and the model only narrates. **The authoritative review output is the
record printed by Python, not the model's paragraph** — a small model has been
observed restating directory names as "tables" and misattributing findings
across categories. The findings table above the narration is the ground truth.
