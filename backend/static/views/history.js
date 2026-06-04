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
import { apiListTransactions, apiGetItemByBarcode } from "../api.js";
import { escapeHtml } from "../format.js";
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
    });
    renderHistory(data);
  } catch (error) {
    console.error("Failed to load transactions:", error);
  }
}

export function renderHistory(data) {
  const items = data.items || [];
  const total = data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
  updateHistoryState({ totalPages });

  const s = getHistoryState();

  historyTbody.innerHTML = "";

  if (items.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="6">No transactions found.</td>`;
    historyTbody.appendChild(row);
  } else {
    items.forEach(txn => {
      const row = document.createElement("tr");
      const timestamp = new Date(txn.created_at).toLocaleString();
      const type = txn.transaction_type;
      row.innerHTML = `
        <td>${escapeHtml(timestamp)}</td>
        <td>${escapeHtml(txn.item_name)} (${escapeHtml(txn.item_barcode)})</td>
        <td><span class="type-badge ${escapeHtml(type)}">${escapeHtml(type)}</span></td>
        <td>${escapeHtml(txn.quantity)}</td>
        <td>${escapeHtml(txn.work_order_number) || "—"}</td>
        <td>${escapeHtml(txn.username) || "—"}</td>
      `;
      historyTbody.appendChild(row);
    });
  }

  historyPageInfo.textContent = `Page ${s.page} of ${totalPages}`;
  historyPrevBtn.disabled = s.page <= 1;
  historyNextBtn.disabled = s.page >= totalPages;

  historyResults.hidden = false;
}

historyTabs.addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("sub-tab-btn")) {
    setHistoryTab(target.dataset.tab);
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
    updateHistoryState({ itemId: item.id, page: 1 });
    setMessage(historyItemMessage, `Showing transactions for "${item.name}".`, "success");
    loadHistory();
  } catch (err) {
    updateHistoryState({ itemId: null });
    historyResults.hidden = true;
    if (err && err.status === 404) {
      setMessage(historyItemMessage, "No item found with that barcode.", "error");
    } else {
      setMessage(historyItemMessage, "Could not connect to the server.", "error");
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
