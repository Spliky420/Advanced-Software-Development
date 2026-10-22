# Bills Multi-Agent validation

Checked locally on 22 October 2026 using isolated test databases and server
history files. Existing Docker containers and saved Bills data were not
restarted or modified.

## Automated checks

- 145 Bills tests passed, including the 54 new Multi-Agent cases.
- 100 tests for the unchanged shared Multi-Agent Server passed.
- The Bills suite also passed with all four external-service modes disabled.
- Frontend JavaScript syntax, Docker Compose configuration and diff
  whitespace checks passed.
- Tests used Python 3.14 in a fresh temporary environment. The Python 3.11
  Docker build and hosted GitHub Actions run still need to be verified.

## HTTP and browser checks

The actual shared server ran in stub mode, with a separate seeded Bills
database. All four decision types completed through the Bills backend.
Repeated decisions returned 409 and the bill records remained unchanged.

Browser checks covered starting a review, the three output panels, the
required explanation for partial acceptance, saving a partial decision,
saving a correction and reopening that correction after a page reload.
Correction text containing HTML remained plain text. Source evidence stayed
collapsed by default. No browser console errors were recorded.

The preview used a same-origin test API address so existing containers on
8040/8041 were untouched. The production frontend's address and Docker
networking still require the rebuilt-container check.

## Real model check

The shared server used host Ollama with qwen2.5:0.5b, not stub agents.
Run ID: b1f1fb8ab3d842debd9bc846bb8b7bdd.

The Planner, Worker and Reviewer finished without fallback. The audit log
recorded approximately 46 seconds for planning, 15 seconds for work and
15 seconds for review. The final state was awaiting_human, with no human
decision recorded. The run used the ten seeded active bills and the saved
Python-calculated costs.

The public result and original evidence are captured in
release2-multi-agent-real-check.json. The matching events are preserved in
release2-multi-agent-development-audit.jsonl. This is evidence from an
isolated development check, not a human-approved production review.

The model's draft was generic and proposed calculating figures that had
already been supplied. It did not perform those calculations. Completion
of the workflow does not establish that the draft is useful or correct;
this output would need human correction or rejection before acceptance.

Earlier attempts hit the shared server's 55-second agent timeout.
Removing repeated bill details and requesting shorter outputs allowed the
run to complete. Timing remains machine-dependent; a single successful
run does not establish reliable performance on every machine.

The temporary shared server was shut down after testing. Its full audit
history was copied to the development evidence file, not the project's
shared history file. For final showcase evidence, run the normal shared
server, record a human decision in the integrated app, and preserve its
audit log.
