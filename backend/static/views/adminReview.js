// View: Admin/Owner final work-order review and fixed-width receipt output.
//
// Review is the last live work-order state. This page lists every Review row,
// builds the authoritative material + labor receipt from WorkOrderDetail, and
// provides the receipt-aware Review -> Closed (soft archive) workflow. Admin+
// may also archive from any status on the ordinary Work Orders page. A rejected
// Review row can be sent back to In-Progress through the status update contract.
// A work order with any blank or $0.00 price is painted red and never shows
// its receipt: selecting it opens a picker that hands the chosen item to its
// missing-price request on User Requests.

import {
  apiArchiveWorkOrder,
  apiGetWorkOrder,
  apiListWorkOrders,
  apiUpdateWorkOrder,
} from "../api.js";
import { buildAdminReviewReceipt, isUnpriced } from "../adminReviewReceipt.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { showPage } from "./nav.js";
import { focusMissingPriceRequest } from "./userRequests.js";
import { workOrderCardClass } from "./workOrders.js";

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
const unpricedOverlay = document.getElementById("admin-review-unpriced-overlay");
const unpricedTitle = document.getElementById("admin-review-unpriced-title");
const unpricedList = document.getElementById("admin-review-unpriced-list");
const unpricedCancel = document.getElementById("admin-review-unpriced-cancel");

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
  // Every queue row is a Review row, but the class still comes from the shared
  // builder so an urgent work order pulses here the way it does everywhere else.
  const unpriced = Boolean(card.has_unpriced_items);
  button.className = `${workOrderCardClass(card)} admin-review-card`;
  if (unpriced) button.classList.add("admin-review-card-unpriced");
  button.dataset.id = card.id;
  button.setAttribute(
    "aria-label",
    `Review work order ${card.number}${unpriced ? " (missing prices)" : ""}`
  );
  if (selectedDetail?.id === card.id) button.classList.add("selected");
  button.innerHTML =
    `<span class="wo-card-wo">${escapeHtml(card.number)}</span>` +
    `<span class="wo-card-status-label">${unpriced ? "Needs price" : "Review"}</span>` +
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

function unpricedItems(detail) {
  return (detail.items || []).filter((item) => isUnpriced(item.unit_price));
}

// Resolves the picked item, or null on Close / Esc / backdrop.
function pickUnpricedItem(detail, items) {
  return new Promise((resolve) => {
    const previouslyFocused = document.activeElement;
    unpricedTitle.textContent =
      `WO ${detail.number} can't be billed until these items have a price`;
    unpricedList.replaceChildren();
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "admin-review-unpriced-item";
      button.dataset.itemId = item.item_id;
      button.textContent = item.item_name;
      unpricedList.appendChild(button);
    }
    unpricedOverlay.hidden = false;
    unpricedList.querySelector("button")?.focus();

    function done(value) {
      unpricedOverlay.hidden = true;
      unpricedList.removeEventListener("click", onPick);
      unpricedCancel.removeEventListener("click", onCancel);
      unpricedOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      if (!value && typeof previouslyFocused?.focus === "function") {
        try { previouslyFocused.focus(); } catch (_err) { /* element removed */ }
      }
      resolve(value);
    }
    function onPick(event) {
      const button = event.target.closest(".admin-review-unpriced-item");
      if (!button) return;
      done(items.find((item) => item.item_id === button.dataset.itemId) || null);
    }
    function onCancel() { done(null); }
    function onBackdrop(event) { if (event.target === unpricedOverlay) done(null); }
    function onKey(event) { if (event.key === "Escape") done(null); }

    unpricedList.addEventListener("click", onPick);
    unpricedCancel.addEventListener("click", onCancel);
    unpricedOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

async function openUnpricedPicker(detail, items) {
  const item = await pickUnpricedItem(detail, items);
  if (!item) return;
  focusMissingPriceRequest({ itemId: item.item_id, itemName: item.item_name });
  showPage("user-requests");
}

function renderReceipt(detail) {
  const { text, missingPrices } = buildAdminReviewReceipt(detail);
  const unpriced = unpricedItems(detail);
  selectedDetail = detail;
  receiptTitle.textContent = `WO ${detail.number} Receipt`;
  // An unpriced receipt is not billable, so it is never offered for copying.
  receiptOutput.hidden = unpriced.length > 0;
  receiptOutput.value = unpriced.length ? "" : text;
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
    void openUnpricedPicker(detail, unpriced);
    return;
  }
  setMessage(receiptMessage, "Receipt ready — select all and copy.", "success");

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
    closeBtn.disabled = unpricedItems(selectedDetail).length > 0;
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
