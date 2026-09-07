# AI mode — the shared Ollama service

Every LLM call in this project goes to one Ollama container shared by all five
students' backends. This file documents that service exactly as the repository
defines it. Everything below is quoted from the root `docker-compose.yml`,
`.env`, `.env.example` and `joshua/backend/llm.py`.

## The `ollama` service

Declared in the root `docker-compose.yml` under `services:`:

```yaml
ollama:
  image: ollama/ollama:latest
  container_name: asd-ollama
  restart: unless-stopped
  ports:
    - "11434:11434"
  volumes:
    - ollama-models:/root/.ollama
  healthcheck:
    test: ["CMD", "ollama", "list"]
    interval: 10s
    timeout: 5s
    retries: 12
    start_period: 30s
```

| Property | Value |
|---|---|
| Image | `ollama/ollama:latest` — a floating tag, not pinned to a version |
| Container name | `asd-ollama` |
| Port | `11434:11434` — reachable as `http://localhost:11434` from the host and `http://ollama:11434` from inside the compose network |
| Volume | named volume `ollama-models` mounted at `/root/.ollama` |
| Healthcheck | runs `ollama list` every 10s, 5s timeout, 12 retries, 30s start period |
| Restart policy | `unless-stopped` |

The port range table at the top of `docker-compose.yml` records `11434` as
shared infrastructure, outside every student's allocated 80xx block.

## Environment variables

### `OLLAMA_BASE_URL`

The base URL of the Ollama service. `docker-compose.yml` sets it to
`http://ollama:11434` — the service name on the compose network, not
`localhost` — for `joshua-backend`, `enerel-backend` and `hyunwoo-backend`.

Two other services name the same endpoint under different variable names:
`maxwell-backend` reads `OLLAMA_HOST`, and `thomas-backend` reads
`OLLAMA_URL`. All three point at `http://ollama:11434`.

### `OLLAMA_MODEL`

The model tag to generate with. In `docker-compose.yml` it is written as:

```yaml
OLLAMA_MODEL: ${OLLAMA_MODEL:-qwen2.5:0.5b}
```

so the value comes from `.env` if present, and falls back to `qwen2.5:0.5b`
if it is not. That fallback means the stack still comes up on a fresh clone
with no `.env`.

### Where they are read

`joshua/backend/llm.py` reads both at **module import time**, not per request:

```python
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
```

The practical consequence: **changing the model requires restarting the
container.** Setting the variable on a running container has no effect,
because the module-level read already happened at start-up. The host-side
default is `http://localhost:11434`, which is what makes the module usable
outside Docker; inside the container compose supplies `http://ollama:11434`.

This is different from `DRIFT_THRESHOLD_PERCENT`, which
`joshua/backend/drift.py` deliberately reads at call time instead.

## Model selection

The repository default is **`qwen2.5:0.5b`** (~400 MB), set in `.env` at the
repository root:

```
OLLAMA_MODEL=qwen2.5:0.5b
DRIFT_THRESHOLD_PERCENT=5
```

Those two lines are the entire non-comment content of `.env`. `.env.example`
documents two further variables — `OLLAMA_EMBED_MODEL` (default
`nomic-embed-text`, used by Enerel's backend for embeddings) and
`OLLAMA_HOST` — that the current `.env` does not set; both fall back to the
`:-` defaults in `docker-compose.yml`.

`.env.example` describes **`llama3.1:8b`** (~4.9 GB) as the higher-quality
option for the demo.

### llama3.1:8b is not a committed default

`llama3.1:8b` is **not** set as a default anywhere that is committed. It is
applied per service through a `docker-compose.override.yml`, which is
gitignored (listed in `.gitignore` under `# --- Docker ---`) and therefore
never checked in:

```yaml
services:
  joshua-backend:
    environment:
      OLLAMA_MODEL: llama3.1:8b
```

This keeps the heavier model an individual, opt-in choice — one service at a
time, on one machine — rather than something every teammate and every CI run
inherits. Because `llm.py` reads the variable at import time, the container
must be recreated after writing the override:

```bash
docker compose up -d joshua-backend
```

Setting `OLLAMA_MODEL` in `.env` instead would change the model for **every**
student's backend at once, since all of them interpolate the same variable.

There is no committed `docker-compose.override.yml` in this repository.

## Pulling a model into the container

**Models must be pulled into the container, not onto the host.** The model
store is the named volume `ollama-models` mounted at `/root/.ollama` inside
`asd-ollama`. A model pulled by an Ollama installed on the host lands in the
host's own store, which that volume does not include, so the container cannot
see it. The comment in `docker-compose.yml` states this directly: "Models are
NOT shared with a host Ollama install."

```bash
docker compose exec ollama ollama pull qwen2.5:0.5b
docker compose exec ollama ollama pull llama3.1:8b
```

To list what the container currently holds:

```bash
docker compose exec ollama ollama list
```

Because `ollama-models` is a named volume, pulled models survive
`docker compose down` and restarts. They are removed only if the volume itself
is deleted (for example `docker compose down -v`).

### If a model has not been pulled

`joshua/backend/llm.py` treats Ollama answering `404` as its own case,
separate from an unreachable service, and raises `LLMUnavailableError` naming
the missing tag and the exact pull command. The API surfaces this as a `503`
rather than a generic failure, and the rest of the application keeps working:
only `/api/insights` and `/api/drift-review` depend on the model.

## Notes on what is not configured

- The image tag is `latest`, not pinned to a version.
- No GPU reservation is declared; the service runs on CPU as configured.
- No model is pre-pulled by the compose file or by any Dockerfile. A fresh
  environment has an empty model store until someone runs `ollama pull`
  inside the container.
- Of the five students' CI workflows, only `maxwell-ci.yml` starts Ollama and
  pulls a model. `joshua-ci.yml`, `enerel-ci.yml` and `hyunwoo-ci.yml`
  deliberately point `OLLAMA_BASE_URL` at the dead port `http://127.0.0.1:1`
  so that any test attempting a real call fails fast; `thomas-ci.yml` runs no
  tests.
