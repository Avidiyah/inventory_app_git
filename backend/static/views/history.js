// View: transaction history page (all / by item / by user tabs).
//
// Layer: views. Owns the history page with three sub-tabs and a
// paginated results table. The tab + filter + page are persisted
// in `state.historyState` so switching to another page and back
// preserves the user's place.
//
// Public surface:
// - `setHistoryTab(tab)` -- switch sub-tab; called by `main.js`
//   on boot (`"all"`) and by the tab buttons here.
// - `loadHistory()` -- fetch one page using current filters;
//   called by `nav.js` on page activation and by the controls
//   here on every state change.
// - `renderHistory(data)` -- paint the table from a fetched page.
//
// The "by item" tab looks up the item by barcode first, so a 404
// from `apiGetItemByBarcode` is rendered as a friendly message
// rather than a generic error.

import {
  getHistoryState,
  updateHistoryState,
  HISTORY_PAGE_SIZE,
} from "../state.js";
import { apiListTransactions, apiGetItemByBarcode, apiVoidTransaction } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const historyTabs = document.getElementById("history-tabs");
const historyAllPanel = document.getElementById("history-all-panel");
const historyItemPanel = document.getElementById("history-item-panel");
const historyUserPanel = document.getElementById("history-user-panel");
const historyItemBarcode = document.getElementById("history-item-barcode");
const historyItemLookupBtn = document.getElementById("history-item-lookup-btn");
const historyItemMessage = document.getElementById("history-item-message");
const historyUserSelect = document.getElementById("history-user-select");
const historyUserMessage = document.getElementById("history-user-message");
const historyResults = document.getElementById("history-results");
const historyTbody = document.getElementById("history-tbody");
const historyPrevBtn = document.getElementById("history-prev-btn");
const historyNextBtn = document.getElementById("history-next-btn");
const historyPageInfo = document.getElementById("history-page-info");
const historyWoFilter = document.getElementById("history-wo-filter");
const historyWoClearBtn = document.getElementById("history-wo-clear-btn");
const historyCopyBtn = document.getElementById("history-copy-btn");
const historyCopyMessage = document.getElementById("history-copy-message");

// Backend cap (see app/routers/transactions.py) -- the copy-all path
// uses this to minimise round-trips.
const MAX_PAGE_SIZE = 100;
// Hard ceiling on the copy-all loop so a runaway dataset can't hang
// the browser. 100 pages * 100 rows = 10 000 rows.
const COPY_MAX_PAGES = 100;

export function setHistoryTab(tab) {
  updateHistoryState({ tab, page: 1 });

  historyTabs.querySelectorAll(".sub-tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });

  historyAllPanel.hidden = tab !== "all";
  historyItemPanel.hidden = tab !== "item";
  historyUserPanel.hidden = tab !== "user";

  setMessage(historyItemMessage, "", "");
  setMessage(historyUserMessage, "", "");

  loadHistory();
}

export async function loadHistory() {
  const s = getHistoryState();

  if (s.tab === "item" && !s.itemId) {
    historyResults.hidden = true;
    return;
  }
  if (s.tab === "user" && !s.userId) {
    historyResults.hidden = true;
    return;
  }

  try {
    const data = await apiListTransactions({
      page: s.page,
      pageSize: HISTORY_PAGE_SIZE,
      itemId: s.tab === "item" ? s.itemId : null,
      userId: s.tab === "user" ? s.userId : null,
      workOrder: s.workOrder,
    });
    renderHistory(data);
  } catch (error) {
    console.error("Failed to load transactions:", error);
  }
}

// Compose the empty-state cell text from the currently-active filters
// so the user can see *why* the table is empty rather than a generic
// "No transactions found."
function emptyStateMessage(s) {
  const clauses = [];
  if (s.workOrder) clauses.push(`WO "${s.workOrder}"`);
  if (s.tab === "item" && s.itemLabel) clauses.push(`item ${s.itemLabel}`);
  if (s.tab === "user" && historyUserSelect.selectedOptions[0]) {
    const label = historyUserSelect.selectedOptions[0].textContent;
    if (label && historyUserSelect.value) clauses.push(`user ${label}`);
  }
  if (clauses.length === 0) return "No history found for those filters.";
  return `No history matches ${clauses.join(" and ")}.`;
}

// Single source of truth for how a transaction row is rendered.
// Returns the six column values, in display order, as plain strings
// (no HTML). Used by both the on-screen table render and the
// copy-to-clipboard TSV builder so the two never drift apart.
function formatRow(txn) {
  const timestamp = new Date(txn.created_at).toLocaleString();
  const item = `${txn.item_name} (${txn.item_barcode})`;
  const type = txn.transaction_type;
  const quantity = String(txn.quantity);
  // The fifth column is overloaded: for stock/dispense it shows the
  // work order number; for adjust (correction) rows it shows the
  // required reason. This avoids a separate column for a field that
  // is only ever populated on adjust rows.
  const detail = type === "adjust"
    ? (txn.reason || txn.work_order_number || "")
    : (txn.work_order_number || "");
  const user = txn.username || "";
  return [timestamp, item, type, quantity, detail, user];
}

// Friendly on-screen labels for the type badge. The CSS class stays the
// raw type (stock/dispense/adjust) so the badge colour is unchanged; only
// the visible text is humanised. TSV export keeps the raw type via formatRow.
const TYPE_LABELS = { stock: "Added", dispense: "Taken Out", adjust: "Correction" };

export function renderHistory(data) {
  const items = data.items || [];
  const total = data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
  updateHistoryState({ totalPages });

  const s = getHistoryState();

  historyTbody.innerHTML = "";

  if (items.length === 0) {
    const row = document.createElement("tr");
    const text = emptyStateMessage(s);
    row.innerHTML = `<td colspan="7">${escapeHtml(text)}</td>`;
    historyTbody.appendChild(row);
  } else {
    items.forEach(txn => {
      const [timestamp, itemLabel, type, quantity, detail, user] = formatRow(txn);
      const row = document.createElement("tr");
      // Every role that can reach this page is Supervisor or above
      // (PAGE_ACCESS gates History at supervisor), which is exactly the
      // set allowed to void, so the button needs no per-row role check.
      const voidLabel = `Void ${TYPE_LABELS[type] || type} of ${quantity} for ${txn.item_name}`;
      row.innerHTML = `
        <td data-label="Time">${escapeHtml(timestamp)}</td>
        <td data-primary>${escapeHtml(itemLabel)}</td>
        <td data-label="Type"><span class="type-badge ${escapeHtml(type)}">${escapeHtml(TYPE_LABELS[type] || type)}</span></td>
        <td data-label="Quantity">${escapeHtml(quantity)}</td>
        <td data-label="Work Order">${escapeHtml(detail || "—")}</td>
        <td data-label="User">${escapeHtml(user || "—")}</td>
        <td data-label="Actions"><button type="button" class="void-txn-btn btn-danger" data-id="${escapeHtml(txn.id)}" aria-label="${escapeHtml(voidLabel)}">Delete</button></td>
      `;
      historyTbody.appendChild(row);
    });
  }

  historyPageInfo.textContent = `Page ${s.page} of ${totalPages}`;
  historyPrevBtn.disabled = s.page <= 1;
  historyNextBtn.disabled = s.page >= totalPages;
  historyCopyBtn.disabled = items.length === 0;

  historyResults.hidden = false;
}

historyTabs.addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("sub-tab-btn")) {
    setHistoryTab(target.dataset.tab);
  }
});

// Void (delete) a mis-clicked transaction. Delegated so it covers every
// re-rendered row. The backend reverses the stock effect and hides the
// row from history; we just confirm and reload the current view.
historyTbody.addEventListener("click", async (event) => {
  const btn = event.target.closest(".void-txn-btn");
  if (!btn) return;
  const id = btn.dataset.id;
  if (!id) return;

  if (!confirm(
    "Delete this transaction?\n\nThis undoes its effect on the on-hand count and removes it from history."
  )) return;

  btn.disabled = true;
  try {
    await apiVoidTransaction(id);
    // If this was the only row left on a page past the first, step back
    // so the user doesn't land on an empty page.
    const s = getHistoryState();
    const remaining = historyTbody.querySelectorAll(".void-txn-btn").length;
    if (remaining <= 1 && s.page > 1) {
      updateHistoryState({ page: s.page - 1 });
    }
    loadHistory();
  } catch (err) {
    btn.disabled = false;
    alert(friendlyError(err, "Could not delete the transaction. Try again."));
  }
});

historyItemLookupBtn.addEventListener("click", async () => {
  const barcode = historyItemBarcode.value.trim();
  setMessage(historyItemMessage, "", "");

  if (!barcode) {
    setMessage(historyItemMessage, "Enter a barcode to look up.", "error");
    return;
  }

  try {
    const item = await apiGetItemByBarcode(barcode);
    updateHistoryState({
      itemId: item.id,
      itemLabel: `${item.name} (${item.barcode})`,
      page: 1,
    });
    setMessage(historyItemMessage, `Showing transactions for "${item.name}".`, "success");
    loadHistory();
  } catch (err) {
    updateHistoryState({ itemId: null, itemLabel: null });
    historyResults.hidden = true;
    if (err && err.status === 404) {
      setMessage(historyItemMessage, "No item found with that barcode.", "error");
    } else {
      setMessage(historyItemMessage, friendlyError(err, "Look-up failed. Try again."), "error");
    }
  }
});

historyUserSelect.addEventListener("change", () => {
  updateHistoryState({ userId: historyUserSelect.value || null, page: 1 });
  setMessage(historyUserMessage, "", "");
  loadHistory();
});

historyPrevBtn.addEventListener("click", () => {
  const s = getHistoryState();
  if (s.page > 1) {
    updateHistoryState({ page: s.page - 1 });
    loadHistory();
  }
});

historyNextBtn.addEventListener("click", () => {
  const s = getHistoryState();
  if (s.page < s.totalPages) {
    updateHistoryState({ page: s.page + 1 });
    loadHistory();
  }
});

// --- Work-order overlay filter ----------------------------------

let woDebounceTimer = null;

function applyWoFilter(value) {
  const trimmed = (value || "").trim();
  updateHistoryState({ workOrder: trimmed || null, page: 1 });
  loadHistory();
}

historyWoFilter.addEventListener("input", () => {
  // Debounce so we don't fire a request per keystroke. 250 ms feels
  // responsive without being chatty.
  clearTimeout(woDebounceTimer);
  woDebounceTimer = setTimeout(() => applyWoFilter(historyWoFilter.value), 250);
});

historyWoClearBtn.addEventListener("click", () => {
  clearTimeout(woDebounceTimer);
  historyWoFilter.value = "";
  applyWoFilter("");
});

// --- Copy table to clipboard ------------------------------------
//
// Copies *all* rows matching the current filters (not just the visible
// page) so a spreadsheet paste reflects what the user is filtering on.
// We paginate the existing list endpoint at the backend's max page
// size; no new endpoint is needed.

const HISTORY_HEADERS = ["Timestamp", "Item", "Type", "Quantity", "Work Order", "User"];

// Strip newlines and tabs from a cell so the TSV columns stay aligned
// when pasted into Excel / Google Sheets.
function sanitiseCell(value) {
  return String(value).replace(/[\t\r\n]+/g, " ");
}

function rowsToTsv(rows) {
  const lines = [HISTORY_HEADERS.join("\t")];
  for (const row of rows) {
    lines.push(row.map(sanitiseCell).join("\t"));
  }
  return lines.join("\n");
}

async function fetchAllMatchingRows() {
  const s = getHistoryState();
  const all = [];
  let page = 1;
  let total = Infinity;
  while (all.length < total && page <= COPY_MAX_PAGES) {
    const data = await apiListTransactions({
      page,
      pageSize: MAX_PAGE_SIZE,
      itemId: s.tab === "item" ? s.itemId : null,
      userId: s.tab === "user" ? s.userId : null,
      workOrder: s.workOrder,
    });
    const batch = data.items || [];
    all.push(...batch);
    total = data.total || 0;
    if (batch.length === 0) break;  // safety: avoid infinite loop
    page += 1;
  }
  if (page > COPY_MAX_PAGES && all.length < total) {
    console.warn(
      `Copy stopped at ${all.length}/${total} rows (capped at ${COPY_MAX_PAGES} pages).`
    );
  }
  return all;
}

async function copyTextToClipboard(text) {
  // Prefer the async Clipboard API; it only works in secure contexts
  // (https / localhost), so fall back to a hidden textarea + execCommand
  // when it's blocked or absent.
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn("navigator.clipboard.writeText failed; falling back.", err);
    }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (err) {
    console.warn("execCommand('copy') threw.", err);
  }
  document.body.removeChild(ta);
  return ok;
}

historyCopyBtn.addEventListener("click", async () => {
  setMessage(historyCopyMessage, "Copying…", "");
  historyCopyBtn.disabled = true;
  try {
    const rows = await fetchAllMatchingRows();
    if (rows.length === 0) {
      setMessage(historyCopyMessage, "Nothing to copy.", "error");
      return;
    }
    const tsv = rowsToTsv(rows.map(formatRow));
    const ok = await copyTextToClipboard(tsv);
    if (ok) {
      setMessage(historyCopyMessage, "Copied history.", "success");
    } else {
      setMessage(historyCopyMessage, "Copy failed — your browser blocked clipboard access.", "error");
    }
  } catch (err) {
    console.error("Copy table failed:", err);
    setMessage(historyCopyMessage, "Copy failed — could not fetch all rows.", "error");
  } finally {
    // Re-enable based on whether the visible table has any rows; the
    // button being disabled forever after a transient failure would
    // be a confusing dead end.
    historyCopyBtn.disabled = historyTbody.children.length === 0
      || (historyTbody.children.length === 1
          && historyTbody.firstElementChild.querySelector("td[colspan]"));
  }
});
