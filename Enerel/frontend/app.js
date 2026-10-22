// Research Library frontend -- plain JS, no build step. Talks to the backend
// same-origin via the /api/ proxy nginx.conf sets up.

const API_BASE = "/api";

// Mirrors validation.DOC_TYPES in the backend. Kept here as a small,
// deliberate duplication rather than fetching it from the API, the same
// level of coupling joshua/backend's frontend placeholder uses for
// ASSET_CLASSES.
const DOC_TYPES = [
  "article",
  "guide",
  "report",
  "news",
  "research_note",
  "filing",
  "whitepaper",
  "other",
];

const state = {
  documents: [],
  selectedId: null,
  editingId: null,
};

// flatpickr instance backing #filter-date-range, set once in init().
let dateRangePicker = null;

const el = (id) => document.getElementById(id);

function labelForType(type) {
  return type.replace(/_/g, " ");
}

function populateDocTypeSelects() {
  const filterSelect = el("filter-doc-type");
  const formSelect = el("field-doc-type");
  for (const type of DOC_TYPES) {
    const filterOpt = document.createElement("option");
    filterOpt.value = type;
    filterOpt.textContent = labelForType(type);
    filterSelect.appendChild(filterOpt);

    const formOpt = document.createElement("option");
    formOpt.value = type;
    formOpt.textContent = labelForType(type);
    formSelect.appendChild(formOpt);
  }
}

async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch (err) {
      body = null;
    }
  }
  if (!response.ok) {
    const message = body && body.error ? body.error : `request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function showBanner(message, isError = false) {
  const banner = el("status-banner");
  banner.textContent = message;
  banner.hidden = false;
  banner.classList.toggle("error", isError);
}

function hideBanner() {
  el("status-banner").hidden = true;
}

// --------------------------------------------------------------------------
// list + filters
// --------------------------------------------------------------------------

// yyyy-mm-dd from local date parts, not toISOString() -- that converts to
// UTC first and can shift the date by a day depending on timezone.
function formatDateYMD(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function currentFilters() {
  const params = new URLSearchParams();
  const q = el("filter-q").value.trim();
  const docType = el("filter-doc-type").value;

  const selectedDates = dateRangePicker ? dateRangePicker.selectedDates : [];
  const dateFrom = selectedDates[0] ? formatDateYMD(selectedDates[0]) : "";
  // A range picker's second date only lands once both ends are picked; a
  // single selected date means "just that day", same as before-and-after
  // both being the two plain date inputs used to give you independently.
  const dateTo = selectedDates[1] ? formatDateYMD(selectedDates[1]) : dateFrom;

  if (q) params.set("q", q);
  if (docType) params.set("doc_type", docType);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return params.toString();
}

async function loadDocuments() {
  const query = currentFilters();
  try {
    state.documents = await apiFetch(`/documents${query ? `?${query}` : ""}`);
    hideBanner();
  } catch (err) {
    showBanner(`Could not load documents: ${err.message}`, true);
    state.documents = [];
  }
  renderGrid();
}

const GRID_VISIBLE_CAP = 8;

function renderGrid() {
  const grid = el("document-grid");
  grid.innerHTML = "";

  if (state.documents.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No documents match. Try clearing filters, or add a new document.";
    grid.appendChild(empty);
    capGridHeight();
    return;
  }

  for (const doc of state.documents) {
    const card = document.createElement("article");
    card.className = "doc-card";
    card.tabIndex = 0;
    card.addEventListener("click", () => openDetail(doc.id));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter") openDetail(doc.id);
    });

    const title = document.createElement("h3");
    title.textContent = doc.title;

    const meta = document.createElement("div");
    meta.className = "doc-meta";
    meta.innerHTML = `
      <span class="badge">${labelForType(doc.doc_type)}</span>
      ${doc.source ? `<span>${escapeHtml(doc.source)}</span>` : ""}
      ${doc.published_on ? `<span>${doc.published_on}</span>` : ""}
    `;

    card.appendChild(title);
    card.appendChild(meta);

    if (doc.summary_text) {
      const preview = document.createElement("p");
      preview.className = "doc-summary-preview";
      preview.textContent = doc.summary_text;
      card.appendChild(preview);
    } else {
      const preview = document.createElement("p");
      preview.className = "doc-summary-preview muted";
      preview.textContent = "Not summarized yet.";
      card.appendChild(preview);
    }

    grid.appendChild(card);
  }

  capGridHeight();
}

// Shows at most GRID_VISIBLE_CAP rows of cards; anything beyond that scrolls
// inside the grid itself rather than growing the page. Measured with
// getBoundingClientRect rather than a fixed pixel height because the grid's
// column count is responsive (auto-fill), so how many cards make up "8" worth
// of rows depends on viewport width.
function capGridHeight() {
  const grid = el("document-grid");
  const cards = grid.querySelectorAll(".doc-card");

  if (cards.length <= GRID_VISIBLE_CAP) {
    grid.classList.remove("grid-capped");
    grid.style.maxHeight = "";
    return;
  }

  const gridTop = grid.getBoundingClientRect().top;
  const lastVisibleCard = cards[GRID_VISIBLE_CAP - 1];
  const visibleHeight = lastVisibleCard.getBoundingClientRect().bottom - gridTop;

  grid.style.maxHeight = `${Math.ceil(visibleHeight)}px`;
  grid.classList.add("grid-capped");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// --------------------------------------------------------------------------
// detail pane
// --------------------------------------------------------------------------

async function openDetail(id) {
  state.selectedId = id;
  el("detail-pane").hidden = false;
  renderDetailLoading();

  try {
    const doc = await apiFetch(`/documents/${id}`);
    renderDetail(doc);
  } catch (err) {
    el("detail-content").innerHTML = `<p class="banner error">Could not load document: ${escapeHtml(err.message)}</p>`;
  }
}

function renderDetailLoading() {
  el("detail-content").innerHTML = `<p class="muted spinner-text">Loading</p>`;
}

function renderDetail(doc) {
  const content = el("detail-content");
  const hasSummary = Boolean(doc.summary_text);

  content.innerHTML = `
    <h2 class="detail-title">${escapeHtml(doc.title)}</h2>
    <div class="doc-meta">
      <span class="badge">${labelForType(doc.doc_type)}</span>
      ${doc.source ? `<span>${escapeHtml(doc.source)}</span>` : ""}
      ${doc.published_on ? `<span>${doc.published_on}</span>` : ""}
    </div>

    <div class="detail-actions">
      <button class="btn btn-primary" id="summarize-btn">
        ${hasSummary ? "Re-summarize" : "Summarize"}
      </button>
      <button class="btn" id="edit-btn">Edit</button>
      <button class="btn btn-danger" id="delete-btn">Delete</button>
    </div>

    <div class="detail-stack">
      <div class="detail-block">
        <h4>AI summary</h4>
        <div id="summary-block">${renderSummaryBlock(doc)}</div>
      </div>
      <div class="detail-block">
        <h4>Glossary lookup <span class="mode-chip" id="mcp-mode-chip">MCP</span></h4>
        <p class="muted">
          Open the document and double-click a word (or select a phrase) to
          define it with the shared MCP server's <code>glossary_lookup</code> tool.
        </p>
        <form id="glossary-form" class="rag-form">
          <input type="text" id="glossary-term" maxlength="60"
            placeholder="e.g. volatility" required />
          <button type="submit" class="btn">Define</button>
        </form>
        <div id="glossary-result" aria-live="polite"></div>
      </div>
      <div class="detail-block">
        <h4>Research brief <span class="mode-chip" id="multi-agent-mode-chip">Multi-Agent</span></h4>
        <p class="muted">
          Sends this document's details and its text to the team's shared
          Multi-Agent Server.
          A Planner, a Worker and a Reviewer agent work through the task in
          turn. No agent calculates a figure. The run is only complete once you
          record a decision.
        </p>
        <div id="brief-result" aria-live="polite"></div>
        <button class="btn" id="multi-agent-btn">Start Multi-Agent Review</button>
        <div id="multi-agent-result" aria-live="polite"></div>
      </div>
      <div class="detail-block">
        <h4>Full document</h4>
        <button type="button" class="file-btn" id="open-doc-btn">
          <span class="file-icon" aria-hidden="true">📄</span>
          <span class="file-name">${escapeHtml(doc.title)}</span>
        </button>
      </div>
    </div>
  `;

  el("glossary-form").addEventListener("submit", (e) => {
    e.preventDefault();
    lookupGlossaryTerm(doc.id, el("glossary-term").value);
  });
  el("open-doc-btn").addEventListener("click", () => openDocumentViewer(doc));
  applyModeChips();

  el("multi-agent-btn").addEventListener("click", () => startMultiAgentRun(doc.id));
  loadBrief(doc.id);
  el("summarize-btn").addEventListener("click", () => triggerSummarize(doc.id));
  el("edit-btn").addEventListener("click", () => openForm(doc));
  el("delete-btn").addEventListener("click", () => deleteDocument(doc.id));
}

// The full text opens in a dialog rather than filling the detail pane.
// Selecting a phrase there fills the glossary box; double-clicking a word
// closes the dialog and looks it up, so the definition is visible in the pane.
function openDocumentViewer(doc) {
  el("doc-view-title").textContent = doc.title;
  el("detail-body-text").textContent = doc.body_text;
  el("doc-view-modal").showModal();
  el("detail-body-text").scrollTop = 0;
}

function renderSummaryBlock(doc) {
  if (!doc.summary_text) {
    return `<p class="muted">Not summarized yet. Click "Summarize" to generate one via Ollama.</p>`;
  }
  const points = (doc.key_points || [])
    .map((point) => `<li>${escapeHtml(point)}</li>`)
    .join("");
  return `
    <div class="summary-text">${escapeHtml(doc.summary_text)}</div>
    ${points ? `<ul class="key-points">${points}</ul>` : ""}
    <p class="muted">Model: ${escapeHtml(doc.summary_model || "unknown")} · ${doc.summarized_at || ""}</p>
  `;
}

async function triggerSummarize(id) {
  const btn = el("summarize-btn");
  const original = btn.textContent;
  btn.disabled = true;
  btn.classList.add("spinner-text");
  btn.textContent = "Summarizing";
  try {
    const result = await apiFetch(`/documents/${id}/summarize`, { method: "POST" });
    renderDetail(result.document);
    await loadDocuments();
  } catch (err) {
    showBanner(`Summarize failed: ${err.message}`, true);
    btn.disabled = false;
    btn.classList.remove("spinner-text");
    btn.textContent = original;
  }
}

async function deleteDocument(id) {
  if (!confirm("Delete this document? This cannot be undone.")) return;
  try {
    await apiFetch(`/documents/${id}`, { method: "DELETE" });
    closeDetail();
    await loadDocuments();
  } catch (err) {
    showBanner(`Delete failed: ${err.message}`, true);
  }
}

function closeDetail() {
  state.selectedId = null;
  el("detail-pane").hidden = true;
}

// --------------------------------------------------------------------------
// create / edit modal
// --------------------------------------------------------------------------

function openForm(doc = null) {
  state.editingId = doc ? doc.id : null;
  el("doc-modal-title").textContent = doc ? "Edit document" : "New document";
  el("field-title").value = doc ? doc.title : "";
  el("field-source").value = doc && doc.source ? doc.source : "";
  el("field-doc-type").value = doc ? doc.doc_type : DOC_TYPES[0];
  el("field-published-on").value = doc && doc.published_on ? doc.published_on : "";
  el("field-body-text").value = doc ? doc.body_text : "";
  el("field-body-file").value = "";
  el("form-errors").hidden = true;
  el("file-error").hidden = true;
  el("doc-modal").showModal();
}

function isPdfFile(file) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

// Extracts plain text from a PDF entirely in the browser via pdf.js -- the
// backend only ever receives the resulting body_text string, never the PDF
// itself, so no server-side parsing dependency is needed.
async function extractPdfText(file) {
  if (!window.pdfjsLib) {
    throw new Error("the PDF reader failed to load (check your internet connection and reload the page)");
  }
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

  const pageTexts = [];
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const textContent = await page.getTextContent();
    pageTexts.push(textContent.items.map((item) => item.str).join(" "));
  }
  return pageTexts.join("\n\n").trim();
}

async function handleFilePicked(event) {
  const file = event.target.files[0];
  const fileError = el("file-error");
  fileError.hidden = true;
  if (!file) return;

  // Extraction is async and can take a moment for a multi-page PDF -- block
  // Save until it finishes, otherwise a fast click submits an empty
  // body_text and the backend rejects it, which looks like "save is broken"
  // when it's really just a race with a file still being read.
  const saveBtn = el("save-doc-btn");
  saveBtn.disabled = true;

  try {
    if (isPdfFile(file)) {
      fileError.textContent = `Extracting text from "${file.name}"…`;
      fileError.classList.add("muted");
      fileError.hidden = false;
      try {
        const text = await extractPdfText(file);
        if (!text) {
          fileError.textContent = `"${file.name}" has no extractable text (likely a scanned image). Paste the text below instead.`;
          fileError.classList.remove("muted");
          event.target.value = "";
          return;
        }
        el("field-body-text").value = text;
        fileError.hidden = true;
        fileError.classList.remove("muted");
      } catch (err) {
        fileError.textContent = `Could not read "${file.name}": ${err.message}`;
        fileError.classList.remove("muted");
        fileError.hidden = false;
        event.target.value = "";
      }
      return;
    }

    const looksTextLike = file.type.startsWith("text/") || file.type === "application/json" || file.type === "";
    if (!looksTextLike) {
      fileError.textContent = `"${file.name}" doesn't look like a plain text or PDF file. Convert it to .txt/.pdf or paste its text below instead.`;
      fileError.hidden = false;
      event.target.value = "";
      return;
    }

    try {
      el("field-body-text").value = await file.text();
    } catch (err) {
      fileError.textContent = `Could not read "${file.name}": ${err.message}`;
      fileError.hidden = false;
    }
  } finally {
    saveBtn.disabled = false;
  }
}

async function submitForm(event) {
  event.preventDefault();
  const payload = {
    title: el("field-title").value,
    source: el("field-source").value || null,
    doc_type: el("field-doc-type").value,
    published_on: el("field-published-on").value || null,
    body_text: el("field-body-text").value,
  };

  const saveBtn = el("save-doc-btn");
  saveBtn.disabled = true;

  try {
    const path = state.editingId ? `/documents/${state.editingId}` : "/documents";
    const method = state.editingId ? "PUT" : "POST";
    const saved = await apiFetch(path, { method, body: JSON.stringify(payload) });

    el("doc-modal").close();
    await loadDocuments();
    openDetail(saved.id);
  } catch (err) {
    const errorsEl = el("form-errors");
    const details = err.body && err.body.errors ? err.body.errors.join("\n") : err.message;
    errorsEl.textContent = details;
    errorsEl.hidden = false;
  } finally {
    saveBtn.disabled = false;
  }
}

// --------------------------------------------------------------------------
// Release 1 -- shared MCP (glossary lookup) and RAG (grounded Q&A)
// --------------------------------------------------------------------------

// Filled from GET /api/library/integrations; null until it loads, which
// leaves the chips neutral rather than claiming a mode is on or off.
let integrations = null;

async function loadIntegrations() {
  try {
    integrations = await apiFetch("/library/integrations");
  } catch (err) {
    integrations = null;
  }
  applyModeChips();
}

function applyModeChips() {
  const chips = [
    ["mcp-mode-chip", "MCP", integrations && integrations.mcp],
    ["rag-mode-chip", "RAG", integrations && integrations.rag],
    ["multi-agent-mode-chip", "Multi-Agent", integrations && integrations.multi_agent],
  ];
  for (const [id, label, mode] of chips) {
    const chip = el(id);
    if (!chip || !mode) continue;
    chip.textContent = mode.enabled ? label : `${label} off`;
    chip.classList.toggle("off", !mode.enabled);
    chip.title = mode.enabled ? `Shared ${label} server: ${mode.server_url}` : `${label} mode is disabled`;
  }
}

// A double-clicked word often carries its trailing punctuation ("risk.").
function cleanTerm(term) {
  return term.trim().replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, "");
}

async function lookupGlossaryTerm(documentId, rawTerm) {
  const term = cleanTerm(rawTerm || "");
  if (!term) return;
  el("glossary-term").value = term;

  const resultEl = el("glossary-result");
  resultEl.innerHTML = `<p class="muted spinner-text">Calling glossary_lookup</p>`;

  try {
    const result = await apiFetch(`/documents/${documentId}/glossary`, {
      method: "POST",
      body: JSON.stringify({ term }),
    });
    renderGlossaryResult(result);
  } catch (err) {
    resultEl.innerHTML = `<p class="banner error">Glossary lookup failed: ${escapeHtml(err.message)}</p>`;
  }
}

function renderGlossaryResult(result) {
  const body = result.found
    ? `<div>${escapeHtml(result.definition)}</div>`
    : `<div class="muted">${escapeHtml(result.message)}</div>`;
  el("glossary-result").innerHTML = `
    <div class="rag-result">
      <div class="rag-result-meta">
        <strong>${escapeHtml(result.input.term)}</strong>
        <span>MCP tool: ${escapeHtml(result.tool)}</span>
      </div>
      ${body}
    </div>
  `;
}

async function askLibrary(event) {
  event.preventDefault();
  const question = el("ask-question").value.trim();
  if (!question) return;

  const resultsEl = el("ask-results");
  resultsEl.innerHTML = `<p class="muted spinner-text">Retrieving context and answering</p>`;

  try {
    const result = await apiFetch("/library/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    renderAskResult(result);
  } catch (err) {
    resultsEl.innerHTML = `<p class="banner error">Ask failed: ${escapeHtml(err.message)}</p>`;
  }
}

function renderAskResult(result) {
  const resultsEl = el("ask-results");
  const confidenceClass = `confidence-${result.confidence_category.toLowerCase()}`;
  const header = `
    <div class="rag-result-meta">
      <span>${result.status === "answered" ? "Grounded answer" : "Insufficient context"}</span>
      <span class="badge confidence ${confidenceClass}">Confidence: ${escapeHtml(result.confidence_category)}</span>
    </div>
  `;

  if (result.status !== "answered") {
    const missing = result.observe.missing_terms.length
      ? `<p class="muted">Not found in the knowledge base: ${result.observe.missing_terms.map(escapeHtml).join(", ")}</p>`
      : "";
    resultsEl.innerHTML = `
      <div class="rag-result insufficient">
        ${header}
        <div>${escapeHtml(result.answer)}</div>
        ${missing}
      </div>
    `;
    return;
  }

  const citations = result.citations
    .map(
      (c, i) => `
        <li>
          <details>
            <summary>[${i + 1}] ${escapeHtml(c.source_id)}</summary>
            <span class="muted">${escapeHtml(c.chunk_id)} · matched: ${c.matched_terms.map(escapeHtml).join(", ")}</span>
            <div class="citation-snippet">${escapeHtml(c.snippet)}</div>
          </details>
        </li>
      `
    )
    .join("");

  resultsEl.innerHTML = `
    <div class="rag-result">
      ${header}
      <div class="summary-text">${escapeHtml(result.answer)}</div>
      <h4 class="citations-heading">Sources</h4>
      <ul class="citations">${citations}</ul>
      <p class="muted">Question coverage ${Math.round(result.observe.coverage * 100)}% · ${result.observe.supporting_count} of ${result.observe.retrieved_count} retrieved chunks support it</p>
    </div>
  `;
}

// --------------------------------------------------------------------------
// Release 2 -- shared Multi-Agent Server: Planner -> Worker -> Reviewer ->
// human review. The backend starts the run asynchronously, so the UI polls
// and shows each agent finishing. Each stage gets its own numbered section,
// the same layout as Joshua's Multi-Agent Review page.
// --------------------------------------------------------------------------

// How often to ask for the run's progress, and the most time to wait in all.
// The server bounds a run at three agent timeouts (3 x 55s); 180s sits above
// that, in case the server restarts mid-run and the run can never finish.
const MULTI_AGENT_POLL_MS = 1500;
const MULTI_AGENT_DEADLINE_MS = 180000;

const IN_FLIGHT = ["planning", "working", "reviewing"];

const STAGES = {
  planner: { step: 1, title: "Planner", tagline: "Break the task into steps" },
  worker: { step: 2, title: "Worker", tagline: "Carry out each step" },
  reviewer: { step: 3, title: "Reviewer", tagline: "Check the work for risks" },
  human: { step: 4, title: "Human review", tagline: "Your decision completes the run" },
};

// The three agents in order, with the run status that means each is running
// and the error.phase name the server uses when it fails.
const AGENTS = [
  { phase: "plan", label: "Planner", running: "planning" },
  { phase: "work", label: "Worker", running: "working" },
  { phase: "review", label: "Reviewer", running: "reviewing" },
];

const AGENT_STATE_LABELS = {
  done: "Done",
  running: "Running…",
  waiting: "Waiting",
  failed: "Failed",
  skipped: "Not run",
  unknown: "Unknown",
};

const AGENT_STATE_MARKS = { done: "✓", failed: "✗", running: "◌" };

const DECISIONS = [
  { value: "approve", label: "Approve", hint: "Accept the agents’ output as it is." },
  { value: "correct", label: "Correct", hint: "Replace the output with your corrected text." },
  { value: "partial", label: "Partially accept", hint: "Say in the note which part you accept." },
  { value: "reject", label: "Reject", hint: "Do not accept the output." },
];

// The run being shown: { run, evidence, task, documentId, lastStatus }.
// Bumped token stops a stale poll loop when a new run starts or the detail
// pane moves to another document.
let multiAgent = null;
let multiAgentToken = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function agentState(run, index) {
  if (run.status === "failed") {
    const failedAt = AGENTS.findIndex((agent) => agent.phase === (run.error || {}).phase);
    if (index < failedAt) return "done";
    return index === failedAt ? "failed" : "skipped";
  }
  if (run.status === "lost" || run.status === "timed_out") {
    const runningAt = AGENTS.findIndex((agent) => agent.running === run.lastStatus);
    return runningAt !== -1 && index < runningAt ? "done" : "unknown";
  }
  const runningAt = AGENTS.findIndex((agent) => agent.running === run.status);
  if (runningAt === -1) return "done"; // awaiting_human or complete
  if (index < runningAt) return "done";
  return index === runningAt ? "running" : "waiting";
}

function renderAgentProgress(run) {
  return `
    <ol class="agent-progress" aria-label="Agent progress">
      ${AGENTS.map((agent, index) => {
        const state = agentState(run, index);
        return `
          <li class="agent-step agent-step-${state}">
            <span class="agent-step-mark" aria-hidden="true">${AGENT_STATE_MARKS[state] || "•"}</span>
            <strong>${agent.label}</strong>
            <span class="agent-step-state">${AGENT_STATE_LABELS[state]}</span>
          </li>
        `;
      }).join("")}
    </ol>
  `;
}

function renderStage(stage, body) {
  return `
    <section class="stage">
      <header class="stage-header">
        <span class="stage-step" aria-hidden="true">${stage.step}</span>
        <div>
          <h5 class="stage-title"><span class="stage-label">Stage ${stage.step}</span>${stage.title}</h5>
          <p class="stage-tagline">${stage.tagline}</p>
        </div>
      </header>
      <div class="stage-body">${body}</div>
    </section>
  `;
}

function renderItemList(items, empty) {
  if (!items || items.length === 0) return `<p class="muted">${empty}</p>`;
  return `<ul class="key-points">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderErrorBanner(title, err) {
  const detail = err.body && err.body.detail ? `<p class="muted">${escapeHtml(err.body.detail)}</p>` : "";
  return `
    <div class="banner error" role="alert">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(err.message)}</p>
      ${detail}
    </div>
  `;
}

async function startMultiAgentRun(documentId) {
  const token = ++multiAgentToken;
  const btn = el("multi-agent-btn");
  btn.disabled = true;
  btn.textContent = "Running…";
  multiAgent = null;
  el("multi-agent-result").innerHTML = `<p class="muted spinner-text">Starting the agents</p>`;

  const stillCurrent = () => token === multiAgentToken && state.selectedId === documentId;

  try {
    const started = await apiFetch(`/documents/${documentId}/multi-agent`, { method: "POST" });
    if (!stillCurrent()) return;
    multiAgent = { run: started, sent: started.sent, task: started.task, documentId };
    renderMultiAgent();

    const startedAt = Date.now();
    while (IN_FLIGHT.includes(multiAgent.run.status)) {
      await sleep(MULTI_AGENT_POLL_MS);
      if (!stillCurrent()) return;
      if (Date.now() - startedAt > MULTI_AGENT_DEADLINE_MS) {
        stopPolling("timed_out", {
          message:
            "The agents did not finish within 3 minutes. The Multi-Agent Server may have " +
            "restarted, or the model is very slow. Start a new review to try again.",
        });
        return;
      }
      try {
        multiAgent.run = await apiFetch(`/multi-agent/runs/${multiAgent.run.run_id}`);
      } catch (err) {
        if (stillCurrent()) stopPolling("lost", err);
        return;
      }
      if (!stillCurrent()) return;
      renderMultiAgent();
    }
  } catch (err) {
    if (stillCurrent()) {
      el("multi-agent-result").innerHTML = renderErrorBanner("The Multi-Agent Review could not be run", err);
    }
  } finally {
    if (token === multiAgentToken && el("multi-agent-btn")) {
      el("multi-agent-btn").disabled = false;
      el("multi-agent-btn").textContent = multiAgent ? "Start a new review" : "Start Multi-Agent Review";
    }
  }
}

// The page stopped polling for its own reasons -- the server could not be
// reached, or the deadline passed -- keeping the last status it saw.
function stopPolling(status, err) {
  multiAgent.run = { ...multiAgent.run, lastStatus: multiAgent.run.status, status };
  renderMultiAgent(renderErrorBanner("Lost contact with the Multi-Agent Review", err));
}

function renderMultiAgent(extra = "") {
  const { run, sent } = multiAgent;
  const resultEl = el("multi-agent-result");
  const busy = IN_FLIGHT.includes(run.status);
  const finished = run.status === "awaiting_human" || run.status === "complete";

  let html = renderAgentProgress(run) + extra;

  if (busy) {
    html += `<p class="muted spinner-text">The agents are working. Three run one after another, so this can take a minute</p>`;
  }

  if (run.status === "failed") {
    const failedAgent = AGENTS.find((agent) => agent.phase === (run.error || {}).phase);
    html += `
      <div class="banner error" role="alert">
        <strong>The ${failedAgent ? failedAgent.label : "agent"} could not run, so this review stopped</strong>
        <p>${escapeHtml((run.error || {}).detail || "unknown error")}</p>
        <p class="muted">Check Ollama is running on the host with the model pulled, or start the
        Multi-Agent Server with <code>STUB_AGENTS=true</code>. Then start a new review.</p>
      </div>
    `;
  }

  if (finished) {
    html += `
      ${run.stub ? `
        <div class="banner warning" role="status">
          <strong>Stub agents</strong>
          <p>The Multi-Agent Server is running with <code>STUB_AGENTS=true</code>, so this output is canned and no model was called.</p>
        </div>` : ""}
      <dl class="run-facts">
        <div><dt>Run</dt><dd><code>${escapeHtml(run.run_id)}</code></dd></div>
        <div><dt>Model</dt><dd><code>${escapeHtml(run.model || "unknown")}</code></dd></div>
        <div><dt>Document words</dt><dd>${sent.word_count}</dd></div>
        <div><dt>Text sent</dt><dd>${sent.cut_short ? `first ${sent.characters_sent} characters` : "whole document"}</dd></div>
      </dl>
      ${renderStage(STAGES.planner, run.plan.length === 0
        ? `<p class="muted">The planner returned no steps.</p>`
        : `<ol class="key-points">${run.plan.map((step) => `
            <li>${escapeHtml(step.action)}${(step.evidence || []).length
              ? ` <span class="muted">(evidence: ${step.evidence.map(escapeHtml).join(", ")})</span>` : ""}</li>`).join("")}
          </ol>`)}
      ${renderStage(STAGES.worker, `
        <div class="summary-text worker-output">${escapeHtml(run.work || "The worker returned no output.")}</div>
        ${run.work_repeated_lines_removed ? `<p class="muted">${run.work_repeated_lines_removed} repeated line${run.work_repeated_lines_removed === 1 ? "" : "s"} hidden. The model got stuck repeating itself.</p>` : ""}
      `)}
      ${renderStage(STAGES.reviewer, `
        <h6 class="stage-subheading">Risks</h6>
        ${renderItemList(run.review && run.review.risks, "No risks reported.")}
        <h6 class="stage-subheading">Recommendations</h6>
        ${renderItemList(run.review && run.review.recommendations, "No recommendations.")}
      `)}
      ${renderStage(STAGES.human, `<div id="human-review"></div>`)}
    `;
  }

  resultEl.innerHTML = html;

  if (finished) {
    if (run.status === "complete") {
      renderDecisionBanner({ run_id: run.run_id, status: run.status, ...run.human_review });
    } else {
      renderHumanReviewForm(run);
    }
  }
}

const DECISION_LABELS = { approve: "Approved", correct: "Corrected", partial: "Partially accepted" };

// The latest brief a person accepted for this document, kept by the backend
// so it shows on every visit, even with the Multi-Agent Server stopped.
async function loadBrief(documentId) {
  let brief = null;
  try {
    brief = await apiFetch(`/documents/${documentId}/brief`);
  } catch (err) {
    if (err.status !== 404) brief = { error: err };
  }
  if (state.selectedId !== documentId || !el("brief-result")) return;
  el("brief-result").innerHTML = renderBrief(brief);
}

function renderBrief(brief) {
  if (!brief) {
    return `<p class="muted brief-empty">No research brief accepted yet. Run a review and approve, correct or partially accept it to keep its main takeaways here.</p>`;
  }
  if (brief.error) {
    return `<p class="banner error">Could not load the research brief: ${escapeHtml(brief.error.message)}</p>`;
  }
  const points = brief.takeaways.length
    ? `<ul class="key-points">${brief.takeaways.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>`
    : `<div class="summary-text">${escapeHtml(brief.brief_text)}</div>`;
  return `
    <div class="brief-card">
      <div class="rag-result-meta">
        <strong>${brief.takeaways.length ? "Main takeaways" : "Research brief"}</strong>
        <span class="badge">${escapeHtml(DECISION_LABELS[brief.decision] || brief.decision)}</span>
      </div>
      ${points}
      ${brief.note ? `<p class="muted">Reviewer note: ${escapeHtml(brief.note)}</p>` : ""}
      ${brief.takeaways.length ? `
        <details class="brief-full">
          <summary>Full brief</summary>
          <div class="summary-text">${escapeHtml(brief.brief_text)}</div>
        </details>` : ""}
      <p class="muted">Run <code>${escapeHtml(brief.run_id.slice(0, 8))}</code> · decided ${escapeHtml(brief.decided_at)}</p>
    </div>
  `;
}

function renderDecisionBanner(decided) {
  const label = (DECISIONS.find((d) => d.value === decided.decision) || {}).label || decided.decision;
  el("human-review").innerHTML = `
    <div class="banner success decision-${escapeHtml(decided.decision)}" role="status">
      <strong>Decision recorded: ${escapeHtml(label)}</strong>
      <p>Run <code>${escapeHtml(decided.run_id)}</code> is <strong>${escapeHtml(decided.status)}</strong>${decided.decided_at ? ` as of ${escapeHtml(decided.decided_at)}` : ""}.</p>
      ${decided.note ? `<p>Note: ${escapeHtml(decided.note)}</p>` : ""}
      ${decided.corrected ? `<p>Corrected text:</p><div class="summary-text">${escapeHtml(decided.corrected)}</div>` : ""}
    </div>
  `;
}

// Mirrors the server's rules so the common mistakes are caught before a
// round trip; the server still has the final say and its errors are shown too.
function validateReview({ decision, note, corrected }) {
  const errors = {};
  if (!decision) errors.decision = "Choose a decision.";
  if (decision === "partial" && !note.trim()) errors.note = "Say which part you accept.";
  if (decision === "correct" && !corrected.trim()) errors.corrected = "Enter the corrected text.";
  return errors;
}

function renderHumanReviewForm(run) {
  el("human-review").innerHTML = `
    <form id="human-review-form" class="human-review-form" novalidate>
      <fieldset class="decision-options" data-field="decision">
        <legend>Decision</legend>
        ${DECISIONS.map((option) => `
          <label class="decision-option">
            <input type="radio" name="decision" value="${option.value}" />
            <span><strong>${option.label}</strong> <span class="muted">${option.hint}</span></span>
          </label>
        `).join("")}
        <p class="field-error" hidden></p>
      </fieldset>
      <div data-field="note">
        <label for="human-review-note">Note <span id="note-required" class="muted">(optional)</span></label>
        <textarea id="human-review-note" rows="3" maxlength="2000"></textarea>
        <p class="field-error" hidden></p>
      </div>
      <div data-field="corrected" hidden>
        <label for="human-review-corrected">Corrected text (required)</label>
        <textarea id="human-review-corrected" rows="5"></textarea>
        <p class="field-error" hidden></p>
      </div>
      <div id="human-review-error"></div>
      <button type="submit" class="btn btn-primary">Submit decision</button>
    </form>
  `;

  const form = el("human-review-form");
  form.addEventListener("change", () => {
    const decision = form.elements.decision.value;
    const correctedField = form.querySelector('[data-field="corrected"]');
    const corrected = el("human-review-corrected");
    if (decision === "correct" && !corrected.value) corrected.value = run.work || "";
    correctedField.hidden = decision !== "correct";
    el("note-required").textContent = decision === "partial" ? "(required)" : "(optional)";
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitHumanReview(run.run_id, form);
  });
}

function showFieldErrors(form, errors) {
  for (const field of form.querySelectorAll("[data-field]")) {
    const message = errors[field.dataset.field];
    const errorEl = field.querySelector(".field-error");
    field.classList.toggle("field-invalid", Boolean(message));
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }
}

async function submitHumanReview(runId, form) {
  const review = {
    decision: form.elements.decision.value,
    note: el("human-review-note").value,
    corrected: el("human-review-corrected").value,
  };
  const errors = validateReview(review);
  showFieldErrors(form, errors);
  if (Object.keys(errors).length > 0) return;

  const payload = { decision: review.decision };
  if (review.note.trim()) payload.note = review.note.trim();
  if (review.decision === "correct") payload.corrected = review.corrected.trim();

  const submitBtn = form.querySelector("button[type=submit]");
  submitBtn.disabled = true;
  submitBtn.textContent = "Submitting…";
  el("human-review-error").innerHTML = "";
  try {
    const decided = await apiFetch(`/multi-agent/runs/${runId}/review`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    multiAgent.run = { ...multiAgent.run, status: decided.status, human_review: { ...payload, decided_at: decided.decided_at } };
    renderMultiAgent();
    loadBrief(multiAgent.documentId);
  } catch (err) {
    el("human-review-error").innerHTML = renderErrorBanner("The decision could not be recorded", err);
    if (err.body && err.body.fields) showFieldErrors(form, err.body.fields);
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit decision";
  }
}

// --------------------------------------------------------------------------
// wiring
// --------------------------------------------------------------------------

function init() {
  populateDocTypeSelects();

  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  }

  if (window.flatpickr) {
    dateRangePicker = flatpickr("#filter-date-range", {
      mode: "range",
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "M j, Y",
      altInputClass: "date-range-input",
    });
  }

  el("filter-form").addEventListener("submit", (e) => {
    e.preventDefault();
    loadDocuments();
  });
  el("clear-filters-btn").addEventListener("click", () => {
    el("filter-form").reset();
    // form.reset() only clears the native input flatpickr wraps, not its
    // own internal selectedDates -- clear that explicitly or a stale range
    // keeps applying after "Clear" is clicked.
    if (dateRangePicker) dateRangePicker.clear();
    loadDocuments();
  });

  el("new-doc-btn").addEventListener("click", () => openForm(null));
  el("cancel-doc-btn").addEventListener("click", () => el("doc-modal").close());
  el("doc-form").addEventListener("submit", submitForm);
  el("field-body-file").addEventListener("change", handleFilePicked);

  el("close-detail-btn").addEventListener("click", closeDetail);

  el("close-doc-view-btn").addEventListener("click", () => el("doc-view-modal").close());
  el("doc-view-modal").addEventListener("click", (e) => {
    // A click on the backdrop lands on the dialog element itself.
    if (e.target === el("doc-view-modal")) el("doc-view-modal").close();
  });
  el("detail-body-text").addEventListener("mouseup", () => {
    const selected = window.getSelection().toString().trim();
    if (selected && selected.length <= 60 && el("glossary-term")) el("glossary-term").value = selected;
  });
  el("detail-body-text").addEventListener("dblclick", () => {
    const selected = window.getSelection().toString().trim();
    if (!selected || state.selectedId === null) return;
    el("doc-view-modal").close();
    lookupGlossaryTerm(state.selectedId, selected);
    el("glossary-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  el("ask-form").addEventListener("submit", askLibrary);

  // The grid's column count is responsive, so how tall 8 rows' worth of
  // cards is changes with viewport width -- recompute the cap on resize.
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(capGridHeight, 150);
  });

  loadDocuments();
  loadIntegrations();
}

document.addEventListener("DOMContentLoaded", init);
