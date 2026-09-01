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
    toast: document.querySelector("#toast"),
};

let bills = [];
let toastTimer;

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
        throw new Error(message);
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

// Connect the page buttons and forms.
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
resetForm();
loadDashboard();
