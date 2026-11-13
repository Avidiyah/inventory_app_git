// Work Orders: the `smr-*` branches of the card's click delegation.
// workOrderActions.js routes every `smr-` action but the paper check here; errors propagate to its shared catch and land in
// `.wo-message`. The markup is built in workOrderSmrLines.js.

import {
  apiSmrAddLine,
  apiSmrDeleteLine,
  apiSmrEditLine,
  apiSmrGenerateBlock,
  apiSmrMarkPasted,
  apiSetSmrPaperReviewed,
  apiSetSmrReady,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { refreshCard } from "./workOrderList.js";
import { fillEntryRow, readEntryRow } from "./workOrderSmrLines.js";

// The section an action sits in is opened again after the card re-renders.
const LABOR = ".wo-smr-section";
const INVOICE = ".wo-smr-invoice";

// Print only the block: a sheet as the body's sole visible child (print CSS).
// Also used by SMR Admin Review.
export function printSmrBlock(text) {
  const sheet = document.createElement("pre");
  sheet.className = "smr-print-sheet";
  sheet.textContent = text;
  document.body.append(sheet);
  document.body.classList.add("smr-printing");
  try {
    window.print();
  } finally {
    document.body.classList.remove("smr-printing");
    sheet.remove();
  }
}

// `msg` comes from the caller: setMessage clears the element's class, so it
// cannot be found by `.wo-message` once the delegation has reset it.
export async function handleSmrAction(action, btn, cardEl, msg) {
  const workOrderId = cardEl.dataset.id;
  const row = cardEl.querySelector(".wo-smr-add");
  const lineEl = btn.closest(".wo-smr-line");
  const lineOf = () => JSON.parse(lineEl.dataset.line);

  if (action === "smr-add-line") {
    // The one entry row adds, or saves the line Edit loaded into it.
    const payload = readEntryRow(row);
    const lineId = row.dataset.lineId;
    if (!payload.hours_each) {
      setMessage(msg, "Enter the hours each person worked.", "error");
      return;
    }
    if (!lineId && !payload.work_date) {
      setMessage(msg, "Enter the date the work was done.", "error");
      return;
    }
    if (lineId) await apiSmrEditLine(lineId, payload);
    else await apiSmrAddLine(workOrderId, { ...payload, reason_code: "as_read" });
    await refreshCard(cardEl, LABOR);
  } else if (action === "smr-edit-line") {
    fillEntryRow(row, lineOf());
    row.querySelector(".wo-smr-a-name").focus();
  } else if (action === "smr-cancel-line") {
    fillEntryRow(row, null);
  } else if (action === "smr-update-line") {
    const hoursEach = lineEl.querySelector(".wo-smr-l-hours").value.trim();
    if (!hoursEach) {
      setMessage(msg, "Enter the hours.", "error");
      return;
    }
    await apiSmrEditLine(lineOf().id, { hours_each: hoursEach });
    await refreshCard(cardEl, LABOR);
  } else if (action === "smr-delete-line") {
    // A real delete (user 2026-11-12): the row is gone, nothing keeps a copy.
    const ok = await confirmDialog(
      "Remove this labor line? It is deleted for good and cannot be brought back.",
      { confirmText: "Remove" },
    );
    if (!ok) return;
    await apiSmrDeleteLine(lineOf().id);
    await refreshCard(cardEl, LABOR);
  } else if (action === "smr-generate-block") {
    await apiSmrGenerateBlock(workOrderId, cardEl.querySelector(".wo-smr-description-text")?.value ?? null);
    await refreshCard(cardEl, INVOICE);
  } else if (action === "smr-print-block") {
    printSmrBlock(cardEl.querySelector(".wo-smr-block-text").value);
  } else if (action === "smr-mark-pasted") {
    await apiSmrMarkPasted(btn.dataset.blockId);
    await refreshCard(cardEl, INVOICE);
  } else if (action === "smr-ready" || action === "smr-not-ready") {
    // Reversible, so no confirm: Not ready clears the stamp the same way.
    await apiSetSmrReady(workOrderId, action === "smr-ready");
    await refreshCard(cardEl);
  } else if (action === "smr-paper-reviewed" || action === "smr-not-paper-reviewed") {
    await apiSetSmrPaperReviewed(workOrderId, action === "smr-paper-reviewed");
    await refreshCard(cardEl);
  }
}
