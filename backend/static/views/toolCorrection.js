// View: tool count correction editor on the Tools page.
//
// Layer: views. Sibling of `correction.js` (items) -- identical shape,
// just posting to `POST /tools/{id}/adjust`. Opens an inline panel when
// Admin+ picks "Correct Count" on a tool row, captures the absolute new
// on-hand quantity and a required reason.
//
// Public surface:
// - `openToolCorrection(tool)` populates and reveals the panel.
// - `closeToolCorrection()` hides it (called on cancel, on success, and by
//   tools.js when the open tool is archived).
// - `setOnSaved(fn)` lets tools.js register a callback so the table
//   refreshes after a successful correction.

import { apiAdjustTool } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const correctionSection = document.getElementById("tool-correction-section");
const correctionSelected = document.getElementById("tool-correction-selected");
const correctionCurrent = document.getElementById("tool-correction-current");
const correctionNewQuantity = document.getElementById("tool-correction-new-quantity");
const correctionReason = document.getElementById("tool-correction-reason");
const correctionSaveBtn = document.getElementById("tool-correction-save-btn");
const correctionCancelBtn = document.getElementById("tool-correction-cancel-btn");
const correctionMessage = document.getElementById("tool-correction-message");

let correctingToolId = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openToolCorrection(tool) {
  correctingToolId = tool.id;
  correctionSelected.textContent = `Correcting: ${tool.name} (${tool.barcode})`;
  correctionCurrent.textContent = `Current count: ${tool.quantity}`;
  correctionNewQuantity.value = tool.quantity;
  correctionReason.value = "";
  setMessage(correctionMessage, "", "");
  correctionSection.hidden = false;
  correctionSection.scrollIntoView({ behavior: "smooth", block: "start" });
  correctionNewQuantity.focus();
  correctionNewQuantity.select();
}

export function closeToolCorrection() {
  correctingToolId = null;
  correctionSection.hidden = true;
  correctionNewQuantity.value = "";
  correctionReason.value = "";
  setMessage(correctionMessage, "", "");
}

export function getCorrectingToolId() {
  return correctingToolId;
}

correctionCancelBtn.addEventListener("click", closeToolCorrection);

correctionSaveBtn.addEventListener("click", async () => {
  if (!correctingToolId) {
    setMessage(correctionMessage, "No tool selected.", "error");
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
    await apiAdjustTool(correctingToolId, { newQuantity, reason });
    setMessage(correctionMessage, "Count corrected.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeToolCorrection, 1000);
  } catch (err) {
    setMessage(correctionMessage, friendlyError(err, "Could not save the correction. Try again."), "error");
  }
});
