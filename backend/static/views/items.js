// View: items list and create-item form (Entry page).
//
// Layer: views. Owns the items table on the Entry page and the
// "Create Item" form above it. Three responsibilities:
//
// 1. Fetch items via `apiListItems`, cache in `state`, render the
//    table with client-side search filtering.
// 2. Handle the create-item submit (with cheap client-side checks
//    before round-tripping to the backend, which is the source of
//    truth for uniqueness and validation).
// 3. Handle row actions: "Edit Notes" delegates to the notes view,
//    delete confirms and calls `apiDeleteItem`.
//
// `setOnDeletedSelectedItem` is set by `main.js` to point at
// `transactions.closeTransactionForm`, so deleting the item that
// is currently selected for a transaction cancels that form
// instead of leaving it pointing at a missing row.
//
// `setOnSaved(loadItems)` registers this view with the notes
// editor so a successful notes save refreshes the table.

import {
  getItems,
  setItems,
  getSelectedItemId,
  getEditingNotesItemId,
  getEditingItemId,
  getRole,
} from "../state.js";
import { apiListItems, apiCreateItem, apiDeleteItem } from "../api.js";
import { escapeHtml, formatError } from "../format.js";
import { setMessage } from "../dom.js";
import { roleAtLeast } from "../roles.js";
import { openNotesEditor, closeNotesEditor, renderNotesSummary, setOnSaved } from "./notes.js";
import {
  openItemEditor,
  closeItemEditor,
  setOnSaved as setOnItemSaved,
} from "./itemEditor.js";
import {
  openCorrection,
  closeCorrection,
  getEditingCorrectionItemId,
  setOnSaved as setOnCorrectionSaved,
} from "./correction.js";

const createItemBtn = document.getElementById("create-item-btn");
const createItemMessage = document.getElementById("create-item-message");
const itemsTbody = document.getElementById("items-tbody");
const itemsSearch = document.getElementById("items-search");
const locationInput = document.getElementById("location");
const barcodeInput = document.getElementById("barcode");
const nameInput = document.getElementById("name");
const quantityInput = document.getElementById("quantity");

let onDeletedSelectedItem = null;

export function setOnDeletedSelectedItem(fn) {
  onDeletedSelectedItem = fn;
}

export async function loadItems() {
  try {
    const items = await apiListItems();
    setItems(items);
    renderItems();
  } catch (error) {
    console.error("Failed to load items:", error);
  }
}

export function renderItems() {
  const term = itemsSearch.value.trim().toLowerCase();
  const all = getItems();
  const items = term
    ? all.filter(item =>
        item.name.toLowerCase().includes(term) ||
        item.barcode.toLowerCase().includes(term))
    : all;

  itemsTbody.innerHTML = "";

  if (items.length === 0) {
    const row = document.createElement("tr");
    const text = term ? "No items match your search." : "No items yet.";
    row.innerHTML = `<td colspan="7">${text}</td>`;
    itemsTbody.appendChild(row);
    return;
  }

  // Items are read/write for Owner/Admin; Supervisor and Technician get
  // a read-only view (search + lookup), so their action cell is empty.
  const canWrite = roleAtLeast(getRole(), "admin");

  items.forEach(item => {
    const row = document.createElement("tr");
    const createdAt = new Date(item.created_at).toLocaleString();
    const actions = canWrite
      ? `<div class="row-actions">
           <button class="edit-item-btn" data-id="${item.id}">Edit</button>
           <button class="edit-notes-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}">Edit Notes</button>
           <button class="correct-item-btn" data-id="${item.id}">Correct</button>
           <button class="delete-btn" data-id="${item.id}" data-name="${escapeHtml(item.name)}">🗑️</button>
         </div>`
      : `<span class="empty">—</span>`;
    row.innerHTML = `
      <td>${escapeHtml(item.barcode)}</td>
      <td>${escapeHtml(item.name)}</td>
      <td>${escapeHtml(item.quantity)}</td>
      <td>${escapeHtml(item.location)}</td>
      <td class="notes-cell">${renderNotesSummary(item.notes)}</td>
      <td>${escapeHtml(createdAt)}</td>
      <td>${actions}</td>
    `;
    itemsTbody.appendChild(row);
  });
}

itemsSearch.addEventListener("input", renderItems);

setOnSaved(loadItems);
setOnItemSaved(loadItems);
setOnCorrectionSaved(loadItems);

createItemBtn.addEventListener("click", async () => {
  const barcode = barcodeInput.value.trim();
  const name = nameInput.value.trim();
  const location = locationInput.value.trim();
  const quantity = quantityInput.value;

  setMessage(createItemMessage, "", "");

  if (!barcode || !name) {
    setMessage(createItemMessage, "Barcode and item name are required.", "error");
    return;
  }
  if (!location) {
    setMessage(createItemMessage, "Location is required.", "error");
    return;
  }

  try {
    const data = await apiCreateItem({
      barcode,
      name,
      location,
      quantity: parseFloat(quantity) || 0,
    });
    setMessage(createItemMessage, `Item "${data.name}" created successfully.`, "success");
    barcodeInput.value = "";
    nameInput.value = "";
    locationInput.value = "";
    quantityInput.value = "0";
    loadItems();
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(createItemMessage, formatError(err.detail, "An error occurred."), "error");
    } else {
      setMessage(createItemMessage, "Could not connect to the server.", "error");
    }
  }
});

itemsTbody.addEventListener("click", async (event) => {
  const target = event.target;

  if (target.classList.contains("edit-item-btn")) {
    const item = getItems().find(i => i.id === target.dataset.id);
    if (item) openItemEditor(item);
    return;
  }

  if (target.classList.contains("correct-item-btn")) {
    const item = getItems().find(i => i.id === target.dataset.id);
    if (item) openCorrection(item);
    return;
  }

  if (target.classList.contains("edit-notes-btn")) {
    openNotesEditor(target.dataset.id, target.dataset.name);
    return;
  }

  if (!target.classList.contains("delete-btn")) return;

  const itemId = target.dataset.id;
  const itemName = target.dataset.name;

  if (!confirm(`Are you sure you want to delete "${itemName}"?`)) return;

  try {
    await apiDeleteItem(itemId);
    if (getSelectedItemId() === itemId && onDeletedSelectedItem) {
      onDeletedSelectedItem();
    }
    if (getEditingNotesItemId() === itemId) {
      closeNotesEditor();
    }
    if (getEditingItemId() === itemId) {
      closeItemEditor();
    }
    if (getEditingCorrectionItemId() === itemId) {
      closeCorrection();
    }
    loadItems();
  } catch (err) {
    alert(err && err.detail ? err.detail : "Failed to delete item.");
  }
});
