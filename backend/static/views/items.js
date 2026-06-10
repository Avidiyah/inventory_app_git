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
import { escapeHtml, friendlyError, formatMoney, safeHttpUrl } from "../format.js";
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
const itemsTheadRow = document.getElementById("items-thead-row");
const itemsTbody = document.getElementById("items-tbody");
const itemsSearch = document.getElementById("items-search");

// Product-link cell: a safe http(s) link renders as an "Open" anchor;
// anything else (missing, or a non-http scheme) shows an em dash.
function productLinkCell(url) {
  const safe = safeHttpUrl(url);
  if (!safe) return "—";
  return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">Open</a>`;
}
const locationInput = document.getElementById("location");
const barcodeInput = document.getElementById("barcode");
const nameInput = document.getElementById("name");
const quantityInput = document.getElementById("quantity");
const priceInput = document.getElementById("price");
const productLinkInput = document.getElementById("product-link");
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

  // Items are read/write for Owner/Admin; Supervisor may edit notes
  // only; Technician is read-only. The backend is still the source of
  // truth -- this is purely UI gating.
  const role = getRole();
  const canAdmin = roleAtLeast(role, "admin");
  const canNotes = roleAtLeast(role, "supervisor");
  // A "worker" here is a Technician: no row actions, so we declutter their
  // lookup table (drop the empty Actions column and the Created timestamp)
  // and lead with the fields they care about on the floor -- quantity and
  // location -- closest to the item name. Supervisor+ keep the full table.
  const isWorker = !canNotes;

  // Per-row Actions menu (only the actions this role can perform). Returns
  // the empty string for a role with no actions, so the column is omitted.
  function actionsCell(item) {
    const options = [];
    if (canAdmin) options.push(`<option value="edit">Edit Details</option>`);
    if (canNotes) options.push(`<option value="notes">Notes</option>`);
    if (canAdmin) {
      options.push(`<option value="correct">Correct Count</option>`);
      options.push(`<option value="delete">Delete Item</option>`);
    }
    if (options.length === 0) return "";
    const ariaLabel = `Actions for ${item.name}`;
    return `<label class="sr-only" for="row-actions-${item.id}">${escapeHtml(ariaLabel)}</label>
       <select id="row-actions-${item.id}" class="row-actions-select" data-id="${item.id}" aria-label="${escapeHtml(ariaLabel)}">
         <option value="" disabled selected>Actions</option>
         ${options.join("")}
       </select>`;
  }

  // Column model in render order; header and rows are both built from this so
  // they can never desync. `primary` marks the name cell (hoisted big on
  // mobile cards); `tdClass` styles the cell.
  const cols = {
    barcode: { label: "Barcode", cell: i => escapeHtml(i.barcode) },
    name: { label: "Name", primary: true, cell: i => escapeHtml(i.name) },
    quantity: { label: "Quantity", cell: i => `<strong>${escapeHtml(i.quantity)}</strong>` },
    location: { label: "Location", cell: i => escapeHtml(i.location) },
    notes: { label: "Notes", tdClass: "notes-cell", cell: i => renderNotesSummary(i.notes) },
  };

  // Technicians lead with quantity/location and drop barcode-first ordering;
  // Supervisor+ keep the original column order.
  const columns = isWorker
    ? [cols.name, cols.quantity, cols.location, cols.barcode, cols.notes]
    : [cols.barcode, cols.name, cols.quantity, cols.location, cols.notes];

  if (canAdmin) {
    columns.push({ label: "Price", cell: i => escapeHtml(formatMoney(i.price)) || "—" });
    columns.push({ label: "Link", cell: i => productLinkCell(i.product_link) });
  }
  if (!isWorker) {
    columns.push({ label: "Created", cell: i => escapeHtml(new Date(i.created_at).toLocaleString()) });
  }
  if (canAdmin || canNotes) {
    columns.push({ label: "Actions", cell: actionsCell });
  }

  // Header.
  itemsTheadRow.innerHTML = columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("");

  // Body.
  itemsTbody.innerHTML = "";
  if (items.length === 0) {
    const row = document.createElement("tr");
    const text = term ? "No items match that search." : "No items yet.";
    row.innerHTML = `<td colspan="${columns.length}">${escapeHtml(text)}</td>`;
    itemsTbody.appendChild(row);
    return;
  }

  items.forEach(item => {
    const row = document.createElement("tr");
    row.innerHTML = columns.map(c => {
      const attr = c.primary ? " data-primary" : ` data-label="${escapeHtml(c.label)}"`;
      const cls = c.tdClass ? ` class="${c.tdClass}"` : "";
      return `<td${cls}${attr}>${c.cell(item)}</td>`;
    }).join("");
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
  const price = priceInput.value;
  const product_link = productLinkInput.value.trim();
  setMessage(createItemMessage, "", "");

  if (!barcode || !name) {
    setMessage(createItemMessage, "Enter a barcode and an item name.", "error");
    return;
  }
  if (!location) {
    setMessage(createItemMessage, "Enter a location.", "error");
    return;
  }

  try {
    const data = await apiCreateItem({
      barcode,
      name,
      location,
      quantity: parseFloat(quantity) || 0,
      price: parseFloat(price) || 0,
      product_link: product_link || null,
    });
    setMessage(createItemMessage, "Item saved.", "success");
    barcodeInput.value = "";
    nameInput.value = "";
    locationInput.value = "";
    quantityInput.value = "";
    priceInput.value = "";
    productLinkInput.value = "";
    loadItems();
  } catch (err) {
    setMessage(createItemMessage, friendlyError(err, "Could not save the item. Try again."), "error");
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
      alert(friendlyError(err, "Could not delete the item. Try again."));
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
