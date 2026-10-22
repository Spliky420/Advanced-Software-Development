# Live run against the real agents (Release 2, step 6)

Run on 2026-10-22 on the development laptop (RTX 3050 Laptop, 4 GB VRAM):
the shared multi-agent server with `STUB_AGENTS=false`, this backend on 8061,
the Vite frontend on 8060, and the Agents tab driven in headless Edge. MCP
and RAG were off; they play no part in the agent review.

## Results

| Goal | Model | Outcome | Time to "your turn" | What the database shows afterwards |
| --- | --- | --- | --- | --- |
| 3 New Laptop | qwen2.5:0.5b | approved | 12.7s and 17.5s | 2 pending instalments totalling 2,350.00, Python's schedule |
| 12 Debt Payoff Buffer | qwen2.5:0.5b | rejected | 2s (the Worker only restated the steps) | plan unchanged (12 steps) |
| 9 Home Deposit | llama3.1:8b, cold | Planner failed: "Ollama timed out after 55s" | 60.8s | plan unchanged |
| 9 Home Deposit | llama3.1:8b, warm | Planner failed again (55s) | 58.1s | plan unchanged |

Each run has a `multi-agent` row in `ai_plan_log` (phase `agent`); each
decided run also has a `human` row with the decision and the run read as
`complete`. The failed runs have only the start row; the failure itself is
recorded in the multi-agent server's `workflow_history.jsonl`.

## What the model said, and why the human gate exists

On goal 3 every figure qwen2.5:0.5b used was one Python supplied, so the
server's figure check raised nothing. Yet it called 2,350.00 "saved so far"
(it is the amount still to save) and said the plan was "within the budget",
when Python's evidence says `plan_within_budget: false`, short by 2,219.62
a month. On goal 12 the Reviewer said the same, and the "Fits the budget: NO"
panel computed by Python sat directly above it.

This is the known limitation in CLAUDE.md: a check on the numbers cannot
catch a misreading of correct numbers. The design does not depend on the
agents being right. Python's figures are shown first and labelled as
Python's, the agents only comment, and nothing is applied until a person
decides.

## Model choice

llama3.1:8b does not fit in 4 GB of VRAM. Ollama ran it 58% on the CPU, and
the Planner's first reply took over 55s even with the model already loaded.
Agent reviews on this machine are therefore demonstrated on qwen2.5:0.5b
(set by `OLLAMA_MODEL` on the multi-agent server, never in code). A machine
that holds llama3.1:8b on the GPU should finish within the limits below.

## Timeout chain

The agents run on the server's own thread (`"async": true`), so no HTTP
request is held open while they work. Every request this backend makes is
short:

| Layer | Limit | Covers |
| --- | --- | --- |
| Agents tab polling | stops after 240s | longer than the three agents' combined limit, with time to spare |
| multi-agent server, per agent | 55s (`AGENT_TIMEOUT_SECONDS`) | one agent, both attempts sharing one deadline; three agents total 165s at most |
| nginx / gunicorn (this backend) | 180s | not reached: no request waits for the agents |
| backend → multi-agent server | 10s read (`MULTI_AGENT_TIMEOUT_SECONDS`), short connect | the start, poll and decision calls, each answered at once |
| backend health probe | 2s | the header light |

When a limit is hit, the person sees the reason (the 55s case above) and
nothing is applied. One coupling to know about: the 240s in the frontend is
a constant. If the server's `AGENT_TIMEOUT_SECONDS` were raised above about
75s, the page could stop waiting before the server finishes. It then says it
has stopped waiting, applies nothing, and keeps the run, so reloading the
page picks up the result.
