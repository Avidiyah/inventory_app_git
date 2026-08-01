// View: user-fixed tool check-in editor on the Tools > Custody feature.
//
// The host derives a selected user's current holding and calls
// openToolReturn(tool, user, custodyEntry). This module keeps the existing
// return endpoint and outstanding-balance semantics while removing the old
// second user-selection step.

import { apiReturnTool } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const returnSection = document.getElementById("tool-return-section");
const returnSelected = document.getElementById("tool-return-selected");
const returnUserSummary = document.getElementById("tool-return-user-summary");
const returnQuantity = document.getElementById("tool-return-quantity");
const returnWorkOrder = document.getElementById("tool-return-work-order");
const returnSaveBtn = document.getElementById("tool-return-save-btn");
const returnCancelBtn = document.getElementById("tool-return-cancel-btn");
const returnMessage = document.getElementById("tool-return-message");

let returningTool = null;
let returnUser = null;
let returnCustody = null;
let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function openToolReturn(tool, user, custodyEntry) {
  returningTool = tool;
  returnUser = user;
  returnCustody = custodyEntry;
  returnSelected.textContent = tool.name + " (" + tool.barcode + ")";
  returnUserSummary.textContent = user.username + " has " + custodyEntry.quantity + " checked out";
  returnQuantity.value = String(custodyEntry.quantity);
  returnQuantity.max = String(custodyEntry.quantity);
  returnWorkOrder.value = "";
  setMessage(returnMessage, "", "");
  returnSection.hidden = false;
  returnSection.scrollIntoView({ behavior: "smooth", block: "start" });
  returnQuantity.focus();
  returnQuantity.select();
}

export function closeToolReturn() {
  returningTool = null;
  returnUser = null;
  returnCustody = null;
  returnSection.hidden = true;
  returnQuantity.value = "1";
  returnQuantity.removeAttribute("max");
  returnWorkOrder.value = "";
  setMessage(returnMessage, "", "");
}

returnCancelBtn.addEventListener("click", closeToolReturn);

returnSaveBtn.addEventListener("click", async () => {
  if (!returningTool || !returnUser || !returnCustody) {
    setMessage(returnMessage, "Select a checked-out tool first.", "error");
    return;
  }
  setMessage(returnMessage, "", "");

  const quantity = Number(returnQuantity.value);
  const outstanding = Number(returnCustody.quantity);
  if (!returnQuantity.value || !Number.isFinite(quantity) || quantity <= 0) {
    setMessage(returnMessage, "Enter a quantity greater than zero.", "error");
    return;
  }
  if (Number.isFinite(outstanding) && quantity > outstanding) {
    setMessage(returnMessage, "Only " + returnCustody.quantity + " checked out.", "error");
    return;
  }

  const workOrderNumber = returnWorkOrder.value.trim() || null;

  try {
    await apiReturnTool(returningTool.id, {
      quantity,
      assignedToId: returnUser.id,
      workOrderNumber,
    });
    setMessage(
      returnMessage,
      "Checked in " + returningTool.name + " for " + returnUser.username + ".",
      "success",
    );
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeToolReturn, 1000);
  } catch (err) {
    setMessage(returnMessage, friendlyError(err, "Could not record the check-in. Try again."), "error");
  }
});
