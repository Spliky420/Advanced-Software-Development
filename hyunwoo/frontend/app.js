// Backend address used by the browser.
const API_BASE = `${window.location.protocol}//${window.location.hostname}:8041/api`;

// Page elements updated by JavaScript.
const elements = {
    connectionStatus: document.querySelector("#connection-status"),
    monthlyCost: document.querySelector("#monthly-cost"),
    annualCost: document.querySelector("#annual-cost"),
    activeCount: document.querySelector("#active-count"),
    renewalCount: document.querySelector("#renewal-count"),
    billRows: document.querySelector("#bill-rows"),
    billForm: document.querySelector("#bill-form"),
    formHeading: document.querySelector("#form-heading"),
    formDescription: document.querySelector("#form-description"),
    cancelEdit: document.querySelector("#cancel-edit"),
    saveBill: document.querySelector("#save-bill"),
    runReview: document.querySelector("#run-review"),
    reviewDate: document.querySelector("#review-date"),
    windowDays: document.querySelector("#window-days"),
    runMcp: document.querySelector("#run-mcp"),
    mcpResult: document.querySelector("#mcp-result"),
    ragForm: document.querySelector("#rag-form"),
    ragQuery: document.querySelector("#rag-query"),
    runRag: document.querySelector("#run-rag"),
    ragResult: document.querySelector("#rag-result"),
    workflowForm: document.querySelector("#workflow-form"),
    workflowDate: document.querySelector("#workflow-date"),
    workflowDays: document.querySelector("#workflow-days"),
    runWorkflow: document.querySelector("#run-workflow"),
    workflowStatus: document.querySelector("#workflow-status"),
    workflowResult: document.querySelector("#workflow-result"),
    humanReviewForm: document.querySelector("#human-review-form"),
    workflowDecision: document.querySelector("#workflow-decision"),
    workflowNote: document.querySelector("#workflow-note"),
    workflowCorrection: document.querySelector("#workflow-correction"),
    workflowCorrectionLabel: document.querySelector("#workflow-correction-label"),
    submitWorkflowReview: document.querySelector("#submit-workflow-review"),
    workflowHistory: document.querySelector("#workflow-history"),
    openWorkflow: document.querySelector("#open-workflow"),
    refreshWorkflows: document.querySelector("#refresh-workflows"),
    workflowHistoryNote: document.querySelector("#workflow-history-note"),
    toast: document.querySelector("#toast"),
};

let bills = [];
let toastTimer;
let currentWorkflow = null;
let workflowBusy = false;
let workflowDisabled = false;

const moneyFormatter = new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
});

function formatMoney(value) {
    return moneyFormatter.format(Number(value));
}

function formatDate(value) {
    if (!value) return "—";

    return new Intl.DateTimeFormat("en-AU", {
        day: "numeric",
        month: "short",
        year: "numeric",
    }).format(new Date(`${value}T00:00:00`));
}

function countLabel(value, singular, plural = `${singular}s`) {
    const count = Number(value);
    return `${count} ${count === 1 ? singular : plural}`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function apiFetch(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, options);

    if (response.status === 204) return null;

    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
        const message = body.error
            || Object.values(body.errors || {})[0]
            || "The request could not be completed.";
        const error = new Error(message);
        error.status = response.status;
        error.body = body;
        throw error;
    }

    return body;
}

// Show whether the backend is available.
function setConnection(connected) {
    elements.connectionStatus.classList.toggle("connected", connected);
    elements.connectionStatus.classList.toggle("disconnected", !connected);
    elements.connectionStatus.querySelector("span:last-child").textContent = connected
        ? "Backend connected"
        : "Backend unavailable";
}

// Show a short success or error message.
function showToast(message, type = "success") {
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", type === "error");
    elements.toast.hidden = false;

    toastTimer = window.setTimeout(() => {
        elements.toast.hidden = true;
    }, 3600);
}

// Fill the summary cards.
function renderSummary(summary) {
    elements.monthlyCost.textContent = formatMoney(summary.monthly_cost);
    elements.annualCost.textContent = formatMoney(summary.annual_cost);
    elements.activeCount.textContent = summary.active_bill_count;
    elements.renewalCount.textContent = summary.auto_renew_count;
}

// Fill the table with saved bills.
function renderBills() {
    if (!bills.length) {
        elements.billRows.innerHTML = '<tr><td colspan="7" class="table-message">No bills have been added.</td></tr>';
        return;
    }

    elements.billRows.innerHTML = bills.map((bill) => `
        <tr>
            <td>
                <div class="bill-name">
                    <strong>${escapeHtml(bill.name)}</strong>
                    <span>${escapeHtml(bill.provider)}</span>
                </div>
            </td>
            <td>${escapeHtml(bill.category)}</td>
            <td>${formatMoney(bill.amount)}</td>
            <td>${escapeHtml(bill.billing_frequency)}</td>
            <td>${formatDate(bill.next_due_date)}</td>
            <td><span class="status-badge status-${escapeHtml(bill.status)}">${escapeHtml(bill.status)}</span></td>
            <td>
                <div class="row-actions">
                    <button class="row-button" type="button" data-action="edit" data-id="${bill.id}">Edit</button>
                    <button class="row-button row-button-danger" type="button" data-action="delete" data-id="${bill.id}">Delete</button>
                </div>
            </td>
        </tr>
    `).join("");
}

// Load the bills and summary together.
async function loadDashboard() {
    try {
        const [billData, summary] = await Promise.all([
            apiFetch("/bills"),
            apiFetch("/summary"),
        ]);

        bills = billData;
        renderBills();
        renderSummary(summary);
        setConnection(true);
    } catch (error) {
        setConnection(false);
        elements.billRows.innerHTML = `<tr><td colspan="7" class="table-message">${escapeHtml(error.message)}</td></tr>`;
        showToast(error.message, "error");
    }
}

// Return the form to add mode.
function resetForm() {
    elements.billForm.reset();
    document.querySelector("#bill-id").value = "";
    document.querySelector("#billing-frequency").value = "monthly";
    document.querySelector("#status").value = "active";
    elements.formHeading.textContent = "Add a bill";
    elements.formDescription.textContent = "Create a recurring payment or subscription.";
    elements.saveBill.textContent = "Save bill";
    elements.cancelEdit.hidden = true;
}

// Fill the form with an existing bill.
function editBill(billId) {
    const bill = bills.find((item) => item.id === billId);
    if (!bill) return;

    document.querySelector("#bill-id").value = bill.id;
    document.querySelector("#name").value = bill.name;
    document.querySelector("#provider").value = bill.provider;
    document.querySelector("#category").value = bill.category;
    document.querySelector("#amount").value = bill.amount;
    document.querySelector("#billing-frequency").value = bill.billing_frequency;
    document.querySelector("#next-due-date").value = bill.next_due_date;
    document.querySelector("#trial-end-date").value = bill.trial_end_date || "";
    document.querySelector("#status").value = bill.status;
    document.querySelector("#auto-renew").checked = Boolean(bill.auto_renew);
    document.querySelector("#notes").value = bill.notes || "";

    elements.formHeading.textContent = `Edit ${bill.name}`;
    elements.formDescription.textContent = "Update this recurring payment or subscription.";
    elements.saveBill.textContent = "Update bill";
    elements.cancelEdit.hidden = false;
    document.querySelector("#bill-editor").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Read the current bill form values.
function getFormPayload() {
    return {
        name: document.querySelector("#name").value,
        provider: document.querySelector("#provider").value,
        category: document.querySelector("#category").value,
        amount: Number(document.querySelector("#amount").value),
        billing_frequency: document.querySelector("#billing-frequency").value,
        next_due_date: document.querySelector("#next-due-date").value,
        auto_renew: document.querySelector("#auto-renew").checked,
        trial_end_date: document.querySelector("#trial-end-date").value || null,
        status: document.querySelector("#status").value,
        notes: document.querySelector("#notes").value,
    };
}

// Add a bill or save changes to one.
async function saveBill(event) {
    event.preventDefault();
    const billId = document.querySelector("#bill-id").value;
    const isEditing = Boolean(billId);
    elements.saveBill.disabled = true;

    try {
        await apiFetch(isEditing ? `/bills/${billId}` : "/bills", {
            method: isEditing ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(getFormPayload()),
        });

        showToast(isEditing ? "Bill updated." : "Bill added.");
        resetForm();
        await loadDashboard();
    } catch (error) {
        showToast(error.message, "error");
    } finally {
        elements.saveBill.disabled = false;
    }
}

// Remove a bill after confirmation.
async function deleteBill(billId) {
    const bill = bills.find((item) => item.id === billId);
    if (!bill || !window.confirm(`Delete ${bill.name}?`)) return;

    try {
        await apiFetch(`/bills/${billId}`, { method: "DELETE" });
        showToast("Bill deleted.");
        resetForm();
        await loadDashboard();
    } catch (error) {
        showToast(error.message, "error");
    }
}

// Replace one phase card with its result.
function setPhaseContent(id, html) {
    const card = document.querySelector(id);
    card.classList.add("complete");
    card.querySelector(".phase-content")?.remove();
    card.insertAdjacentHTML("beforeend", `<div class="phase-content">${html}</div>`);
}

// Show the results from all four phases.
function renderReview(review) {
    const priorities = review.plan.priority_order
        .map((priority) => escapeHtml(priority))
        .join(", ");

    setPhaseContent("#phase-plan", `
        <p class="phase-summary">Review strategy</p>
        <ul>
            <li>Review all ${countLabel(review.act.active_bill_count, "active bill")} from ${formatDate(review.plan.review_date)} to ${formatDate(review.plan.review_end_date)}.</li>
            <li>Flag payments due within ${review.plan.due_soon_days} days.</li>
            <li>Priority order: ${priorities}.</li>
        </ul>
        <div class="phase-meta">
            <span class="meta-chip">${review.plan.window_days} day window</span>
        </div>
    `);

    setPhaseContent("#phase-act", `
        <p class="phase-summary">Work completed</p>
        <ul>
            <li>Loaded ${countLabel(review.act.active_bill_count, "active bill and subscription record", "active bill and subscription records")}.</li>
            <li>Converted recurring charges into monthly and annual totals.</li>
            <li>Calculated days until payment and sorted bills by urgency.</li>
        </ul>
        <div class="phase-meta">
            <span class="meta-chip">${formatMoney(review.act.monthly_cost)} monthly</span>
            <span class="meta-chip">${formatMoney(review.act.annual_cost)} annually</span>
        </div>
    `);

    setPhaseContent("#phase-observe", `
        <p class="phase-summary">Findings</p>
        <ul>
            <li>${countLabel(review.observe.overdue.length, "overdue bill")} and ${countLabel(review.observe.due_soon.length, "payment")} due within ${review.plan.due_soon_days} days.</li>
            <li>${countLabel(review.observe.upcoming_auto_renewals.length, "automatic renewal")} in the review period.</li>
            <li>${countLabel(review.observe.expiring_trials.length, "trial")} ending in the review period.</li>
        </ul>
        <div class="phase-meta">
            <span class="meta-chip">${countLabel(review.observe.attention_count, "record")} ${review.observe.attention_count === 1 ? "needs" : "need"} attention</span>
        </div>
    `);

    const actions = review.adapt.actions
        .map((action) => `<li>${escapeHtml(action)}</li>`)
        .join("");
    const actionList = actions
        ? `<p class="phase-summary">Recommended next steps</p><ul>${actions}</ul>`
        : "";
    const fallback = review.adapt.summary_fallback_used
        ? '<span class="meta-chip">Safe summary used</span>'
        : `<span class="meta-chip">${escapeHtml(review.adapt.summary_tone)} tone</span>`;
    const model = review.adapt.llm_called
        ? `<span class="meta-chip">${escapeHtml(review.adapt.model_name)}</span>`
        : '<span class="meta-chip">No AI call needed</span>';

    setPhaseContent("#phase-adapt", `
        <p>${escapeHtml(review.adapt.summary)}</p>
        <p class="phase-priority"><strong>First priority:</strong> ${escapeHtml(review.adapt.priority.reason)}</p>
        ${actionList}
        <div class="phase-meta">
            ${model}
            ${fallback}
        </div>
    `);
}

// Ask the backend to run the full review.
async function runReview() {
    elements.runReview.disabled = true;
    elements.runReview.textContent = "Running review…";

    try {
        const review = await apiFetch("/bills/review", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                review_date: elements.reviewDate.value,
                window_days: Number(elements.windowDays.value),
            }),
        });

        renderReview(review);
        showToast("Agentic review completed.");
    } catch (error) {
        showToast(error.message, "error");
    } finally {
        elements.runReview.disabled = false;
        elements.runReview.textContent = "Run AI review";
    }
}

// Display the shared bills tool result.
async function runMcp() {
    elements.runMcp.disabled = true;
    elements.mcpResult.textContent = "Checking saved commitments…";
    try {
        const response = await apiFetch("/bills/mcp", { method: "POST" });
        const { summary, bills: toolBills } = response.result;
        elements.mcpResult.innerHTML = `
            <p><strong>Shared bill summary received</strong></p>
            <p>${escapeHtml(summary.active_bill_count)} active bills · ${formatMoney(summary.monthly_cost)} monthly · ${formatMoney(summary.annual_cost)} annually</p>
            <p>${escapeHtml(summary.auto_renew_count)} active automatic renewals.</p>
            <details>
                <summary>View ${toolBills.length} saved records</summary>
                <ul>${toolBills.map((bill) => `<li>${escapeHtml(bill.name)} — ${formatMoney(bill.amount)} ${escapeHtml(bill.billing_frequency)}, due ${formatDate(bill.next_due_date)}, ${escapeHtml(bill.status)}</li>`).join("")}</ul>
            </details>
            <details><summary>Structured tool result</summary><pre>${escapeHtml(JSON.stringify(response, null, 2))}</pre></details>
        `;
    } catch (error) {
        elements.mcpResult.textContent = error.message;
    } finally {
        elements.runMcp.disabled = false;
    }
}

// Show the answer together with its retrieved source excerpts.
async function runRag(event) {
    event.preventDefault();
    elements.runRag.disabled = true;
    elements.ragResult.textContent = "Looking for sources and preparing an answer…";
    try {
        const result = await apiFetch("/bills/rag", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: elements.ragQuery.value.trim(), k: 5 }),
        });
        const citations = result.citations.map((citation) => `
            <li><strong>${escapeHtml(citation.source_title || citation.source_id)}</strong> · ${escapeHtml(citation.chunk_id)}
                ${citation.source_url ? `<p><a href="${escapeHtml(citation.source_url)}" target="_blank" rel="noopener noreferrer">Official provider source</a> · Checked ${escapeHtml(citation.checked_on)}</p>` : ""}
                <blockquote>${escapeHtml(citation.excerpt)}</blockquote>
            </li>
        `).join("");
        const fallbackNotes = {
            model_abstention: "The model could not produce an answer. Relevant source wording is shown instead; check whether it answers your question.",
            provider_grounding: "Original reference wording is shown to keep provider details grounded in the source.",
            numerical_grounding: "The numerical explanation was replaced with the original source wording.",
        };
        elements.ragResult.innerHTML = `
            <p class="meta-chip">${result.status === "insufficient_context" ? "Insufficient context" : result.source_excerpt_fallback_used ? "Source excerpt" : "Sourced answer"} · ${escapeHtml(result.confidence_category)} confidence</p>
            <p class="rag-answer">${escapeHtml(result.answer)}</p>
            ${result.source_excerpt_fallback_used ? `<p class="assistant-note">${escapeHtml(fallbackNotes[result.source_excerpt_fallback_reason] || "Original source wording is shown.")}</p>` : ""}
            ${citations ? `<details><summary>Sources and retrieved context</summary><ul class="citation-list">${citations}</ul></details>` : ""}
            <p class="assistant-note">Confidence describes source coverage, not a guarantee of correctness.</p>
        `;
    } catch (error) {
        elements.ragResult.textContent = error.message;
    } finally {
        elements.runRag.disabled = false;
    }
}

// Give the three agents time to finish.
async function workflowFetch(path, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 210000);
    try {
        return await apiFetch(path, { ...options, signal: controller.signal });
    } catch (error) {
        if (controller.signal.aborted) {
            throw new Error("The review took too long. Refresh saved reviews before trying again.");
        }
        throw error;
    } finally {
        window.clearTimeout(timer);
    }
}

function setWorkflowBusy(busy) {
    workflowBusy = busy;
    for (const element of [
        elements.runWorkflow, elements.workflowDate, elements.workflowDays,
        elements.workflowDecision, elements.workflowNote, elements.workflowCorrection,
        elements.submitWorkflowReview, elements.workflowHistory, elements.refreshWorkflows,
    ]) {
        element.disabled = busy;
    }
    elements.openWorkflow.disabled = busy || !elements.workflowHistory.value;
    elements.runWorkflow.disabled = busy || workflowDisabled;
}

function setDecisionFields() {
    const decision = elements.workflowDecision.value;
    elements.workflowNote.required = decision === "partial";
    elements.workflowCorrection.required = decision === "correct";
    elements.workflowCorrectionLabel.hidden = decision !== "correct";
}

// Always show the original agent output beside any human correction.
function renderWorkflow(run) {
    currentWorkflow = run;
    elements.workflowDate.value = run.evidence.review_scope.review_date;
    elements.workflowDays.value = run.evidence.review_scope.window_days;
    const statusLabels = {
        planning: "Planner running",
        working: "Worker running",
        reviewing: "Reviewer running",
        awaiting_human: "Waiting for your decision",
        complete: "Human decision recorded",
        failed: "Review failed",
    };
    elements.workflowStatus.textContent = `${statusLabels[run.status] || run.status} · Review ${run.run_id}`;
    const steps = run.plan.map((step) => `
        <li>${escapeHtml(step.action)}
            <p class="assistant-note">Evidence: ${escapeHtml(step.evidence.join(", ") || "No evidence key named")}</p>
        </li>`).join("");
    const review = run.review || { risks: [], recommendations: [] };
    const list = (items, empty) => items.length
        ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : `<p>${escapeHtml(empty)}</p>`;
    const decisionLabels = {
        approve: "Approved", correct: "Corrected", partial: "Partially accepted", reject: "Rejected",
    };
    const human = run.human_review;
    const decision = human ? `
        <div class="workflow-decision-result">
            <h3>Human decision: ${escapeHtml(decisionLabels[human.decision] || human.decision)}</h3>
            <p>${escapeHtml(human.reviewer)} · ${escapeHtml(human.decided_at)}</p>
            ${human.note ? `<p class="workflow-text">${escapeHtml(human.note)}</p>` : ""}
            ${human.corrected ? `<h4>Human correction</h4><p class="workflow-text">${escapeHtml(human.corrected)}</p>` : ""}
            <p>No bill records were changed.</p>
        </div>` : "";
    const evidence = run.evidence;
    elements.workflowResult.innerHTML = `
        <p class="meta-chip">${escapeHtml(run.model)} · ${run.stub ? "Test agents" : "Local agents"}</p>
        ${run.stub ? '<p class="workflow-warning">Test mode: these are canned outputs, not a real model review. Use real agents for the final demonstration.</p>' : ""}
        ${run.status === "failed" ? `<p class="workflow-warning">${escapeHtml(run.error?.detail || run.error || "An agent could not finish. Start a new review when the server is available.")}</p>` : ""}
        <div class="workflow-phases">
            <article class="workflow-phase"><h3>1. Planner</h3><ol>${steps || "<li>No plan was completed.</li>"}</ol></article>
            <article class="workflow-phase"><h3>2. Worker</h3><div class="workflow-text">${escapeHtml(run.work || "No draft was completed.")}</div></article>
            <article class="workflow-phase"><h3>3. Reviewer</h3>
                <h4>Risks</h4>${list(review.risks, "No risks listed. This is not a guarantee of correctness.")}
                <h4>Recommendations</h4>${list(review.recommendations, "No recommendations listed.")}
            </article>
        </div>
        <p><strong>Evidence snapshot:</strong> ${formatDate(evidence.review_scope.review_date)} ·
            ${escapeHtml(evidence.cost_summary.active_bill_count)} active bills ·
            ${formatMoney(evidence.cost_summary.monthly_cost)} monthly ·
            ${formatMoney(evidence.cost_summary.annual_cost)} annually</p>
        <details><summary>Bill evidence used for this review</summary><pre>${escapeHtml(JSON.stringify(evidence, null, 2))}</pre></details>
        ${decision}
    `;
    elements.humanReviewForm.hidden = run.status !== "awaiting_human";
    elements.humanReviewForm.reset();
    setDecisionFields();
}

// Reload links saved by this Bills feature only.
async function loadWorkflows(preferred = currentWorkflow?.run_id) {
    elements.refreshWorkflows.disabled = true;
    try {
        const runs = await apiFetch("/bills/workflows");
        workflowDisabled = false;
        elements.runWorkflow.disabled = workflowBusy;
        elements.workflowHistory.innerHTML = runs.length
            ? runs.map((run) => `<option value="${escapeHtml(run.run_id)}">${escapeHtml(run.review_date)} · ${escapeHtml(run.run_id.slice(0, 8))}</option>`).join("")
            : '<option value="">No saved reviews</option>';
        if (preferred && runs.some((run) => run.run_id === preferred)) {
            elements.workflowHistory.value = preferred;
        }
        elements.workflowHistoryNote.textContent = "The latest 20 reviews are listed. Reopen one to see its original evidence and saved decision.";
    } catch (error) {
        elements.workflowHistoryNote.textContent = error.message;
        if (error.body?.disabled) {
            workflowDisabled = true;
            elements.workflowStatus.textContent = error.message;
            elements.runWorkflow.disabled = true;
        }
    } finally {
        elements.refreshWorkflows.disabled = workflowBusy;
        elements.openWorkflow.disabled = workflowBusy || !elements.workflowHistory.value;
    }
}

async function startWorkflow(event) {
    event.preventDefault();
    setWorkflowBusy(true);
    currentWorkflow = null;
    elements.workflowResult.textContent = "";
    elements.humanReviewForm.hidden = true;
    elements.workflowStatus.textContent = "The Planner, Worker and Reviewer are running. This can take a few minutes.";
    try {
        const run = await workflowFetch("/bills/workflows", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                review_date: elements.workflowDate.value,
                window_days: Number(elements.workflowDays.value),
            }),
        });
        renderWorkflow(run);
        await loadWorkflows(run.run_id);
    } catch (error) {
        elements.workflowStatus.textContent = error.message;
        if (error.body?.disabled) workflowDisabled = true;
        if (error.body?.run_id) {
            await loadWorkflows(error.body.run_id);
            elements.workflowStatus.textContent += " The failed review is saved; use Open review to inspect it.";
        }
    } finally {
        setWorkflowBusy(false);
    }
}

async function openWorkflow() {
    const runId = elements.workflowHistory.value;
    if (!runId) return;
    setWorkflowBusy(true);
    elements.humanReviewForm.hidden = true;
    elements.workflowStatus.textContent = "Loading the saved review…";
    try {
        renderWorkflow(await workflowFetch(`/bills/workflows/${encodeURIComponent(runId)}`));
    } catch (error) {
        currentWorkflow = null;
        elements.workflowResult.textContent = "";
        elements.workflowStatus.textContent = error.message;
    } finally {
        setWorkflowBusy(false);
    }
}

async function saveWorkflowDecision(event) {
    event.preventDefault();
    if (!currentWorkflow || currentWorkflow.status !== "awaiting_human") return;
    const runId = currentWorkflow.run_id;
    const decision = {
        decision: elements.workflowDecision.value,
        note: elements.workflowNote.value.trim(),
        corrected: elements.workflowDecision.value === "correct"
            ? elements.workflowCorrection.value.trim() : null,
    };
    setWorkflowBusy(true);
    elements.workflowStatus.textContent = "Saving your decision…";
    try {
        const result = await workflowFetch(`/bills/workflows/${encodeURIComponent(runId)}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(decision),
        });
        renderWorkflow({
            ...currentWorkflow, status: result.status,
            human_review: result.human_review,
        });
        showToast("Human decision saved. No bills were changed.");
    } catch (error) {
        elements.workflowStatus.textContent = `${error.message} Reopen this review to confirm its state before trying again.`;
        elements.humanReviewForm.hidden = true;
    } finally {
        setWorkflowBusy(false);
    }
}

// Connect the page buttons and forms.
elements.workflowForm.addEventListener("submit", startWorkflow);
elements.workflowDecision.addEventListener("change", setDecisionFields);
elements.humanReviewForm.addEventListener("submit", saveWorkflowDecision);
elements.openWorkflow.addEventListener("click", () => openWorkflow());
elements.refreshWorkflows.addEventListener("click", () => loadWorkflows());
elements.workflowHistory.addEventListener("change", () => {
    elements.openWorkflow.disabled = workflowBusy || !elements.workflowHistory.value;
});
elements.runMcp.addEventListener("click", runMcp);
elements.ragForm.addEventListener("submit", runRag);
elements.billForm.addEventListener("submit", saveBill);
elements.cancelEdit.addEventListener("click", resetForm);
elements.runReview.addEventListener("click", runReview);
document.querySelector("#new-bill").addEventListener("click", () => {
    resetForm();
    document.querySelector("#bill-editor").scrollIntoView({ behavior: "smooth", block: "start" });
});

elements.billRows.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;

    const billId = Number(button.dataset.id);
    if (button.dataset.action === "edit") editBill(billId);
    if (button.dataset.action === "delete") deleteBill(billId);
});

// Load the first dashboard view.
elements.reviewDate.value = new Date().toISOString().slice(0, 10);
elements.workflowDate.value = elements.reviewDate.value;
resetForm();
loadDashboard();
loadWorkflows();
