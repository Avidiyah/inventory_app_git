// View: correction (quantity adjust) editor on Saved Items.
//
// Layer: views. Sibling of `notes.js` and `itemEditor.js`. Opens an
// inline panel when the user clicks "Correct" on an item row,
// captures the absolute new quantity and a required reason, and
// posts to `POST /transactions/adjust` (Admin+).
//
// The backend computes the signed delta under the item row lock and
// appends a `transaction_type = "adjust"` audit row -- the existing
// quantity rule (`Item.quantity` only changes via a transaction)
// still holds.
//
// Public surface:
// - `openCorrection(item)` populates and reveals the panel.
// - `closeCorrection()` hides it (called on cancel, on success, and
//   by `items.js` when the open item is deleted).
// - `setOnSaved(fn)` lets the items view register a callback so the
//   table refreshes after a successful correction.

import { apiCreateCorrection } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const correctionSection = document.getElementById("correction-section");
const correctionSelected = document.getElementById("correction-selected");
const correctionCurrent = document.getElementById("correction-current");
const correctionNewQuantity = document.getElementById("correction-new-quantity");
const correctionReason = document.getElementById("correction-reason");
const correctionSaveBtn = document.getElementById("correction-save-btn");
const correctionCancelBtn = document.getElementById("correction-cancel-btn");
const correctionMessage = document.getElementById("correction-message");

let editingItemId = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openCorrection(item) {
  editingItemId = item.id;
  correctionSelected.textContent = `Correcting: ${item.name} (${item.barcode})`;
  correctionCurrent.textContent = `Current count: ${item.quantity}`;
  correctionNewQuantity.value = item.quantity;
  correctionReason.value = "";
  setMessage(correctionMessage, "", "");
  correctionSection.hidden = false;
  correctionSection.scrollIntoView({ behavior: "smooth", block: "start" });
  correctionNewQuantity.focus();
  correctionNewQuantity.select();
}

export function closeCorrection() {
  editingItemId = null;
  correctionSection.hidden = true;
  correctionNewQuantity.value = "";
  correctionReason.value = "";
  setMessage(correctionMessage, "", "");
}

export function getEditingCorrectionItemId() {
  return editingItemId;
}

correctionCancelBtn.addEventListener("click", closeCorrection);

correctionSaveBtn.addEventListener("click", async () => {
  if (!editingItemId) {
    setMessage(correctionMessage, "No item selected.", "error");
    return;
  }
  setMessage(correctionMessage, "", "");

  const raw = correctionNewQuantity.value;
  const newQuantity = Number(raw);
  if (raw === "" || !Number.isFinite(newQuantity)) {
    setMessage(correctionMessage, "Enter a valid new count.", "error");
    return;
  }
  if (newQuantity < 0) {
    setMessage(correctionMessage, "Enter a count of zero or more.", "error");
    return;
  }
  const reason = correctionReason.value.trim();
  if (!reason) {
    setMessage(correctionMessage, "Enter a reason for the correction.", "error");
    return;
  }

  try {
    await apiCreateCorrection({
      itemId: editingItemId,
      newQuantity,
      reason,
    });
    setMessage(correctionMessage, "Count corrected.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeCorrection, 1000);
  } catch (err) {
    setMessage(correctionMessage, friendlyError(err, "Could not save the correction. Try again."), "error");
  }
});
