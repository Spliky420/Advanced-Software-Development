# Bills and Subscriptions Release 1

The dashboard adds access to the team's shared MCP and RAG servers through
the Bills API. Existing CRUD, summaries and the PAOA review remain available.

## Connections

| Component | Address |
| --- | --- |
| Dashboard | http://localhost:8040 |
| Bills API | http://localhost:8041 |
| Shared MCP protocol | http://localhost:8071/mcp |
| Shared RAG server | http://localhost:5003 |
| Local Ollama | http://localhost:11434 |

The containerised backend uses `host.docker.internal` to reach the host.
Running the backend directly uses `localhost` by default. Compose also adds
the host gateway mapping for Linux. MCP and RAG URLs come from server-side
configuration; clients cannot choose an arbitrary service or tool.

## Start the feature

From the repository root:

```bash
python3 -m venv /tmp/asd-release1-services
source /tmp/asd-release1-services/bin/activate
python -m pip install mcp==1.30.0 requests chromadb
docker compose up -d --build shared-frontend hyunwoo-database hyunwoo-backend hyunwoo-frontend
```

Start the shared MCP protocol in a second terminal. The launcher imports the
existing shared server and sets host URLs for the student APIs. It keeps the
server on localhost and adds Docker's host name to the allowed Host headers:

```bash
source /tmp/asd-release1-services/bin/activate
python hyunwoo/scripts/run_mcp.py
```

Start the shared RAG server in a third terminal. Its dependencies are in
`rag-server/requirements.txt`; that
file currently contains a malformed `mcpmcp==1.30.0` line, so the explicit
package install above avoids that existing issue. The HTTP server itself
needs `requests` and `chromadb`:

```bash
source /tmp/asd-release1-services/bin/activate
python hyunwoo/scripts/run_rag.py
```

The RAG launcher imports the existing shared server and pipeline, uses their
shared corpus, and refreshes a runtime index under `/tmp/asd-release1-rag` on
startup. `RAG_DATA_DIR` can select another runtime folder. This avoids changing
the checked-in Chroma files and generated corpus file. Only one shared RAG
process should run on port 5003. The new reference document is
`rag-server/corpus/HyunWoo_bills_knowledge.txt` and describes the feature's
actual behaviour, cost conversions, statuses and review rules. It does not
contain current personal bill totals. Six short `HyunWoo_provider_*.txt` files
add selected Netflix and Spotify billing and cancellation guidance, checked
against official help pages on 2 October 2026. Spotify's references use its
Australian support pages; Netflix's references cover general billing and
cancellation. No prices, promotions, fees or refund policies are included.
Each reference fits into one 80-word chunk so its source link, check date and
facts stay together. These are manually checked snapshots, not live web data.

Restart `run_rag.py` after updating the launcher code. For later document-only
updates, restart it or refresh its running runtime index:

```bash
curl -s -X POST http://localhost:5003/refresh \
  -H 'Content-Type: application/json' -d '{"caller":"hyunwoo-provider-update"}'
```

Ollama must be running on the host with the selected model available. Both
the RAG launcher and the Bills AI review read `OLLAMA_MODEL`. The RAG launcher's
`OLLAMA_BASE_URL` defaults to `http://localhost:11434`.

## New endpoints and validation

`POST /api/bills/mcp` initialises a real MCP Streamable HTTP session and calls
only the registered `bill_summary` tool. It returns its saved records and
summary as structured JSON. The tool reads the existing API and cannot create,
update, delete, pay or cancel a bill. Four Gunicorn threads allow the tool's
callback to the Bills API while its original request is waiting.

`POST /api/bills/rag` accepts a `query` of 3–500 characters and an optional
source count `k` of 1–10. It calls the shared `/retrieve` endpoint first. A
source must cover at least half of the question's non-stopword terms, with
two matching terms unless the question has only one. If none qualifies,
the endpoint returns `insufficient_context`, an empty citation list and Low
confidence without an LLM call.

For relevant context, the shared `/answer` endpoint generates the response.
Returned citations must correspond to retrieved source and chunk IDs. The
dashboard displays the relevant cited excerpts. A model response of
`Insufficient evidence.` is also displayed as insufficient context. Answers
without citations or with invented citation IDs are rejected with HTTP 503.

High confidence means a cited excerpt covers all question terms; Medium means
partial qualifying coverage. Low denotes insufficient context. These are
transparent retrieval heuristics, not probabilities or factual guarantees.
Numerical answers must match source wording. If they do not, the application
shows the original cited excerpts with `source_excerpt_fallback_used: true`.
This guard was added after a live model incorrectly explained a fortnightly
conversion. Non-numerical prose can still misinterpret a source; excerpts let
the user inspect the evidence. Retrieval uses the shared server's existing hash
embeddings, which have limited semantic quality and can miss paraphrases.

Named Netflix/Spotify questions use only the checked references for that
provider and a supported topic. Price, promotion, fee, refund and personal
credential questions return insufficient context. Trial questions require a
trial reference, rather than general paid cancellation guidance. Simple word
aliases help match wording such as "cancelled" and "cancellation".

The local RAG launcher supports an optional `source_ids` filter on `/retrieve`
and `/answer`. Chroma filters source metadata before retrieval, and the model
receives those filtered results. The filter is request-local; requests without
it keep the shared server's existing behaviour. Use this launcher for the new
provider flow, rather than starting `rag_http_server.py` directly.

Provider answer wording must match the relevant reference; otherwise the
response shows the reference body with a grounding-fallback notice. The local
model is still called through the shared RAG server. Official URLs and check
dates are attached by the backend from its source registry, not generated by
the model. This guards against invented policy claims and unsafe citation
links, but retrieval/topic matching remains heuristic and can miss questions.

## Demonstration

On http://localhost:8040:

1. Use **Check bill summary**. Inspect the displayed costs and structured result.
2. Ask **How are fortnightly bills converted to a monthly cost?**. Inspect the
   answer, confidence and source excerpt.
3. Ask **Who won the lunar football tournament?**. Expect insufficient context.
4. Verify create/edit/delete and the existing AI review still work.

For a provider-focused Release 1 demo, try:

- **How do I cancel Netflix?**
- **Will I keep my Spotify playlists after cancelling?**
- **What happens if I cancel a Spotify free trial?**
- **How can I change my Spotify billing date?**
- **What is Netflix's current price in Australia?** — insufficient context.

The provider cards show the official source link and the date checked.
They describe provider actions; the app does not perform cancellation.

Run the provider checks against the live feature with:

```bash
python hyunwoo/scripts/validate_provider_rag.py --output hyunwoo/evidence/provider-rag-live.json
```

On 2 October 2026, all six supported questions and three insufficient-context
cases passed against the running backend. Their responses are saved in
`hyunwoo/evidence/provider-rag-live.json`. All 77 tests passed under Python 3.11
with external modes disabled; the updated backend/frontend images built.
Browser checks confirmed the provider answer, source link/check date,
insufficient-context display and MCP summary. The existing API validation
script also passed after the provider update.

API examples:

```bash
curl -s -X POST http://localhost:8041/api/bills/mcp
curl -s -X POST http://localhost:8041/api/bills/rag \
  -H 'Content-Type: application/json' \
  -d '{"query":"How are fortnightly bills converted to a monthly cost?","k":5}'
curl -s -X POST http://localhost:8041/api/bills/rag \
  -H 'Content-Type: application/json' \
  -d '{"query":"Who won the lunar football tournament?","k":5}'
```

Capture the live backend checks without adding, changing or deleting bills:

```bash
python hyunwoo/scripts/validate_release1.py --output hyunwoo/evidence/release1-live.json
```

The captured run on 1 October 2026 passed health, summary, the real MCP tool,
sourced RAG, insufficient context and the existing AI review. All 46 automated
tests also passed under Python 3.11, all three feature images built, and the
three feature containers were healthy. JavaScript syntax and Compose
configuration checks passed. Browser clicks and visual layout have not been
automatically verified; capture the frontend demonstration separately.

## CI

The `hyunwoo-ci` workflow sets `AI_MODE_ENABLED`, `MCP_ENABLED` and
`RAG_ENABLED` to false, and points their URLs to an unreachable local port.
Tests replace service responses. Dedicated tests assert that disabled modes
make no network request. CI runs pytest, checks JavaScript syntax and builds
the three feature images. All HyunWoo provider reference files are included
in the workflow path filters so changing a knowledge source also validates
this feature. Tests cover provider boundaries, topic exclusions, trial
exceptions, grounding fallbacks, official-link metadata and source-filter
validation/isolation. No Chroma service or model is needed by the CI tests.

## Shared work still required

The root Compose file still defines shared Ollama and MCP containers used by
other features. The Release 1 brief requires these to run outside Compose.
Only the HyunWoo service's connection settings and dependencies were updated
here; the shared service migration needs the team owners' integration work.
This branch alone does not make the full group deployment Release 1 compliant.

The shared agentic loop currently exposes MCP validation but no RAG mode.
The team must add and capture both required modes. The shared RAG owner's
retrieval quality and dependency-file issue should also be addressed.
Successful GitHub workflow evidence must be collected after
the user commits and pushes this branch.
