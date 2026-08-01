// View: user-fixed tool checkout editor on the Tools > Custody feature.
//
// The host chooses the user first, then resolves a tool by search or scan
// and calls openToolCheckout(tool, user). This module owns only the final
// quantity/work-order confirmation and the existing checkout API call.

import { apiCheckoutTool } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const checkoutSection = document.getElementById("tool-checkout-section");
const checkoutSelected = document.getElementById("tool-checkout-selected");
const checkoutUserSummary = document.getElementById("tool-checkout-user-summary");
const checkoutQuantity = document.getElementById("tool-checkout-quantity");
const checkoutWorkOrder = document.getElementById("tool-checkout-work-order");
const checkoutSaveBtn = document.getElementById("tool-checkout-save-btn");
const checkoutCancelBtn = document.getElementById("tool-checkout-cancel-btn");
const checkoutMessage = document.getElementById("tool-checkout-message");

let checkingOutTool = null;
let checkoutUser = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openToolCheckout(tool, user) {
  checkingOutTool = tool;
  checkoutUser = user;
  checkoutSelected.textContent = tool.name + " (" + tool.barcode + ") — " + tool.quantity + " on hand";
  checkoutUserSummary.textContent = "Checking out to " + user.username;
  checkoutQuantity.value = "1";
  checkoutQuantity.max = String(tool.quantity);
  checkoutWorkOrder.value = "";
  setMessage(checkoutMessage, "", "");
  checkoutSection.hidden = false;
  checkoutSection.scrollIntoView({ behavior: "smooth", block: "start" });
  checkoutQuantity.focus();
  checkoutQuantity.select();
}

export function closeToolCheckout() {
  checkingOutTool = null;
  checkoutUser = null;
  checkoutSection.hidden = true;
  checkoutQuantity.value = "1";
  checkoutQuantity.removeAttribute("max");
  checkoutWorkOrder.value = "";
  setMessage(checkoutMessage, "", "");
}

checkoutCancelBtn.addEventListener("click", closeToolCheckout);

checkoutSaveBtn.addEventListener("click", async () => {
  if (!checkingOutTool || !checkoutUser) {
    setMessage(checkoutMessage, "Select a user and tool first.", "error");
    return;
  }
  setMessage(checkoutMessage, "", "");

  const quantity = Number(checkoutQuantity.value);
  const onHand = Number(checkingOutTool.quantity);
  if (!checkoutQuantity.value || !Number.isFinite(quantity) || quantity <= 0) {
    setMessage(checkoutMessage, "Enter a quantity greater than zero.", "error");
    return;
  }
  if (Number.isFinite(onHand) && quantity > onHand) {
    setMessage(checkoutMessage, "Only " + checkingOutTool.quantity + " on hand.", "error");
    return;
  }

  const workOrderNumber = checkoutWorkOrder.value.trim() || null;

  try {
    await apiCheckoutTool(checkingOutTool.id, {
      quantity,
      assignedToId: checkoutUser.id,
      workOrderNumber,
    });
    setMessage(
      checkoutMessage,
      "Checked out " + checkingOutTool.name + " to " + checkoutUser.username + ".",
      "success",
    );
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeToolCheckout, 1000);
  } catch (err) {
    setMessage(checkoutMessage, friendlyError(err, "Could not check out the tool. Try again."), "error");
  }
});
