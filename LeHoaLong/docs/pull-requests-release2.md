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

