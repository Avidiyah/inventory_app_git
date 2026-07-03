// View helper: the inline "Edit charge" billing editor.
//
// Layer: views (no fetch, no state of its own). One implementation shared by
// the History Charge cell (`views/history.js`) and the Work Orders line-charge
// cell (`views/workOrders.js`), which drove the same editor nearly
// line-for-line before this was extracted. Both call `openBillingEditor` with
// the row's numbers and a page-specific `onSave`; the markup, focus handling,
// validation, and Save / Don't charge / Cancel wiring live here so the two
// pages can't drift.

import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

// Markup for the editor that replaces a charge cell: a "Bill for N of M"
// number input plus Save / Don't charge / Cancel and a live-region message.
function billingEditorHtml(quantity, billable) {
  return `
    <div class="charge-editor">
      <label class="charge-editor-label">Bill for
        <input type="number" class="charge-input" min="0" max="${escapeHtml(String(quantity))}" step="any" value="${escapeHtml(String(billable))}">
        of ${escapeHtml(String(quantity))}
      </label>
      <div class="charge-editor-actions">
        <button type="button" class="charge-save">Save</button>
        <button type="button" class="charge-zero secondary-btn">Don't charge</button>
        <button type="button" class="charge-cancel secondary-btn">Cancel</button>
      </div>
      <p class="charge-editor-msg" aria-live="polite"></p>
    </div>`;
}

// Swap `cell` for the billing editor and wire its buttons.
//
// - `quantity` is the recorded quantity (the max billable); `billable`
//   prefills the input.
// - `onSave(value)` persists the new billable count and repaints the row:
//   `value` is the count to bill, or `null` to clear the override (empty
//   input, or a value equal to the full quantity — both mean "charge for
//   everything"). It must resolve on success and reject on failure.
//
// On a successful save the caller's repaint discards this editor, so nothing
// is restored. Cancel and a failed save restore the cell's original contents.
export function openBillingEditor(cell, { quantity, billable, onSave }) {
  const original = cell.innerHTML;
  cell.innerHTML = billingEditorHtml(quantity, billable);
  const input = cell.querySelector(".charge-input");
  const msg = cell.querySelector(".charge-editor-msg");
  input.focus();
  input.select();

  async function submit(value) {
    // `value` is the billable count, or null to clear the override.
    cell.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      await onSave(value);  // persists, then repaints the row (discarding this editor)
    } catch (err) {
      cell.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      setMessage(msg, friendlyError(err, "Could not update the charge."), "error");
    }
  }

  cell.querySelector(".charge-cancel").addEventListener("click", () => { cell.innerHTML = original; });
  cell.querySelector(".charge-zero").addEventListener("click", () => submit(0));
  cell.querySelector(".charge-save").addEventListener("click", () => {
    const raw = input.value.trim();
    if (raw === "") { submit(null); return; }  // empty = charge the full amount
    const n = Number(raw);
    if (Number.isNaN(n) || n < 0 || n > quantity) {
      setMessage(msg, `Enter a number between 0 and ${quantity}.`, "error");
      return;
    }
    // Billing the full quantity is the same as no override; send null so the
    // line carries no stale "Billing N of N" annotation.
    submit(n === quantity ? null : n);
  });
}
