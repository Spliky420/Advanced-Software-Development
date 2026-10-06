# Week 9 demo script — Goals and Budgeting (Release 1)

A ~100 second segment. Three things have to be on screen, because they are the
marked requirements:

1. the feature working,
2. MCP pulling real context from **another student's** feature,
3. a grounded answer with its **citations and confidence category visible**.

Everything else is narration over those three.

Every duration below was measured on the development laptop with the model
warm. Cold, they are ten times worse — see the pre-flight, which exists
entirely to avoid that.

---

## Pre-flight — do all of this before you hit record

### 1. Rebuild the backend image

`requirements.txt` gained `mcp==1.30.0` in Release 1. A container built before
that will answer every MCP call with a 503 that says "add mcp to
requirements.txt and rebuild the image" — correct behaviour, wrong thing to
have on camera.

```bash
docker compose build lehoalong-backend
docker compose up -d lehoalong-database lehoalong-backend lehoalong-frontend
```

### 2. Bring up the two teammates' backends that MCP reads

```bash
docker compose up -d hyunwoo-backend thomas-backend
```

**This matters.** The whole point of beat 3 is that the bills figure comes from
somebody else's service. If their containers are down, the feature degrades
correctly and says "MCP unavailable, using budget settings" — honest, but it
does not demonstrate the requirement.

There is a stand-in script used during development that serves their seeded
figures (`teammate_stub.py`, kept out of the repository). **Do not film
against it** and present the result as cross-feature integration. If their
containers will not start, film the degraded state instead and say what it is
— a graceful fallback is a real result and an honest one.

### 3. Start the two shared servers as host processes

Not containers: the Release 1 brief requires them not to be containerised, and
my backend reaches them at `host.docker.internal`.

```bash
# Terminal 1 -- MCP. The env vars matter: run on the host, the server cannot
# resolve container hostnames like http://lehoalong-backend:5000.
cd mcp-server
LEHOALONG_BACKEND_URL=http://localhost:8061 \
HYUNWOO_BACKEND_URL=http://localhost:8041 \
THOMAS_BACKEND_URL=http://localhost:8051 \
python server.py

# Terminal 2 -- RAG
cd rag-server
python rag_http_server.py
```

### 4. Index the corpus, and get past the cold-start bug

```bash
curl -X POST localhost:5003/refresh    # needed once my corpus file is merged
```

`rag_pipeline.retrieve_context` queries a collection handle that
`refresh_corpus` has just deleted, so **the first grounded question after a
cold start always fails** (see `docs/pull-requests.md`, PR 3). The refresh
above plus the warm-up below both get you past it.

### 5. Reset the goal so the figures match this script

Do this **before** the warm-up, and before recording. Every number quoted in
the shot list below is a freshly seeded value, verified on a clean database;
generating a plan changes which instalments have fallen due, and therefore
changes `required_to_date` and the variance on the progress panel.

```bash
LEHOALONG_INIT_DB_FORCE=1 docker compose up -d --force-recreate lehoalong-database
docker compose up -d --force-recreate lehoalong-backend
```

Destructive, as the compose comment says: it discards any goal created live.
That is what you want before a demo, and nothing else.

### 6. Warm the model — the single most important step

```bash
# Load the model into memory. NOT `docker compose exec -T ollama ollama run
# ...` -- that command hangs without a TTY, which is a trap inherited from the
# Release 0 README.
curl -s http://localhost:11434/api/generate   -d '{"model":"qwen2.5:0.5b","prompt":"warm up","stream":false}' > /dev/null

# A grounded answer, which also clears the cold-start bug from step 4.
curl -s -X POST localhost:8061/api/rag/ask -H 'Content-Type: application/json'   -d '{"question":"What is an emergency fund?"}' > /dev/null

# Warm the planning path too -- on goal 2, NOT goal 3. Planning rewrites the
# pending instalments, so warming up on the goal you are about to film would
# change the figures in beat 1.
curl -s -X POST localhost:8061/api/goals/2/plan -H 'Content-Type: application/json'   -d '{"use_mcp":false}' > /dev/null
```

**What costs the time is loading the model, not generating.** Measured: the
first request after Ollama starts takes **91 seconds** while the weights load;
every request after it takes **one to two seconds**. Ollama unloads a model
after five minutes idle, so warm up within five minutes of recording, and do
it again if you stop to re-set up.

### 6b. Use the GPU, or everything is fifteen times slower

The shared compose `ollama` service has no device reservation, so it runs on
the CPU. Measured on this laptop with `qwen2.5:0.5b`:

| | Generation | Grounded answer | Plan |
| --- | --- | --- | --- |
| compose `ollama` as configured (CPU) | 20.5 tok/s | 23.5s | ~20s |
| the same image with `--gpus all` | 172 tok/s | **1.0s** | **1.3s** |

`docs/pull-requests.md` PR 6 proposes fixing this in the compose file. Until
it merges, run Ollama yourself and attach it to the compose network under the
name the other services expect:

```bash
docker compose stop ollama
docker run -d --name asd-ollama-gpu --gpus all   --network asd2026_default --network-alias ollama   -v asd2026_ollama-models:/root/.ollama -p 11434:11434   ollama/ollama:latest
```

`--network-alias ollama` is the load-bearing part. Without it every backend's
`OLLAMA_BASE_URL` of `http://ollama:11434` fails with a clean 503 while the
host-run RAG server keeps working on `localhost:11434` — a confusing
half-broken state. Then redo step 6, because this is a fresh Ollama.

### 7. Confirm the lights, and open the page

Open <http://localhost:8060> and check the header: **MCP ready** and **RAG
ready**, both green. `unreachable` means that host process is not running;
`off` means an environment variable disabled it.

Then open goal 3, **New Laptop**, and leave the browser there. The progress
panel should read exactly: saved **$450.00**, the plan expected
**$1,401.00**, difference **−$951.00**, still to save **$2,350.00**. If it
does not, step 5 did not take effect.

### Which model to use

| | `/plan` click | Grounded answer | Verdict |
| --- | --- | --- | --- |
| `qwen2.5:0.5b` | ~10s | ~7s | **Use this for a 100 second video** |
| `llama3.1:8b` | 30–70s | ~69s | Better prose, does not fit the slot |

The team default is the 0.5b model and the amounts and dates are Python's
either way, so the only thing you lose is the wording of the step
descriptions. Say so in the voice-over if you like: "the figures are
calculated in Python, the model only writes the sentences around them."

Note the RAG server currently hardcodes its own model (PR 2), so
`OLLAMA_MODEL` does **not** affect the grounded answer until that merges.

---

## The shot list

### Beat 1 — the feature, and the figures it computed itself (0:00–0:10)

**On screen:** goal 3, New Laptop. The progress panel: Behind badge, saved
$450.00, plan expected $1,401.00, difference −$951.00, still to save
$2,350.00.

> "This is my Goals and Budgeting feature. One savings goal, $2,800 by
> mid-December. Every figure on this panel is calculated in Python — the model
> never does arithmetic. Right now this goal is behind its plan."

### Beat 2 — AI-Mode: Release 0, for comparison (0:10–0:25)

**Do:** the **AI mode** panel, **AI-Mode** tab. Click **Regenerate plan**.
Wait ~2.5s.

**On screen, after:** a one-sentence summary of what changed, then the
figures: **Revised instalment $783.33** · **Available to save
−$1,074.16**, labelled *after other goals only* · **Fits the budget: no**
· **Short by, each month: $1,857.49**.

(Goal 3 is seeded with a plan already, so the button reads *Regenerate plan*
and the panel reports a revised instalment rather than a first one. One
completed instalment is preserved; only the pending ones are rebuilt.)

> "This tab is the Release 0 behaviour. Python splits what's left into
> instalments; the model writes a description for each one. It knows about my
> other savings goals — but nothing else. It thinks I'm short by about
> eighteen hundred a month."

**Point the cursor at $1,857.49 and leave it a beat.** The whole next beat is
this number changing.

### Beat 3 — MCP: the same plan, with another feature's data (0:25–0:57)

**Do:** click the **MCP** tab. Context loads in ~4s.

**On screen:** the tools table — `bill_summary` (HyunWoo — Bills and
Subscriptions) ok, ~900ms; `transaction_summary` (Thomas — Transaction Ledger)
ok, ~300ms. Then the calculation, each line naming where its figure came from:

```
+  $2,500.00   Monthly budget                    Goals and Budgeting (this service)
−  $3,574.16   Committed to other active goals   Goals and Budgeting (this service)
−    $620.24   Recurring monthly bills           bill_summary via MCP (HyunWoo)
=  −$1,694.40  Available to save each month      computed_by: python
```

> "The MCP tab asks the shared MCP server what the rest of the team already
> knows. Two tools, over one session: HyunWoo's bills service says $620.24 a
> month is already committed to electricity, internet, insurance and a gym
> membership. Thomas's ledger supplies observed income and spending. Those
> figures arrive already calculated — my feature carries them through and
> doesn't recompute them. Python then does the one subtraction."

**Do:** click **Regenerate plan with this context**. Wait ~10s.

**On screen:** **Revised instalment: still $783.33** — and **Short by,
each month: $2,477.73**. The *Available to save* label now reads *after other
goals and bills*.

> "Same instalment, same target date — MCP doesn't move those, because
> re-cutting the instalments would miss the date I asked for. What changes is
> the verdict: I'm short by $2,477.73 instead of $1,857.49. That difference is
> $620.24 — exactly HyunWoo's bills figure, pulled over MCP."

*(If you have a spare second: "and if his service is down, this falls back to
budget settings and says so on the panel.")*

### Beat 4 — RAG: a grounded answer with its sources (0:57–1:28)

**Do:** click the **RAG** tab. Click the suggestion **"What is an emergency
fund?"** (or type it). Wait ~7s.

**On screen:** the answer, the green **High confidence** badge beside the
heading, and the **Sources (5)** list showing every `source_id` and
`chunk_id` — visible without expanding anything.

> "The RAG tab answers from the team's shared knowledge corpus, not from the
> model's own knowledge. The answer comes back with a confidence category and
> five citations — the file and the exact chunk each sentence was grounded in.
> I pass both through exactly as the RAG server returned them; I don't
> recalculate the confidence, because it isn't mine to calculate."

**Do:** click **Show the retrieved text** to expand one citation.

> "And this is the text it was actually grounded in — from the corpus file my
> feature contributed."

### Beat 5 — the audit trail (1:28–1:40)

**Do:** either expand **Show the raw MCP response** on the MCP tab, or hit
`localhost:8061/api/goals/3/ai-log` in a tab you opened earlier.

**On screen:** log entries with phases `plan`, `observe`, `adapt`, `mcp`,
`rag`.

> "Every MCP tool call and every grounded answer is written to the audit
> table, alongside the Release 0 phases — the question, the chunk ids, the
> answer and the confidence. That's the evidence trail for the report."

---

## Fallbacks, if something fails live

| It happens | Do this |
| ---------- | ------- |
| A grounded answer hangs for 30s+ | The model went cold. Stop, re-run the warm-up, restart that beat. |
| First grounded question errors | PR 3's cold-start bug. Ask it a second time; it works. |
| MCP panel says "MCP unavailable" | A teammate's container or the MCP server is down. Either fix it, or **film it deliberately** and narrate the fallback — it is a requirement in its own right. |
| MCP tab shows `transaction_summary` failed but bills worked | That is the `partial` state. Still a valid shot: the figure is still MCP's, only Thomas's context is missing. |
| The plan click 503s | Ollama is unreachable or the model was never pulled. `docker compose exec ollama ollama pull qwen2.5:0.5b`. |

## Do not film these

* **The teammate stand-in** standing in for HyunWoo's or Thomas's service
  while narrating it as cross-feature integration.
* **`/api/goals/3/explain`** as your RAG beat, until PR 4 (the embedding fix)
  merges. It works — High confidence, five citations, all audited — but the
  shared server's embedding ranks chunks almost independently of word overlap,
  so it currently retrieves the general savings-goal definitions rather than
  the paragraphs about *being behind*. The answer is grounded and true, just
  not pointedly about the question. "What is an emergency fund?" retrieves
  cleanly and is the better shot. (Worth one sentence in the written report,
  not in a 100 second video.)
* **A cold first request** of any kind.

## Timing summary

With the GPU (step 6b) and the model warm, every measured figure below is from
this stack running the real teammate backends:

| Beat | Length | Waiting on a model |
| ---- | ------ | ------------------ |
| 1 Progress panel | 10s | — |
| 2 AI-Mode plan | 15s | 1.4s |
| 3 MCP context and plan | 32s | 4.2s + 1.3s |
| 4 Grounded answer | 31s | 1.0s |
| 5 Audit trail | 12s | — |
| **Total** | **100s** | **7.9s** |

On the CPU-only container the same waits come to roughly 50 seconds, which
does not fit. That is the whole argument for PR 6.

Because the waits are now short, there is room for a sixth beat if you want
one. In order of what a marker would value:

1. **The degraded state.** Stop the MCP server, reload, and show the panel
   reading *"MCP unavailable, using budget settings"* with the Release 0
   figure restored. Graceful degradation is a requirement in its own right
   and nothing else in the video demonstrates it.
2. **`/explain`**, once PR 4 has merged — the goal's own situation, grounded,
   with the Python figures stated beside the answer.
3. **`?use_mcp=false` against the API directly**, if you would rather show the
   mechanism than the UI.
