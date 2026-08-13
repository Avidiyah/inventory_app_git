// View: Admin/Owner final work-order review and fixed-width receipt output.
//
// Review is the last live work-order state. This page lists every Review row,
// builds the authoritative material + labor receipt from WorkOrderDetail, and
// provides the receipt-aware Review -> Closed (soft archive) workflow. Admin+
// may also archive from any status on the ordinary Work Orders page. A rejected
// Review row can be sent back to In-Progress through the status update contract.

import {
  apiArchiveWorkOrder,
  apiGetWorkOrder,
  apiListWorkOrders,
  apiUpdateWorkOrder,
} from "../api.js";
import { buildAdminReviewReceipt } from "../adminReviewReceipt.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";

const REVIEW_QUEUE_CHANGED_EVENT = "work_order.review_queue.changed";
const ADMIN_REVIEW_PAGE = "admin-review";

const listEl = document.getElementById("admin-review-list");
const listMessage = document.getElementById("admin-review-list-message");
const receiptSection = document.getElementById("admin-review-receipt-section");
const receiptTitle = document.getElementById("admin-review-receipt-title");
const receiptOutput = document.getElementById("admin-review-receipt-output");
const receiptMessage = document.getElementById("admin-review-receipt-message");
const reopenBtn = document.getElementById("admin-review-reopen-btn");
const closeBtn = document.getElementById("admin-review-close-btn");

let selectedDetail = null;
let selectionRequestId = 0;
let queueRequestId = 0;
let committedQueueRequestId = 0;

function assignedNames(card) {
  const names = Array.isArray(card.assigned_to_names)
    ? card.assigned_to_names.filter(Boolean)
    : [];
  return names.length ? names.join(", ") : "Unassigned";
}

function locationText(card) {
  const parts = [card.location, card.community, card.building_number, card.unit_number]
    .map((part) => String(part || "").trim())
    .filter(Boolean);
  return parts.length ? parts.join(" · ") : "No location";
}

function buildCard(card) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "wo-card wo-card-status-review admin-review-card";
  button.dataset.id = card.id;
  button.setAttribute("aria-label", `Review work order ${card.number}`);
  if (selectedDetail?.id === card.id) button.classList.add("selected");
  button.innerHTML =
    `<span class="wo-card-wo">${escapeHtml(card.number)}</span>` +
    `<span class="wo-card-status-label">Review</span>` +
    `<span class="wo-card-meta">${escapeHtml(locationText(card))}</span>` +
    `<span class="wo-card-assignee">${escapeHtml(assignedNames(card))}</span>`;
  return button;
}

function renderQueue(cards) {
  listEl.replaceChildren();
  for (const card of cards) listEl.appendChild(buildCard(card));
  if (cards.length === 0) {
    setMessage(listMessage, "No work orders are waiting for Admin Review.", "success");
  } else {
    setMessage(
      listMessage,
      `${cards.length} work order${cards.length === 1 ? "" : "s"} waiting for review.`,
      ""
    );
  }
}

function renderReceipt(detail) {
  const { text, missingPrices } = buildAdminReviewReceipt(detail);
  selectedDetail = detail;
  receiptTitle.textContent = `WO ${detail.number} Receipt`;
  receiptOutput.value = text;
  receiptSection.hidden = false;
  reopenBtn.disabled = false;
  closeBtn.disabled = missingPrices.length > 0;
  listEl.querySelectorAll(".admin-review-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.id === detail.id);
  });

  if (missingPrices.length) {
    setMessage(
      receiptMessage,
      `Cannot close until a price is added for: ${missingPrices.join(", ")}.`,
      "error"
    );
  } else {
    setMessage(receiptMessage, "Receipt ready — select all and copy.", "success");
  }

  receiptOutput.focus();
  receiptOutput.select();
  receiptOutput.scrollLeft = 0;
  receiptOutput.scrollTop = 0;
}

async function selectWorkOrder(workOrderId) {
  const requestId = ++selectionRequestId;
  setMessage(listMessage, "Building receipt…", "");
  try {
    const detail = await apiGetWorkOrder(workOrderId);
    if (requestId !== selectionRequestId) return;
    renderReceipt(detail);
    setMessage(listMessage, "", "");
  } catch (err) {
    if (requestId !== selectionRequestId) return;
    setMessage(listMessage, friendlyError(err, "Could not load that work order."), "error");
  }
}

export async function loadAdminReview({ background = false } = {}) {
  const requestId = ++queueRequestId;
  if (!background) {
    setMessage(listMessage, "Loading Review work orders…", "");
  }
  try {
    const cards = await apiListWorkOrders({ status: "review" });
    // A writer's own invalidation can overlap the explicit post-action load.
    // Commit only responses at least as new as the last result/error rendered,
    // so a slower old request cannot repaint stale queue data.
    if (requestId < committedQueueRequestId) return;
    committedQueueRequestId = requestId;
    renderQueue(cards || []);
  } catch (err) {
    // Automatic refresh is best-effort: keep a usable queue rather than turn a
    // socket-driven failure into visible UI. Foreground loads retain today's
    // error behavior, unless a newer result has already won the render race.
    if (background || requestId < committedQueueRequestId) return;
    committedQueueRequestId = requestId;
    listEl.replaceChildren();
    setMessage(listMessage, friendlyError(err, "Could not load Admin Review."), "error");
  }
}

listEl.addEventListener("click", (event) => {
  const card = event.target.closest(".admin-review-card");
  if (!card) return;
  selectWorkOrder(card.dataset.id);
});

reopenBtn.addEventListener("click", async () => {
  if (!selectedDetail) return;
  if (!(await confirmDialog(
    `Return WO ${selectedDetail.number} to In-Progress for corrections?`
  ))) return;

  reopenBtn.disabled = true;
  closeBtn.disabled = true;
  try {
    await apiUpdateWorkOrder(selectedDetail.id, { status: "in_progress" });
    await loadAdminReview();
    setMessage(
      receiptMessage,
      `WO ${selectedDetail.number} returned to In-Progress. The receipt remains available for reference.`,
      "success"
    );
  } catch (err) {
    reopenBtn.disabled = false;
    closeBtn.disabled = (selectedDetail.items || []).some(
      (item) => item.unit_price === null || item.unit_price === undefined
    );
    setMessage(receiptMessage, friendlyError(err, "Could not return that work order."), "error");
  }
});

closeBtn.addEventListener("click", async () => {
  if (!selectedDetail || closeBtn.disabled) return;
  if (!(await confirmDialog(
    `Close WO ${selectedDetail.number}? It will leave the live work-order views.`
  ))) return;

  reopenBtn.disabled = true;
  closeBtn.disabled = true;
  try {
    await apiArchiveWorkOrder(selectedDetail.id);
    await loadAdminReview();
    setMessage(
      receiptMessage,
      `WO ${selectedDetail.number} closed. The receipt remains available for copying.`,
      "success"
    );
  } catch (err) {
    reopenBtn.disabled = false;
    closeBtn.disabled = false;
    setMessage(receiptMessage, friendlyError(err, "Could not close that work order."), "error");
  }
});

// Both a matching invalidation and a recovered connection mean the queue may
// be stale. Admin Review is explicitly UX-6-safe to refresh: rebuilding its
// cards preserves selectedDetail and never touches the open receipt. Inactive
// pages need no dirty flag because nav.js already loads this queue on entry.
subscribe(REVIEW_QUEUE_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== ADMIN_REVIEW_PAGE) return;
  return loadAdminReview({ background: true });
});
