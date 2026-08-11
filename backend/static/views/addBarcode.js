// View: add a scanned barcode to an existing item (Find Item page).
//
// Layer: views. Opens when a Find Item scan returns 404 and the user
// picks the "Add Barcode" shortcut instead of "Create Item" (see
// views/scan.js::handleUnknownBarcode). The panel lets the user find an
// existing item *by name* and attach the just-scanned code to it as an
// additional barcode, reusing the multi-barcode endpoint.
//
// Public surface (mirrors itemEditor.js / notes.js):
// - `openAddBarcode(barcode)` stores the scanned code and reveals the panel.
// - `closeAddBarcode()` hides it (cancel / success).
// - `setOnSaved(fn)` lets the items view refresh the table after a save.
//
// The scanned code came back 404, so no *live* item owns it. It may still
// belong to an *archived* item, in which case the append gets a 409 and
// confirmArchivedReuse prompts ("Barcode exists but is archived. Continue?")
// before retrying with override_archived; a genuine race still backstops
// with DuplicateBarcodeError, surfaced via friendlyError.

import { apiListItems, apiUpdateBarcodes, apiGetItemByBarcode } from "../api.js";
import { escapeHtml, friendlyError, filterRanked } from "../format.js";
import { setMessage, confirmArchivedReuse, confirmDialog } from "../dom.js";

const section = document.getElementById("add-barcode-section");
const scannedEl = document.getElementById("add-barcode-scanned");
const searchEl = document.getElementById("add-barcode-search");
const resultsEl = document.getElementById("add-barcode-results");
const cancelBtn = document.getElementById("add-barcode-cancel-btn");
const messageEl = document.getElementById("add-barcode-message");

const MAX_RESULTS = 8;

let pendingBarcode = null;
let onSavedCallback = null;
let candidateItems = [];
let searchTimer = null;
let searchRequestId = 0;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openAddBarcode(barcode) {
  searchRequestId += 1;
  clearTimeout(searchTimer);
  candidateItems = [];
  pendingBarcode = barcode;
  scannedEl.innerHTML = `Scanned code: <strong>${escapeHtml(barcode)}</strong>`;
  searchEl.value = "";
  setMessage(messageEl, "", "");
  renderResults();
  section.hidden = false;
  section.scrollIntoView({ behavior: "smooth", block: "start" });
  searchEl.focus();
}

export function closeAddBarcode() {
  searchRequestId += 1;
  clearTimeout(searchTimer);
  candidateItems = [];
  pendingBarcode = null;
  section.hidden = true;
  resultsEl.innerHTML = "";
  resultsEl.hidden = true;
  setMessage(messageEl, "", "");
}

// Search by name without depending on Find Item's result cache. The API may
// also match barcodes, so the returned rows are narrowed to name matches here.
//
// That narrowing MUST use `filterRanked`, the same rule the backend applies.
// A raw `includes(term)` post-filter would discard exactly the rows the
// punctuation-insensitive server search just found -- typing `2x4` would have
// the API return `2"x4"` and this filter throw it straight back out, turning
// partial results into none at all.
function renderResults() {
  const term = searchEl.value.trim().toLowerCase();
  clearTimeout(searchTimer);
  const requestId = ++searchRequestId;
  candidateItems = [];
  resultsEl.innerHTML = "";
  if (!term) {
    resultsEl.hidden = true;
    return;
  }

  resultsEl.innerHTML = `<p class="hint">Loading…</p>`;
  resultsEl.hidden = false;
  searchTimer = setTimeout(() => loadResults(term, requestId), 200);
}

async function loadResults(term, requestId) {
  try {
    const items = await apiListItems({ query: term });
    if (requestId !== searchRequestId) return;
    // Re-ranked on the name alone: the API ordered these by relevance across
    // name AND barcode, which is the wrong ordering once barcode hits are
    // dropped.
    candidateItems = filterRanked(items, item => [item.name], term)
      .slice(0, MAX_RESULTS);
    resultsEl.innerHTML = "";

    if (candidateItems.length === 0) {
      resultsEl.innerHTML = `<p class="hint">No items match that name.</p>`;
      return;
    }

    candidateItems.forEach(item => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "scan-choice-btn";
      btn.dataset.id = item.id;
      // textContent (not innerHTML): item fields are user-supplied.
      btn.textContent = `${item.name}  ·  ${item.barcode}  ·  ${item.location}`;
      resultsEl.appendChild(btn);
    });
  } catch (error) {
    if (requestId !== searchRequestId) return;
    resultsEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(error, "Could not search items. Try again."))}</p>`;
  }
}

searchEl.addEventListener("input", renderResults);
cancelBtn.addEventListener("click", closeAddBarcode);

resultsEl.addEventListener("click", async (event) => {
  const btn = event.target.closest(".scan-choice-btn");
  if (!btn) return;
  const item = candidateItems.find(i => i.id === btn.dataset.id);
  if (!item || !pendingBarcode) return;

  if (!(await confirmDialog(`Add barcode ${pendingBarcode} to "${item.name}"?`))) return;
  setMessage(messageEl, "Adding…", "");

  try {
    // Re-fetch the item fresh so we don't clobber additional barcodes added
    // since the cache loaded -- PATCH /items/{id}/barcodes is a wholesale
    // replace, so we must send the *current* full list plus the new code.
    const fresh = await apiGetItemByBarcode(item.barcode);
    const existing = Array.isArray(fresh.barcodes) ? fresh.barcodes : [];
    // A 404 lookup means no *live* item owns the code, but an *archived* one
    // still can -- that's a 409 here, which confirmArchivedReuse prompts on
    // and retries with override_archived to free the archived holder.
    await confirmArchivedReuse((override) =>
      apiUpdateBarcodes(item.id, [...existing, pendingBarcode], override)
    );
    setMessage(messageEl, `Added ${pendingBarcode} to ${item.name}.`, "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeAddBarcode, 1200);
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(messageEl, "", "");
      return;
    }
    setMessage(messageEl, friendlyError(err, "Could not add the barcode. Try again."), "error");
  }
});
