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
import { mountScanner } from "./scan.js";

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

  // Items are read/write for Owner/Admin; Supervisor may edit notes
  // only; Technician is read-only. The action column renders a
  // per-row dropdown of only the actions the current role can perform
  // (see §3 in docs/plan-saved-items-and-history.md). The backend is
  // still the source of truth -- this is purely UI gating.
  const role = getRole();
  const canAdmin = roleAtLeast(role, "admin");
  const canNotes = roleAtLeast(role, "supervisor");

  items.forEach(item => {
    const row = document.createElement("tr");
    const createdAt = new Date(item.created_at).toLocaleString();

    const actionOptions = [];
    if (canAdmin) actionOptions.push(`<option value="edit">Edit</option>`);
    if (canNotes) actionOptions.push(`<option value="notes">Edit Notes</option>`);
    if (canAdmin) {
      actionOptions.push(`<option value="correct">Correct</option>`);
      actionOptions.push(`<option value="delete">Delete</option>`);
    }

    const ariaLabel = `Actions for ${item.name}`;
    const actions = actionOptions.length === 0
      ? `<span class="empty">—</span>`
      : `<label class="sr-only" for="row-actions-${item.id}">${escapeHtml(ariaLabel)}</label>
         <select id="row-actions-${item.id}" class="row-actions-select" data-id="${item.id}" aria-label="${escapeHtml(ariaLabel)}">
           <option value="" disabled selected>Actions</option>
           ${actionOptions.join("")}
         </select>`;

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

itemsTbody.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.classList.contains("row-actions-select")) return;

  const action = target.value;
  const itemId = target.dataset.id;
  // Reset to the placeholder so picking the same action twice in a
  // row still fires `change` and so the cell never visually "remembers"
  // a destructive choice.
  target.value = "";

  if (!action || !itemId) return;
  const item = getItems().find(i => i.id === itemId);
  if (!item) return;

  if (action === "edit") {
    openItemEditor(item);
    return;
  }

  if (action === "correct") {
    openCorrection(item);
    return;
  }

  if (action === "notes") {
    openNotesEditor(item.id, item.name);
    return;
  }

  if (action === "delete") {
    if (!confirm(`Are you sure you want to delete "${item.name}"?`)) return;
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
  }
});

// --- Saved Items scanner ----------------------------------------
//
// Same widget as the Transaction page (see views/scan.js). Visible to
// all roles -- it's a read-only lookup aid. On a successful match we
// filter the items table by the scanned barcode and scroll the
// matching row into view. On a 404 the Create-Item shortcut inside
// the chooser is gated to Owner/Admin by `mountScanner` itself.

const itemsScanInput = document.getElementById("items-scan-input");
const itemsScanMessage = document.getElementById("items-scan-message");
const itemsScanChooser = document.getElementById("items-scan-chooser");

// Shared with the Transaction-page scanner: the Create-Item form
// lives on its own page, so the shortcut prefills `#barcode` and
// clicks the nav button to switch pages.
const createItemNavBtnForItems = document.querySelector('.nav-btn[data-page="create-item"]');
const createItemBarcodeInput = document.getElementById("barcode");

export const itemsScanner = mountScanner({
  inputEl: itemsScanInput,
  messageEl: itemsScanMessage,
  chooserEl: itemsScanChooser,
  allowCreate: true,
  onItemFound: (item) => {
    itemsSearch.value = item.barcode;
    renderItems();
    // Scroll the (now-single) matching row into view if it exists.
    const row = itemsTbody.querySelector("tr");
    if (row && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  },
  onCreateShortcut: (barcode) => {
    if (createItemBarcodeInput) createItemBarcodeInput.value = barcode;
    if (createItemNavBtnForItems) createItemNavBtnForItems.click();
  },
  liveEls: {
    videoEl:   document.getElementById("items-scan-video"),
    scanBtn:   document.getElementById("items-scan-scan-btn"),
    uploadBtn: document.getElementById("items-scan-upload-btn"),
    torchBtn:  document.getElementById("items-scan-torch-btn"),
    aimboxEl:  document.getElementById("items-scan-aimbox"),
  },
});
