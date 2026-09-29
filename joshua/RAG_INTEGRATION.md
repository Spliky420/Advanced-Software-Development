# RAG integration — the contract joshua/backend codes against

`joshua/backend/rag_client.py` calls the team's RAG server (`rag-server/` on
`origin/thomas-release1`, commit `0d0425c`). That server was not containerised
when this was written, so the client was built and tested against the contract
below, not against a running server. **If the server changes any of this,
`joshua/tests/test_rag_client.py` still passes (it uses a stub) but the live
integration breaks.** Please update this file and the stub in that test.

## Location

| Setting | Default | Notes |
|---|---|---|
| `RAG_SERVER_URL` | `http://rag-server:5003` | Assumes a compose service named `rag-server` on container port 5003. Set to an empty string to switch RAG off. |
| `RAG_TIMEOUT_SECONDS` | `5` | Per request. |

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

| Server behaviour | Client result |
|---|---|
| HTTP 500 `{"status": "error", "error": "..."}` | `ok: false`, error `RAG server returned 500: ...` |
| Any non-200 status | `ok: false` |
| HTTP 200 with `"status": "error"` | `ok: false` |
| Non-JSON body, or no `results` list | `ok: false` |
| No response within the timeout | `ok: false`, error `did not respond within Ns` |
| Connection refused / DNS failure | `ok: false`, error `could not reach RAG server ...` |

The client never raises for any of these. The drift review returns `200` with
`context.retrieval.status` set to `"unavailable"` and continues without
reference material.

## How the drift review uses retrieved text

- Passages go into the ADAPT prompt under a `REFERENCE MATERIAL` heading, for
  wording only. Portfolio figures are in a separate `PORTFOLIO FIGURES` block
  and must be used verbatim.
- After generation, any number in the model's text that was not in the
  figures block rejects the text. The summary is then rebuilt in Python
  (`summary_source: "fallback"`), so no number from retrieved text can reach
  the client as a portfolio figure.
- `adapt.citations` lists the passages (then glossary definitions) that the
  summary was grounded on, in the order given. It is empty for a fallback
  summary.
