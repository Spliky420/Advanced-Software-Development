# Pull requests to shared files — Release 1

`docker-compose.yml`, `rag-server/` and `mcp-server/` are shared files and
directories: changes to them go through a pull request, never a direct commit
(CLAUDE.md). This document holds every change Release 1 of Goals and Budgeting
needs from outside `LeHoaLong/`, as a diff ready to raise.

Nothing here is applied. The feature works without PRs 2–4 — it degrades and
says so — but PR 2 and PR 4 materially change how trustworthy the grounded
answers are, and the evidence for each is below.

| PR | File | What | Blocking? |
| -- | ---- | ---- | --------- |
| 1 | `docker-compose.yml` | My backend needs to reach two host processes | Yes, for the containerised run |
| 2 | `rag-server/rag_pipeline.py` | Read the Ollama URL and model from the environment | Not blocking, but answers are untrustworthy without it |
| 3 | `rag-server/rag_pipeline.py` | The first question after a cold start always fails | No — workaround below |
| 4 | `rag-server/rag_pipeline.py` | 224 of 256 embedding dimensions are always zero | No, but retrieval ranking is near-random without it |
| 5 | `rag-server/corpus/` | My corpus contribution (a new file, already written) | Yes, for grounded answers about my feature |
| 6 | `docker-compose.yml` | Give the `ollama` service the GPU; it is CPU-only today | No, but every AI endpoint in the project is ~15x slower without it |

---

## PR 1 — `docker-compose.yml`: let my backend reach the host-run servers

**Why.** The MCP and RAG servers are host processes (the Release 1 brief
requires them not to be containerised). My backend runs in a container, so it
cannot reach them on `localhost` — inside a container that is the container.
On Docker Desktop the host is `host.docker.internal`; `extra_hosts` makes the
same name work on Linux, where it is not defined by default.

The defaults in `config.py` already point at `host.docker.internal`, so the
environment entries below are not strictly required — they are there so the
compose file states the dependency rather than hiding it in Python, which is
how the rest of my block is written.

```diff
   lehoalong-backend:
     build: ./LeHoaLong/backend
     container_name: lehoalong-backend
     restart: unless-stopped
     ports:
       - "8061:5000"
+    # The MCP and RAG servers are HOST processes, not containers (Release 1
+    # brief). A container reaches the host at host.docker.internal on Docker
+    # Desktop; this mapping makes the same name resolve on Linux, where it is
+    # not built in.
+    extra_hosts:
+      - "host.docker.internal:host-gateway"
     environment:
       DB_PATH: /data/goals.db
       OLLAMA_BASE_URL: http://ollama:11434
       OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:0.5b}
+      # Release 1. Both are optional at runtime: if either server is absent,
+      # the feature falls back to its Release 0 behaviour and says so in the
+      # response. Set MCP_ENABLED/RAG_ENABLED to false to switch them off.
+      MCP_ENABLED: ${LEHOALONG_MCP_ENABLED:-true}
+      MCP_SERVER_URL: ${LEHOALONG_MCP_SERVER_URL:-http://host.docker.internal:5002/mcp}
+      RAG_ENABLED: ${LEHOALONG_RAG_ENABLED:-true}
+      RAG_SERVER_URL: ${LEHOALONG_RAG_SERVER_URL:-http://host.docker.internal:5003}
       # Only used by `npm run dev`; in the container nginx makes /api
       # same-origin and this layer never fires.
       CORS_ORIGINS: http://localhost:8060,http://127.0.0.1:8060
```

**Not included on purpose.** No service is added for the MCP server, the RAG
server, AI-Mode or the agentic loop. The brief says compose keeps running the
containerised feature microservices and is not extended to cover them.

### The matching run instruction (no code change)

The MCP server relays to each student's backend using the URLs in
`mcp-server/tools.py`, which default to container hostnames. Run on the host,
it cannot resolve `http://lehoalong-backend:5000`, so the `goal_progress` tool
fails unless it is told the published port:

```bash
cd mcp-server
LEHOALONG_BACKEND_URL=http://localhost:8061 \
JOSHUA_BACKEND_URL=http://localhost:8011 \
MAXWELL_BACKEND_URL=http://localhost:8021 \
ENEREL_BACKEND_URL=http://localhost:8031 \
HYUNWOO_BACKEND_URL=http://localhost:8041 \
THOMAS_BACKEND_URL=http://localhost:8051 \
python server.py
```

`tools.py` already reads all six, so this is purely a run instruction. Verified:
without `LEHOALONG_BACKEND_URL`, `goal_progress` returns
`{"error": "Could not reach backend at http://lehoalong-backend:5000/..."}`;
with it, the tool answers.

### Discrepancy to settle as a team

`docker-compose.yml` currently contains a **containerised** `mcp-server`
service publishing 8070 and 8071, and `mcp-server/` has a `Dockerfile` and an
`entrypoint.sh`. The Release 1 brief says the MCP server is not
containerised. Both cannot be right.

My integration does not depend on the outcome: `MCP_SERVER_URL` is an
environment variable, so pointing it at `http://mcp-server:5002/mcp` (the
container) or `http://host.docker.internal:5002/mcp` (the host process) is a
configuration change, not a code change. Nothing of theirs has been deleted.

---

## PR 2 — `rag_pipeline.py`: read the Ollama URL and model from the environment

**Why this is more than a style fix.** CLAUDE.md's rule is that the model tag
is never hardcoded, and these two lines break it. But the consequence is
concrete: the tag that is hardcoded, `qwen2.5:0.5b`, **does not obey the
grounding prompt**, and the one that does cannot be selected without editing
the file.

Measured on the development laptop, same question, same corpus, same `k`,
asking something the corpus could not answer at the time:

| Model | Time | Answer |
| ----- | ---- | ------ |
| `qwen2.5:0.5b` (hardcoded) | 1.5s | Four invented paragraphs, including a worked example the prompt explicitly forbids — with citations attached to two chunks about tax deductions |
| `llama3.1:8b` (the team's demo model) | 68.6s | `Insufficient evidence.` |

Both models were already pulled on the host. The 0.5b model produced a
confidently wrong answer *with citations*, which is worse than no answer: the
citations make it look sourced. The team's demo model behaves correctly and
cannot be chosen, because `.env` has no effect on this file.

```diff
+import os
 import json
 import hashlib
 from pathlib import Path

 import chromadb
 import requests


 BASE_DIR = Path(__file__).resolve().parent
 CORPUS_DIR = BASE_DIR / "corpus"
 CHROMA_DIR = BASE_DIR / "chroma"
 CORPUS_JSON = CORPUS_DIR / "corpus.jsonl"

 COLLECTION_NAME = "personal_finance_context"
 EMBED_SIZE = 256

-OLLAMA_URL = "http://localhost:11434/api/generate"
-OLLAMA_MODEL = "qwen2.5:0.5b"
+# Read from the environment, never hardcoded (CLAUDE.md). The defaults are the
+# values this file used to hardcode, so a run with no environment set behaves
+# exactly as before.
+#
+# OLLAMA_BASE_URL is the name every student's backend already uses, so one
+# .env switches the whole stack. This server runs as a host process, so its
+# default is localhost rather than the compose service name.
+OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
+OLLAMA_URL = os.environ.get("OLLAMA_URL") or f"{OLLAMA_BASE_URL}/api/generate"
+OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
```

No other line changes: `answer_question` already reads both constants.

**How to verify after merging.**

```bash
OLLAMA_MODEL=llama3.1:8b python rag_http_server.py
curl -s -X POST localhost:5003/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the capital of France?","k":5}' | python -m json.tool
# expect: "answer": "Insufficient evidence."
```

**Until it merges**, my README records it as a known limitation: grounded
answers are produced by whichever model that file names, my backend cannot
influence it, and `ai_plan_log` records `model_name = 'rag-server'` rather
than a tag, because reporting the tag my service happens to have configured
would be a guess.

---

## PR 3 — `rag_pipeline.py`: the first question after a cold start always fails

**Why.** `retrieve_context` takes a handle to the collection, notices it is
empty, and calls `refresh_corpus()` — which *deletes and recreates* the
collection — then queries the handle it took before the delete.

Observed on a clean checkout, through my backend, on the very first request:

```
RAGUnavailable -> the RAG server could not answer:
  Error getting collection: Collection [730f7243-0e47-4e87-af81-6e6630c1cd75] does not exist.
```

The second request succeeds, because by then the module-level cache holds the
new collection and the count is non-zero. So the only request that fails is
the first one after a fresh start — which is the one a marker is most likely
to watch.

```diff
 def retrieve_context(query, k=5, caller="student"):

     collection = get_collection()

     if collection.count() == 0:
         refresh_corpus("auto_refresh")
+        # refresh_corpus deleted and recreated the collection, so the handle
+        # taken above now points at a collection that no longer exists.
+        collection = get_collection()

     results = collection.query(
         query_embeddings=embed_texts([query]),
         n_results=k
     )
```

**Workaround until it merges:** make one throwaway request (or
`curl -X POST localhost:5003/refresh`) after starting the server. That is in
my demo script as a pre-flight step regardless, because the corpus has to be
refreshed after my file is added anyway.

---

## PR 4 — `rag_pipeline.py`: 224 of 256 embedding dimensions are always zero

**Why.** `embed_texts` builds a 256-dimension vector, then writes the 32 bytes
of each token's sha256 digest into `vector[i % EMBED_SIZE]` for `i` in `0..31`.
With only 32 bytes, `i % 256` never exceeds 31, so **dimensions 32–255 are
always zero** and the embedding is effectively 32-dimensional. Each token adds
a value in `[-0.5, 0.5]` to every one of those 32 dimensions, so an 80-word
chunk is the sum of ~80 random vectors and converges on the mean rather than
on anything about its words.

The effect is that ranking is only loosely related to word overlap. For the
question `POST /api/goals/<id>/explain` asks about a goal that is behind:

```
 1. d=0.8600  ...knowledge_2   "A contribution is money recorded..."   6 shared tokens
 ...
10. d=1.0301  ...knowledge_10  "A savings goal is behind when..."     12 shared tokens
```

The chunk that *defines* the word in the question, sharing twice as many
tokens as the winner, ranks tenth of seventeen.

The fix is the standard hashing vectoriser: hash each token to one dimension
and count it, so the vector is a sparse term-frequency profile and cosine
distance measures real overlap.

```diff
 def embed_texts(texts):
     vectors = []

     for text in texts:
         vector = [0.0] * EMBED_SIZE

         for token in text.lower().split():
-            digest = hashlib.sha256(token.encode()).digest()
-
-            for i, byte in enumerate(digest):
-                vector[i % EMBED_SIZE] += (byte / 255.0) - 0.5
+            # Hash each token to ONE dimension and count it: a sparse term
+            # frequency profile, so cosine distance measures word overlap.
+            #
+            # The previous version added all 32 sha256 bytes into dimensions
+            # 0..31 (i % 256 never exceeds 31 with a 32-byte digest), leaving
+            # 224 dimensions always zero and making a long chunk the sum of
+            # many random vectors.
+            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
+            vector[index % EMBED_SIZE] += 1.0

         norm = sum(x * x for x in vector) ** 0.5

         if norm:
             vector = [x / norm for x in vector]

         vectors.append(vector)

     return vectors
```

**Measured.** Over the nine questions my feature asks, counting whether the
fact needed to answer is present in the `k=5` context the model is given
(`/answer` concatenates every retrieved chunk into the prompt, so presence
matters more than rank):

| Corpus and embedding | Key facts retrieved |
| -------------------- | ------------------- |
| Unaligned prose, current embedding | 10/15 |
| Window-aligned corpus, current embedding | 13/15 |
| Window-aligned corpus, this fix | **15/15** |

**Caveat to state when raising it.** The stored vectors change, so the Chroma
collection has to be rebuilt: `curl -X POST localhost:5003/refresh` after
merging, or delete `rag-server/chroma/`. Every student's retrieval results
change, which is why this is a PR and a team decision rather than something I
would apply quietly.

---

## PR 5 — `rag-server/corpus/`: my corpus contribution

**One new file**, `rag-server/corpus/LeHoaLong_goals_budgeting_knowledge.txt`
(1,360 words). Nothing else in `rag-server/` is touched.

> Adds the Goals and Budgeting knowledge file to the shared corpus: savings
> goal definitions, goal prioritisation, emergency funds, target-date planning
> and contribution scheduling, what on-track / behind / ahead / achieved mean,
> budget allocation across competing goals, and how recurring bills reduce the
> amount available to save. Plain declarative facts in the same style as the
> existing file, so the grounding rules never need to infer anything. Run
> `POST /refresh` after merging so the new chunks are indexed.

Two things about its shape are deliberate and are documented in
`LeHoaLong/tools/build_corpus.py`, which regenerates it:

* **Topics are aligned to the 80-word chunk window.** `chunk_text` splits the
  whole file's words into consecutive 80-word groups with no regard for
  sentences, so a topic that does not begin on a multiple of 80 is blended
  into its neighbour's chunk. Each topic block is padded to an exact multiple
  of 80 words with further true facts, so every chunk is one topic.
* **Each progress status gets its own chunk.** The `/explain` question for a
  goal that is behind asks both what "behind" means and what to do about it,
  so the definition and the remedy have to share a chunk; in a two-chunk block
  they land either side of the boundary.

After merging:

```bash
curl -X POST localhost:5003/refresh    # 17 new chunks, ids LeHoaLong_goals_budgeting_knowledge_1..17
```

**Two generated artefacts change when that runs**, and both are worth a line
in the PR so nobody is surprised by a dirty working tree:

* `rag-server/corpus/corpus.jsonl` is tracked and is rewritten by every
  `/refresh`. After this file is added it holds 19 chunks (17 mine, 2
  Thomas's) instead of 2. Either commit the regenerated file with the PR, or
  add it to `.gitignore` -- it is derived from the `.txt` files beside it and
  nothing reads it back.
* `rag-server/chroma/` is the Chroma index and is created on first use. It is
  not in `.gitignore` today, so it shows up as untracked for anyone who runs
  the server. Worth adding.

**Corpus balance, worth raising with the team.** This file is 17 chunks
against the existing file's 2, so it dominates retrieval for any question —
including questions it cannot answer. That is not a problem with the file; it
is what happens when one feature has contributed and the others have not yet.
It also interacts with the confidence category: the shared server reads three
or more retrieved chunks as `High`, so a larger corpus makes every answer read
`High` regardless of relevance. Noted in my known issues rather than worked
around, because the category is the shared server's to define.

---

## PR 6 — `docker-compose.yml`: give the `ollama` service the GPU

**Why.** The shared `ollama` service has no device reservation, so it runs on
the CPU even on a machine with a working NVIDIA GPU. This is not a small
difference, and it affects every student's AI endpoints, not just mine.

Measured on the development laptop (RTX 3050 Laptop, 4GB, driver 596.36),
`qwen2.5:0.5b`, same corpus, same question:

| | Generation rate | A grounded answer | A plan |
| --- | --- | --- | --- |
| `ollama` container as configured today (CPU) | 20.5 tok/s | 23.5s | ~20s |
| The same container with `--gpus all` | 172.0 tok/s | **1.0s** | **1.3s** |

Fifteen times faster at generating, and the difference between a demo that
fits in a 100 second slot and one that does not. GPU passthrough was verified
to work on this machine before proposing it:

```
$ docker run --rm --gpus all --entrypoint nvidia-smi ollama/ollama:latest \
    --query-gpu=name,memory.total --format=csv,noheader
NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB
```

```diff
   ollama:
     image: ollama/ollama:latest
     container_name: asd-ollama
     restart: unless-stopped
     ports:
       - "11434:11434"
+    # Use an NVIDIA GPU when the host has one. Measured on an RTX 3050:
+    # 20.5 tok/s on the CPU against 172 tok/s on the GPU with qwen2.5:0.5b,
+    # which is the difference between a 23 second grounded answer and a one
+    # second one.
+    #
+    # `count: all` with `capabilities: [gpu]` is a no-op on a machine with no
+    # NVIDIA runtime -- compose logs a warning and the container starts on the
+    # CPU as it does today -- so this is safe for teammates without one.
+    deploy:
+      resources:
+        reservations:
+          devices:
+            - driver: nvidia
+              count: all
+              capabilities: [gpu]
     volumes:
```

**Caveats to raise with it.**

* `deploy.resources` needs Docker Compose v2 (`docker compose`, not
  `docker-compose`), which the project already uses.
* A teammate on a machine with no NVIDIA GPU, or on Docker Desktop without
  the WSL2 backend, gets a warning and a CPU container — the same behaviour as
  today, so nobody is worse off. Worth confirming on at least one other
  laptop before merging.
* 4GB of VRAM holds `qwen2.5:0.5b` comfortably. `llama3.1:8b` is 4.9GB and
  will partly spill to the CPU, so it stays slower than the small model even
  with this merged.

### The interim workaround, no file change needed

Until it merges, the same effect can be had by running Ollama yourself and
attaching it to the compose network under the name the other services expect:

```bash
docker compose stop ollama
docker run -d --name asd-ollama-gpu --gpus all \
  --network asd2026_default --network-alias ollama \
  -v asd2026_ollama-models:/root/.ollama -p 11434:11434 \
  ollama/ollama:latest
```

The `--network-alias ollama` is the part that matters: every backend's
`OLLAMA_BASE_URL` is `http://ollama:11434`, and without the alias they get a
clean 503 while the host-run RAG server (which uses `localhost:11434`, the
published port) carries on working — a confusing half-broken state, verified
while measuring the above.
