# Bills integrated Release 2 check

Checked on 22 October 2026 after merging main into
HyunWoo-Bills-Subscriptions. Starting commit: 452f97e.
The student has not committed or pushed the follow-up security changes.

## Passed checks

- All three Bills Docker images built and the containers became healthy.
- The existing volume was retained. All ten original bill records matched
  the pre-rebuild snapshot. A SQLite backup was saved outside the repository.
- Live create/read/update/delete requests returned 201, 200, 200 and 204.
  Only the temporary smoke-test record was deleted; the original records
  were unchanged afterward.
- All 145 Bills tests passed with the updated dependencies on macOS Python
  3.14 and inside the rebuilt Python 3.11 Docker image.
- The two selected endpoint tests passed inside Docker: the seeded bill
  list and the create/read/update/delete lifecycle. JUnit XML was captured.
- The live MCP summary matched the direct Bills summary.
- Sourced RAG, insufficient-context handling and the existing AI review
  passed. All nine provider-RAG checks passed before the dependency update;
  the core MCP/RAG/AI-review checks also passed after the update.
- Ruff backend security rules, Bills secret detection and the combined
  dependency audit passed. No published vulnerabilities were returned by
  the final audit. This is not a guarantee that no vulnerabilities exist.
- JavaScript syntax, Compose configuration and diff checks passed.

The first Docker test harness omitted the shared corpus mount; adding the
read-only corpus mount resolved its missing-file errors. The recorded final
Python 3.11 results contain all 145 passing tests.

## Security changes

Updated Bills Flask to 3.1.3, Requests to 2.34.2 and pytest to 9.0.3 after
the initial dependency audits. Direct local Flask runs no longer enable the
debugger or bind beyond the local machine. Docker still uses Gunicorn.

Installed a local Git pre-commit hook using hyunwoo/.pre-commit-config.yaml.
It checks Bills files only. The matching CI job and explicit endpoint test
artifact step were added to hyunwoo-ci.yml. No commit was created to test
the hook: actual commit-time evidence must be captured by the student.

The latest observed hosted Bills workflow was successful for commit
279a3ed, before these follow-up edits:
https://github.com/Spliky420/Advanced-Software-Development/actions/runs/39755398529
The new CI changes require a student commit/push and a new successful run.

## Real-agent limitation: not a completed showcase review

The shared server was unchanged and ran on the host with real Ollama,
not stub agents. The rebuilt Bills backend sent its Python-calculated
snapshot and saved the returned review links.

- 2ac993a11e524316988f9a1b61faa097: qwen2.5:0.5b completed, but the Worker
  used the shared server's evidence-only fallback.
- aace0caaf8024203bc6da80c326cd504: llama3.1:8b completed, but Planner and
  Worker used fallbacks. The Reviewer also treated a past due date as proof
  of non-payment, which the saved data does not establish.
- 4ea666d8ea4b4c5c938766fa0ad4d22f: a Bills-only prompt experiment with
  llama3.1:8b failed when the Worker reached the 55-second agent timeout.
- 5a9c8027fe34426688cb4729ac40d1b6: the prompt experiment with
  qwen2.5:0.5b completed but still used the Worker fallback.

The prompt-only experiment did not resolve the issue and was reverted.
No human approval or correction has been submitted for these runs.
The last run reopened through the Bills backend after restarting the shared
server with the same history file. Its saved evidence remained unchanged.

The shared fallback adds a tax-deduction recommendation regardless of the
calling feature. That is not supported by this Bills snapshot. Twelve
shared-server tests also fail after the main update; the shared server and
its tests are identical to origin/main, not locally edited by this feature.
These issues need shared-server coordination before claiming showcase-ready
AI output. Completing the three stages alone does not prove useful advice.

## Local runtime and evidence

MCP runs on 8071 because an unrelated application already occupies 5002.
The rebuild used MCP_SERVER_URL=http://host.docker.internal:8071/mcp.
No unrelated containers were stopped or rebuilt.

Host RAG uses a separate temporary runtime index. The tracked corpus was
not rewritten. MCP, RAG and Multi-Agent processes were left running locally
for inspection; the final Multi-Agent process binds only to 127.0.0.1:5004.
Shared workflow audit events were saved at:

`/Users/dannycho/Documents/Codex/2026-09-01/the-video-must-also-include-demonstration/outputs/release2-checks/workflow-history.jsonl`

When restarting the shared server, use that same WORKFLOW_HISTORY_PATH
to reopen these test runs. Starting with a different history file makes
their local links unavailable; it does not delete the bill records.

The same evidence directory contains the database backup, live CRUD/MCP/
RAG responses, initial/final dependency audits, real-model responses and
the final Python 3.11 and endpoint-test XML files. It is local test evidence,
not a substitute for the group's completed cloud deployment or loop reviews.
