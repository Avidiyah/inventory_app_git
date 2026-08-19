// View: items list and create-item form (Entry page).
//
// Layer: views. Owns the items table on the Entry page and the
// "Create Item" form above it. Three responsibilities:
//
// 1. Keep the initial view empty, then fetch and render full item rows only
//    after an explicit search, load-all action, or scan.
// 2. Handle the create-item submit (with cheap client-side checks
//    before round-tripping to the backend, which is the source of
//    truth for uniqueness and validation).
// 3. Handle row actions: "Edit Notes" delegates to the notes view,
//    delete confirms and calls `apiDeleteItem`.
//
// Row-editor callbacks refresh only the currently displayed result set.

import {
  getItems,
  setItems,
  getEditingNotesItemId,
  getEditingItemId,
  getRole,
} from "../state.js";
import {
  apiListItems,
  apiCreateItem,
  apiDeleteItem,
} from "../api.js";
import { escapeHtml, friendlyError, formatMoney, safeHttpUrl } from "../format.js";
import { setMessage, confirmArchivedReuse, confirmDialog } from "../dom.js";
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
import { openAddBarcode, closeAddBarcode, setOnSaved as setOnAddBarcodeSaved } from "./addBarcode.js";
import { itemRequestPromptHtml } from "./itemRequest.js";
import { initSubNav } from "./subnav.js";
import { toolScanWidget } from "./tools.js";

const createItemBtn = document.getElementById("create-item-btn");
const createItemMessage = document.getElementById("create-item-message");
const itemsTable = document.getElementById("items-table");
const itemsTheadRow = document.getElementById("items-thead-row");
const itemsTbody = document.getElementById("items-tbody");
const itemsSearch = document.getElementById("items-search");
const itemsSearchBtn = document.getElementById("items-search-btn");
const itemsLoadAllBtn = document.getElementById("items-load-all-btn");
const itemsMessage = document.getElementById("items-message");

let resultMode = "none";
let resultQuery = "";
let resultRequestId = 0;

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

export function loadItems() {
  // Opening Find Item intentionally makes no item request and renders no
  // rows. The plain search field has no browser-native suggestion popup;
  // results require Search / Enter, Load All Items, or a successful scan.
  resultRequestId += 1;
  resultMode = "none";
  resultQuery = "";
  setItems([]);
  itemsSearch.value = "";
  itemsTable.hidden = true;
  itemsTbody.innerHTML = "";
  setResultsBusy(false);
  setMessage(itemsMessage, "Search by name or barcode, or load all items.", "");
}

function setResultsBusy(busy) {
  itemsSearchBtn.disabled = busy;
  itemsLoadAllBtn.disabled = busy;
}

async function loadItemResults({ query = null, emptyMessage }) {
  const requestId = ++resultRequestId;
  setResultsBusy(true);
  itemsTable.hidden = false;
  itemsTbody.innerHTML = `<tr><td colspan="8" class="hint">Loading…</td></tr>`;

  try {
    const items = query === null
      ? await apiListItems()
      : await apiListItems({ query });
    if (requestId !== resultRequestId) return;
    setItems(items);
    renderItems(emptyMessage);
  } catch (error) {
    if (requestId !== resultRequestId) return;
    setItems([]);
    itemsTbody.innerHTML =
      `<tr><td colspan="8" class="error">${escapeHtml(friendlyError(error, "Could not load items. Try again."))}</td></tr>`;
  } finally {
    if (requestId === resultRequestId) setResultsBusy(false);
  }
}

async function searchItems() {
  const term = itemsSearch.value.trim();
  if (!term) {
    setMessage(itemsMessage, "Enter a name or barcode to search.", "error");
    itemsSearch.focus();
    return;
  }
  setMessage(itemsMessage, "", "");
  resultMode = "search";
  resultQuery = term;
  await loadItemResults({ query: term, emptyMessage: "No items match that search." });
}

async function loadAllItems() {
  itemsSearch.value = "";
  setMessage(itemsMessage, "", "");
  resultMode = "all";
  resultQuery = "";
  await loadItemResults({ emptyMessage: "No items yet." });
}

async function refreshDisplayedItems() {
  if (resultMode === "search" || resultMode === "scan") {
    await loadItemResults({ query: resultQuery, emptyMessage: "No items match that search." });
  } else if (resultMode === "all") {
    await loadItemResults({ emptyMessage: "No items yet." });
  }
}

export function renderItems(emptyMessage = "No items match that search.") {
  const items = getItems();
  itemsTable.hidden = false;

  // Items are read/write for TechFM OA and above; Supervisor may edit notes
  // only; Technician is read-only. The backend is still the source of
  // truth -- this is purely UI gating.
  const role = getRole();
  const canAdmin = roleAtLeast(role, "techfm_oa");
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
      options.push(`<option value="delete">Archive Item</option>`);
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
    // Only a *search* that found nothing means "the catalogue has no such
    // item" -- an empty Load All just means an empty catalogue, and a scan
    // has its own create-item shortcut, so neither offers to file a request.
    const prompt = resultMode === "search" && resultQuery
      ? itemRequestPromptHtml({ searchedText: resultQuery, source: "find_item" })
      : "";
    row.innerHTML =
      `<td colspan="${columns.length}">${escapeHtml(emptyMessage)}${prompt}</td>`;
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

itemsSearchBtn.addEventListener("click", searchItems);
itemsLoadAllBtn.addEventListener("click", loadAllItems);
itemsSearch.addEventListener("keydown", event => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  searchItems();
});

setOnSaved(refreshDisplayedItems);
setOnItemSaved(refreshDisplayedItems);
setOnCorrectionSaved(refreshDisplayedItems);
setOnAddBarcodeSaved(refreshDisplayedItems);

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
    // On a 409 the barcode belongs to an archived item; confirmArchivedReuse
    // prompts and re-submits with override_archived to free it.
    await confirmArchivedReuse((override) => apiCreateItem({
      barcode,
      name,
      location,
      quantity: parseFloat(quantity) || 0,
      price: parseFloat(price) || 0,
      product_link: product_link || null,
      override_archived: override,
    }));
    setMessage(createItemMessage, "Item saved.", "success");
    barcodeInput.value = "";
    nameInput.value = "";
    locationInput.value = "";
    quantityInput.value = "";
    priceInput.value = "";
    productLinkInput.value = "";
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(createItemMessage, "", "");
      return;
    }
    setMessage(createItemMessage, friendlyError(err, "Could not save the item. Try again."), "error");
  }
});

// --- Add Item scanner (Item tab, create-item page) ----------------------
//
// Scoped to this form's own barcode field: a match warns (someone else
// already has this code), a miss fills the field so the user doesn't
// retype it. Distinct from `itemsScanner` below, which is the Saved
// Items page's Find/Scan lookup aid.

const itemScanToggleBtn = document.getElementById("item-scan-toggle-btn");
const itemScanControls = document.getElementById("item-scan-controls");
const itemScanInput = document.getElementById("item-scan-input");
const itemScanMessage = document.getElementById("item-scan-message");
const itemScanChooser = document.getElementById("item-scan-chooser");

export const itemScanWidget = mountScanner({
  inputEl: itemScanInput,
  messageEl: itemScanMessage,
  chooserEl: itemScanChooser,
  allowCreate: false,
  onNotFound: (barcode) => {
    barcodeInput.value = barcode;
    itemScanControls.hidden = true;
  },
  onItemFound: (item) => setMessage(itemScanMessage, `Already in use by ${item.name}.`, "error"),
  liveEls: {
    videoEl: document.getElementById("item-scan-video"),
    scanBtn: document.getElementById("item-scan-scan-btn"),
    uploadBtn: document.getElementById("item-scan-upload-btn"),
    torchBtn: document.getElementById("item-scan-torch-btn"),
    aimboxEl: document.getElementById("item-scan-aimbox"),
  },
});

itemScanToggleBtn.addEventListener("click", () => {
  const collapsing = !itemScanControls.hidden;
  itemScanControls.hidden = collapsing;
  if (collapsing) itemScanWidget.stopLive();
});

// Item and Tool are sub-nav tabs on the create-item page; only one camera
// should ever be live, so leaving a tab stops that tab's scanner.
initSubNav(document.getElementById("create-item-page"), {
  onShow(feature, prev) {
    if (prev === "item" && feature !== "item") itemScanWidget.stopLive();
    if (prev === "tool" && feature !== "tool") toolScanWidget.stopLive();
  },
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
    setMessage(itemsMessage, "", "");
    if (!(await confirmDialog(`Archive "${item.name}"? It will be hidden from lookup and lists, but its history is kept.`))) return;
    try {
      await apiDeleteItem(itemId);
      if (getEditingNotesItemId() === itemId) {
        closeNotesEditor();
      }
      if (getEditingItemId() === itemId) {
        closeItemEditor();
      }
      if (getEditingCorrectionItemId() === itemId) {
        closeCorrection();
      }
      setMessage(itemsMessage, `Archived "${item.name}".`, "success");
      await refreshDisplayedItems();
    } catch (err) {
      setMessage(itemsMessage, friendlyError(err, "Could not archive the item. Try again."), "error");
    }
  }
});

// --- Saved Items scanner ----------------------------------------
//
// Same widget as the Transaction page (see views/scan.js). Visible to
// all roles -- it's a read-only lookup aid. On a successful match we
// render the returned item directly and scroll the matching row into view.
// On a 404 the Create-Item shortcut inside
// the chooser is gated to Owner/Admin by `mountScanner` itself.

const itemsScanInput = document.getElementById("items-scan-input");
const itemsScanMessage = document.getElementById("items-scan-message");
const itemsScanChooser = document.getElementById("items-scan-chooser");

// Shared with the Transaction-page scanner: the Create-Item form
// lives on its own page, so the shortcut prefills `#barcode` and
// clicks the nav button to switch pages.
const createItemNavBtnForItems = document.querySelector('.nav-btn[data-page="create-item"]');
const createItemBarcodeInput = document.getElementById("barcode");

// Assigned at the bottom of this module once the scanner exists; the
// scanner's onItemFound reads it to flip back to the Find feature.
let itemsSubNav = null;

export const itemsScanner = mountScanner({
  inputEl: itemsScanInput,
  messageEl: itemsScanMessage,
  chooserEl: itemsScanChooser,
  allowCreate: true,
  onItemFound: (item) => {
    // A scan resolves on the Scan feature, but the result lives in the
    // Find list -- switch back so the match is actually visible.
    if (itemsSubNav) itemsSubNav.showFeature("find");
    resultRequestId += 1;
    resultMode = "scan";
    resultQuery = item.barcode;
    setResultsBusy(false);
    setItems([item]);
    itemsSearch.value = item.barcode;
    setMessage(itemsMessage, "", "");
    renderItems("No items match that barcode.");
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
  onAddBarcode: (barcode) => openAddBarcode(barcode),
  liveEls: {
    videoEl:   document.getElementById("items-scan-video"),
    scanBtn:   document.getElementById("items-scan-scan-btn"),
    uploadBtn: document.getElementById("items-scan-upload-btn"),
    torchBtn:  document.getElementById("items-scan-torch-btn"),
    aimboxEl:  document.getElementById("items-scan-aimbox"),
  },
});

// --- Find Item sub-navigation -----------------------------------
//
// Find (the list) and Scan are sibling features: exactly one is shown at a
// time via the page's `.sub-nav`. The lifecycle hook keeps the camera and
// the contextual sub-flows honest when the feature switches:
//   - leaving Scan releases the camera (it never lingers on a hidden panel);
//   - entering Scan refreshes the camera-permission state (toggles the
//     Scan button / blocked message), mirroring nav.js's page-level call;
//   - any feature switch closes an open Edit / Notes / Correct / Add-barcode
//     sub-flow so only one thing is ever on screen.
itemsSubNav = initSubNav(document.getElementById("saved-items-page"), {
  onShow(feature, prev) {
    if (prev === "scan" && feature !== "scan") itemsScanner.stopLive();
    if (feature === "scan") itemsScanner.refreshPermissionState();
    if (prev && prev !== feature) {
      closeNotesEditor();
      closeItemEditor();
      closeCorrection();
      closeAddBarcode();
    }
  },
});
