// View: transaction (stock/dispense) page.
//
// Layer: views. Owns the items table on the Transaction page and
// the stock/dispense form that opens below it on row click.
//
// Public surface:
// - `loadTxnItems()` repaints the items table; called by `nav.js`
//   on page activation and after a successful save.
// - `openTransactionForm(itemId, itemName, action)` reveals the
//   form pre-filled for "stock" or "dispense"; chosen via the
//   row-action buttons.
// - `closeTransactionForm()` hides the form; `main.js` wires it as
//   `items.onDeletedSelectedItem` so deleting the selected item
//   from the Entry page also dismisses a stale form.
//
// On successful save, both `loadTxnItems` and `loadItems` are
// called so the Entry table reflects the new stock level
// immediately without page navigation.

import {
  getSelectedItemId,
  setSelectedItemId,
  getRole,
} from "../state.js";
import { apiListItems, apiCreateTransaction } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
import { roleAtLeast } from "../roles.js";
import { loadItems } from "./items.js";

const txnItemsTbody = document.getElementById("txn-items-tbody");
const transactionSection = document.getElementById("transaction-section");
const transactionSelected = document.getElementById("transaction-selected");
const transactionType = document.getElementById("transaction-type");
const segStockBtn = document.querySelector(".seg-stock");
const segDispenseBtn = document.querySelector(".seg-dispense");
const transactionQuantity = document.getElementById("transaction-quantity");
const transactionWorkOrder = document.getElementById("transaction-work-order");
const transactionMessage = document.getElementById("transaction-message");
const saveTransactionBtn = document.getElementById("save-transaction-btn");
const cancelTransactionBtn = document.getElementById("cancel-transaction-btn");

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
const scangoQuantity = document.getElementById("scango-quantity");
const scangoSummary = document.getElementById("scango-summary");
const scangoLog = document.getElementById("scango-log");
const txnScanSection = document.getElementById("txn-scan-section");
const txnItemsSection = document.getElementById("txn-items-section");

// Per-scan confirmation modal (see confirmScan).
const scanConfirmOverlay = document.getElementById("scan-confirm-overlay");
const scanConfirmTitle = document.getElementById("scan-confirm-title");
const scanConfirmYesBtn = document.getElementById("scan-confirm-yes");
const scanConfirmNoBtn = document.getElementById("scan-confirm-no");

// Injected by `main.js` (see `setOnTransactionSaved`) so a completed
// stock/dispense can reset the scan UI without this module importing the
// scan view -- keeping the dependency one-way (scan -> transactions).
let onTransactionSaved = null;

export function setOnTransactionSaved(fn) {
  onTransactionSaved = fn;
}

// =================================================================
// Scan-and-go (work-order batch flow)
// =================================================================
//
// The Transaction page opens on a work-order gate. Once a work order is
// entered, the operator picks a direction + quantity and scans items;
// each scan commits a transaction straight into the active work order
// (see views/scan.js continuous mode) and is appended to a running log.
// Technicians are dispense-only and never see the manual items table /
// form; Supervisor+ keep those below as a fallback. See
// docs/plan-scan-and-go.md.

// Active work order, or null while the gate (State A) is showing.
let batchWorkOrder = null;
// Running tallies for the current work order's on-screen summary.
let batchScanCount = 0;
let batchUnitCount = 0;
// Supervisor+ opt-in: false = same streamlined dispense-only flow as a
// Technician; true = reveal the direction toggle + manual items table / form.
// Technicians can never flip this. Reset to false on each fresh login.
let supervisorAdvanced = false;

// Injected by main.js so changing the work order can stop the live camera
// without this module importing the scan view (keeps the dependency
// one-way: scan -> transactions).
let resetScanUi = null;
export function setScanResetter(fn) {
  resetScanUi = fn;
}

function isTechnician() {
  // Technician is the only role below Supervisor that can reach this page.
  return !roleAtLeast(getRole(), "supervisor");
}

function setScangoType(value) {
  scangoType.value = value;
  if (scangoSegStock) scangoSegStock.classList.toggle("active", value === "stock");
  if (scangoSegDispense) scangoSegDispense.classList.toggle("active", value === "dispense");
}

// Show the gate or the active batch, and apply role visibility. By default
// Supervisor+ get the same streamlined dispense-only flow as a Technician; the
// `#scango-advanced-toggle` opt-in (Supervisor+ only) reveals the Stock/Dispense
// toggle plus the manual items table / form.
function showScanGoState() {
  const tech = isTechnician();
  const active = batchWorkOrder !== null;
  // "advanced" = a Supervisor+ who has opted in. Everyone else (Technicians,
  // and Supervisor+ by default) gets the streamlined dispense-only view.
  const advanced = !tech && supervisorAdvanced;

  if (woGate) woGate.hidden = active;
  if (scangoActive) scangoActive.hidden = !active;
  if (txnScanSection) txnScanSection.hidden = !active;

  // Opt-in control: Supervisor+ only, and only inside an active batch.
  if (scangoAdvancedToggle) {
    scangoAdvancedToggle.hidden = tech || !active;
    scangoAdvancedToggle.textContent = advanced ? "Hide manual entry" : "Manual entry & stock options";
    scangoAdvancedToggle.setAttribute("aria-expanded", advanced ? "true" : "false");
  }

  // Direction control: toggle only in advanced mode; otherwise the fixed
  // "Taking out stock" indicator, with the type pinned to dispense.
  if (scangoDirection) scangoDirection.hidden = !advanced;
  if (scangoDirectionFixed) scangoDirectionFixed.hidden = advanced;
  if (!advanced) setScangoType("dispense");

  // Manual fallback table + form: advanced mode only. The form stays hidden
  // until a row button opens it.
  if (txnItemsSection) txnItemsSection.hidden = !advanced || !active;
  if (!advanced && transactionSection) transactionSection.hidden = true;
}

function clearBatchLog() {
  batchScanCount = 0;
  batchUnitCount = 0;
  if (scangoLog) {
    scangoLog.innerHTML = "";
    scangoLog.hidden = true;
  }
  if (scangoSummary) {
    scangoSummary.textContent = "";
    scangoSummary.hidden = true;
  }
}

function appendLogLine(text, ok) {
  if (!scangoLog) return;
  const line = document.createElement("div");
  line.className = `scango-log-line ${ok ? "scango-log-ok" : "scango-log-err"}`;
  // textContent, not innerHTML -- item names are untrusted.
  line.textContent = text;
  scangoLog.prepend(line); // newest first
  scangoLog.hidden = false;
}

function updateSummary() {
  if (!scangoSummary) return;
  const scans = `${batchScanCount} ${batchScanCount === 1 ? "scan" : "scans"}`;
  scangoSummary.textContent = `This work order: ${scans}, ${batchUnitCount} units`;
  scangoSummary.hidden = false;
}

function startBatch() {
  const workOrder = woGateInput ? woGateInput.value.trim() : "";
  if (!workOrder) {
    setMessage(woGateMessage, "Enter a work order number to start.", "error");
    return;
  }
  batchWorkOrder = workOrder;
  clearBatchLog();
  setMessage(woGateMessage, "", "");
  if (scangoWoLabel) scangoWoLabel.textContent = `Work order: ${workOrder}`;
  // Quantity defaults to 1 so the batch is armed without typing; the operator
  // taps the field only to opt into a different amount.
  if (scangoQuantity) scangoQuantity.value = "1";
  // Default to dispense (the common work-order job is taking parts out);
  // Supervisor+ can toggle to Add Stock. Techs are forced to dispense in
  // showScanGoState regardless.
  setScangoType("dispense");
  showScanGoState();
}

function changeWorkOrder() {
  if (
    batchScanCount > 0 &&
    !window.confirm("Start a new work order? This clears the list below. Saved scans stay in history.")
  ) {
    return;
  }
  batchWorkOrder = null;
  if (resetScanUi) resetScanUi(); // stop the camera + clear the scan message
  clearBatchLog();
  if (woGateInput) woGateInput.value = "";
  showScanGoState();
  if (woGateInput) woGateInput.focus();
}

// Gate consulted by the scanner before it commits a decode (see
// views/scan.js `canScan`): refuse unless a batch is active and a
// positive quantity is set.
export function scanGoArmed() {
  if (batchWorkOrder === null) return false;
  const quantity = scangoQuantity ? parseFloat(scangoQuantity.value) : NaN;
  return Number.isFinite(quantity) && quantity > 0;
}

// Per-scan confirmation. Resolves true (Yes) or false (No / Esc / backdrop).
// The live decoder stays paused while this is open because handleLiveAccept
// awaits the whole resolve+commit chain before starting its dwell timer (see
// docs/plan-scan-and-go.md), so there are never stacked modals.
function confirmScan(message) {
  return new Promise((resolve) => {
    if (!scanConfirmOverlay) {
      resolve(true); // no modal in the DOM -> fall back to instant commit
      return;
    }
    scanConfirmTitle.textContent = message; // textContent: item name is untrusted
    scanConfirmOverlay.hidden = false;
    if (scanConfirmYesBtn) scanConfirmYesBtn.focus();

    function cleanup() {
      if (scanConfirmYesBtn) scanConfirmYesBtn.removeEventListener("click", onYes);
      if (scanConfirmNoBtn) scanConfirmNoBtn.removeEventListener("click", onNo);
      scanConfirmOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function done(ok) {
      scanConfirmOverlay.hidden = true;
      cleanup();
      resolve(ok);
    }
    function onYes() { done(true); }
    function onNo() { done(false); }
    function onBackdrop(event) { if (event.target === scanConfirmOverlay) done(false); }
    function onKey(event) { if (event.key === "Escape") done(false); }

    if (scanConfirmYesBtn) scanConfirmYesBtn.addEventListener("click", onYes);
    if (scanConfirmNoBtn) scanConfirmNoBtn.addEventListener("click", onNo);
    scanConfirmOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

// Commit a scanned item into the active work order. Returns
// `{committed, declined}` so the scanner knows whether to start its
// same-barcode cooldown (set on either) and whether to buzz. Never throws --
// failures are surfaced in the log and the camera keeps running.
export async function commitScannedItem(item) {
  const quantity = scangoQuantity ? parseFloat(scangoQuantity.value) : NaN;
  if (batchWorkOrder === null || !Number.isFinite(quantity) || quantity <= 0) {
    return { committed: false };
  }
  const type = scangoType.value; // "stock" | "dispense"

  // Confirm before committing: the Yes click is this flow's "Save".
  const confirmVerb = type === "stock" ? "Add" : "Take out";
  const confirmed = await confirmScan(`${confirmVerb} ${quantity} × ${item.name}?`);
  if (!confirmed) {
    return { committed: false, declined: true };
  }

  try {
    await apiCreateTransaction({
      item_id: item.id,
      transaction_type: type,
      quantity,
      work_order_number: batchWorkOrder,
    });
  } catch (err) {
    appendLogLine(`✗ ${item.name}: ${friendlyError(err, "Could not save. Try again.")}`, false);
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
  appendLogLine(`✓ ${verb} ${quantity} × ${item.name}${tail}`, true);
  updateSummary();

  // Reset quantity to the default of 1 so the next scan is immediately armed
  // (a non-1 amount is a deliberate per-item opt-in that does not carry over).
  // Don't focus the field -- on mobile that pops the keyboard mid-batch.
  if (scangoQuantity) scangoQuantity.value = "1";

  // Keep the manual table's on-hand numbers fresh -- only when it's actually
  // visible (a Supervisor+ who has opted in).
  if (!isTechnician() && supervisorAdvanced) loadTxnItems();

  return { committed: true };
}

// Called by nav.js when the Transaction page activates: paint the right
// state and, for an opted-in Supervisor+, load the manual table.
export function enterTransactionPage() {
  showScanGoState();
  if (batchWorkOrder !== null && !isTechnician() && supervisorAdvanced) {
    loadTxnItems();
  }
}

// Called by auth.js on login/logout so a session always starts at the
// work-order gate with no stale batch.
export function resetBatch() {
  batchWorkOrder = null;
  supervisorAdvanced = false; // every fresh login starts streamlined
  if (woGateInput) woGateInput.value = "";
  if (scangoQuantity) scangoQuantity.value = "1";
  clearBatchLog();
  showScanGoState();
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
    // Populate the now-visible manual table when opting in.
    if (supervisorAdvanced && batchWorkOrder !== null) loadTxnItems();
  });
}
if (scangoSegStock) scangoSegStock.addEventListener("click", () => setScangoType("stock"));
if (scangoSegDispense) scangoSegDispense.addEventListener("click", () => setScangoType("dispense"));

export async function loadTxnItems() {
  try {
    const items = await apiListItems();
    txnItemsTbody.innerHTML = "";
    items.forEach(item => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td data-label="Barcode">${escapeHtml(item.barcode)}</td>
        <td data-primary>${escapeHtml(item.name)}</td>
        <td data-label="Quantity"><strong>${escapeHtml(item.quantity)}</strong></td>
        <td data-label="Actions">
          <div class="row-actions">
            <button class="stock-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}" data-action="stock" data-quantity="${escapeHtml(item.quantity)}" data-location="${escapeHtml(item.location)}">Add Stock</button>
            <button class="dispense-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}" data-action="dispense" data-quantity="${escapeHtml(item.quantity)}" data-location="${escapeHtml(item.location)}">Take Out</button>
          </div>
        </td>
      `;
      txnItemsTbody.appendChild(row);
    });
  } catch (error) {
    console.error("Failed to load items:", error);
  }
}

// Set the (hidden) transaction_type and reflect it in the segmented
// control. The submitted value stays "stock" | "dispense" -- only the
// presentation changed (select -> two big buttons).
function setTxnType(value) {
  transactionType.value = value;
  if (segStockBtn) segStockBtn.classList.toggle("active", value === "stock");
  if (segDispenseBtn) segDispenseBtn.classList.toggle("active", value === "dispense");
}

// Render the selected/scanned item: a large name plus an optional quiet
// meta line (on-hand + location). `meta` is supplied when we know the
// item's quantity/location (row button or scan); omitted callers get the
// name alone.
function renderSelected(name, meta) {
  const parts = [];
  if (meta) {
    if (meta.quantity !== undefined && meta.quantity !== null && meta.quantity !== "") {
      parts.push(`On hand: ${meta.quantity}`);
    }
    if (meta.location) parts.push(`Location: ${meta.location}`);
  }
  transactionSelected.innerHTML =
    `<span class="confirm-name">${escapeHtml(name)}</span>` +
    (parts.length ? `<span class="confirm-meta">${escapeHtml(parts.join(" · "))}</span>` : "");
}

export function openTransactionForm(itemId, itemName, action, meta) {
  setSelectedItemId(itemId);
  setTxnType(action);
  transactionQuantity.value = "0";
  transactionWorkOrder.value = "";
  setMessage(transactionMessage, "", "");
  renderSelected(itemName, meta);
  transactionSection.hidden = false;
  transactionSection.scrollIntoView({ behavior: "smooth", block: "start" });

  // The transaction is attributed to the logged-in user server-side, so
  // there is no user to pick here -- just focus the quantity field.
  saveTransactionBtn.disabled = false;
  transactionQuantity.focus();
  transactionQuantity.select();
}

export function closeTransactionForm() {
  setSelectedItemId(null);
  transactionSection.hidden = true;
  setMessage(transactionMessage, "", "");
}

txnItemsTbody.addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("stock-btn") || target.classList.contains("dispense-btn")) {
    openTransactionForm(target.dataset.id, target.dataset.name, target.dataset.action, {
      quantity: target.dataset.quantity,
      location: target.dataset.location,
    });
  }
});

// Segmented Add Stock / Take Out Stock control (replaces the type select).
if (segStockBtn) segStockBtn.addEventListener("click", () => setTxnType("stock"));
if (segDispenseBtn) segDispenseBtn.addEventListener("click", () => setTxnType("dispense"));

cancelTransactionBtn.addEventListener("click", closeTransactionForm);

saveTransactionBtn.addEventListener("click", async () => {
  setMessage(transactionMessage, "", "");

  const selectedId = getSelectedItemId();
  if (!selectedId) {
    setMessage(transactionMessage, "No item selected.", "error");
    return;
  }

  const quantity = parseFloat(transactionQuantity.value);
  if (!Number.isFinite(quantity) || quantity <= 0) {
    setMessage(transactionMessage, "Enter a quantity greater than zero.", "error");
    return;
  }

  const workOrder = transactionWorkOrder.value.trim();

  try {
    const data = await apiCreateTransaction({
      item_id: selectedId,
      transaction_type: transactionType.value,
      quantity,
      work_order_number: workOrder || null,
    });
    const savedMsg = data.transaction_type === "dispense" ? "Stock taken out." : "Stock added.";
    setMessage(transactionMessage, savedMsg, "success");
    // Auto-reset the scan UI so the next scan starts clean (no-op if the
    // transaction was started manually rather than by a scan).
    if (onTransactionSaved) onTransactionSaved();
    loadTxnItems();
    loadItems();
    setTimeout(closeTransactionForm, 1200);
  } catch (err) {
    setMessage(transactionMessage, friendlyError(err, "Something went wrong. Try again."), "error");
  }
});
