// View helper: the inline "Correct Count" panel shared by Saved Items
// (`correction.js`, posting `POST /transactions/adjust`) and Tools
// (`toolCorrection.js`, posting `POST /tools/{id}/adjust`).
//
// Layer: views. Both panels are the same markup under different id prefixes
// and the same flow: open with the row, capture an absolute new quantity and
// a required reason, submit, refresh the caller's table, close after a beat.
// The backend computes the signed delta under the row lock and appends the
// audit row -- the quantity rule (`quantity` only changes via a transaction)
// still holds.
//
// `createCorrectionPanel({ idPrefix, noun, submit })` returns
// `{ open, close, getEditingId, setOnSaved }`; the two view modules export
// those under their existing names.

import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

export function createCorrectionPanel({ idPrefix, noun, submit }) {
  const section = document.getElementById(`${idPrefix}-section`);
  const selected = document.getElementById(`${idPrefix}-selected`);
  const current = document.getElementById(`${idPrefix}-current`);
  const newQuantityInput = document.getElementById(`${idPrefix}-new-quantity`);
  const reasonInput = document.getElementById(`${idPrefix}-reason`);
  const saveBtn = document.getElementById(`${idPrefix}-save-btn`);
  const cancelBtn = document.getElementById(`${idPrefix}-cancel-btn`);
  const message = document.getElementById(`${idPrefix}-message`);

  let editingId = null;
  let onSavedCallback = null;

  function setOnSaved(fn) {
    onSavedCallback = fn;
  }

  function open(row) {
    editingId = row.id;
    selected.textContent = `Correcting: ${row.name} (${row.barcode})`;
    current.textContent = `Current count: ${row.quantity}`;
    newQuantityInput.value = row.quantity;
    reasonInput.value = "";
    setMessage(message, "", "");
    section.hidden = false;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    newQuantityInput.focus();
    newQuantityInput.select();
  }

  function close() {
    editingId = null;
    section.hidden = true;
    newQuantityInput.value = "";
    reasonInput.value = "";
    setMessage(message, "", "");
  }

  function getEditingId() {
    return editingId;
  }

  cancelBtn.addEventListener("click", close);

  saveBtn.addEventListener("click", async () => {
    if (!editingId) {
      setMessage(message, `No ${noun} selected.`, "error");
      return;
    }
    setMessage(message, "", "");

    const raw = newQuantityInput.value;
    const newQuantity = Number(raw);
    if (raw === "" || !Number.isFinite(newQuantity)) {
      setMessage(message, "Enter a valid new count.", "error");
      return;
    }
    if (newQuantity < 0) {
      setMessage(message, "Enter a count of zero or more.", "error");
      return;
    }
    const reason = reasonInput.value.trim();
    if (!reason) {
      setMessage(message, "Enter a reason for the correction.", "error");
      return;
    }

    try {
      await submit(editingId, { newQuantity, reason });
      setMessage(message, "Count corrected.", "success");
      if (onSavedCallback) await onSavedCallback();
      setTimeout(close, 1000);
    } catch (err) {
      setMessage(message, friendlyError(err, "Could not save the correction. Try again."), "error");
    }
  });

  return { open, close, getEditingId, setOnSaved };
}
