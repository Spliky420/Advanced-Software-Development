# RAG integration — the contract joshua/backend codes against

`joshua/backend/rag_client.py` calls the team's RAG server (`rag-server/`,
merged to `main` in PR #24, `bd07a5a`). The client is tested against a stub
that follows the contract below, not against the real server. **If the server
changes any of this, `joshua/tests/test_rag_client.py` still passes (it uses
the stub) but the live integration breaks.** Please update this file and the
stub in that test.

## Deployment: host-run, not a compose service

The Release 1 brief makes the **MCP server, RAG server, AI-Mode and agentic
loop non-containerised by design**. They run on the host and must not be
docker-compose services. So the RAG server is started on the host (port
5003), and `joshua-backend`, which does run in compose, reaches it through
Docker's host alias.

| Setting | Default | Notes |
|---|---|---|
| `RAG_SERVER_URL` | `http://host.docker.internal:5003` | The host, from inside the container. Set to an empty string to switch RAG off (CI does this). |
| `RAG_TIMEOUT_SECONDS` | `5` | Per request. |

`host.docker.internal` resolves by default on Docker Desktop (Windows and
macOS). On Linux, the `joshua-backend` service also needs
`extra_hosts: ["host.docker.internal:host-gateway"]`.

When nobody has started the RAG server, the drift review still returns 200.
It reports the server as `unavailable` / `unreachable` and treats the context
as insufficient (see below).

## Endpoints

All bodies are JSON.

### `POST /retrieve` — the endpoint the drift review uses

Request (both `k` and `top_k` are sent: the RAG server reads `k`, the MCP
server's `document_search` uses `top_k`):

```json
{"query": "Portfolio allocation drift: ETFs overweight.", "k": 3, "top_k": 3}
```

Response `200`:

```json
{"status": "success", "query": "...", "k": 3,
 "results": [{"rank": 1, "chunk_id": "...", "source_id": "...", "text": "...", "distance": 0.42}]}
```

Relied on: `results` is a list, and each entry has a non-empty `text`.
Entries without one are dropped. `rank`, `chunk_id`, `source_id` and
`distance` are passed through as given.

**`distance` is opaque.** The client never sorts, inverts or thresholds on it.
Results keep the server's order. So switching from L2 to cosine, or to
similarity rather than distance, breaks nothing here, but the server must
return results best first.

### `POST /answer` — implemented in the client, not used by the feature yet

Same request body. Response `200`: `{"answer": str, "citations": [{"chunk_id", "source_id"}], "confidence_category": str}`.
Relied on: `answer` is a string. The server makes its own LLM call here, so
this can take longer than `RAG_TIMEOUT_SECONDS`.

### `GET /health`

Response `200`: `{"status": "ok", ...}`. Any other `status` counts as unhealthy.

## Errors

Every client result carries a `status` of `ok`, `disabled`, `unreachable`,
`timeout` or `error`. The client never raises.

| Server behaviour | Client `status` | Error text |
|---|---|---|
| `RAG_SERVER_URL` is empty | `disabled` | `RAG is disabled ...` |
| Connection refused / DNS failure | `unreachable` | `could not reach RAG server ...` |
| No response within the timeout | `timeout` | `did not respond within Ns` |
| HTTP 500 `{"status": "error", "error": "..."}` | `error` | `RAG server returned 500: ...` |
| Any other non-200, a 200 with `"status": "error"`, a non-JSON body, or no `results` list | `error` | describes which |

## Relevance and insufficient context

The server always returns its top `k` results, however poor the match, so the
drift review filters them before they reach the prompt. **A passage is kept
only if it mentions a breached asset class** (e.g. "ETF", "equit", "bond") or
a general allocation concept ("rebalanc", "diversif", "asset allocation").
This is a word match in `drift.RELEVANCE_PATTERNS_BY_ASSET_CLASS`, never the
distance. Kept passages stay in server order, and dropped ones are listed in
the response.

`context.retrieval.status` in the `/api/drift-review` response:

| Status | Meaning |
|---|---|
| `found` | At least one relevant passage was sent to the model. |
| `insufficient_context` | The server answered, but nothing it returned was about the breached asset classes (or it returned nothing). |
| `unavailable` | The server could not be used. `failure` says `unreachable`, `timeout` or `error`. |
| `disabled` | `RAG_SERVER_URL` is empty. |

When neither RAG nor the MCP glossary produced anything relevant,
`context.insufficient_context` is `true` and `context.insufficient_reason`
names the cause. ADAPT then sends the model an explicit
"no reference material, state the figures only" notice instead of a reference
block. The response has `adapt.context_status: "insufficient_context"` and no
citations, and the UI shows an "Insufficient context" banner.

## How the drift review uses retrieved text

- Relevant passages go into the ADAPT prompt under a `REFERENCE MATERIAL`
  heading, for wording only. Portfolio figures are in a separate
  `PORTFOLIO FIGURES` block and must be used verbatim.
- After generation, any number in the model's text that was not in the
  figures block rejects the text. The summary is then rebuilt in Python
  (`summary_source: "fallback"`), so no number from retrieved text can reach
  the client as a portfolio figure.
- `adapt.citations` lists the passages (then glossary definitions) that the
  summary was grounded on, in the order given. It is empty for a fallback
  summary and when context was insufficient.
