# Bills and Subscriptions Release 2

The Bills dashboard now connects to the existing shared Multi-Agent Server.
The backend builds a snapshot of the user's bills, cost totals, due-date
findings and first priority in Python. The shared Planner, Worker and
Reviewer use this evidence. The dashboard shows their original outputs,
the evidence and the human decision.

Approval is advisory. It never pays, cancels, updates or deletes a bill.
The existing CRUD, summary, AI review, MCP and RAG routes remain available.

## Configuration

The Bills backend reads:

| Variable | Purpose |
| --- | --- |
| MULTI_AGENT_ENABLED | Explicitly enables the new routes. Defaults to false outside local Compose. |
| MULTI_AGENT_URL | Shared server address. Direct host execution defaults to http://localhost:5004. |

Only the HyunWoo backend's Compose settings were extended. Local Compose
enables the new mode and uses http://host.docker.internal:5004. The shared
server is not added to Compose. CI explicitly disables the new mode.
For the required cloud baseline, set this flag to false alongside
AI_MODE_ENABLED, MCP_ENABLED and RAG_ENABLED; keep ordinary Bills CRUD enabled.

The backend waits up to 190 seconds for the shared server after connecting.
Its Gunicorn timeout is 240 seconds and the browser waits up to 210 seconds.
These allow the shared server's three agent calls and its own timeout to finish.

## Run locally

Keep the existing integrated application and host AI services running.
Create a separate environment for the shared Multi-Agent Server:

```bash
python3 -m venv /tmp/hyunwoo-multi-agent-env
source /tmp/hyunwoo-multi-agent-env/bin/activate
python -m pip install -r multi-agent-server/requirements.txt
```

For initial wiring checks:

```bash
STUB_AGENTS=true ./multi-agent-server/run.sh
```

Leave that terminal open. Stub mode is clearly labelled in the dashboard
and does not count as evidence that a real model reviewed the bills.

For the actual AI demonstration, stop that process with Ctrl-C, ensure
host Ollama and the selected OLLAMA_MODEL are available, then run:

```bash
STUB_AGENTS=false ./multi-agent-server/run.sh
```

In another terminal, rebuild only the Bills services:

```bash
docker compose up -d --build hyunwoo-database hyunwoo-backend hyunwoo-frontend
```

Existing bill volumes are not reset. The backend creates the review-link
table when needed, so existing databases work without reseeding.

Open http://localhost:8040 and scroll to **Multi-Agent review**:

1. Choose a review date and a 1–90 day window.
2. Start the review and wait for all three agents.
3. Read the plan, draft, risks, recommendations and original bill evidence.
4. Choose Approve, Correct, Accept part, or Reject.
5. Supply corrected text for a correction, or a note for partial acceptance.
6. Save the decision. Refresh the page and reopen it under Saved reviews.

The saved evidence stays unchanged if bills are edited later.
Each active bill appears once, with its calculated flags. Alert counts
and the first priority are calculated in Python, not inferred by a model.

## Backend routes

| Method and path | Purpose |
| --- | --- |
| POST /api/bills/workflows | Starts a review using saved Bills data and returns 201. |
| GET /api/bills/workflows | Lists the user's latest 20 saved review links. |
| GET /api/bills/workflows/{run_id} | Reads an owned review and its original evidence. |
| POST /api/bills/workflows/{run_id}/review | Records the human decision through the shared server. |

The client supplies only the review date/window and human decision fields.
It cannot replace the task, evidence, caller or reviewer. Unknown reviews
and reviews not linked to the current Bills user return 404 before any
request is sent to the shared server.

The bill_workflows table holds each run ID, user ID and evidence snapshot.
The shared server owns the phases, decisions and append-only audit history.
A second decision is rejected with 409. A failed shared-server request
returns 503, while core Bills APIs remain usable. If a failed run ID is
returned, its link is retained so it can be inspected.

This retains the project's existing single-user model. It does not add
authentication or make the shared server safe to expose publicly.
Use one shared server process and preserve its history file.

## Validation and evidence

Run the offline Bills tests:

```bash
python -m pytest hyunwoo/tests -v
```

The new tests cover period/decision validation, supplied evidence, disabled
and unavailable services, invalid server responses, user boundaries,
snapshot persistence, all four human decisions and repeat-decision errors.
They do not contact a real model.

To start a review from the terminal without making a human decision:

```bash
python hyunwoo/scripts/validate_multi_agent.py --review-date 2026-09-01
```

Record the decision in the dashboard. Then capture the completed result
using the printed run ID:

```bash
python hyunwoo/scripts/validate_multi_agent.py \
  --run-id REPLACE_WITH_RUN_ID --require-complete \
  --output hyunwoo/evidence/release2-multi-agent-live.json
```

The script reports whether it used stub agents. For showcase evidence,
capture a real-agent run, its original evidence, the human decision and
the matching events in the shared server's workflow_history.jsonl.
That shared audit file includes the prompts, model replies and fallback
details that are intentionally not exposed by the public API.

## Limits and remaining Release 2 work

Model output can misinterpret correct figures. The shared Reviewer's checks
flag unsupplied numbers and written arithmetic but do not prove the advice
is correct. A human must review it.

Workflow creation is synchronous. If a connection drops before the server
returns a run ID, the remote run may exist without a local Bills link.
Inspect the shared audit history before retrying; do not assume it failed.
If the shared history file is lost or replaced, old local review links may
return 404.

Local development checks are recorded in evidence/release2-validation.md.
The successful real-model check is awaiting human review; it is not a
completed, human-approved showcase run.

This change does not implement the group's cloud deployment, security
pre-commit hooks or the three Release 2 agentic-loop review modes.
Live Docker builds, real-model demonstration, GitHub Actions execution
and final evidence capture must be verified in the integrated environment.
