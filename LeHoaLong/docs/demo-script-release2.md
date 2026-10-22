# Release 2 demo script — Goals and Budgeting (~100 s)

Four things must be on screen (Release 2 brief): the Multi-Agent workflow
through the frontend UI, the feature in **both** local and cloud
deployments, the pre-commit scans running, and the post-commit CI run.

Every timing below was measured on 2026-10-22, on the development laptop,
with qwen2.5:0.5b.

---

## Pre-flight — before you hit record

1. **Docker Desktop is running**, and your three containers are healthy:

   ```bash
   docker compose up -d lehoalong-database lehoalong-backend lehoalong-frontend
   docker compose ps lehoalong-database lehoalong-backend lehoalong-frontend
   ```

2. **Only one thing is listening on 8061**, the backend container. A Flask
   dev server left over from earlier work can hold 8061 too, and then the UI
   writes to the wrong database:

   ```bash
   netstat -ano | findstr :8061
   ```

3. **The multi-agent server is running with real agents, on qwen.**
   llama3.1:8b times out on this laptop's 4 GB GPU, at 55 s per agent.

   ```bash
   cd multi-agent-server
   STUB_AGENTS=false OLLAMA_MODEL=qwen2.5:0.5b python server.py
   ```

4. **Warm the model** so the first review doesn't pay the load time:
   `ollama run qwen2.5:0.5b "hi"`.

5. **Open http://localhost:8060.** The header should show **Agents: ready**.
   Use goal **12, Debt Payoff Buffer**: it hasn't been reviewed in the
   compose database yet, and its plan does **not** fit the budget, which
   gives you the best line in the video (step 3 below). Goal 3 has already
   been approved there.

6. **Wake the cloud app.** Its frontend scales to zero, so the first load is
   slow. Open these once, a minute before recording:
   - https://shared-frontend.wittywater-a7b31e13.australiaeast.azurecontainerapps.io
   - https://lehoalong-frontend.wittywater-a7b31e13.australiaeast.azurecontainerapps.io

7. **Pre-commit config is in the working tree.** `.pre-commit-config.yaml`
   and `.secrets.baseline` are copied from branch `LeHoaLong-pre-commit`
   (PR B). They're untracked: **don't commit them** to the Release 2
   branch.

8. **Browser tab open on the CI run:**
   https://github.com/Spliky420/Advanced-Software-Development/actions/runs/39772867106
   That is lehoalong-ci on the Release 2 branch, all 4 jobs green, including
   *Post-commit endpoint tests (2 endpoints, real HTTP)*.

---

## Shot list

| Time | On screen | Say |
| ---- | --------- | --- |
| 0–8 s | The cloud home page, then click into Goals and Budgeting | "Goals and Budgeting, deployed to Azure Container Apps by our team pipeline." |
| 8–22 s | Cloud: the goal list. Create a goal (New goal → save), open it, show it saved. | "In the cloud it's frontend, backend and database, CRUD working. The backend has no public address; only the frontend reaches it. AI services aren't deployed in the cloud." |
| 22–30 s | Terminal: `docker compose ps` showing the three containers healthy. Switch to localhost:8060, goal 12. | "Locally, the same three containers under Docker Compose, with Ollama and the multi-agent server on the host." |
| 30–40 s | AI mode → **Agents** → *Ask the agents to review a plan*. The proposal appears at once. | "Python calculates the plan first, every amount and date. The agents never get asked for a number." |
| 40–55 s | Planner, Worker and Reviewer tick to done (about 10 s), then *You*. | "Three agents review it in turn on the shared multi-agent server. This progress is real: the page polls the run." |
| 55–68 s | Point at **Fits the budget: NO**, then at the Reviewer's text. Choose **Reject** (note: "doesn't fit my budget") and submit. | "A small model misreads correct figures, so nothing is applied until a person decides. Python says this doesn't fit the budget, so I reject it, and nothing changes." |
| 68–82 s | Terminal: `pre-commit run ruff-check --all-files` then `pre-commit run detect-secrets --all-files` (about 6 s together). | "Every commit goes through ruff's security rules, a secrets scan and a dependency audit." |
| 82–97 s | GitHub tab: the lehoalong-ci run, then the post-commit job and its endpoint report in the summary. | "After a commit, CI runs the tests and then the post-commit job: it starts the real containers and tests two endpoints over HTTP." |
| 97–100 s | Back to the app. | "Python decides, the agents comment, a person approves." |

If you'd rather show an approval, use **Approve** on a goal whose plan fits.
The applied instalments then appear in the savings plan below; goal 3
showed this, in 9.5 s from click to applied.

---

## Things not to click on camera

- **Cloud: the AI-Mode, MCP, RAG and Agents tabs, and "Generate plan".** The
  cloud runs `main`'s Release 1 code. AI-Mode tries a model that isn't there
  and returns 503. MCP and RAG show *unreachable*. There's no Agents tab
  until Release 2 is merged and redeployed (with PR E, which switches those
  three off).
- **The full `pre-commit run --all-files`.** It's correct but takes 78 s,
  mostly pip-audit's online lookup. Either show the two fast hooks, or record
  it and speed it up in the edit.
- **llama3.1:8b anywhere.**
