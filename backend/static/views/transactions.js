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
  getUsers,
  getSelectedItemId,
  setSelectedItemId,
} from "../state.js";
import { apiListItems, apiCreateTransaction } from "../api.js";
import { escapeHtml, formatError } from "../format.js";
import { setMessage } from "../dom.js";
import { loadItems } from "./items.js";

const txnItemsTbody = document.getElementById("txn-items-tbody");
const transactionSection = document.getElementById("transaction-section");
const transactionSelected = document.getElementById("transaction-selected");
const transactionType = document.getElementById("transaction-type");
const transactionUser = document.getElementById("transaction-user");
const transactionQuantity = document.getElementById("transaction-quantity");
const transactionWorkOrder = document.getElementById("transaction-work-order");
const transactionMessage = document.getElementById("transaction-message");
const saveTransactionBtn = document.getElementById("save-transaction-btn");
const cancelTransactionBtn = document.getElementById("cancel-transaction-btn");

export async function loadTxnItems() {
  try {
    const items = await apiListItems();
    txnItemsTbody.innerHTML = "";
    items.forEach(item => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeHtml(item.barcode)}</td>
        <td>${escapeHtml(item.name)}</td>
        <td>${escapeHtml(item.quantity)}</td>
        <td>
          <div class="row-actions">
            <button class="stock-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}" data-action="stock">Stock</button>
            <button class="dispense-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}" data-action="dispense">Dispense</button>
          </div>
        </td>
      `;
      txnItemsTbody.appendChild(row);
    });
  } catch (error) {
    console.error("Failed to load items:", error);
  }
}

export function openTransactionForm(itemId, itemName, action) {
  setSelectedItemId(itemId);
  transactionType.value = action;
  transactionQuantity.value = "0";
  transactionWorkOrder.value = "";
  transactionUser.value = "";
  setMessage(transactionMessage, "", "");
  transactionSelected.textContent = `Selected item: ${itemName}`;
  transactionSection.hidden = false;
  transactionSection.scrollIntoView({ behavior: "smooth", block: "start" });

  if (getUsers().length === 0) {
    saveTransactionBtn.disabled = true;
    setMessage(transactionMessage, "Create a user first to record transactions.", "error");
  } else {
    saveTransactionBtn.disabled = false;
    transactionQuantity.focus();
    transactionQuantity.select();
  }
}

export function closeTransactionForm() {
  setSelectedItemId(null);
  transactionSection.hidden = true;
  setMessage(transactionMessage, "", "");
}

txnItemsTbody.addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("stock-btn") || target.classList.contains("dispense-btn")) {
    openTransactionForm(target.dataset.id, target.dataset.name, target.dataset.action);
  }
});

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
    setMessage(transactionMessage, "Quantity must be greater than zero.", "error");
    return;
  }

  const userId = transactionUser.value;
  if (!userId) {
    setMessage(transactionMessage, "Please select a user.", "error");
    return;
  }

  const workOrder = transactionWorkOrder.value.trim();

  try {
    const data = await apiCreateTransaction({
      item_id: selectedId,
      transaction_type: transactionType.value,
      quantity,
      user_id: userId,
      work_order_number: workOrder || null,
    });
    setMessage(transactionMessage, `Transaction saved (${data.transaction_type}, qty ${data.quantity}).`, "success");
    loadTxnItems();
    loadItems();
    setTimeout(closeTransactionForm, 1200);
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(transactionMessage, formatError(err.detail, "An error occurred."), "error");
    } else {
      setMessage(transactionMessage, "Could not connect to the server.", "error");
    }
  }
});
