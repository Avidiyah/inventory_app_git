// View: item editor (inline panel on the Saved Items page).
//
// Layer: views. Mirrors `notes.js`: a sibling panel that opens
// when the user clicks "Edit" on an item row, edits the three
// core fields (barcode, name, location), and saves via
// `PATCH /items/{id}`. Quantity is intentionally not editable
// here -- direct corrections go through the corrections flow.
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
import { apiUpdateItem } from "../api.js";
import { formatError } from "../format.js";
import { setMessage } from "../dom.js";

const itemEditorSection = document.getElementById("item-editor-section");
const itemEditorSelected = document.getElementById("item-editor-selected");
const itemEditorBarcode = document.getElementById("item-editor-barcode");
const itemEditorName = document.getElementById("item-editor-name");
const itemEditorLocation = document.getElementById("item-editor-location");
const itemEditorSaveBtn = document.getElementById("item-editor-save-btn");
const itemEditorCancelBtn = document.getElementById("item-editor-cancel-btn");
const itemEditorMessage = document.getElementById("item-editor-message");

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
  itemEditorSelected.textContent = `Editing: ${item.name}`;
  itemEditorBarcode.value = item.barcode;
  itemEditorName.value = item.name;
  itemEditorLocation.value = item.location;
  setMessage(itemEditorMessage, "", "");
  itemEditorSection.hidden = false;
  itemEditorSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function closeItemEditor() {
  setEditingItemId(null);
  originalBarcode = "";
  itemEditorSection.hidden = true;
  setMessage(itemEditorMessage, "", "");
}

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

  if (!barcode || !name || !location) {
    setMessage(itemEditorMessage, "Barcode, name, and location are required.", "error");
    return;
  }

  if (barcode !== originalBarcode) {
    const ok = confirm(
      "Changing this barcode breaks any scanner labels still pointing at this row. Continue?"
    );
    if (!ok) return;
  }

  // Always send all three. The backend treats same-value fields as a
  // no-op write; keeping the request shape stable simplifies the client
  // and makes the PATCH idempotent.
  try {
    await apiUpdateItem(editingId, { barcode, name, location });
    setMessage(itemEditorMessage, "Item updated.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeItemEditor, 1000);
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(itemEditorMessage, formatError(err.detail, "Failed to update item."), "error");
    } else {
      setMessage(itemEditorMessage, "Could not connect to the server.", "error");
    }
  }
});
