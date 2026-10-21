# Shared Multi-Agent Server

One shared server for every feature. Three agents (**Planner**, **Worker**,
**Reviewer**) run over a task and evidence you supply, and a **human review
gate** follows them. A run is not complete until a person decides on it.

**It is not containerised.** The Release 2 brief requires it to run as a
local process on the host, like Ollama, the MCP server and the RAG server.
It is never added to `docker-compose.yml`. Your backend container reaches it
at:

```
http://host.docker.internal:5004
```

Add `MULTI_AGENT_URL=http://host.docker.internal:5004` to your service's
environment and read it from there.

**It is feature-agnostic.** It knows nothing about goals, bills,
portfolios, transactions, documents or glossaries. Your backend assembles the
evidence (figures already computed in Python, per CLAUDE.md), and the agents
only plan, describe and review around it. No agent is ever asked for a
figure.

## Running it

```bash
cd multi-agent-server
pip install -r requirements.txt

STUB_AGENTS=true ./run.sh   # canned agents, no Ollama needed
./run.sh                    # real agents, Ollama must be running on the host
```

On Windows gunicorn does not install; `run.sh` falls back to Flask's threaded
server (or run `python server.py` directly).

| Variable                | Default                   | Meaning                                 |
| ----------------------- | ------------------------- | --------------------------------------- |
| `STUB_AGENTS`           | `false`                   | `true` returns canned agent output      |
| `OLLAMA_BASE_URL`       | `http://localhost:11434`  | Ollama on the host                      |
| `OLLAMA_MODEL`          | `qwen2.5:0.5b`            | model tag; never hardcoded              |
| `AGENT_TIMEOUT_SECONDS` | `55`                      | per-agent Ollama call timeout           |
| `MULTI_AGENT_PORT`      | `5004`                    | listen port                             |

## API contract

### `POST /workflow`

```json
{ "task": "<what to plan>", "evidence": { ... }, "caller": "<student>" }
```

- `task` is a required, non-empty string.
- `evidence` is a required JSON object. Its keys are how plan steps refer to
  it, so give them meaningful names (`"monthly_totals"`, not `"data"`).
- `caller` is optional and defaults to `"unknown"`. It identifies you in the
  audit trail, so send it.

It blocks until all three agents have run, then returns **201**:

```json
{
  "run_id": "785b03cafab14facafb9ef4416af93d3",
  "status": "awaiting_human",
  "plan": [
    { "step": 1, "action": "Examine the 'rows' evidence.", "evidence": ["rows"] }
  ],
  "work": "Step 1: ...",
  "review": { "risks": ["..."], "recommendations": ["..."] },
  "model": "qwen2.5:0.5b",
  "stub": false,
  "human_review": null,
  "error": null
}
```

`human_review` and `error` are additions to the circulated contract. Every
circulated key is unchanged.

### `GET /workflow/<run_id>`

**200** with the same body, reflecting the current state. Poll it from
another request while a `POST /workflow` is still running to show progress.

| `status`         | Meaning                                              |
| ---------------- | ---------------------------------------------------- |
| `planning`       | Planner running                                      |
| `working`        | `plan` filled in, Worker running                     |
| `reviewing`      | `work` filled in, Reviewer running                   |
| `awaiting_human` | all three agents done, waiting for a decision        |
| `complete`       | decided; `human_review` holds the decision           |
| `failed`         | an agent could not run; `error` says which phase     |

### `POST /workflow/<run_id>/review`

```json
{ "decision": "approve|correct|partial|reject", "note": "...", "corrected": "..." }
```

| Decision  | Rules                                                    |
| --------- | -------------------------------------------------------- |
| `approve` | `note` optional                                          |
| `correct` | `corrected` **required**: the corrected text             |
| `partial` | `note` **required**: say which part is accepted          |
| `reject`  | `note` optional                                          |

`corrected` is refused with any decision other than `correct`. An optional
`reviewer` string names who decided and defaults to the run's `caller`. The
agents' original output is never overwritten: a correction is stored next to
it.

**200**:

```json
{ "run_id": "...", "status": "complete", "decision": "approve",
  "decided_at": "2026-10-21T04:17:28+00:00" }
```

### `GET /health`

```json
{ "status": "ok", "model": "qwen2.5:0.5b", "stub": false, "ollama_reachable": true }
```

### Errors

Every error is JSON with `error` (a fixed code to branch on) and `detail`
(a message for people to read).

| Status | `error`              | When                                                        |
| ------ | -------------------- | ----------------------------------------------------------- |
| 400    | `validation_failed`  | bad body; `fields` maps each bad field to its reason        |
| 404    | `not_found`          | unknown `run_id` (on GET and on review)                     |
| 409    | `conflict`           | review of a run not `awaiting_human`: already reviewed, or failed |
| 503    | `agent_unavailable`  | Ollama unreachable, model not pulled, or an agent timed out |

```json
{ "error": "validation_failed",
  "detail": "task is required; evidence is required",
  "fields": { "task": "is required", "evidence": "is required" } }
```

A 503 still carries the `run_id`. The failed run is kept (status `failed`)
along with any phases that finished.

## Stub mode

`STUB_AGENTS=true` replaces all three agents with deterministic output built
in Python from your evidence's **keys**: one plan step per key plus a summary
step. No Ollama call is made. It runs the full state machine, including
`awaiting_human`, the review transition, the 409 on a second review and the
400s, so you can write real integration tests against it with no model.
Stub runs report `"stub": true` and `"model": "stub"`.

## Timeouts

`POST /workflow` is **synchronous**: three Ollama calls in sequence, roughly
**15–40 seconds warm on CPU**. Every layer in the chain has to allow for
that, and none of them says "timeout" when it gives up:

1. **gunicorn** kills a worker at 30s by default, and the caller just sees
   the connection drop, usually as the Reviewer starts. `run.sh` sets
   `--timeout 180`.
2. **Each agent's Ollama call** has its own timeout (`AGENT_TIMEOUT_SECONDS`,
   55s), so one hung agent fails that phase with a 503 instead of the
   worker being killed mid-run. 3 × 55s stays inside gunicorn's 180s.
3. **Your client needs its own long timeout.** Keep it separate from the
   short timeouts you use for MCP and RAG:

   ```python
   requests.post(f"{MULTI_AGENT_URL}/workflow", json=body, timeout=(5, 190))
   ```

   A (connect, read) tuple fails fast when the server is down and waits
   long enough when it is busy. A read timeout above 180s lets the server's
   own 503 reach you before your client gives up.

### Cold model

The first call after Ollama loads a model adds roughly **100 seconds**, which
on its own is enough to break the timeout chain above. Warm the model before
a demo or test run:

```bash
ollama run "$OLLAMA_MODEL" "ready" >/dev/null
```

Ollama unloads an idle model after 5 minutes by default. Set
`OLLAMA_KEEP_ALIVE=30m` on the host's Ollama to keep it loaded through a
demo.

## Process model

Runs are held in memory, so `run.sh` starts **one** gunicorn worker with
eight threads. The single worker means every request for a run reaches the
process that holds it. The threads let `GET /workflow/<id>` answer while a
`POST /workflow` is blocked.

## Tests

```bash
pip install -r requirements.txt
python -m pytest multi-agent-server/tests
```

No test touches the network: `conftest.py` blocks every socket connection,
and the suite runs against the stub agents. That is how CI runs it.
