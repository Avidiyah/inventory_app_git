// View: transaction (stock/dispense) page.
//
// Layer: views. Owns the Transaction page's scan-and-go batch flow:
// a work-order gate, then an active batch where items are added
// either by camera/upload scan (views/scan.js) or by the manual
// entry panel below (search-and-pick, or browse-all for an
// opted-in Supervisor+). Both paths funnel through the single
// `commitScannedItem` commit function so every addition -- scanned
// or manual -- posts to the same active work order the same way.

import { getRole, getCurrentUser } from "../state.js";
import { apiListItems, apiCreateTransaction, apiListWorkOrders, apiGetWorkOrder, apiStartWorkOrder, apiVoidTransaction } from "../api.js";
import { escapeHtml, friendlyError, matchesSearch } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { roleAtLeast } from "../roles.js";
import { showPage } from "./nav.js";
import { focusWorkOrder } from "./workOrders.js";

// --- Scan-and-go (work-order batch) elements --------------------
const woGate = document.getElementById("wo-gate");
const woGateInput = document.getElementById("wo-gate-input");
const woGateMessage = document.getElementById("wo-gate-message");
const scangoActive = document.getElementById("scango-active");
const scangoWoLabel = document.getElementById("scango-wo-label");
const scangoChangeWoBtn = document.getElementById("scango-change-wo-btn");
const scangoType = document.getElementById("scango-type");
const scangoDirection = document.getElementById("scango-direction");
const scangoSegStock = document.querySelector(".scango-seg-stock");
const scangoSegDispense = document.querySelector(".scango-seg-dispense");
const scangoDirectionFixed = document.getElementById("scango-direction-fixed");
const scangoAdvancedToggle = document.getElementById("scango-advanced-toggle");
const scangoQuickmodeToggle = document.getElementById("scango-quickmode-toggle");
const scangoQuantity = document.getElementById("scango-quantity");
const scangoSummary = document.getElementById("scango-summary");
const scangoLog = document.getElementById("scango-log");
const scangoMessage = document.getElementById("scango-message");
const txnScanSection = document.getElementById("txn-scan-section");
const txnManualSection = document.getElementById("txn-manual-section");
const txnItemSearch = document.getElementById("txn-item-search");
const txnItemSearchResults = document.getElementById("txn-item-search-results");

// Cards-first gate: saved work-order cards (all roles, server-scoped) plus a
// Supervisor+ number filter -- technicians scan only assigned cards.
// Work orders are import-only, so both surfaces ATTACH to an existing work
// order; neither can bring one into existence (the quick-add form that used to
// live here is gone).
const woGateCardsSection = document.getElementById("wo-gate-cards-section");
const woGateCards = document.getElementById("wo-gate-cards");
const woGateCardsMessage = document.getElementById("wo-gate-cards-message");
const woGateSearchCard = document.getElementById("wo-gate-search-card");
// Item list for the manual entry panel (search, or browse-all in advanced
// mode), loaded once per session and kept in sync with committed quantities
// (see commitScannedItem) so it never needs a refetch mid-batch.
let searchItems = [];
let searchItemsLoaded = false;

// Injected by main.js so changing the work order can stop the live camera
// without this module importing the scan view (keeps the dependency
// one-way: scan -> transactions).
let resetScanUi = null;
export function setScanResetter(fn) {
  resetScanUi = fn;
}

// Injected by main.js: start the live camera when a batch begins, but only
// if permission is already granted (never prompts). Same one-way dependency
// (scan -> transactions) as resetScanUi.
let scanAutoStart = null;
export function setScanAutostarter(fn) {
  scanAutoStart = fn;
}

function isTechnician() {
  // Technician is the only role below Supervisor that can reach this page.
  return !roleAtLeast(getRole(), "supervisor");
}

function setScangoType(value) {
  scangoType.value = value;
  if (scangoSegStock) scangoSegStock.classList.toggle("active", value === "stock");
  if (scangoSegDispense) scangoSegDispense.classList.toggle("active", value === "dispense");
  persistBatch(); // no-op while at the gate (persistBatch guards on batchWorkOrder)
}

// Show the gate or the active batch, and apply role visibility. By default
// Supervisor+ get the same streamlined dispense-only flow as a Technician; the
// `#scango-advanced-toggle` opt-in (Supervisor+ only) reveals the Stock/Dispense
// toggle plus browse-all in the manual entry panel.
function showScanGoState() {
  const tech = isTechnician();
  const active = batchWorkOrder !== null;
  // "advanced" = a Supervisor+ who has opted in. Everyone else (Technicians,
  // and Supervisor+ by default) gets the streamlined dispense-only view.
  const advanced = !tech && supervisorAdvanced;

  if (woGate) woGate.hidden = active;
  if (scangoActive) scangoActive.hidden = !active;
  if (txnScanSection) txnScanSection.hidden = !active;
  if (txnManualSection) txnManualSection.hidden = !active;

  // Saved work-order cards: shown to all roles on the gate (State A); the
  // server scopes the list (technician -> assigned, supervisor -> created).
  if (woGateCardsSection) woGateCardsSection.hidden = active;
  // The live number filter is Supervisor+ only; a technician selects from the
  // server-scoped cards assigned to them.
  if (woGateSearchCard) woGateSearchCard.hidden = tech || active;

  // Opt-in control: Supervisor+ only, and only inside an active batch.
  if (scangoAdvancedToggle) {
    scangoAdvancedToggle.hidden = tech || !active;
    scangoAdvancedToggle.textContent = advanced ? "Hide manual entry" : "Manual entry & stock options";
    scangoAdvancedToggle.setAttribute("aria-expanded", advanced ? "true" : "false");
  }

  // Quick-mode toggle: every role, only inside an active batch (unlike
  // advanced mode, this isn't Supervisor+ gated -- see the toggle's HTML
  // comment for why).
  if (scangoQuickmodeToggle) {
    scangoQuickmodeToggle.hidden = !active;
    scangoQuickmodeToggle.textContent = quickMode ? "Quick mode: On" : "Quick mode: Off";
    scangoQuickmodeToggle.setAttribute("aria-pressed", quickMode ? "true" : "false");
  }

  // Direction control: toggle only in advanced mode; otherwise the fixed
  // "Taking out stock" indicator, with the type pinned to dispense.
  if (scangoDirection) scangoDirection.hidden = !advanced;
  if (scangoDirectionFixed) scangoDirectionFixed.hidden = advanced;
  if (!advanced) setScangoType("dispense");

  // The manual entry panel itself is always visible inside an active batch
  // (every role can search); only its browse-all behavior depends on
  // `advanced`, handled by renderManualResults().
  renderManualResults();
}

// Load the item list once per session for the manual entry panel.
async function loadSearchItems() {
  if (searchItemsLoaded) return;
  try {
    searchItems = await apiListItems();
    searchItemsLoaded = true;
  } catch {
    searchItems = [];
  }
}

// Render the manual entry results: a name/barcode search filter for every
// role, plus a browse-all list (empty search) for an opted-in Supervisor+.
// Called on every keystroke, on advanced-mode toggle, and on batch state
// changes -- always safe to call, self-gates on current state.
function renderManualResults() {
  if (!txnItemSearch || !txnItemSearchResults) return;
  const query = txnItemSearch.value.trim().toLowerCase();
  const advanced = !isTechnician() && supervisorAdvanced;

  let matches;
  if (query) {
    matches = searchItems
      .filter((it) => matchesSearch([it.name, it.barcode], query))
      .slice(0, 8);
  } else if (advanced) {
    matches = [...searchItems].sort((a, b) => a.name.localeCompare(b.name));
  } else {
    matches = [];
  }

  if (!matches.length) {
    txnItemSearchResults.innerHTML = query ? `<p class="hint">No matching items.</p>` : "";
    txnItemSearchResults.hidden = !query;
    return;
  }

  txnItemSearchResults.innerHTML = matches
    .map((it) => {
      const meta = [`Barcode: ${escapeHtml(it.barcode)}`, `On hand: ${escapeHtml(it.quantity)}`];
      if (it.location) meta.push(`Location: ${escapeHtml(it.location)}`);
      return `<button type="button" class="manual-item-card" data-item-id="${escapeHtml(it.id)}">
                <span class="manual-item-name">${escapeHtml(it.name)}</span>
                <span class="manual-item-meta">${meta.map((m) => `<span>${m}</span>`).join("")}</span>
              </button>`;
    })
    .join("");
  txnItemSearchResults.hidden = false;
}

function clearItemSearch() {
  if (txnItemSearch) txnItemSearch.value = "";
  renderManualResults();
}

function clearBatchLog() {
  batchScanCount = 0;
  batchUnitCount = 0;
  batchLog = [];
  if (scangoLog) {
    scangoLog.innerHTML = "";
    scangoLog.hidden = true;
  }
  if (scangoSummary) {
    scangoSummary.textContent = "";
    scangoSummary.hidden = true;
  }
}

// `undo`, when set, is `{txnId, itemId, quantity, type}` for a saved batch line.
// The backend lets a Technician remove only their own work-order dispense;
// Supervisor+ retain the broader void contract.
// `retry`, when set, is `{itemId, itemName, quantity, type}` on a
// failed line -- the payload the Retry button re-posts (see the retry handler).
// `undone` re-applies the strike-through on a restored line -- the undo
// handler marks the entry so the state survives the batch snapshot (the
// "— Undone" text alone would otherwise read like a normal commit).
function renderLogLine(text, ok, undo, retry, undone, warning = false) {
  const line = document.createElement("div");
  line.className = `scango-log-line ${warning ? "scango-log-warning" : ok ? "scango-log-ok" : "scango-log-err"}`;
  if (undone) line.classList.add("scango-log-undone");
  const span = document.createElement("span");
  span.className = "scango-log-text";
  // textContent, not innerHTML -- item names are untrusted.
  span.textContent = text;
  line.appendChild(span);
  if (undo) {
    const undoBtn = document.createElement("button");
    undoBtn.type = "button";
    undoBtn.className = "scango-log-undo-btn secondary-btn";
    undoBtn.textContent = "Remove";
    undoBtn.dataset.txnId = undo.txnId;
    line.appendChild(undoBtn);
  }
  if (retry) {
    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "scango-log-retry-btn secondary-btn";
    retryBtn.textContent = "Retry";
    line.appendChild(retryBtn);
  }
  return line;
}

function appendLogLine(text, ok, undo, retry, warning = false) {
  // Kept in parallel with the DOM (newest first, same order) so the batch
  // snapshot (see persistBatch) can restore it after a reload. The array index
  // and the DOM child index stay in lockstep -- the retry handler relies on it.
  batchLog.unshift({ text, ok, undo: undo || null, retry: retry || null, warning });
  if (!scangoLog) return;
  scangoLog.prepend(renderLogLine(text, ok, undo, retry, false, warning));
  scangoLog.hidden = false;
}

// Rebuild the log from a resumed batch's saved lines (already newest-first).
function restoreBatchLog(lines) {
  batchLog = Array.isArray(lines) ? lines : [];
  if (!scangoLog) return;
  scangoLog.innerHTML = "";
  batchLog.forEach(({ text, ok, undo, retry, undone, warning }) => scangoLog.appendChild(renderLogLine(text, ok, undo, retry, undone, warning)));
  scangoLog.hidden = batchLog.length === 0;
}

function updateSummary() {
  if (!scangoSummary) return;
  const scans = `${batchScanCount} ${batchScanCount === 1 ? "scan" : "scans"}`;
  scangoSummary.textContent = `This work order: ${scans}, ${batchUnitCount} units`;
  scangoSummary.hidden = false;
}

// Active work order `{id, number}`, or null while the gate (State A) is showing.
let batchWorkOrder = null;
// Running tallies for the current work order's on-screen summary.
let batchScanCount = 0;
let batchUnitCount = 0;
// Log lines in on-screen order (newest first) -- kept alongside the DOM so
// persistBatch can snapshot it; see appendLogLine/restoreBatchLog.
let batchLog = [];
// Supervisor+ opt-in: false = same streamlined dispense-only flow as a
// Technician; true = reveal the direction toggle + manual entry browse-all.
// Technicians can never flip this. Reset to false on each fresh login.
let supervisorAdvanced = false;
// Every role's opt-in: skip the per-scan confirm dialog for a dispense
// (never for stock -- see commitScannedItem). Reset to false on each fresh
// login/logout, same lifetime as supervisorAdvanced.
let quickMode = false;

// --- Batch persistence (survive reload/tab eviction/phone sleep) --------
// A reload with a still-valid session cookie re-runs auth.js's boot check,
// which used to unconditionally drop the active batch. This snapshot lets
// that boot path resume instead, as long as the same user's session comes
// back and the work order is confirmed still one the gate would offer (see
// tryResumeBatch). Never trusted blindly -- only read back through that
// validation path, never applied directly.
const BATCH_STORAGE_KEY = "scango-batch";

function persistBatch() {
  const user = getCurrentUser();
  if (!batchWorkOrder || !user) return;
  try {
    sessionStorage.setItem(BATCH_STORAGE_KEY, JSON.stringify({
      userId: user.id,
      workOrder: batchWorkOrder,
      scangoType: scangoType ? scangoType.value : "dispense",
      quickMode,
      batchScanCount,
      batchUnitCount,
      log: batchLog,
    }));
  } catch {
    // sessionStorage can throw (private browsing, quota) -- the batch just
    // won't survive a reload; nothing else depends on this succeeding.
  }
}

function clearSavedBatch() {
  try {
    sessionStorage.removeItem(BATCH_STORAGE_KEY);
  } catch {
    /* nothing to clean up if storage isn't available */
  }
}

function readSavedBatch() {
  try {
    const raw = sessionStorage.getItem(BATCH_STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    return saved && saved.workOrder && saved.workOrder.id ? saved : null;
  } catch {
    return null;
  }
}

// Start a batch on an already-resolved In-Progress work order
// `{id, number, status}` from a tapped card. Assigned cards can be started in
// place through the narrow start endpoint; Created cards still need assignment
// on the Work Orders page. The search field only filters cards.
function startBatchFor(workOrder) {
  cancelWoSearch();
  woCardsRequestId += 1; // ignore a filter response that was already in flight
  // Keep the persisted batch snapshot small even when the start endpoint
  // returned a full WorkOrderDetail.
  batchWorkOrder = {
    id: workOrder.id,
    number: workOrder.number,
    status: workOrder.status,
  };
  clearBatchLog();
  setMessage(woGateMessage, "", "");
  if (scangoWoLabel) scangoWoLabel.textContent = `Work order: ${workOrder.number}`;
  // Quantity defaults to 1 so the batch is armed without typing; the operator
  // taps the field only to opt into a different amount.
  if (scangoQuantity) scangoQuantity.value = "1";
  // Default to dispense (the common work-order job is taking parts out);
  // Supervisor+ can toggle to Add Stock. Techs are forced to dispense in
  // showScanGoState regardless.
  setScangoType("dispense");
  clearItemSearch();
  loadSearchItems().then(renderManualResults);
  showScanGoState();
  // Bring the camera up immediately so the first thing after the work order
  // is a live scanner (only if permission is already granted; otherwise the
  // manual "Scan Barcode" button remains).
  if (scanAutoStart) scanAutoStart();
}

async function selectWorkOrderForBatch(workOrder) {
  if (workOrder.status === "in_progress") {
    startBatchFor(workOrder);
    return;
  }
  if (workOrder.status === "assigned") {
    const shouldStart = await confirmDialog(
      `Start WO ${workOrder.number}? This will set it to In-Progress.`
    );
    if (!shouldStart) return;
    setMessage(woGateMessage, "Starting work order...", "");
    try {
      const started = await apiStartWorkOrder(workOrder.id);
      startBatchFor(started);
    } catch (err) {
      setMessage(woGateMessage, friendlyError(err, "Could not start that work order."), "error");
      refreshWoCards();
    }
    return;
  }
  const goToWorkOrder = await confirmDialog(
    `WO ${workOrder.number} is not assigned. Go to Work Orders to assign it?`
  );
  if (!goToWorkOrder) return;
  focusWorkOrder(workOrder.id);
  showPage("work-orders");
}

async function changeWorkOrder() {
  if (
    batchScanCount > 0 &&
    !(await confirmDialog("Start a new work order? This clears the list below. Saved scans stay in history."))
  ) {
    return;
  }
  if (scangoMessage) setMessage(scangoMessage, "", "");
  batchWorkOrder = null;
  clearSavedBatch();
  if (resetScanUi) resetScanUi(); // stop the camera + clear the scan message
  clearBatchLog();
  clearItemSearch();
  if (woGateInput) woGateInput.value = "";
  resetWoCards();
  showScanGoState();
  refreshWoCards();
  if (woGateInput && !isTechnician()) woGateInput.focus();
}

// --- Saved work-order cards ---------------------------------------
// The scan gate shows Created/Assigned/In-Progress cards this user can see
// (server-scoped). Supervisor+ can filter those cards by number as they type.
// Tapping In-Progress starts a batch; Assigned confirms an in-place start;
// Created prompts a trip to Work Orders for assignment.
// Scanning is a plain transaction on the work order; nothing is written back to
// a mass stage (the stage stays the plan/load record). Every card here came from
// the work-order CSV import -- the gate can only attach to what was imported.

let woCardsRequestId = 0;
let woSearchTimer = null;

function cancelWoSearch() {
  if (woSearchTimer !== null) {
    clearTimeout(woSearchTimer);
    woSearchTimer = null;
  }
}

function resetWoCards() {
  woCardsRequestId += 1;
  if (woGateCards) woGateCards.innerHTML = "";
  if (woGateCardsMessage) setMessage(woGateCardsMessage, "", "");
  if (woGateMessage) setMessage(woGateMessage, "", "");
}

function renderWoCards(workOrders, query = "") {
  if (!woGateCards) return;
  woGateCards.innerHTML = "";
  if (!workOrders.length) {
    const empty = query
      ? `No work orders match “${query}”.`
      : isTechnician()
        ? "No work orders assigned to you."
        : "No ready work orders. Import the work-order CSV to add them.";
    setMessage(woGateCardsMessage, empty, "");
    return;
  }
  setMessage(woGateCardsMessage, "", "");
  const showAssignee = !isTechnician(); // a tech's cards are all their own
  workOrders.forEach((w) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `wo-card wo-card-status-${w.status}`;
    card.dataset.wo = w.number;
    card.dataset.woId = w.id;
    card.dataset.woStatus = w.status;
    const assignee = showAssignee
      ? `<span class="wo-card-assignee">${
          w.assigned_to_name ? "Assigned: " + escapeHtml(w.assigned_to_name) : "Unassigned"
        }</span>`
      : "";
    const place = [
      w.community,
      w.building_number ? `Bldg ${w.building_number}` : "",
      w.unit_number ? `Unit ${w.unit_number}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    card.innerHTML =
      `<span class="wo-card-wo">WO ${escapeHtml(w.number)}</span>` +
      `<span class="wo-card-status-label">${escapeHtml({ created: "Created", assigned: "Assigned", in_progress: "In-Progress" }[w.status] || w.status)}</span>` +
      `<span class="wo-card-meta">${escapeHtml(place || "—")}</span>` +
      assignee;
    woGateCards.appendChild(card);
  });
}

// Fetch + render the cards, only while the gate is showing (no active batch).
// Supervisor+ sends the trimmed number filter through the existing server-side
// `q` contract. A request id prevents a slow earlier response from repainting a
// newer search. Called on page activation, live filter input, and gate return.
async function refreshWoCards() {
  if (batchWorkOrder !== null || !woGateCards) return;
  const query = !isTechnician() && woGateInput ? woGateInput.value.trim() : "";
  const requestId = ++woCardsRequestId;
  setMessage(woGateCardsMessage, query ? "Searching…" : "Loading work orders…", "");
  try {
    const workOrders = (await apiListWorkOrders({ q: query || null })).filter(
      (workOrder) => ["created", "assigned", "in_progress"].includes(workOrder.status)
    );
    if (requestId !== woCardsRequestId || batchWorkOrder !== null) return;
    renderWoCards(workOrders, query);
  } catch (err) {
    if (requestId !== woCardsRequestId || batchWorkOrder !== null) return;
    setMessage(woGateCardsMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

function scheduleWoSearch({ immediate = false } = {}) {
  cancelWoSearch();
  woCardsRequestId += 1; // invalidate any response for the previous input value
  if (woGateMessage) setMessage(woGateMessage, "", "");
  const delay = immediate || !woGateInput || !woGateInput.value.trim() ? 0 : 250;
  woSearchTimer = setTimeout(() => {
    woSearchTimer = null;
    refreshWoCards();
  }, delay);
}

// Gate consulted by the scanner before it commits a decode (see
// views/scan.js `canScan`): refuse unless a batch is active and a
// positive quantity is set.
export function scanGoArmed() {
  if (batchWorkOrder === null) return false;
  const quantity = scangoQuantity ? parseFloat(scangoQuantity.value) : NaN;
  return Number.isFinite(quantity) && quantity > 0;
}

// Per-scan confirmation with an inline quantity stepper (#11): resolves the
// chosen count (Yes) or false (No / Esc / backdrop). Passing `quantity` turns
// the shared `dom.confirmDialog` into quantity mode, so the operator adjusts
// the amount here instead of the page field below the camera. The live decoder
// stays paused while this is open because handleLiveAccept awaits the whole
// resolve+commit chain before starting its dwell timer (see
// docs/current-state.md), so there are never stacked modals.
function confirmScan(message, quantity) {
  return confirmDialog(message, { quantity });
}

// Commit an item (scanned or manually picked) into the active work order.
// Returns `{committed, declined}` so callers know whether to start a
// same-barcode cooldown (scan.js) and whether to buzz. Never throws --
// failures are surfaced in the log and the camera/panel stay usable.
export async function commitScannedItem(item) {
  // Seed the quantity from the page field (armed to 1 by default, see
  // scanGoArmed); the confirm modal's stepper can bump it before commit.
  let quantity = scangoQuantity ? parseFloat(scangoQuantity.value) : NaN;
  if (batchWorkOrder === null || !Number.isFinite(quantity) || quantity <= 0) {
    return { committed: false };
  }
  const type = scangoType.value; // "stock" | "dispense"

  // Quick mode skips the confirm tap for a dispense -- the common
  // truck-scanning case. Stock (Add Stock) always confirms regardless: a
  // mistake there is costlier to reverse, and it's a Supervisor+-only path
  // anyway (Technicians are pinned to dispense in showScanGoState).
  const quickCommit = quickMode && type === "dispense";
  if (!quickCommit) {
    const confirmVerb = type === "stock" ? "Add" : "Take out";
    // #11: the confirm carries a +/- stepper; it returns the (possibly
    // adjusted) count, or false on decline. Quick mode has no modal, so it
    // commits the page-field quantity as before.
    const confirmedQty = await confirmScan(`${confirmVerb} ${item.name}?`, quantity);
    if (!confirmedQty) {
      return { committed: false, declined: true };
    }
    quantity = confirmedQty;
  }

  let txn;
  try {
    txn = await apiCreateTransaction({
      item_id: item.id,
      transaction_type: type,
      quantity,
      work_order_id: batchWorkOrder.id,
      work_order_number: batchWorkOrder.number,
    });
  } catch (err) {
    // #7: keep what a retry needs so a flaky-connection failure doesn't force
    // another trip to the shelf. Capture quantity/type as they were at commit
    // time -- the page field resets to 1 after each scan, so it can't be
    // trusted later.
    const retry = { itemId: item.id, itemName: item.name, quantity, type };
    appendLogLine(`✗ ${item.name}: ${friendlyError(err, "Could not save. Try again.")}`, false, null, retry);
    return { committed: false };
  }

  batchScanCount += 1;
  batchUnitCount += quantity;

  const responseQuantity = txn.item_quantity;
  const authoritativeAfter = responseQuantity === null || responseQuantity === undefined
    ? NaN
    : Number(responseQuantity);
  const before = Number(item.quantity);
  const after = Number.isFinite(authoritativeAfter)
    ? authoritativeAfter
    : Number.isFinite(before)
      ? type === "stock"
        ? before + quantity
        : before - quantity
      : null;
  const verb = type === "stock" ? "Added" : "Took out";
  const tail = after !== null ? ` (now ${after} on hand)` : "";
  const warning = !!txn.recount_required;
  const prefix = warning ? "⚠" : "✓";
  const recountTail = warning ? " — Please re-count stock" : "";
  const undo = { txnId: txn.id, itemId: item.id, quantity, type };
  appendLogLine(`${prefix} ${verb} ${quantity} × ${item.name}${tail}${recountTail}`, true, undo, null, warning);
  updateSummary();
  persistBatch();

  // Reset quantity to the default of 1 so the next scan is immediately armed
  // (a non-1 amount is a deliberate per-item opt-in that does not carry over).
  // Don't focus the field -- on mobile that pops the keyboard mid-batch.
  if (scangoQuantity) scangoQuantity.value = "1";

  // Keep the manual entry panel's on-hand numbers fresh in place -- cheaper
  // than a refetch, and correct whether the commit came from a scan (a
  // freshly-fetched item, not the cached object) or a manual pick (the
  // cached object itself).
  if (after !== null) {
    item.quantity = after;
    const cached = searchItems.find((it) => it.id === item.id);
    if (cached) cached.quantity = after;
  }
  renderManualResults();

  return { committed: true };
}

// Called by nav.js when the Transaction page activates: paint the right
// state and, for an active batch, load the manual entry item cache.
export function enterTransactionPage() {
  showScanGoState();
  if (batchWorkOrder !== null) {
    // Returning to an in-progress batch: bring the camera back up (permission
    // is already granted by this point, so this won't prompt).
    if (scanAutoStart) scanAutoStart();
    loadSearchItems().then(renderManualResults);
  } else {
    // At the gate: load the Supervisor+ saved work-order cards.
    refreshWoCards();
  }
}

// Tear the in-memory batch down and return to the work-order gate. Called by
// auth.js on logout and (via enterApp's fallback) when a resume didn't happen.
//
// `keepSaved: true` preserves the sessionStorage snapshot so a re-login can
// resume it -- passed on a session *timeout* (see auth.js showLoginScreen),
// where the operator was mid-batch and should be able to pick up where they
// left off. A deliberate logout / fresh login clears it (the default). This
// only tears down module state + UI; it never writes the snapshot (batchWorkOrder
// is nulled first, so the persistBatch inside showScanGoState is a no-op).
export function resetBatch({ keepSaved = false } = {}) {
  cancelWoSearch();
  batchWorkOrder = null;
  if (!keepSaved) clearSavedBatch();
  supervisorAdvanced = false; // every fresh login starts streamlined
  quickMode = false; // every fresh login starts with the confirm dialog on
  searchItemsLoaded = false; // re-fetch the item list for the new session
  if (woGateInput) woGateInput.value = "";
  if (scangoQuantity) scangoQuantity.value = "1";
  clearBatchLog();
  clearItemSearch();
  resetWoCards();
  showScanGoState();
}

// Resume a batch that was active before a reload/tab-eviction/phone sleep,
// after tryResumeBatch has confirmed both ownership and that the work order
// is still one the gate would offer. Mirrors startBatchFor but restores the
// tallies/log instead of clearing them.
function resumeBatchFor(saved) {
  batchWorkOrder = saved.workOrder;
  batchScanCount = saved.batchScanCount || 0;
  batchUnitCount = saved.batchUnitCount || 0;
  setMessage(woGateMessage, "", "");
  if (scangoWoLabel) scangoWoLabel.textContent = `Work order: ${saved.workOrder.number}`;
  if (scangoQuantity) scangoQuantity.value = "1";
  quickMode = !!saved.quickMode;
  setScangoType(saved.scangoType === "stock" ? "stock" : "dispense");
  restoreBatchLog(saved.log);
  updateSummary();
  clearItemSearch();
  loadSearchItems().then(renderManualResults);
  showScanGoState();
  if (scanAutoStart) scanAutoStart();
}

// Called from auth.js only on the boot-check path (a page load where the
// session cookie is still valid), never on an explicit login submit -- see
// auth.js `enterApp`. Returns whether a batch was resumed; the caller falls
// back to resetBatch() otherwise.
export async function tryResumeBatch(userId) {
  const saved = readSavedBatch();
  if (!saved || saved.userId !== userId) return false;

  let wo;
  try {
    wo = await apiGetWorkOrder(saved.workOrder.id);
  } catch (err) {
    if (err && err.status) {
      // A real response (404: out-of-scope/archived/unknown) confirms the
      // work order is gone -- drop the stale snapshot.
      clearSavedBatch();
      setMessage(woGateMessage, "Your previous work order is no longer active — pick another to continue.", "error");
    }
    // Anything else (offline, etc.) is inconclusive -- keep the snapshot so
    // the next boot can retry instead of discarding a possibly-valid batch.
    return false;
  }

  if (!["created", "assigned", "in_progress"].includes(wo.status)) {
    clearSavedBatch();
    setMessage(woGateMessage, "Your previous work order is no longer active — pick another to continue.", "error");
    return false;
  }

  resumeBatchFor(saved);
  return true;
}

if (woGateInput) {
  woGateInput.addEventListener("input", () => scheduleWoSearch());
  woGateInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    scheduleWoSearch({ immediate: true });
  });
}
if (scangoChangeWoBtn) scangoChangeWoBtn.addEventListener("click", changeWorkOrder);
if (scangoAdvancedToggle) {
  scangoAdvancedToggle.addEventListener("click", () => {
    supervisorAdvanced = !supervisorAdvanced;
    showScanGoState();
  });
}
if (scangoQuickmodeToggle) {
  scangoQuickmodeToggle.addEventListener("click", () => {
    quickMode = !quickMode;
    showScanGoState();
    persistBatch();
  });
}
if (scangoSegStock) scangoSegStock.addEventListener("click", () => setScangoType("stock"));
if (scangoSegDispense) scangoSegDispense.addEventListener("click", () => setScangoType("dispense"));

// Remove a saved Scan / Stock entry. The backend limits a Technician to their
// own work-order dispenses; Supervisor+ may also remove stock entries. Voids
// the transaction, backs the tallies and cache out, resolves any linked recount
// request, and marks the line so it cannot be removed twice.
if (scangoLog) {
  scangoLog.addEventListener("click", async (event) => {
    const btn = event.target.closest(".scango-log-undo-btn");
    if (!btn) return;
    const txnId = btn.dataset.txnId;
    const entry = batchLog.find((l) => l.undo && l.undo.txnId === txnId);
    if (!entry) return;

    if (scangoMessage) setMessage(scangoMessage, "", "");
    btn.disabled = true;
    try {
      await apiVoidTransaction(txnId);
    } catch (err) {
      btn.disabled = false;
      if (scangoMessage) setMessage(scangoMessage, friendlyError(err, "Could not undo. Try again."), "error");
      return;
    }

    batchScanCount = Math.max(0, batchScanCount - 1);
    batchUnitCount = Math.max(0, batchUnitCount - entry.undo.quantity);
    updateSummary();

    const line = btn.closest(".scango-log-line");
    if (line) {
      line.classList.add("scango-log-undone");
      const span = line.querySelector(".scango-log-text");
      if (span) span.textContent = `${entry.text} — Removed`;
    }
    btn.remove();

    const cached = searchItems.find((it) => it.id === entry.undo.itemId);
    if (cached && Number.isFinite(cached.quantity)) {
      cached.quantity = entry.undo.type === "stock"
        ? cached.quantity - entry.undo.quantity
        : cached.quantity + entry.undo.quantity;
    }
    renderManualResults();

    entry.text = `${entry.text} — Removed`;
    entry.undo = null;
    entry.undone = true; // survives the snapshot so a resume re-strikes the line
    persistBatch();
  });
}

// Retry a failed commit (any role). The failed log line captured the item,
// quantity, and type at commit time (see commitScannedItem); Retry re-posts
// with those exact values and, on success, converts the line in place into a
// normal commit -- tallies, on-hand cache, summary, warning state, and a Remove
// button. The batchLog array and the DOM child
// list are kept in lockstep, so the clicked line's position maps to its entry.
if (scangoLog) {
  scangoLog.addEventListener("click", async (event) => {
    const btn = event.target.closest(".scango-log-retry-btn");
    if (!btn) return;
    if (batchWorkOrder === null) return;

    const line = btn.closest(".scango-log-line");
    const idx = line ? [...scangoLog.children].indexOf(line) : -1;
    const entry = idx >= 0 ? batchLog[idx] : null;
    if (!entry || !entry.retry) return;

    const { itemId, itemName, quantity, type } = entry.retry;
    btn.disabled = true;

    let txn;
    try {
      txn = await apiCreateTransaction({
        item_id: itemId,
        transaction_type: type,
        quantity,
        work_order_id: batchWorkOrder.id,
        work_order_number: batchWorkOrder.number,
      });
    } catch (err) {
      // Still failing: refresh the line's message and leave Retry available.
      btn.disabled = false;
      entry.text = `✗ ${itemName}: ${friendlyError(err, "Could not save. Try again.")}`;
      const span = line.querySelector(".scango-log-text");
      if (span) span.textContent = entry.text;
      persistBatch();
      return;
    }

    // Success: mirror a fresh commit's bookkeeping.
    batchScanCount += 1;
    batchUnitCount += quantity;

    const cached = searchItems.find((it) => it.id === itemId);
    const responseQuantity = txn.item_quantity;
    const authoritativeAfter = responseQuantity === null || responseQuantity === undefined
      ? NaN
      : Number(responseQuantity);
    const before = cached ? Number(cached.quantity) : NaN;
    const after = Number.isFinite(authoritativeAfter)
      ? authoritativeAfter
      : Number.isFinite(before)
        ? (type === "stock" ? before + quantity : before - quantity)
        : null;
    if (cached && after !== null) cached.quantity = after;

    const verb = type === "stock" ? "Added" : "Took out";
    const tail = after !== null ? ` (now ${after} on hand)` : "";
    const warning = !!txn.recount_required;
    const prefix = warning ? "⚠" : "✓";
    const recountTail = warning ? " — Please re-count stock" : "";
    const undo = { txnId: txn.id, itemId, quantity, type };

    entry.ok = true;
    entry.text = `${prefix} ${verb} ${quantity} × ${itemName}${tail}${recountTail}`;
    entry.retry = null;
    entry.undo = undo;
    entry.warning = warning;

    // Repaint just this line (err -> success/warning, swap Retry for Remove).
    if (line) line.replaceWith(renderLogLine(entry.text, true, undo, null, false, warning));

    updateSummary();
    renderManualResults();
    persistBatch();
  });
}

if (woGateCards) {
  woGateCards.addEventListener("click", async (event) => {
    const card = event.target.closest(".wo-card");
    if (!card) return;
    await selectWorkOrderForBatch({
      id: card.dataset.woId,
      number: card.dataset.wo,
      status: card.dataset.woStatus,
    });
  });
}
// --- Manual entry panel (all roles) ---------------------------------
// Filters the cached item list client-side (same pattern as the Find Item
// page and the Work Orders "add material" picker) so an operator can find
// an item by name/barcode -- or, for an opted-in Supervisor+, browse the
// full list -- and commit it into the active batch without a camera. Every
// pick funnels through commitScannedItem, the same path a scan uses.
if (txnItemSearch) {
  txnItemSearch.addEventListener("input", renderManualResults);
}

if (txnItemSearchResults) {
  txnItemSearchResults.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-item-id]");
    if (!btn) return;
    const item = searchItems.find((it) => it.id === btn.dataset.itemId);
    clearItemSearch();
    if (item) await commitScannedItem(item);
  });
}
