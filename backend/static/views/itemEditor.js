// View: item editor (inline panel on the Saved Items page).
//
// Layer: views. Mirrors `notes.js`: a sibling panel that opens
// when the user clicks "Edit" on an item row, edits the core
// fields (barcode, name, location, price, product link) plus the
// item's *additional* barcodes, and saves via `PATCH /items/{id}`
// (core fields) and `PATCH /items/{id}/barcodes` (additional
// codes). Quantity is intentionally not editable here -- direct
// corrections go through the corrections flow.
//
// The additional-barcodes list is the add-a-row / remove-a-row
// pattern borrowed from the notes editor: each physical item can
// carry several package codes, and a scan of any of them resolves
// to the item. Save issues the barcodes PATCH first (so a
// duplicate-code 400 surfaces before the core fields are written),
// then the core PATCH.
//
// Public surface:
// - `openItemEditor(item)` populates and reveals the panel.
// - `closeItemEditor()` hides it (called on cancel, on success,
//   and by `items.js` when the open item is deleted).
// - `setOnSaved(fn)` lets the items view register a callback so
//   the table refreshes after a successful edit (same pattern
//   `notes.js` uses).
//
// Barcode is editable, but a confirm dialog warns that any scanner
// labels in the field still pointing at the old code will stop
// resolving. The user can dismiss the change without losing the
// other field edits.

import { getEditingItemId, setEditingItemId } from "../state.js";
import { apiUpdateItem, apiUpdateBarcodes } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmArchivedReuse } from "../dom.js";

const itemEditorSection = document.getElementById("item-editor-section");
const itemEditorSelected = document.getElementById("item-editor-selected");
const itemEditorBarcode = document.getElementById("item-editor-barcode");
const itemEditorName = document.getElementById("item-editor-name");
const itemEditorLocation = document.getElementById("item-editor-location");
const itemEditorBarcodesRows = document.getElementById("item-editor-barcodes-rows");
const itemEditorAddBarcodeBtn = document.getElementById("item-editor-add-barcode-btn");
const itemEditorPrice = document.getElementById("item-editor-price");
const itemEditorProductLink = document.getElementById("item-editor-product-link");
const itemEditorSaveBtn = document.getElementById("item-editor-save-btn");
const itemEditorCancelBtn = document.getElementById("item-editor-cancel-btn");
const itemEditorMessage = document.getElementById("item-editor-message");

// Snapshot of the item's additional barcodes captured on open, so we can
// skip the second API call entirely when the list is unchanged.
let originalBarcodes = [];

// Original barcode captured on open, so we can detect a change at
// save-time and prompt the confirm dialog only when it actually shifts.
let originalBarcode = "";

let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openItemEditor(item) {
  setEditingItemId(item.id);
  originalBarcode = item.barcode;
  originalBarcodes = Array.isArray(item.barcodes) ? [...item.barcodes] : [];
  itemEditorSelected.textContent = `Editing: ${item.name}`;
  itemEditorBarcode.value = item.barcode;
  itemEditorName.value = item.name;
  itemEditorLocation.value = item.location;
  itemEditorPrice.value = item.price ?? "";
  itemEditorProductLink.value = item.product_link ?? "";

  itemEditorBarcodesRows.innerHTML = "";
  originalBarcodes.forEach(code => addBarcodeRow(code));

  setMessage(itemEditorMessage, "", "");
  itemEditorSection.hidden = false;
  itemEditorSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function closeItemEditor() {
  setEditingItemId(null);
  originalBarcode = "";
  originalBarcodes = [];
  itemEditorBarcodesRows.innerHTML = "";
  itemEditorSection.hidden = true;
  setMessage(itemEditorMessage, "", "");
}

// Append one additional-barcode input row (text field + remove button),
// mirroring the notes editor's add-a-row pattern.
function addBarcodeRow(code = "") {
  const row = document.createElement("div");
  row.className = "barcode-row";
  row.innerHTML = `
    <input type="text" class="barcode-code" placeholder="Additional barcode" aria-label="Additional barcode" value="${escapeHtml(code)}">
    <button type="button" class="note-remove-btn" title="Remove" aria-label="Remove barcode">×</button>
  `;
  row.querySelector(".note-remove-btn").addEventListener("click", () => row.remove());
  itemEditorBarcodesRows.appendChild(row);
}

// Collect the current rows into a trimmed, blank-dropped list. Returns
// `null` (after showing a message) if two rows hold the same code.
function collectBarcodes() {
  const codes = [];
  const seen = new Set();
  for (const input of itemEditorBarcodesRows.querySelectorAll(".barcode-code")) {
    const code = input.value.trim();
    if (!code) continue;
    if (seen.has(code)) {
      setMessage(itemEditorMessage, `The barcode "${code}" is listed twice. Remove the duplicate.`, "error");
      return null;
    }
    seen.add(code);
    codes.push(code);
  }
  return codes;
}

itemEditorAddBarcodeBtn.addEventListener("click", () => addBarcodeRow());
itemEditorCancelBtn.addEventListener("click", closeItemEditor);

itemEditorSaveBtn.addEventListener("click", async () => {
  const editingId = getEditingItemId();
  if (!editingId) {
    setMessage(itemEditorMessage, "No item selected.", "error");
    return;
  }
  setMessage(itemEditorMessage, "", "");

  const barcode = itemEditorBarcode.value.trim();
  const name = itemEditorName.value.trim();
  const location = itemEditorLocation.value.trim();
  const price = itemEditorPrice.value.trim();
  const productLink = itemEditorProductLink.value.trim();

  if (!barcode || !name || !location) {
    setMessage(itemEditorMessage, "Barcode, name, and location are required.", "error");
    return;
  }

  const codes = collectBarcodes();
  if (codes === null) return; // duplicate in the list; message already shown

  if (barcode !== originalBarcode) {
    const ok = confirm(
      "Changing this barcode breaks any scanner labels still pointing at this row. Continue?"
    );
    if (!ok) return;
  }

  const barcodesChanged = JSON.stringify(codes) !== JSON.stringify(originalBarcodes);

  // Two awaited calls behind one Save: the additional barcodes go through
  // their own endpoint (PATCH /items/{id}/barcodes), the core fields
  // through PATCH /items/{id}. Barcodes go first so a duplicate-code 400
  // surfaces before the core fields are touched. On any failure we leave
  // the panel open (no auto-close) so the user can fix and retry; both
  // writes are idempotent wholesale replacements, so re-saving reconciles
  // any partial application.
  try {
    // Both writes ride one confirmArchivedReuse: if either the additional
    // barcodes or the new primary collide with an *archived* item, the backend
    // answers 409, we prompt once, and re-run the whole (idempotent) sequence
    // with override_archived to free the archived holder.
    await confirmArchivedReuse(async (override) => {
      if (barcodesChanged) {
        await apiUpdateBarcodes(editingId, codes, override);
      }
      await apiUpdateItem(editingId, {
        barcode,
        name,
        location,
        price: price ? parseFloat(price) : null,
        product_link: productLink ? productLink : null,
        override_archived: override,
      });
    });
    originalBarcodes = [...codes];
    setMessage(itemEditorMessage, "Item saved.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeItemEditor, 1000);
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(itemEditorMessage, "", "");
      return;
    }
    setMessage(itemEditorMessage, friendlyError(err, "Could not save the changes. Try again."), "error");
  }
});
