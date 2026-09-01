// View: the TechFM OA+ reorder queue.
//
// Layer: views. Lists every item at or below its own threshold, deepest
// below first, and lets that threshold be retuned in place. The 7-day
// dispensed figure sits in the same action column as the threshold
// control on purpose: the number that answers "how fast is this moving"
// and the control that answers "when should it warn me" are read
// together or not at all.
//
// Rows are rebuilt from the server on every load. Nothing is patched in
// place, because a threshold edit can remove the row it was made on
// (lowering a threshold below the current count clears the condition),
// and a list that quietly kept such a row would be lying.

import { apiListLowStock, apiSetLowStockThreshold } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { cardBodyHtml } from "./lowStockCard.js";

const LOW_STOCK_CHANGED_EVENT = "item.low_stock.changed";
const LOW_STOCK_PAGE = "low-stock";

const listEl = document.getElementById("low-stock-list");
const messageEl = document.getElementById("low-stock-message");
const refreshBtn = document.getElementById("low-stock-refresh");
const tabsEl = document.getElementById("low-stock-tabs");

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEK_MS = 7 * DAY_MS;

// Labels live here rather than in the markup so the count can be appended
// without the view having to parse the text already on the button.
const BUCKETS = [
  { key: "day", label: "Last 24h" },
  { key: "week", label: "2-7 days" },
  { key: "stale", label: "Older or never" },
];

const EMPTY_TEXT = {
  day: "Nothing low was dispensed in the last 24 hours.",
  week: "Nothing low was dispensed in the last week.",
  stale: "Everything low has moved within the last week.",
};

// The whole queue, held so a tab switch is a filter rather than a fetch.
let allRows = [];
let activeBucket = "day";

// Guards against an out-of-order response overwriting a newer one: a
// realtime invalidation can land while a slower manual refresh is still
// in flight.
let loadSequence = 0;

function quantityText(value) {
  // Matches the backend's `domain.receipt.format_quantity`: 3.00 -> 3.
  return String(Number(value));
}

function buildCard(row) {
  const card = document.createElement("div");
  card.className = "low-stock-card";
  card.dataset.id = row.id;
  // The pre-edit values, so a save can tell a changed barcode from an
  // untouched one without holding draft state in a module variable.
  card.dataset.barcode = row.barcode;
  card.dataset.barcodes = JSON.stringify(row.barcodes || []);
  card.innerHTML =
    `<div class="low-stock-card-header">` +
      `<h3>${escapeHtml(row.name)}</h3>` +
      `<span class="low-stock-count">${escapeHtml(quantityText(row.quantity))} on hand</span>` +
    `</div>` +
    `<div class="low-stock-details">` +
      `<span>${escapeHtml(row.barcode)}</span>` +
      `<span>${escapeHtml(row.location)}</span>` +
    `</div>` +
    `<div class="low-stock-actions">` +
      `<span class="low-stock-usage">7-day used: ` +
        `${escapeHtml(quantityText(row.dispensed_last_7_days))}</span>` +
      `<label class="low-stock-threshold">` +
        `<span>Warn at</span>` +
        `<input type="number" min="1" step="1" inputmode="numeric" ` +
          `class="low-stock-threshold-input" ` +
          `value="${escapeHtml(String(row.low_stock_threshold))}" ` +
          `aria-label="Low stock threshold for ${escapeHtml(row.name)}">` +
      `</label>` +
    `</div>` +
    `<p class="low-stock-row-message" aria-live="polite"></p>` +
    cardBodyHtml(row);
  return card;
}

// Which tab a row belongs to. Boundaries are exclusive on purpose: an item
// dispensed an hour ago is in `day` and NOT also in `week`, so the three
// counts sum to the queue and no card is read twice. A missing or
// unparseable timestamp means "never dispensed", which is the oldest
// bucket -- not a hidden row.
function bucketOf(row, now) {
  if (!row.last_dispensed_at) return "stale";
  const at = Date.parse(row.last_dispensed_at);
  if (Number.isNaN(at)) return "stale";
  const age = now - at;
  if (age < DAY_MS) return "day";
  if (age < WEEK_MS) return "week";
  return "stale";
}

function bucketRows(rows) {
  const now = Date.now();
  const grouped = { day: [], week: [], stale: [] };
  // Server order (headroom ascending) is preserved: rows are appended in
  // the order they arrived and never re-sorted.
  for (const row of rows) grouped[bucketOf(row, now)].push(row);
  return grouped;
}

// A background reload rebuilds every card, which would slam shut an editor
// the user is typing in. Remember which ones were open by item id and
// reopen them after the rebuild.
function openCardIds() {
  return new Set(
    Array.from(listEl.querySelectorAll("details.low-stock-more[open]"))
      .map(el => el.dataset.id)
  );
}

function restoreOpenCards(ids) {
  if (!ids.size) return;
  for (const el of listEl.querySelectorAll("details.low-stock-more")) {
    if (ids.has(el.dataset.id)) el.open = true;
  }
}

function paintTabs(grouped) {
  if (!tabsEl) return;
  for (const { key, label } of BUCKETS) {
    const btn = tabsEl.querySelector(`.sub-nav-btn[data-bucket="${key}"]`);
    if (!btn) continue;
    btn.textContent = `${label} (${grouped[key].length})`;
    btn.classList.toggle("active", key === activeBucket);
  }
}

function render() {
  const grouped = bucketRows(allRows);

  // Never strand the user on an empty tab: keep the one they chose while it
  // still holds rows, otherwise fall to the first that does. This covers
  // both the initial load and a background reload that emptied the tab
  // under them.
  if (!grouped[activeBucket].length) {
    const firstFilled = BUCKETS.find(b => grouped[b.key].length);
    if (firstFilled) activeBucket = firstFilled.key;
  }
  paintTabs(grouped);

  const open = openCardIds();
  listEl.replaceChildren();

  if (!allRows.length) {
    setMessage(messageEl, "Nothing is below its threshold.", "success");
    return;
  }

  const rows = grouped[activeBucket];
  if (!rows.length) {
    setMessage(messageEl, EMPTY_TEXT[activeBucket], "success");
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(buildCard(row));
  listEl.append(fragment);
  restoreOpenCards(open);
  setMessage(messageEl, "", "");
}

export async function loadLowStock({ background = false } = {}) {
  if (!listEl) return;
  const sequence = ++loadSequence;
  if (!background) setMessage(messageEl, "Loading low stock...", "");
  try {
    const rows = await apiListLowStock();
    if (sequence !== loadSequence) return;
    allRows = rows;
    render();
  } catch (err) {
    if (sequence !== loadSequence) return;
    allRows = [];
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load low stock."), "error");
  }
}

// Commit on blur and on Enter, not on every keystroke: a threshold typed
// as "20" passes through "2", which would fire a push for a crossing the
// operator never intended.
async function commitThreshold(input) {
  const card = input.closest(".low-stock-card");
  const rowMessage = card.querySelector(".low-stock-row-message");
  const previous = input.defaultValue;
  const value = Number(input.value);

  if (!Number.isInteger(value) || value < 1) {
    input.value = previous;
    setMessage(rowMessage, "Threshold must be a whole number of at least 1.", "error");
    return;
  }
  if (String(value) === previous) return;

  input.disabled = true;
  try {
    await apiSetLowStockThreshold(card.dataset.id, value);
    input.defaultValue = String(value);
    setMessage(rowMessage, "Saved.", "success");
    // The row may no longer belong on the page -- a lowered threshold can
    // clear the condition entirely -- so reload rather than trusting the
    // card that is on screen.
    loadLowStock({ background: true });
  } catch (err) {
    input.value = previous;
    setMessage(rowMessage, friendlyError(err, "Could not save that threshold."), "error");
  } finally {
    input.disabled = false;
  }
}

if (listEl) {
  listEl.addEventListener("blur", (event) => {
    if (event.target.classList.contains("low-stock-threshold-input")) {
      commitThreshold(event.target);
    }
  }, true);

  listEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.classList.contains("low-stock-threshold-input")) {
      event.preventDefault();
      event.target.blur();
    }
  });
}

if (tabsEl) {
  tabsEl.addEventListener("click", (event) => {
    const btn = event.target.closest(".sub-nav-btn");
    if (!btn || !btn.dataset.bucket || btn.dataset.bucket === activeBucket) return;
    activeBucket = btn.dataset.bucket;
    // Filter, do not refetch: the queue in hand is the same queue.
    render();
  });
}

if (refreshBtn) refreshBtn.addEventListener("click", () => loadLowStock());

// A matching invalidation or a recovered connection both mean the queue
// may be stale. Inactive pages need no dirty flag: `nav.js` reloads this
// page on entry.
subscribe(LOW_STOCK_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== LOW_STOCK_PAGE) return;
  return loadLowStock({ background: true });
});
