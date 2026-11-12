// View: SMR Admin Review -- Admin Review (adminReview.js) for SMR27 orders in
// the final "Ready to invoice" stage. Lists ready, unarchived SMR tiles; a
// selected order shows its full correction block for print and paste, then
// Not ready (back to the SMR page) or Archive (Close). The block stays on
// screen after an action, like the Admin Review receipt.

import {
  apiArchiveWorkOrder,
  apiGetWorkOrder,
  apiListSmrTiles,
  apiSetSmrReady,
  apiSmrGenerateBlock,
  apiSmrMarkPasted,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError, netfacilitiesWorkOrderUrl } from "../format.js";
import { printSmrBlock } from "./workOrderSmrActions.js";
import { blockStatusText } from "./workOrderSmrLines.js";

const $ = (id) => document.getElementById(`smr-admin-review-${id}`);
const listEl = $("list");
const listMessage = $("list-message");
const blockSection = $("block-section");
const blockTitle = $("block-title");
const blockStatus = $("block-status");
const blockOutput = $("block-output");
const blockMessage = $("block-message");
const regenerateBtn = $("regenerate-btn");
const printBtn = $("print-btn");
const pastedBtn = $("pasted-btn");
const notReadyBtn = $("not-ready-btn");
const archiveBtn = $("archive-btn");

let selectedDetail = null;
let selectionRequestId = 0;
let queueRequestId = 0;

function statusLabel(tile) {
  const lines = tile.lines || {};
  if (!lines.block_version) return "No block";
  if (lines.block_stale) return "Block stale";
  if (!lines.block_pasted_at) return "Not pasted";
  return "Ready to invoice";
}

function locationText(tile) {
  const parts = [tile.location, tile.building_number, tile.unit_number]
    .map((part) => String(part || "").trim())
    .filter(Boolean);
  return parts.length ? parts.join(" · ") : "No location";
}

function buildCard(tile) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "wo-card admin-review-card";
  button.dataset.id = tile.id;
  button.setAttribute("aria-label", `Review SMR order ${tile.number}`);
  if (selectedDetail?.id === tile.id) button.classList.add("selected");
  button.innerHTML =
    `<span class="wo-card-wo">${escapeHtml(tile.number)}</span>` +
    `<span class="wo-card-status-label">${statusLabel(tile)}</span>` +
    `<span class="wo-card-meta">${escapeHtml(locationText(tile))}</span>` +
    `<span class="wo-card-assignee">${escapeHtml(tile.vendor_assignee || "No vendor")}</span>`;
  return button;
}

function renderQueue(tiles) {
  listEl.replaceChildren(...tiles.map(buildCard));
  if (tiles.length === 0) {
    setMessage(listMessage, "No SMR orders are ready to invoice.", "success");
  } else {
    setMessage(
      listMessage,
      `${tiles.length} SMR order${tiles.length === 1 ? "" : "s"} ready to invoice.`,
      ""
    );
  }
}

function setActionsDisabled(disabled) {
  for (const btn of [regenerateBtn, printBtn, pastedBtn, notReadyBtn, archiveBtn]) {
    btn.disabled = disabled;
  }
}

function renderBlock(detail) {
  selectedDetail = detail;
  const block = detail.smr_block;
  const usable = Boolean(block?.text) && !block.stale;
  blockTitle.textContent = `WO ${detail.number} Correction Block`;
  blockStatus.textContent = blockStatusText(block);
  blockOutput.hidden = !block?.text;
  blockOutput.value = block?.text || "";
  blockOutput.rows = Math.max(block?.text ? block.text.split("\n").length : 0, 2);
  blockSection.hidden = false;
  setActionsDisabled(false);
  regenerateBtn.hidden = usable;
  printBtn.hidden = !block?.text;
  pastedBtn.hidden = !block || Boolean(block.pasted_at);
  listEl.querySelectorAll(".admin-review-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.id === detail.id);
  });
  if (!block) {
    setMessage(blockMessage, "This order has no correction block yet. Regenerate it before invoicing.", "error");
  } else if (block.stale) {
    setMessage(blockMessage, "The labor lines changed since this block was made. Regenerate it before invoicing.", "error");
  } else {
    setMessage(blockMessage, "Block ready — print it or select all and copy.", "success");
  }
}

async function selectWorkOrder(workOrderId) {
  const requestId = ++selectionRequestId;
  setMessage(listMessage, "Loading correction block…", "");
  try {
    const detail = await apiGetWorkOrder(workOrderId);
    if (requestId !== selectionRequestId) return;
    renderBlock(detail);
    setMessage(listMessage, "", "");
  } catch (err) {
    if (requestId !== selectionRequestId) return;
    setMessage(listMessage, friendlyError(err, "Could not load that work order."), "error");
  }
}

export async function loadSmrAdminReview() {
  const requestId = ++queueRequestId;
  setMessage(listMessage, "Loading SMR orders…", "");
  try {
    const payload = await apiListSmrTiles();
    if (requestId !== queueRequestId) return;
    renderQueue((payload?.tiles || []).filter((t) => t.stage === "ready" && !t.archived_at));
  } catch (err) {
    if (requestId !== queueRequestId) return;
    listEl.replaceChildren();
    setMessage(listMessage, friendlyError(err, "Could not load SMR Admin Review."), "error");
  }
}

// Runs one action on the selected order: buttons off while it runs, the
// queue reloaded after, the block left on screen. Failure turns them back on.
async function runAction(action, done, failure) {
  const detail = selectedDetail;
  setActionsDisabled(true);
  try {
    await action(detail);
    await loadSmrAdminReview();
    setMessage(blockMessage, done(detail), "success");
  } catch (err) {
    setActionsDisabled(false);
    setMessage(blockMessage, friendlyError(err, failure), "error");
  }
}

listEl.addEventListener("click", (event) => {
  const card = event.target.closest(".admin-review-card");
  if (card) selectWorkOrder(card.dataset.id);
});

$("netfacilities-btn").addEventListener("click", () => {
  if (!selectedDetail) return;
  window.open(netfacilitiesWorkOrderUrl(selectedDetail.number), "_blank", "noopener,noreferrer");
});

printBtn.addEventListener("click", () => {
  if (selectedDetail?.smr_block?.text) printSmrBlock(selectedDetail.smr_block.text);
});

// Regenerate and Mark pasted keep the order in the queue, so the order is
// selected again to show the new block and status.
async function changeBlock(action, failure) {
  const detail = selectedDetail;
  setActionsDisabled(true);
  try {
    await action(detail);
    await loadSmrAdminReview();
    await selectWorkOrder(detail.id);
  } catch (err) {
    setActionsDisabled(false);
    setMessage(blockMessage, friendlyError(err, failure), "error");
  }
}

regenerateBtn.addEventListener("click", () => {
  if (!selectedDetail) return;
  changeBlock(
    (d) => apiSmrGenerateBlock(d.id, d.smr_description ?? null),
    "Could not regenerate the block."
  );
});

pastedBtn.addEventListener("click", () => {
  if (!selectedDetail?.smr_block) return;
  changeBlock((d) => apiSmrMarkPasted(d.smr_block.id), "Could not mark that block pasted.");
});

notReadyBtn.addEventListener("click", async () => {
  if (!selectedDetail) return;
  if (!(await confirmDialog(
    `Send WO ${selectedDetail.number} back? It leaves Ready to invoice.`
  ))) return;
  await runAction(
    (d) => apiSetSmrReady(d.id, false),
    (d) => `WO ${d.number} sent back. The block remains available for reference.`,
    "Could not send that order back."
  );
});

archiveBtn.addEventListener("click", async () => {
  if (!selectedDetail) return;
  if (!(await confirmDialog(
    `Archive WO ${selectedDetail.number}? It will leave the live work-order views.`
  ))) return;
  await runAction(
    (d) => apiArchiveWorkOrder(d.id),
    (d) => `WO ${d.number} archived. The block remains available for copying.`,
    "Could not archive that order."
  );
});
