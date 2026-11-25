// Work Orders: the Takeoff section of the card.
//
// Layer: one HTML builder and one click handler. Team Lead+ plans material per
// order here (no stock moves); anyone who may add material turns a planned line
// into a real dispense with one tap, through the existing Add Item endpoint.
// The line holds only what is still to dispense, so "m" in "n left of m" is
// that plus what the order already logged for the same item.
//
// Imports no card module: workOrderCardHtml.js imports this one, and the page
// pieces the handler needs (refresh, the add-item success line) arrive in `ctx`.

import {
  apiAddTakeoffLine,
  apiAddWorkOrderItem,
  apiDeleteTakeoffLine,
  apiUpdateTakeoffLine,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml } from "../format.js";

const lines = (detail) => detail.takeoff ?? [];

// Decimal strings summed without float drift (six places is far past stock counts).
const sum = (...parts) => String(Math.round(parts.reduce((a, b) => a + Number(b), 0) * 1e6) / 1e6);

export const takeoffVisible = (detail, canEdit) => canEdit || lines(detail).length > 0;

export function takeoffMoreLabel(detail) {
  const n = lines(detail).length;
  return n ? `Takeoff · ${n}` : "Takeoff";
}

function lineHtml(detail, line, { canEdit, canDispense }) {
  const id = escapeHtml(line.id);
  const done = detail.items.filter((it) => it.item_id === line.item_id).map((it) => it.quantity);
  const left = `${escapeHtml(line.quantity)} left of ${escapeHtml(sum(line.quantity, ...done))}`;
  const dispense = canDispense
    ? `<button type="button" data-action="open-dispense-takeoff">Dispense</button>`
    : "";
  const edit = canEdit
    ? `<input type="number" class="wo-line-qty wo-tk-qty" id="wo-tk-qty-${id}" value="${escapeHtml(line.quantity)}" min="0" step="any" aria-label="Planned quantity">
       <button type="button" class="secondary-btn" data-action="edit-takeoff">Update</button>
       <button type="button" class="btn-danger" data-action="remove-takeoff">Remove</button>`
    : "";
  const form = canDispense
    ? `<div class="wo-takeoff-dispense" id="wo-tk-dispense-${id}" hidden>
         <input type="number" class="wo-tk-dispense-qty" id="wo-tk-dispense-qty-${id}" value="${escapeHtml(line.quantity)}" min="0" step="any" aria-label="Quantity to dispense">
         <button type="button" data-action="dispense-takeoff">Dispense</button>
       </div>`
    : "";
  return `<div class="wo-takeoff-line" id="wo-tk-${id}" data-takeoff-id="${id}" data-item-id="${escapeHtml(line.item_id)}">
            <div class="wo-takeoff-head">
              <span class="ms-item-name">${escapeHtml(line.item_name)}</span>
              <span class="wo-takeoff-left">${left}</span>
            </div>
            <div class="wo-item-actions">${dispense}${edit}</div>
            ${form}
          </div>`;
}

// "" when there is nothing to show: no lines and nobody who may plan them.
export function takeoffSectionHtml(detail, { canEdit, canDispense }) {
  if (!takeoffVisible(detail, canEdit)) return "";
  const rows = lines(detail).map((line) => lineHtml(detail, line, { canEdit, canDispense })).join("");
  const add = canEdit
    ? `<div class="wo-takeoff-add" id="wo-add-takeoff">
         <div class="wo-add-item-row">
           <input type="text" class="ms-item-search" placeholder="+ Takeoff item: search by name or barcode">
           <input type="number" class="wo-item-qty" placeholder="Qty" min="0" step="any">
           <button type="button" data-action="add-takeoff">Add</button>
         </div>
         <div class="ms-item-results scan-chooser" hidden></div>
       </div>`
    : "";
  return `<details class="wo-section-card wo-takeoff-section" id="wo-sec-takeoff">
            <summary class="wo-section-summary">Takeoff</summary>
            <div class="wo-section-content">
              <p class="hint">Planned, not yet used · no stock moved</p>
              <div class="wo-takeoff-lines">${rows || `<p class="hint">Nothing planned yet.</p>`}</div>
              ${add}
            </div>
          </details>`;
}

const positive = (value) => {
  const n = parseFloat(value);
  return Number.isFinite(n) && n > 0 ? n : null;
};

// `ctx`: { cardEl, workOrderId, msg, refresh(), reportAdded(addedLine, text) }.
// Resolves true when the action was one of this section's. Errors propagate to
// the card's shared inline handler (a stale-line 409 shows the server's text).
export async function handleTakeoffAction(action, btn, ctx) {
  const { cardEl, workOrderId, msg, refresh } = ctx;
  const row = btn.closest(".wo-takeoff-line");
  const needQty = () => setMessage(msg, "Enter a quantity greater than zero.", "error");
  const said = (text) => setMessage(cardEl.querySelector(".wo-message"), text, "success");

  if (action === "add-takeoff") {
    const container = btn.closest(".wo-takeoff-add");
    const quantity = positive(container.querySelector(".wo-item-qty").value);
    if (!container.dataset.itemId) return setMessage(msg, "Search and pick an item first.", "error"), true;
    if (!quantity) return needQty(), true;
    await apiAddTakeoffLine(workOrderId, { itemId: container.dataset.itemId, quantity });
    await refresh();
    said("Added to takeoff.");
  } else if (action === "edit-takeoff") {
    const quantity = positive(row.querySelector(".wo-tk-qty").value);
    if (!quantity) return needQty(), true;
    await apiUpdateTakeoffLine(workOrderId, row.dataset.takeoffId, quantity);
    await refresh();
  } else if (action === "remove-takeoff") {
    if (!(await confirmDialog("Remove this takeoff line?"))) return true;
    await apiDeleteTakeoffLine(workOrderId, row.dataset.takeoffId);
    await refresh();
  } else if (action === "open-dispense-takeoff") {
    // Held open through live patches (data-live-keep) until it is closed again.
    const form = row.querySelector(".wo-takeoff-dispense");
    form.hidden = !form.hidden;
    form.toggleAttribute("data-live-keep", !form.hidden);
    if (!form.hidden) form.querySelector(".wo-tk-dispense-qty").focus();
  } else if (action === "dispense-takeoff") {
    const quantity = positive(row.querySelector(".wo-tk-dispense-qty").value);
    if (!quantity) return needQty(), true;
    // Off while in flight so a double tap cannot move stock twice.
    btn.disabled = true;
    try {
      const added = await apiAddWorkOrderItem(workOrderId, {
        itemId: row.dataset.itemId,
        quantity,
        takeoffLineId: row.dataset.takeoffId,
      });
      await refresh();
      ctx.reportAdded(added, "Dispensed.");
    } finally {
      btn.disabled = false;
    }
  } else {
    return false;
  }
  return true;
}
