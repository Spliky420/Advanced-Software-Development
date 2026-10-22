# Pull requests to shared files — Release 2

Every change Release 2 of Goals and Budgeting needs outside `LeHoaLong/` and
`.github/workflows/lehoalong-ci.yml`. Each one is its own branch off `main`
and its own pull request, never a commit on the feature branch (CLAUDE.md;
the Release 2 checklist). The feature branch itself never modifies
`multi-agent-server/` or any root file.

| PR | Branch | Files | Status |
| -- | ------ | ----- | ------ |
| A | `LeHoaLong-multi-agent-async` | `multi-agent-server/` | Merged, #40 |
| B | `LeHoaLong-pre-commit` | `.pre-commit-config.yaml`, `.secrets.baseline`, `README.md` | Committed (94dcdfd), ready to raise |
| C | `docker-compose.yml` | the `lehoalong-backend` environment | Optional — not raised yet |
| D | `LeHoaLong-agentic-loop-modes` | `ai-services/agentic-loop/` | Committed (1b9d2c0, 22fa1a2), ready to raise |
| E | `LeHoaLong-cloud-ai-off` (off `main`, after #45 and #46) | `scripts/deploy/03-deploy-apps.sh`, `.github/workflows/cloud-deployment.yml` | Pushed (cad16f0), ready to raise |

---

## PR A — multi-agent server: opt-in `"async": true` (merged, #40)

**Why.** The contract returned `run_id` only once all three agents had
finished, so no caller could poll progress during a run. The Agents tab
needs to show the Planner, Worker and Reviewer finishing one by one.

**What.** `POST /workflow` with `"async": true` returns 202 with the run at
`planning` and a `Location` header, then runs the agents on a background
thread. Without the flag nothing changed. A side fix: an unexpected error
in an agent now fails the run instead of leaving it stuck at `planning`.
112 tests. See `multi-agent-server/README.md`, "Asynchronous runs".

---

## PR B — pre-commit security checks

**Why.** The Release 2 brief requires pre-commit checks for linting with
security rules, secrets and vulnerable dependencies. `.pre-commit-config.yaml`
has to sit at the repository root for pre-commit to find it, which makes it
a shared file.

**Raise it:** push the branch `LeHoaLong-pre-commit`, then open
`https://github.com/Spliky420/Advanced-Software-Development/pull/new/LeHoaLong-pre-commit`.

**What it does to teammates.** Nothing until they run
`pre-commit install`. After that:

- **detect-secrets** checks every commit, repo-wide. The baseline is empty
  because the scan found nothing, and canaries confirmed it detects real
  keys.
- **ruff** and **pip-audit** only look at `LeHoaLong/`. No teammate's code is
  judged by rules they did not choose. The README says how to opt a
  directory in.

**Merge order.** Merge the `LeHoaLong/` security fixes (the feature branch's
step 2 commit) **before or with** this PR. On today's `main` the pins are
still the vulnerable ones, so a teammate running `pre-commit run --all-files`
would see pip-audit fail on my requirements files. The hook is right to
fail, but it would land on someone else.

### `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.6
    hooks:
      - id: ruff-check
        files: ^LeHoaLong/

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]
        exclude: (^|/)package-lock\.json$

  - repo: https://github.com/pypa/pip-audit
    rev: v2.10.1
    hooks:
      - id: pip-audit
        name: pip-audit (LeHoaLong backend)
        args: ["-r", "LeHoaLong/backend/requirements.txt"]
        files: ^LeHoaLong/backend/requirements\.txt$
      - id: pip-audit
        name: pip-audit (LeHoaLong tests)
        args: ["-r", "LeHoaLong/tests/requirements.txt"]
        files: ^LeHoaLong/tests/requirements\.txt$
```

(The committed file carries a comment on every block explaining it.)

Design choices to be ready to defend:

| Choice | Why |
| ------ | --- |
| Exact tags for every `rev` | Hooks cannot change under the team. ruff's tag matches the version CI installs, so local and CI agree. |
| `ruff-check`, not `ruff` | In ruff-pre-commit 0.16 `ruff` is a legacy alias. |
| detect-secrets is repo-wide, the others are scoped | A leaked secret is everyone's problem wherever it lands. Lint rules and dependency pins belong to each directory's owner. |
| One pip-audit entry per file | Audited together, two files that pin a package differently fail as a resolver error rather than an audit result. Found by testing. |
| pip-audit runs only when a requirements file changes | That is when a commit can introduce a vulnerability. New advisories against unchanged pins are caught by CI's weekly scheduled run. |
| `package-lock.json` excluded from detect-secrets | It is npm-generated, and its `sha512-` integrity hashes are high-entropy noise. |

### Verified

- `pre-commit run --all-files` on the feature branch: all four hooks pass.
- Canaries: a string-built SQL query blocked by ruff S608, an AWS key by
  detect-secrets, and `pytest==8.3.3` by pip-audit (PYSEC-2026-1845).
- Committed files are LF; the baseline's exclude pattern is the real regex
  (see `docs/security/2026-10-22-detect-secrets.md` for the Git Bash pitfall).

### README note (in the PR, under "Running the stack from a clean clone")

> ### Pre-commit security checks (once per clone)
>
> ```bash
> pip install pre-commit && pre-commit install
> ```
>
> Run this once after cloning. From then on every `git commit` runs the
> checks in `.pre-commit-config.yaml` and stops the commit if one fails …

---

## PR C — `docker-compose.yml`: state the Release 2 settings (optional)

**Not blocking.** `config.py` and the backend Dockerfile already default to
`MULTI_AGENT_URL=http://host.docker.internal:5004` with both switches on, and
the block already has `extra_hosts`, so the containerised backend reaches the
multi-agent server with no compose change. This PR only makes the dependency
visible in the compose file and switchable from `.env`, the way the Release 1
PR did for MCP and RAG.

It adds environment entries only. **No service is added**: the multi-agent
server, like Ollama, MCP and RAG, stays a host process and is never defined
in `docker-compose.yml` (Release 2 checklist).

```diff
   lehoalong-backend:
     environment:
       DB_PATH: /data/goals.db
       OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
       OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:0.5b}
       MCP_SERVER_URL: ${MCP_SERVER_URL:-http://host.docker.internal:5002/mcp}
+      # Release 2. The multi-agent server is a HOST process, like MCP and RAG.
+      # Off or unreachable, plan reviews degrade to Release 1 and say so.
+      AI_MODE_ENABLED: ${LEHOALONG_AI_MODE_ENABLED:-true}
+      MULTI_AGENT_ENABLED: ${LEHOALONG_MULTI_AGENT_ENABLED:-true}
+      MULTI_AGENT_URL: ${MULTI_AGENT_URL:-http://host.docker.internal:5004}
```

---

## PR D — agentic loop: `multiagent`, `testing` and `cloud` review modes

**Why.** The Release 2 brief adds three review modes to the shared agentic
loop, each writing a validation log to `reports/`, following the MCP mode's
Python-collects, model-comments discipline. Criterion 8 needs the logs to
appear in the report, not only the modes to run.

**What.** Menu entries 7–9, alongside the six existing modes, which are
unchanged (the only edits to existing files are additions: three entries
in `core/mode_config.py`, a dispatch in `core/orchestrator.py`, the menu
lines, and an optional `--mode` CLI in `main.py`). Each mode:

1. **Act, no model call.** A collector reads its evidence and decides every
   check as PASS, WARN, FAIL or SKIP in Python (`core/validation.py`).
2. **Observe.** Ollama assesses Python's result, without changing it.
3. **Adapt.** A second Ollama pass checks that assessment against the same
   evidence. Python then flags three things in the model's text: numbers
   the evidence did not contain, claims of "no warnings" or "no failures"
   that its counts contradict, and checks quoted with the wrong status.
4. **Report.** `reports/<mode>-review.md`: Python's verdict first, then the
   checks, the evidence, the sources read, and the model's text with
   Python's flags.

| Mode | Reads | Checks |
| ---- | ----- | ------ |
| `multiagent` | `workflow_history.jsonl` (or `WORKFLOW_HISTORY_PATH`), the server's source | all three agents ran before the human gate, decisions valid and recorded once, audit records complete, failures name their phase |
| `testing` | `<student>/docs/security/`, `.pre-commit-config.yaml`, `<student>-ci.yml` and its newest run (GitHub API), the endpoint report | reports present and clean, audit newer than the pins, post-commit job present, AI off in CI, CI green, route coverage |
| `cloud` | `<student>/docs/cloud/deployment-report.json`, `cloud-deployment.yml` and its newest run, the live URLs | report complete, OIDC with no stored credential, live frontend, backend, database and proxy, AI switches as reported by the running backend |

`cloud` ends at a **human release decision**: approve, hold or reject.
Approve is refused while Python's verdict is FAIL. Approving over warnings
needs a note, and so do hold and reject. Each decision is appended to
`reports/release-decisions.jsonl`.

**Also fixed.** `main.py` imported `numpy` without using it. numpy is not in
`requirements.txt`, so a clean install failed on start.

**Verified.** 35 offline tests (`python -m pytest tests` in
`ai-services/agentic-loop/`), ruff-clean. All three modes were run against
qwen2.5:0.5b; their reports are in the PR. On the `cloud` report, qwen
claimed "working end to end" while Python's verdict was FAIL, and Python
flagged it. The `cloud` report is FAIL until step 8 deploys. Run it again
after deploying, and record the release decision then:

```bash
cd ai-services/agentic-loop
python main.py --mode multiagent --target LeHoaLong
python main.py --mode testing --target LeHoaLong
python main.py --mode cloud --target LeHoaLong       # asks for the release decision
```

The `multiagent` report in the PR was run on the step 6 live history (the
server's own history file is git-ignored), so its source path is a local
one.

---

## PR E — team cloud deployment: this feature's AI switches off, and a CRUD smoke test

**Context.** The team deploys to Azure Container Apps with Joshua's
`scripts/deploy/` and `cloud-deployment.yml` (branch `cloud-deployment`):
`az` scripts, OIDC as a user-assigned managed identity, every student's CI
as a gate, and each SQLite database seeded by an init container. That is
this feature's cloud deployment. A second Bicep deployment of the same
resources would only duplicate it.

**Why.** `lehoalong-backend` gets `AI_MODE_ENABLED=false` and empty AI URLs,
but its other three switches are not set. They default to `true` (backend
Dockerfile), and an empty URL falls back to the `host.docker.internal`
default, so the backend runs with MCP, RAG and the multi-agent server on,
pointing at servers that do not exist. Requests degrade, but the Release 2
brief requires all four off. Enerel's and HyunWoo's lines already set
theirs.

**What.**

```diff
 deploy lehoalong-backend 5000 internal 1 1 \
   --db lehoalong-database /usr/local/bin/entrypoint.sh "DB_FILE=/data/goals.db" "INIT_DB_FORCE=0" -- \
-  "DB_PATH=/data/goals.db" "OLLAMA_MODEL=qwen2.5:0.5b" "${NO_AI[@]}"
+  "DB_PATH=/data/goals.db" "OLLAMA_MODEL=qwen2.5:0.5b" \
+  "MCP_ENABLED=false" "RAG_ENABLED=false" "MULTI_AGENT_ENABLED=false" "MULTI_AGENT_URL=" "${NO_AI[@]}"
```

and in the smoke test, a CRUD read through the frontend's nginx, the
internal backend and its seeded database:

```diff
           check "https://joshua-frontend.$domain/api/holdings" "ticker" || status=1
+          check "https://lehoalong-frontend.$domain/api/goals" "goal_id" || status=1
```

**What the deployed backend runs with**, resolved by
`LeHoaLong/tools/write_deployment_report.py` from the files at each commit:

| Switch | Deployed now (d2dff07, Release 1 code) | Release 2 merged, no PR E | Release 2 + PR E |
| ------ | -------------------------------------- | ------------------------- | ---------------- |
| `AI_MODE_ENABLED` | not in the code: plan calls Ollama at the default address and fails with 503 | off | off |
| `MCP_ENABLED` | on | on | off |
| `RAG_ENABLED` | on | on | off |
| `MULTI_AGENT_ENABLED` | not in the code | on | off |

Both merges are needed. Neither one alone gives all four off.

## Contract notes from integrating with the multi-agent server

No gap blocked integration. After PR A, the contract covered everything the
plan review needs. Two observations, neither requiring a change:

- `POST /workflow/<run_id>/review` returns only `{run_id, status, decision,
  decided_at}`, not the run body. This backend reads the run with `GET`
  before deciding and stores that body with the decision, so the decided-on
  output is in `ai_plan_log` even if the server's history is later reset.
- `GET /workflow/<run_id>` serves any caller's run to anyone who knows the id.
  This backend does not rely on that: it serves only runs it started, looked
  up in its own `ai_plan_log`. Ids are 128-bit random, so on a local host
  process this is a note, not a hole.

### PR #42 (merged into `main` after this branch was cut) changed the server

PR #42 rewrote `multi-agent-server/agents.py` and all three prompts. The
contract (routes, statuses, run body) is unchanged, so this backend still
integrates, and the `multiagent` mode's checks still pass on it. Three
things affect Goals and Budgeting and need a PR on the shared server:

1. **A recommendation from another feature is added to every review.**
   When the Worker falls back, the Reviewer appends "Review the transaction
   records, verify supporting receipts, and confirm potential tax
   deductions" whatever the caller. On a savings-plan review that is wrong
   advice, shown under "What the agents said". The server is meant to be
   feature-agnostic. The fix is to drop the sentence or take it from the
   caller's task.
2. **Two new Python checks are not badged in the Agents tab.** Risks
   starting "Completeness check:" and "Analysis quality:" are written by
   Python, but the tab badges only "Figure check:" and "Arithmetic check:"
   as Python's. That is a one-line change in `AgentReviewPanel.jsx`, made
   once this branch has merged `main`.
3. **Blank lines between functions were removed** throughout `agents.py`.
   Behaviour is unchanged, but PEP 8 spacing breaks: ruff reports 25
   blank-line errors (E302, E305) in it, all auto-fixable.

