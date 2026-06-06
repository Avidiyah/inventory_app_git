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
} from "../state.js";
import { apiListItems, apiCreateTransaction } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
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

// When a barcode scan resolves to an item, the items table is narrowed to
// just that row so the operator sees exactly what they scanned. `null`
// means "show everything" (the normal state). Set via `focusItemByBarcode`,
// cleared via `clearTxnScanFilter` (called by the scan view's reset).
let scanFilterBarcode = null;

// Injected by `main.js` (see `setOnTransactionSaved`) so a completed
// stock/dispense can reset the scan UI without this module importing the
// scan view -- keeping the dependency one-way (scan -> transactions).
let onTransactionSaved = null;

export function setOnTransactionSaved(fn) {
  onTransactionSaved = fn;
}

export async function loadTxnItems() {
  try {
    const items = await apiListItems();
    const visible = scanFilterBarcode
      ? items.filter(item => item.barcode === scanFilterBarcode)
      : items;
    txnItemsTbody.innerHTML = "";
    visible.forEach(item => {
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
  // If a scan had narrowed the table, restore the full list when the form
  // closes (cancel, post-save, or the selected item being deleted).
  if (scanFilterBarcode !== null) {
    scanFilterBarcode = null;
    loadTxnItems();
  }
}

// Called by the scan view after a successful decode + exact lookup: narrow
// the items table to the scanned item and open its transaction form,
// defaulting to "stock" (the Type dropdown flips to dispense in one click).
export function focusItemByBarcode(item) {
  scanFilterBarcode = item.barcode;
  loadTxnItems();
  openTransactionForm(item.id, item.name, "stock", {
    quantity: item.quantity,
    location: item.location,
  });
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
