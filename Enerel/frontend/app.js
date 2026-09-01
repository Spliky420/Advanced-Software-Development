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

function currentFilters() {
  const params = new URLSearchParams();
  const q = el("filter-q").value.trim();
  const docType = el("filter-doc-type").value;
  const dateFrom = el("filter-date-from").value;
  const dateTo = el("filter-date-to").value;
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

function renderGrid() {
  const grid = el("document-grid");
  grid.innerHTML = "";

  if (state.documents.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No documents match. Try clearing filters, or add a new document.";
    grid.appendChild(empty);
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
  document.querySelector(".layout").classList.add("has-detail");
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
        <h4>Full document</h4>
        <div class="body-text">${escapeHtml(doc.body_text)}</div>
      </div>
    </div>
  `;

  el("summarize-btn").addEventListener("click", () => triggerSummarize(doc.id));
  el("edit-btn").addEventListener("click", () => openForm(doc));
  el("delete-btn").addEventListener("click", () => deleteDocument(doc.id));
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
  document.querySelector(".layout").classList.remove("has-detail");
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

async function handleFilePicked(event) {
  const file = event.target.files[0];
  const fileError = el("file-error");
  fileError.hidden = true;
  if (!file) return;

  const looksTextLike = file.type.startsWith("text/") || file.type === "application/json" || file.type === "";
  if (!looksTextLike) {
    fileError.textContent = `"${file.name}" doesn't look like a plain text file. Convert it to .txt or paste its text below instead.`;
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
// RAG search
// --------------------------------------------------------------------------

async function runRagSearch(event) {
  event.preventDefault();
  const query = el("rag-query").value.trim();
  if (!query) return;

  const resultsEl = el("rag-results");
  resultsEl.innerHTML = `<p class="muted spinner-text">Searching</p>`;

  try {
    const result = await apiFetch("/documents/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k: 5 }),
    });
    renderRagResults(result.observe.results);
  } catch (err) {
    resultsEl.innerHTML = `<p class="banner error">Search failed: ${escapeHtml(err.message)}</p>`;
  }
}

function renderRagResults(results) {
  const resultsEl = el("rag-results");
  if (!results || results.length === 0) {
    resultsEl.innerHTML = `<p class="muted">No relevant chunks found. Documents need to be indexed first (this happens automatically when you add or edit them, once the embedding model is pulled).</p>`;
    return;
  }
  resultsEl.innerHTML = results
    .map(
      (r) => `
        <div class="rag-result">
          <div class="rag-result-meta">
            <span>${escapeHtml(r.title)} · ${labelForType(r.doc_type)}</span>
            <span>score ${r.score}</span>
          </div>
          <div>${escapeHtml(r.chunk_text)}</div>
        </div>
      `
    )
    .join("");
}

// --------------------------------------------------------------------------
// wiring
// --------------------------------------------------------------------------

function init() {
  populateDocTypeSelects();

  el("filter-form").addEventListener("submit", (e) => {
    e.preventDefault();
    loadDocuments();
  });
  el("clear-filters-btn").addEventListener("click", () => {
    el("filter-form").reset();
    loadDocuments();
  });

  el("new-doc-btn").addEventListener("click", () => openForm(null));
  el("cancel-doc-btn").addEventListener("click", () => el("doc-modal").close());
  el("doc-form").addEventListener("submit", submitForm);
  el("field-body-file").addEventListener("change", handleFilePicked);

  el("close-detail-btn").addEventListener("click", closeDetail);

  el("rag-form").addEventListener("submit", runRagSearch);

  loadDocuments();
}

document.addEventListener("DOMContentLoaded", init);
