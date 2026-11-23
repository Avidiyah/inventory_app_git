// View: the TechFM OA+ reorder queue.
//
// Layer: views. Lists every item at or below its own threshold, deepest
// below first, and lets that threshold be retuned in place. Cards are
// full-width `details` stacked one per row, opened by a click, the same
// shape a work order uses. The 7-day dispensed figure rides the collapsed
// summary beside the on-hand count: the queue is scanned for what is both
// low and moving, and that question has to be answerable without opening
// anything.
//
// Every load -- first draw, Refresh, own save, live event -- builds the
// cards detached and patches the list in place (`morph.js`). A patch leaves
// alone what the user holds: a focused or typed field, a barcode block they
// added to or removed from, a message that is showing text. A card that left
// the list is removed even so, and the page says so.

import { apiListLowStock, apiSetLowStockThreshold } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { isDirty, keepPlace, morphInto } from "../morph.js";
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

const NO_LONGER_LOW = "An item you were editing is no longer low.";

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

// Live events coalesce: one background fetch at a time, one rerun queued
// behind it, so a bulk stock write costs two fetches rather than hundreds.
// `pending` settles when the queue behind it has drained, so a save that
// awaits its reload waits for the paint that includes its write.
let pending = null;
let rerun = false;

function quantityText(value) {
  // Matches the backend's `domain.receipt.format_quantity`: 3.00 -> 3.
  return String(Number(value));
}

// One full-width, click-to-open card, the same `details` + `summary` shape a
// work order uses. The summary carries only what the queue is read for --
// what it is, how much is left, how fast it moves -- and holds no control:
// a click anywhere in a `<summary>` toggles it, so an input there would
// fight the user. Every editable thing lives in the body below.
function buildCard(row) {
  const card = document.createElement("details");
  card.className = "low-stock-card";
  card.id = `low-stock-card-${row.id}`;
  card.dataset.id = row.id;
  // The pre-edit values, so a save can tell a changed barcode from an
  // untouched one without holding draft state in a module variable.
  card.dataset.barcode = row.barcode;
  card.dataset.barcodes = JSON.stringify(row.barcodes || []);
  card.innerHTML =
    `<summary class="low-stock-summary">` +
      `<span class="low-stock-title">${escapeHtml(row.name)}</span>` +
      `<span class="low-stock-count">${escapeHtml(quantityText(row.quantity))} on hand</span>` +
      `<span class="low-stock-usage">7-day used: ` +
        `${escapeHtml(quantityText(row.dispensed_last_7_days))}</span>` +
    `</summary>` +
    `<div class="low-stock-body">` +
      `<div class="low-stock-details">` +
        `<span>${escapeHtml(row.barcode)}</span>` +
        `<span>${escapeHtml(row.location)}</span>` +
        `<label class="low-stock-threshold">` +
          `<span>Warn at</span>` +
          `<input type="number" min="1" step="1" inputmode="numeric" ` +
            `class="low-stock-threshold-input" ` +
            `value="${escapeHtml(String(row.low_stock_threshold))}" ` +
            `aria-label="Low stock threshold for ${escapeHtml(row.name)}">` +
        `</label>` +
      `</div>` +
      `<p class="low-stock-row-message" aria-live="polite"></p>` +
      cardBodyHtml(row) +
    `</div>`;
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

// What a patch leaves as it is. The two message lines are found by tag and
// parent: `setMessage` replaces their class with the message type.
function skip(el) {
  if (el.matches("input, select, textarea")) return el === document.activeElement || isDirty(el);
  if (el.matches(".ls-barcode-rows[data-touched]")) return true;
  return el.localName === "p" && el.textContent !== ""
    && el.parentElement.classList.contains("low-stock-body");
}

// Cards holding input a patch cannot bring back if the card goes. A card in
// the middle of its own save is exempt: its input was just sent.
function heldCards() {
  return Array.from(listEl.querySelectorAll(".low-stock-card:not([data-saving])")).filter(
    (card) => card.querySelector(".ls-barcode-rows[data-touched]")
      || Array.from(card.querySelectorAll("input")).some(isDirty)
  );
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

// `reset` is a tab change: the user asked for a different list, so it is a
// first draw (no glow, nothing held). `background` is a live or own-save
// reload, which leaves an error or the no-longer-low message on the page.
function render({ reset = false, background = false } = {}) {
  const grouped = bucketRows(allRows);
  const chosen = activeBucket;

  // Never strand the user on an empty tab: keep the one they chose while it
  // still holds rows, otherwise fall to the first that does. This covers
  // both the initial load and a background reload that emptied the tab
  // under them.
  if (!grouped[activeBucket].length) {
    const firstFilled = BUCKETS.find(b => grouped[b.key].length);
    if (firstFilled) activeBucket = firstFilled.key;
  }
  paintTabs(grouped);

  const held = reset ? [] : heldCards();
  // Another tab's cards are not these cards changed: wipe, do not morph.
  if (reset || activeBucket !== chosen) listEl.replaceChildren();

  const rows = grouped[activeBucket];
  const tree = document.createElement("div");
  for (const row of rows) tree.append(buildCard(row));
  const restore = keepPlace(listEl);
  morphInto(listEl, tree.childNodes, { skip, flashSelector: ".low-stock-card" });
  restore();

  if (held.some(card => !card.isConnected)) {
    setMessage(messageEl, NO_LONGER_LOW, "error");
    return;
  }
  if (background && messageEl.className === "error") return;
  if (!allRows.length) setMessage(messageEl, "Nothing is below its threshold.", "success");
  else if (!rows.length) setMessage(messageEl, EMPTY_TEXT[activeBucket], "success");
  else setMessage(messageEl, "", "");
}

async function fetchAndRender(background) {
  const sequence = ++loadSequence;
  if (!background) setMessage(messageEl, "Loading low stock...", "");
  try {
    const rows = await apiListLowStock();
    if (sequence !== loadSequence) return;
    allRows = rows;
    render({ background });
  } catch (err) {
    if (sequence !== loadSequence) return;
    allRows = [];
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load low stock."), "error");
  }
}

export function loadLowStock({ background = false } = {}) {
  if (!listEl) return Promise.resolve();
  if (!background) return fetchAndRender(false);
  if (pending) {
    rerun = true;
    return pending;
  }
  pending = (async () => {
    do {
      rerun = false;
      await fetchAndRender(true);
    } while (rerun);
  })().finally(() => { pending = null; });
  return pending;
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
  // The card's own save may remove it; that is not "someone else".
  card.dataset.saving = "";
  try {
    await apiSetLowStockThreshold(card.dataset.id, value);
    input.defaultValue = String(value);
    setMessage(rowMessage, "Saved.", "success");
    // The row may no longer belong on the page -- a lowered threshold can
    // clear the condition entirely -- so reload rather than trusting the
    // card that is on screen.
    loadLowStock({ background: true }).finally(() => { delete card.dataset.saving; });
  } catch (err) {
    delete card.dataset.saving;
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
    render({ reset: true });
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
