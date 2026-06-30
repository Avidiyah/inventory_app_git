// View: transaction history page (all / by item / by user tabs).
//
// Layer: views. Owns the history page with three sub-tabs and a
// paginated results table. The sub-tabs use the shared in-page sub-nav
// helper (`views/subnav.js`): each is a `.feature-panel`, and the
// `#history-results` table sits outside them so it persists across all
// three. The tab + filter + page are persisted in `state.historyState`
// so switching to another page and back preserves the user's place.
//
// Public surface:
// - `setHistoryTab(tab)` -- switch sub-tab; a thin wrapper over the
//   sub-nav's `showFeature`. Called by `auth.js` to prime `"all"` on
//   login; the tab buttons themselves are wired by `initSubNav`.
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
  getRole,
  HISTORY_PAGE_SIZE,
} from "../state.js";
import {
  apiListTransactions,
  apiGetItemByBarcode,
  apiVoidTransaction,
  apiSetBillableQuantity,
  apiGetWorkOrder,
  apiListWorkOrders,
} from "../api.js";
import { escapeHtml, friendlyError, formatMoney } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { setMessage } from "../dom.js";
import { initSubNav } from "./subnav.js";

const historyPage = document.getElementById("history-page");
const historyTable = document.getElementById("history-table");
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

// History's three sub-tabs (All / By Item / By User) are sibling features
// switched via the shared in-page sub-nav helper. `fireInitialOnShow: false`
// because this module is imported at app boot: the onShow hook fetches a page,
// which must wait until the user has logged in and opened the History page
// (nav.js calls loadHistory() on activation; auth.js primes "all" on login).
const historySubNav = initSubNav(historyPage, {
  fireInitialOnShow: false,
  onShow(feature) {
    updateHistoryState({ tab: feature, page: 1 });
    setMessage(historyItemMessage, "", "");
    setMessage(historyUserMessage, "", "");
    loadHistory();
  },
});

// Retained as a thin compatibility wrapper over the sub-nav so external
// callers (auth.js primes "all" on login) don't need to know about the helper.
export function setHistoryTab(tab) {
  historySubNav.showFeature(tab);
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

// --- Billing / charge maths (Admin/Owner-only Charge column) -------
//
// Every Charge figure flows from three numbers on a row: the per-unit
// `item_price`, the recorded `quantity`, and the Admin's optional
// `billable_quantity` override (how many units to actually charge for).
// All three are backend-gated to Admin/Owner, so lower roles never reach
// this code path (the column is hidden for them).

// Fixed company mark-up applied on top of the line total. 1.15 = +15%.
const MARKUP_RATE = 1.15;

// The number of units to charge for: the override when set, else the full
// recorded quantity. `billable_quantity` is null when no override exists.
function effectiveBillable(txn) {
  const b = txn.billable_quantity;
  return (b === null || b === undefined) ? Number(txn.quantity) : Number(b);
}

// Bundle the numbers the Charge cell + copy export need, or null when the
// item has no price (nothing to charge). `editable` gates the inline
// editor to billable row types — an `adjust` correction is not a charge.
function chargeData(txn) {
  const hasPrice = txn.item_price !== null && txn.item_price !== undefined;
  const unit = hasPrice ? Number(txn.item_price) : null;
  const quantity = Number(txn.quantity);
  const billable = effectiveBillable(txn);
  const base = hasPrice ? unit * billable : null;
  const marked = hasPrice ? base * MARKUP_RATE : null;
  const editable = hasPrice
    && (txn.transaction_type === "stock" || txn.transaction_type === "dispense");
  return { id: txn.id, unit, quantity, billable, base, marked, editable };
}

// Render the *display* state of the Charge cell (not the editor): the
// line total, the marked-up total, an override flag when billable differs
// from the recorded quantity, and the "Edit charge" button when editable.
// Pulled out so the editor's Cancel can repaint the cell without a reload.
function chargeDisplayHtml(c) {
  if (c.unit === null) return "—";
  let html =
    `<span class="charge-base">${escapeHtml(formatMoney(c.base))}</span>` +
    `<span class="charge-marked">+15%: ${escapeHtml(formatMoney(c.marked))}</span>`;
  if (c.billable !== c.quantity) {
    html += c.billable === 0
      ? `<span class="charge-flag not-charged">Not charged</span>`
      : `<span class="charge-flag">Billing ${escapeHtml(String(c.billable))} of ${escapeHtml(String(c.quantity))}</span>`;
  }
  if (c.editable) {
    html += `<button type="button" class="edit-charge-btn" data-id="${escapeHtml(c.id)}">Edit charge</button>`;
  }
  return html;
}

// The full <td> for the Charge column. Carries `data-quantity` /
// `data-billable` so the inline editor can read them without re-fetching.
function chargeCellHtml(txn) {
  const c = chargeData(txn);
  return `<td class="admin-col charge-cell" data-label="Charge" ` +
    `data-quantity="${escapeHtml(String(c.quantity))}" ` +
    `data-billable="${escapeHtml(String(c.billable))}">` +
    `${chargeDisplayHtml(c)}</td>`;
}

export function renderHistory(data) {
  const items = data.items || [];
  const total = data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));
  updateHistoryState({ totalPages });

  const s = getHistoryState();

  // The Charge column (line total + mark-up, plus the inline billing
  // editor) is Admin/Owner only. Toggle the header column to match the
  // cells we emit; the backend redacts `item_price` / `billable_quantity`
  // for lower roles, so this is presentational only.
  const canSeePrice = roleAtLeast(getRole(), "admin");
  historyTable.querySelectorAll("thead .admin-col").forEach(th => { th.hidden = !canSeePrice; });
  // Base table is 7 columns (Time, Item, Type, Qty, WO, User, Actions);
  // the Charge column adds one for Admin/Owner.
  const colCount = canSeePrice ? 8 : 7;

  historyTbody.innerHTML = "";

  if (items.length === 0) {
    const row = document.createElement("tr");
    const text = emptyStateMessage(s);
    row.innerHTML = `<td colspan="${colCount}">${escapeHtml(text)}</td>`;
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
        ${canSeePrice ? chargeCellHtml(txn) : ""}
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

// --- Inline billing editor (Admin/Owner) ------------------------
//
// Lets an Admin reviewing a work order charge for fewer units than were
// dispensed, or exclude a line entirely, without disturbing the on-hand
// count (the items were really used). The edit swaps the Charge cell for
// a small form: Save / Don't charge call the billing endpoint and reload;
// Cancel repaints the cell in place from the data-* it was built with.

function billingEditorHtml(quantity, billable) {
  return `
    <div class="charge-editor">
      <label class="charge-editor-label">Bill for
        <input type="number" class="charge-input" min="0" max="${escapeHtml(String(quantity))}" step="any" value="${escapeHtml(String(billable))}">
        of ${escapeHtml(String(quantity))}
      </label>
      <div class="charge-editor-actions">
        <button type="button" class="charge-save">Save</button>
        <button type="button" class="charge-zero secondary-btn">Don't charge</button>
        <button type="button" class="charge-cancel secondary-btn">Cancel</button>
      </div>
      <p class="charge-editor-msg" aria-live="polite"></p>
    </div>`;
}

historyTbody.addEventListener("click", (event) => {
  const editBtn = event.target.closest(".edit-charge-btn");
  if (!editBtn) return;

  const cell = editBtn.closest(".charge-cell");
  if (!cell) return;

  const id = editBtn.dataset.id;
  const quantity = Number(cell.dataset.quantity);
  const billable = Number(cell.dataset.billable);
  const original = cell.innerHTML;

  cell.innerHTML = billingEditorHtml(quantity, billable);
  const input = cell.querySelector(".charge-input");
  const msg = cell.querySelector(".charge-editor-msg");
  input.focus();
  input.select();

  function restore() { cell.innerHTML = original; }

  async function submit(value) {
    // `value` is the billable count, or null to clear the override.
    cell.querySelectorAll("button").forEach(b => { b.disabled = true; });
    try {
      await apiSetBillableQuantity(id, value);
      loadHistory();  // repaint the whole table from fresh data
    } catch (err) {
      cell.querySelectorAll("button").forEach(b => { b.disabled = false; });
      setMessage(msg, friendlyError(err, "Could not update the charge."), "error");
    }
  }

  cell.querySelector(".charge-cancel").addEventListener("click", restore);
  cell.querySelector(".charge-zero").addEventListener("click", () => submit(0));
  cell.querySelector(".charge-save").addEventListener("click", () => {
    const raw = input.value.trim();
    if (raw === "") { submit(null); return; }  // empty = charge the full amount
    const n = Number(raw);
    if (Number.isNaN(n) || n < 0 || n > quantity) {
      setMessage(msg, `Enter a number between 0 and ${quantity}.`, "error");
      return;
    }
    // Billing the full quantity is the same as having no override; send
    // null so the row carries no stale "Billing N of N" annotation.
    submit(n === quantity ? null : n);
  });
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

// The six columns shown to every role, mirroring `formatRow`. Admin/Owner
// get four extra Charge columns appended (see PRICE_HEADERS) so a pasted
// invoice worksheet carries the billable count, unit price, line total,
// and the marked-up total.
const BASE_HEADERS = ["Timestamp", "Item", "Type", "Quantity", "Work Order", "User"];
const PRICE_HEADERS = ["Billable Qty", "Unit Price", "Price x Qty", "Price x Qty x 1.15"];

// Strip newlines and tabs from a cell so the TSV columns stay aligned
// when pasted into Excel / Google Sheets.
function sanitiseCell(value) {
  return String(value).replace(/[\t\r\n]+/g, " ");
}

// Build the clipboard TSV. `includePrice` (Admin/Owner) appends the four Charge
// columns. `woPrices` (workOrderId -> itemId -> unit price) fills per-row pricing
// for work-order rows: the history row suppresses `item_price` so the on-screen
// charge stays on the line, but the export still wants a price on every line.
// Only material-out rows (stock/dispense) are priced this way -- an `adjust`
// correction is a signed inventory delta, not a charge, so it stays blank.
function buildTsv(txns, includePrice, woPrices) {
  const headers = includePrice ? [...BASE_HEADERS, ...PRICE_HEADERS] : BASE_HEADERS;
  const lines = [headers.join("\t")];
  for (const txn of txns) {
    let cols = formatRow(txn);
    if (includePrice) {
      let c = chargeData(txn);
      if (
        c.unit === null
        && txn.work_order_id
        && (txn.transaction_type === "stock" || txn.transaction_type === "dispense")
        && woPrices
      ) {
        const unit = woPrices.get(txn.work_order_id)?.get(txn.item_id);
        if (unit !== undefined) {
          const qty = Number(txn.quantity);
          c = { ...c, unit, billable: qty, base: unit * qty, marked: unit * qty * MARKUP_RATE };
        }
      }
      cols = cols.concat([
        String(c.billable),
        c.unit === null ? "" : formatMoney(c.unit),
        c.base === null ? "" : formatMoney(c.base),
        c.marked === null ? "" : formatMoney(c.marked),
      ]);
    }
    lines.push(cols.map(sanitiseCell).join("\t"));
  }
  return lines.join("\n");
}

// Fetch each distinct work order referenced by the export (Admin/Owner only) and
// derive two things from its authoritative line data:
//   - `prices`: workOrderId -> (itemId -> current unit price), used to fill
//     per-row pricing for work-order rows (the history row itself suppresses
//     `item_price` so the on-screen charge lives on the line, not the row).
//   - `summary`: a "Work Order Summary" TSV block, one line per work order with
//     its `materials_total` (override-aware) and that total +15%.
// A work order that can't be loaded (e.g. archived since) is skipped rather than
// failing the whole copy.
async function fetchWorkOrderBilling(txns) {
  // Group the referenced work orders by NUMBER (always present on a history row).
  // A row's `work_order_id` is kept when available as a fast path, but resolving
  // by number is what lets the summary cover rows that carry only a number --
  // legacy/pre-rebuild dispenses whose `work_order_id` is NULL.
  const groups = new Map(); // numberKey -> { number, id }
  for (const t of txns) {
    const num = (t.work_order_number || "").trim();
    if (!num) continue;
    const key = num.toLowerCase();
    const g = groups.get(key) || { number: num, id: null };
    if (!g.id && t.work_order_id) g.id = t.work_order_id;
    groups.set(key, g);
  }

  const prices = new Map(); // work_order_id -> (item_id -> unit price)
  const summaryRows = [];
  for (const { number, id } of groups.values()) {
    try {
      let woId = id;
      if (!woId) {
        // Resolve the number to its work order (identity is the number).
        const matches = await apiListWorkOrders({ q: number });
        const exact = (matches || []).find(
          (w) => (w.number || "").trim().toLowerCase() === number.toLowerCase()
        );
        if (!exact) continue;
        woId = exact.id;
      }
      const wo = await apiGetWorkOrder(woId);

      const itemPrices = new Map();
      for (const li of wo.items || []) {
        if (li.unit_price !== null && li.unit_price !== undefined) {
          itemPrices.set(li.item_id, Number(li.unit_price));
        }
      }
      prices.set(woId, itemPrices);

      // Prefer the server's authoritative total; fall back to summing the lines
      // (effective billable * unit price) if it wasn't provided.
      let base = wo.materials_total;
      base = (base === null || base === undefined)
        ? (wo.items || []).reduce((sum, li) => {
            const price = (li.unit_price === null || li.unit_price === undefined) ? 0 : Number(li.unit_price);
            const qty = (li.billable_quantity === null || li.billable_quantity === undefined)
              ? Number(li.quantity) : Number(li.billable_quantity);
            return sum + price * qty;
          }, 0)
        : Number(base);
      summaryRows.push([wo.number, formatMoney(base), formatMoney(base * MARKUP_RATE)]);
    } catch (err) {
      console.warn(`Work order billing: could not load "${number}"`, err);
    }
  }

  let summary = "";
  if (summaryRows.length > 0) {
    const header = ["Work Order", "Total", "Total +15%"].join("\t");
    const body = summaryRows.map((r) => r.map(sanitiseCell).join("\t")).join("\n");
    summary = `\n\nWork Order Summary\n${header}\n${body}`;
  }
  return { prices, summary };
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
    const includePrice = roleAtLeast(getRole(), "admin");
    // Admin/Owner exports: fetch each referenced work order once for per-row
    // pricing (work-order rows suppress `item_price`) and the appended summary.
    const woBilling = includePrice
      ? await fetchWorkOrderBilling(rows)
      : { prices: null, summary: "" };
    const tsv = buildTsv(rows, includePrice, woBilling.prices) + woBilling.summary;
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
