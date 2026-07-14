// View: tool return editor on the Tools page.
//
// Layer: views. Sibling of `toolCheckout.js` / `correction.js`. Opens an
// inline panel when any role picks "Return" on a tool row they currently
// hold, captures a quantity and the user whose custody is being reduced,
// and posts to `POST /tools/{id}/return`.
//
// Unlike checkout (Admin+, which always has the full user list cached via
// the boot-time `loadUsers()` call), a Technician cannot call `GET
// /users/` (Supervisor+ gated) -- so `openToolReturn` accepts an already-
// resolved `users` list that tools.js decides: Supervisor+ pass the full
// cached list (any holder returnable), a Technician passes an empty array
// and this module falls back to a single option built from `custody` (the
// caller's own outstanding balance on this tool -- tools.js only offers
// Return when that's non-null).
//
// Public surface:
// - `openToolReturn(tool, users, custody)` populates and reveals the panel.
// - `closeToolReturn()` hides it.
// - `getReturningToolId()` lets tools.js close this panel if the tool it's
//   open for gets archived from elsewhere.
// - `setOnSaved(fn)` lets tools.js register a callback so the table
//   refreshes after a successful return.

import { apiReturnTool } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const returnSection = document.getElementById("tool-return-section");
const returnSelected = document.getElementById("tool-return-selected");
const returnQuantity = document.getElementById("tool-return-quantity");
const returnUserSelect = document.getElementById("tool-return-user");
const returnWorkOrder = document.getElementById("tool-return-work-order");
const returnSaveBtn = document.getElementById("tool-return-save-btn");
const returnCancelBtn = document.getElementById("tool-return-cancel-btn");
const returnMessage = document.getElementById("tool-return-message");

let returningToolId = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

function populateUserSelect(users, custody) {
  returnUserSelect.innerHTML = '<option value="" disabled selected>Select a user</option>';
  const list = users.length > 0 ? users : (custody ? [{ id: custody.user_id, username: custody.username }] : []);
  list.forEach(user => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.username;
    returnUserSelect.appendChild(option);
  });
  if (custody && list.some(u => u.id === custody.user_id)) {
    returnUserSelect.value = custody.user_id;
  }
}

export function openToolReturn(tool, users, custody) {
  returningToolId = tool.id;
  returnSelected.textContent = `Returning: ${tool.name} (${tool.barcode}) — ${tool.quantity} on hand`;
  populateUserSelect(users, custody);
  returnQuantity.value = custody ? String(custody.quantity) : "1";
  returnWorkOrder.value = "";
  setMessage(returnMessage, "", "");
  returnSection.hidden = false;
  returnSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function closeToolReturn() {
  returningToolId = null;
  returnSection.hidden = true;
  setMessage(returnMessage, "", "");
}

export function getReturningToolId() {
  return returningToolId;
}

returnCancelBtn.addEventListener("click", closeToolReturn);

returnSaveBtn.addEventListener("click", async () => {
  if (!returningToolId) {
    setMessage(returnMessage, "No tool selected.", "error");
    return;
  }
  setMessage(returnMessage, "", "");

  const quantity = Number(returnQuantity.value);
  if (!returnQuantity.value || !Number.isFinite(quantity) || quantity <= 0) {
    setMessage(returnMessage, "Enter a quantity greater than zero.", "error");
    return;
  }
  const assignedToId = returnUserSelect.value;
  if (!assignedToId) {
    setMessage(returnMessage, "Select who is returning the tool.", "error");
    return;
  }
  const workOrderNumber = returnWorkOrder.value.trim() || null;

  try {
    await apiReturnTool(returningToolId, { quantity, assignedToId, workOrderNumber });
    setMessage(returnMessage, "Returned.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeToolReturn, 1000);
  } catch (err) {
    setMessage(returnMessage, friendlyError(err, "Could not record the return. Try again."), "error");
  }
});
