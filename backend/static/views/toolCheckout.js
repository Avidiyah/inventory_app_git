// View: tool checkout editor on the Tools page.
//
// Layer: views. Sibling of `correction.js` -- same open/close/save shape.
// Opens an inline panel when Admin+ picks "Check Out" on a tool row,
// captures a quantity, a required assigned-to user, and an optional
// work-order number, and posts to `POST /tools/{id}/checkout`.
//
// Public surface:
// - `openToolCheckout(tool, users)` populates and reveals the panel.
//   `users` is the full user list (Admin+ always has it cached via the
//   boot-time `loadUsers()` call, since Admin can always reach Users).
// - `closeToolCheckout()` hides it (called on cancel, on success, and by
//   tools.js on a feature switch).
// - `setOnSaved(fn)` lets tools.js register a callback so the table
//   refreshes after a successful checkout.

import { apiCheckoutTool } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const checkoutSection = document.getElementById("tool-checkout-section");
const checkoutSelected = document.getElementById("tool-checkout-selected");
const checkoutQuantity = document.getElementById("tool-checkout-quantity");
const checkoutUserSelect = document.getElementById("tool-checkout-user");
const checkoutWorkOrder = document.getElementById("tool-checkout-work-order");
const checkoutSaveBtn = document.getElementById("tool-checkout-save-btn");
const checkoutCancelBtn = document.getElementById("tool-checkout-cancel-btn");
const checkoutMessage = document.getElementById("tool-checkout-message");

let checkingOutToolId = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

function populateUserSelect(users) {
  checkoutUserSelect.innerHTML = '<option value="" disabled selected>Select a user</option>';
  users.forEach(user => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.username;
    checkoutUserSelect.appendChild(option);
  });
}

export function openToolCheckout(tool, users) {
  checkingOutToolId = tool.id;
  checkoutSelected.textContent = `Checking out: ${tool.name} (${tool.barcode}) — ${tool.quantity} on hand`;
  populateUserSelect(users);
  checkoutQuantity.value = "1";
  checkoutWorkOrder.value = "";
  setMessage(checkoutMessage, "", "");
  checkoutSection.hidden = false;
  checkoutSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function closeToolCheckout() {
  checkingOutToolId = null;
  checkoutSection.hidden = true;
  setMessage(checkoutMessage, "", "");
}

export function getCheckingOutToolId() {
  return checkingOutToolId;
}

checkoutCancelBtn.addEventListener("click", closeToolCheckout);

checkoutSaveBtn.addEventListener("click", async () => {
  if (!checkingOutToolId) {
    setMessage(checkoutMessage, "No tool selected.", "error");
    return;
  }
  setMessage(checkoutMessage, "", "");

  const quantity = Number(checkoutQuantity.value);
  if (!checkoutQuantity.value || !Number.isFinite(quantity) || quantity <= 0) {
    setMessage(checkoutMessage, "Enter a quantity greater than zero.", "error");
    return;
  }
  const assignedToId = checkoutUserSelect.value;
  if (!assignedToId) {
    setMessage(checkoutMessage, "A tool must be assigned to a user before it can be checked out.", "error");
    return;
  }
  const workOrderNumber = checkoutWorkOrder.value.trim() || null;

  try {
    await apiCheckoutTool(checkingOutToolId, { quantity, assignedToId, workOrderNumber });
    setMessage(checkoutMessage, "Checked out.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeToolCheckout, 1000);
  } catch (err) {
    setMessage(checkoutMessage, friendlyError(err, "Could not check out the tool. Try again."), "error");
  }
});
