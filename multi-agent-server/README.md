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

## How the real agents work

The prompts live in `prompts/` (`planner.txt`, `worker.txt`,
`reviewer.txt`). Each agent makes one Ollama call to `/api/generate`, and
the model only writes words. Python owns everything structural:

- **Planner** answers in JSON. Python numbers the steps itself, caps them
  at 8, and keeps only evidence keys you actually sent. A field reference
  like `"goal.saved"` maps back to `goal`; an invented key is dropped.
- **Worker** writes plain text, one `Step N:` paragraph per step.
- **Reviewer** answers in JSON with `risks` and `recommendations`.

A Planner or Reviewer reply that is not usable is retried once, then
replaced by deterministic output: the one-step-per-key plan, or a review
that says no model reviewed the work. A bad answer is never a 503; only
Ollama being unreachable, missing the model, or timing out is. Both
attempts share the agent's one `AGENT_TIMEOUT_SECONDS` budget, and each
reply is capped at 768 tokens, so a runaway reply cannot overrun the
timeout chain.

**Two Python checks guard the arithmetic rule.** Their findings go first
in `review.risks`, ahead of anything the Reviewer said:

- `Figure check:` names any number in the work that appears nowhere in the
  task or evidence (compared by value, so `12.50` matches `12.5`).
- `Arithmetic check:` names any calculation the work writes out
  (`5000.0 - 3200.0 = 1800.0`), even when every figure in it was supplied.

Neither check judges meaning. A sentence with the right figures and the
wrong reasoning passes. The Reviewer is a model too and can be wrong about
the evidence (in testing it claimed a supplied figure was missing), which
is why the human gate decides, not the Reviewer.

Each phase's audit record (prompt, raw reply, every attempt, whether the
fallback was used, and the checks' findings) is kept with the run but
never returned by the API.

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

### Model speed

Measured warm on a development laptop: `qwen2.5:0.5b` finished whole runs
in 2–8 seconds. `llama3.1:8b`, with only part of the model fitting in GPU
memory, generated about 3.6 tokens a second. One Worker reply took longer
than 55s, and a full run took 121s with `AGENT_TIMEOUT_SECONDS=300`. On
hardware like that, the 8b model does not fit the default timeout chain.
Check a machine's speed before relying on it (`ollama run llama3.1:8b
--verbose` prints the eval rate).

**This server is demoed on `qwen2.5:0.5b`.** The demo laptop (RTX 3050,
4GB) runs `llama3.1:8b` at 3.6–4.6 tokens a second, and a smaller context
does not change that. The 0.5b model's weaker output is what the Figure and
Arithmetic checks and the human gate are there to catch. This is an
exception to CLAUDE.md's "demo on `llama3.1:8b`" for this server only.

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
