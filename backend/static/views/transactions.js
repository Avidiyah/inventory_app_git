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
const scangoQuantity = document.getElementById("scango-quantity");
const scangoSummary = document.getElementById("scango-summary");
const scangoLog = document.getElementById("scango-log");
const txnScanSection = document.getElementById("txn-scan-section");
const txnItemsSection = document.getElementById("txn-items-section");

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

// Show the gate or the active batch, and apply role visibility: hide the
// Stock/Dispense toggle (and force dispense) for Technicians, and hide
// the manual items table / form from them entirely.
function showScanGoState() {
  const tech = isTechnician();
  const active = batchWorkOrder !== null;

  if (woGate) woGate.hidden = active;
  if (scangoActive) scangoActive.hidden = !active;
  if (txnScanSection) txnScanSection.hidden = !active;

  // Direction control: toggle for Supervisor+, fixed "dispense" for techs.
  if (scangoDirection) scangoDirection.hidden = tech;
  if (scangoDirectionFixed) scangoDirectionFixed.hidden = !tech;
  if (tech) setScangoType("dispense");

  // Manual fallback table: Supervisor+ only, and only inside an active
  // batch. The manual form stays hidden until a row button opens it.
  if (txnItemsSection) txnItemsSection.hidden = tech || !active;
  if (tech && transactionSection) transactionSection.hidden = true;
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
  if (scangoQuantity) scangoQuantity.value = "";
  // Supervisor+ default to Add Stock; techs are forced to dispense in
  // showScanGoState.
  setScangoType("stock");
  showScanGoState();
  if (scangoQuantity) scangoQuantity.focus();
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

// Commit a scanned item into the active work order. Returns
// `{committed}` so the scanner knows whether to start its same-barcode
// cooldown. Never throws -- failures are surfaced in the log and the
// camera keeps running.
export async function commitScannedItem(item) {
  const quantity = scangoQuantity ? parseFloat(scangoQuantity.value) : NaN;
  if (batchWorkOrder === null || !Number.isFinite(quantity) || quantity <= 0) {
    return { committed: false };
  }
  const type = scangoType.value; // "stock" | "dispense"

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

  // Reset quantity so the next item gets a deliberate count; this also
  // disarms scanning until a new quantity is entered.
  if (scangoQuantity) {
    scangoQuantity.value = "";
    scangoQuantity.focus();
  }

  // Keep the Supervisor+ manual table's on-hand numbers fresh.
  if (roleAtLeast(getRole(), "supervisor")) loadTxnItems();

  return { committed: true };
}

// Called by nav.js when the Transaction page activates: paint the right
// state and (Supervisor+) load the manual table.
export function enterTransactionPage() {
  showScanGoState();
  if (batchWorkOrder !== null && roleAtLeast(getRole(), "supervisor")) {
    loadTxnItems();
  }
}

// Called by auth.js on login/logout so a session always starts at the
// work-order gate with no stale batch.
export function resetBatch() {
  batchWorkOrder = null;
  if (woGateInput) woGateInput.value = "";
  if (scangoQuantity) scangoQuantity.value = "";
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
