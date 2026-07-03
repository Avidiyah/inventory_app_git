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
import { apiListItems, apiCreateTransaction, apiListWorkOrders, apiCreateWorkOrder, apiListUsers, apiGetWorkOrder, apiVoidTransaction } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { roleAtLeast } from "../roles.js";

// --- Scan-and-go (work-order batch) elements --------------------
const woGate = document.getElementById("wo-gate");
const woGateInput = document.getElementById("wo-gate-input");
const woGateStartBtn = document.getElementById("wo-gate-start-btn");
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
const txnItemSearch = document.getElementById("txn-item-search");
const txnItemSearchResults = document.getElementById("txn-item-search-results");

// Cards-first gate: saved work-order cards (all roles, server-scoped) + a
// Supervisor+ quick-add form (with an optional technician assignee). The
// free-text gate is Supervisor+ only now -- technicians scan assigned cards.
const woGateCardsSection = document.getElementById("wo-gate-cards-section");
const woGateCards = document.getElementById("wo-gate-cards");
const woGateCardsMessage = document.getElementById("wo-gate-cards-message");
const woGateNew = document.getElementById("wo-gate-new");
const woGateManual = document.getElementById("wo-gate-manual");
const newBuilding = document.getElementById("wo-gate-new-building");
const newBuildingNo = document.getElementById("wo-gate-new-buildingno");
const newRoom = document.getElementById("wo-gate-new-room");
const newWo = document.getElementById("wo-gate-new-wo");
const newAssignee = document.getElementById("wo-gate-new-assignee");
const newSaveBtn = document.getElementById("wo-gate-new-save-btn");
const newMessage = document.getElementById("wo-gate-new-message");
// Technician list for the assignee dropdown, loaded once per session.
let assigneesLoaded = false;
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

  // Saved work-order cards: shown to all roles on the gate (State A); the
  // server scopes the list (technician -> assigned, supervisor -> created).
  if (woGateCardsSection) woGateCardsSection.hidden = active;
  // Quick-add + free-text gate are Supervisor+ only; a technician scans only
  // the cards assigned to them.
  if (woGateNew) woGateNew.hidden = tech || active;
  if (woGateManual) woGateManual.hidden = tech || active;

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
      .filter(
        (it) =>
          it.name.toLowerCase().includes(query) ||
          (it.barcode && it.barcode.toLowerCase().includes(query))
      )
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

// `undo`, when set, is `{txnId, itemId, quantity, type}` -- present only for
// a quick-mode commit a Supervisor+ can still void (see commitScannedItem).
// `retry`, when set, is `{itemId, itemName, quantity, type, quickCommit}` on a
// failed line -- the payload the Retry button re-posts (see the retry handler).
// `undone` re-applies the strike-through on a restored line -- the undo
// handler marks the entry so the state survives the batch snapshot (the
// "— Undone" text alone would otherwise read like a normal commit).
function renderLogLine(text, ok, undo, retry, undone) {
  const line = document.createElement("div");
  line.className = `scango-log-line ${ok ? "scango-log-ok" : "scango-log-err"}`;
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
    undoBtn.textContent = "Undo";
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

function appendLogLine(text, ok, undo, retry) {
  // Kept in parallel with the DOM (newest first, same order) so the batch
  // snapshot (see persistBatch) can restore it after a reload. The array index
  // and the DOM child index stay in lockstep -- the retry handler relies on it.
  batchLog.unshift({ text, ok, undo: undo || null, retry: retry || null });
  if (!scangoLog) return;
  scangoLog.prepend(renderLogLine(text, ok, undo, retry));
  scangoLog.hidden = false;
}

// Rebuild the log from a resumed batch's saved lines (already newest-first).
function restoreBatchLog(lines) {
  batchLog = Array.isArray(lines) ? lines : [];
  if (!scangoLog) return;
  scangoLog.innerHTML = "";
  batchLog.forEach(({ text, ok, undo, retry, undone }) => scangoLog.appendChild(renderLogLine(text, ok, undo, retry, undone)));
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

// Start a batch on an already-resolved work order `{id, number}` (a tapped card
// or a freshly created one).
function startBatchFor(workOrder) {
  batchWorkOrder = workOrder;
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

// Free-text gate (Supervisor+): resolve the typed number to a work order
// (find-or-create), then start a batch on it.
async function startBatch() {
  const number = woGateInput ? woGateInput.value.trim() : "";
  if (!number) {
    setMessage(woGateMessage, "Enter a work order number to start.", "error");
    return;
  }
  try {
    const wo = await apiCreateWorkOrder({ number });
    startBatchFor({ id: wo.id, number: wo.number });
  } catch (err) {
    setMessage(woGateMessage, friendlyError(err, "Could not start that work order."), "error");
  }
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
  if (woGateInput) woGateInput.focus();
}

// --- Saved work-order cards (Supervisor+) -------------------------
// The scan gate opens on cards of the saved work orders (mass-staging rooms:
// building + room + one work order). Tapping a card starts a scan-and-go batch
// on that work order. "Add a new work order" quick-adds building + room + WO
// (find-or-create the building's active stage) and starts the batch -- it then
// persists as a card. Scanning is a plain transaction on the work order;
// nothing is written back to the stage (the stage stays the plan/load record).

function resetWoCards() {
  if (woGateCards) woGateCards.innerHTML = "";
  if (woGateCardsMessage) setMessage(woGateCardsMessage, "", "");
  if (newBuilding) newBuilding.value = "";
  if (newBuildingNo) newBuildingNo.value = "";
  if (newRoom) newRoom.value = "";
  if (newWo) newWo.value = "";
  if (newAssignee) newAssignee.value = "";
  if (newMessage) setMessage(newMessage, "", "");
}

function renderWoCards(workOrders) {
  if (!woGateCards) return;
  woGateCards.innerHTML = "";
  if (!workOrders.length) {
    const empty = isTechnician()
      ? "No work orders assigned to you."
      : "No active work orders yet. Add one below.";
    setMessage(woGateCardsMessage, empty, "");
    return;
  }
  setMessage(woGateCardsMessage, "", "");
  const showAssignee = !isTechnician(); // a tech's cards are all their own
  workOrders.forEach((w) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "wo-card";
    card.dataset.wo = w.number;
    card.dataset.woId = w.id;
    const assignee = showAssignee
      ? `<span class="wo-card-assignee">${
          w.assigned_to_username ? "Assigned: " + escapeHtml(w.assigned_to_username) : "Unassigned"
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
      `<span class="wo-card-meta">${escapeHtml(place || "—")}</span>` +
      assignee;
    woGateCards.appendChild(card);
  });
}

// Populate the quick-add assignee dropdown with technicians (Supervisor+ only,
// loaded once per session). Leaves just "Unassigned" if the list can't load.
async function loadAssignees() {
  if (assigneesLoaded || isTechnician() || !newAssignee) return;
  try {
    const users = await apiListUsers();
    newAssignee.innerHTML = `<option value="">Unassigned</option>`;
    users
      .filter((u) => u.role === "technician")
      .forEach((u) => {
        const opt = document.createElement("option");
        opt.value = u.id;
        opt.textContent = u.username;
        newAssignee.appendChild(opt);
      });
    assigneesLoaded = true;
  } catch {
    /* keep just "Unassigned" until a later reload */
  }
}

// Fetch + render the cards. Supervisor+ only, and only while the gate is
// showing (no active batch). Called on page activation and after a quick-add.
async function refreshWoCards() {
  if (batchWorkOrder !== null || !woGateCards) return;
  loadAssignees(); // Supervisor+ quick-add dropdown (no-op for technicians)
  try {
    const workOrders = await apiListWorkOrders({ status: "in_progress" });
    renderWoCards(workOrders);
  } catch (err) {
    setMessage(woGateCardsMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

// Quick-add a building + room + work order, then start the batch on it. The
// card list refreshes when the operator returns to the gate.
async function submitNewWorkOrder() {
  const community = newBuilding ? newBuilding.value.trim() : "";
  const buildingNumber = newBuildingNo ? newBuildingNo.value.trim() : "";
  const unitNumber = newRoom ? newRoom.value.trim() : "";
  const number = newWo ? newWo.value.trim() : "";
  const assignedToId = newAssignee && newAssignee.value ? newAssignee.value : null;
  if (!number) {
    setMessage(newMessage, "Enter a work order number.", "error");
    return;
  }
  let wo;
  try {
    wo = await apiCreateWorkOrder({
      number,
      community: community || null,
      buildingNumber: buildingNumber || null,
      unitNumber: unitNumber || null,
      assignedToId,
    });
  } catch (err) {
    setMessage(newMessage, friendlyError(err, "Could not save the work order."), "error");
    return;
  }
  resetWoCards();
  startBatchFor({ id: wo.id, number: wo.number });
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
    // trusted later. quickCommit rides along so a retried quick-mode dispense
    // still earns the same Supervisor+ Undo affordance a fresh one would.
    const retry = { itemId: item.id, itemName: item.name, quantity, type, quickCommit };
    appendLogLine(`✗ ${item.name}: ${friendlyError(err, "Could not save. Try again.")}`, false, null, retry);
    return { committed: false };
  }

  batchScanCount += 1;
  batchUnitCount += quantity;

  const before = Number(item.quantity);
  const after = Number.isFinite(before)
    ? type === "stock"
      ? before + quantity
      : before - quantity
    : null;
  const verb = type === "stock" ? "Added" : "Took out";
  const tail = after !== null ? ` (now ${after} on hand)` : "";
  // Undo is only offered for a quick-mode commit (it's the confirm step's
  // replacement, not a general safety net) and only to a role that can
  // actually void a transaction -- see the Tier 1 #3 permission decision.
  const undo = quickCommit && roleAtLeast(getRole(), "supervisor")
    ? { txnId: txn.id, itemId: item.id, quantity, type }
    : null;
  appendLogLine(`✓ ${verb} ${quantity} × ${item.name}${tail}`, true, undo);
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
  batchWorkOrder = null;
  if (!keepSaved) clearSavedBatch();
  supervisorAdvanced = false; // every fresh login starts streamlined
  quickMode = false; // every fresh login starts with the confirm dialog on
  assigneesLoaded = false; // re-fetch the technician list for the new session
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

  if (wo.status !== "in_progress") {
    clearSavedBatch();
    setMessage(woGateMessage, "Your previous work order is no longer active — pick another to continue.", "error");
    return false;
  }

  resumeBatchFor(saved);
  return true;
}

if (woGateStartBtn) woGateStartBtn.addEventListener("click", startBatch);
if (woGateInput) {
  woGateInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") startBatch();
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

// Undo a quick-mode commit (Supervisor+ only -- see commitScannedItem).
// Voids the transaction, backs the tallies and the manual-entry cache out,
// and marks the line so it can't be undone twice.
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
      if (span) span.textContent = `${entry.text} — Undone`;
    }
    btn.remove();

    const cached = searchItems.find((it) => it.id === entry.undo.itemId);
    if (cached && Number.isFinite(cached.quantity)) {
      cached.quantity = entry.undo.type === "stock"
        ? cached.quantity - entry.undo.quantity
        : cached.quantity + entry.undo.quantity;
    }
    renderManualResults();

    entry.text = `${entry.text} — Undone`;
    entry.undo = null;
    entry.undone = true; // survives the snapshot so a resume re-strikes the line
    persistBatch();
  });
}

// Retry a failed commit (any role). The failed log line captured the item,
// quantity, and type at commit time (see commitScannedItem); Retry re-posts
// with those exact values and, on success, converts the line in place into a
// normal commit -- tallies, on-hand cache, summary, and (for an eligible
// quick-mode dispense) an Undo button. The batchLog array and the DOM child
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

    const { itemId, itemName, quantity, type, quickCommit } = entry.retry;
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

    // Best-effort on-hand: the failed commit never moved stock, so the item's
    // current cached quantity is the right "before" (other commits this batch
    // already updated it). Absent from the cache -> no on-hand tail.
    const cached = searchItems.find((it) => it.id === itemId);
    const before = cached ? Number(cached.quantity) : NaN;
    const after = Number.isFinite(before)
      ? (type === "stock" ? before + quantity : before - quantity)
      : null;
    if (cached && after !== null) cached.quantity = after;

    const verb = type === "stock" ? "Added" : "Took out";
    const tail = after !== null ? ` (now ${after} on hand)` : "";
    const undo = quickCommit && roleAtLeast(getRole(), "supervisor")
      ? { txnId: txn.id, itemId, quantity, type }
      : null;

    entry.ok = true;
    entry.text = `✓ ${verb} ${quantity} × ${itemName}${tail}`;
    entry.retry = null;
    entry.undo = undo;

    // Repaint just this line (err -> ok, swap Retry for Undo) in place.
    if (line) line.replaceWith(renderLogLine(entry.text, true, undo, null));

    updateSummary();
    renderManualResults();
    persistBatch();
  });
}

if (woGateCards) {
  woGateCards.addEventListener("click", (event) => {
    const card = event.target.closest(".wo-card");
    if (!card) return;
    startBatchFor({ id: card.dataset.woId, number: card.dataset.wo });
  });
}
if (newSaveBtn) newSaveBtn.addEventListener("click", submitNewWorkOrder);
if (newWo) {
  newWo.addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitNewWorkOrder();
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
