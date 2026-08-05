// View: Admin/Owner operational User Requests queue.

import { apiListUserRequests, apiUpdateItem, apiUpdateUserRequest } from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";

const statusEl = document.getElementById("user-requests-status");
const refreshBtn = document.getElementById("user-requests-refresh");
const listEl = document.getElementById("user-requests-list");
const messageEl = document.getElementById("user-requests-message");

function formatDate(value) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function requestTypeLabel(type) {
  if (type === "inventory_recount") return "Stock recount";
  if (type === "missing_item_price") return "Missing price / link";
  return type.replaceAll("_", " ");
}

function detailLine(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return `<span><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
}

function buildRequestCard(request) {
  const details = request.details || {};
  const card = document.createElement("article");
  card.className = `user-request-card user-request-${request.status}`;
  card.dataset.id = request.id;
  card.dataset.itemId = request.item_id || "";

  const itemLabel = request.item_name || "Unknown item";
  const isMissingPrice = request.request_type === "missing_item_price";
  let action;
  if (isMissingPrice && request.status === "open") {
    action =
      '<label class="user-request-price-label">Price' +
        '<input type="number" class="user-request-price-input" min="0.01" step="0.01" placeholder="0.00" inputmode="decimal">' +
      '</label>' +
      '<label class="user-request-link-label">Product link' +
        '<input type="url" class="user-request-link-input" placeholder="https://..." inputmode="url">' +
      '</label>' +
      '<button type="button" class="user-request-price-save">Save price &amp; link</button>';
  } else if (isMissingPrice) {
    action = '<span class="hint">Resolved automatically when the item price and product link were added.</span>';
  } else {
    action = request.status === "open"
      ? '<button type="button" class="user-request-action" data-status="resolved">Mark resolved</button>'
      : '<button type="button" class="user-request-action secondary-btn" data-status="open">Reopen</button>';
  }
  const affectedWorkOrders = Array.isArray(details.work_order_numbers)
    ? details.work_order_numbers.join(", ")
    : request.work_order_number;
  const resolution = request.status === "resolved"
    ? `<div class="user-request-resolution">${detailLine("Resolved by", request.resolved_by_name || "Unknown")}${detailLine("Resolved", formatDate(request.resolved_at))}${detailLine("Note", request.resolution_note)}</div>`
    : "";

  card.innerHTML =
    `<div class="user-request-header">` +
      `<div><span class="user-request-type">${escapeHtml(requestTypeLabel(request.request_type))}</span>` +
      `<h3>${escapeHtml(itemLabel)}</h3></div>` +
      `<span class="user-request-status">${escapeHtml(request.status)}</span>` +
    `</div>` +
    `<p class="user-request-alert">${escapeHtml(request.message)}</p>` +
    `<div class="user-request-details">` +
      detailLine("Barcode", request.item_barcode) +
      detailLine(isMissingPrice ? "Work orders" : "Work order", affectedWorkOrders) +
      detailLine("Recorded before", details.recorded_quantity_before) +
      detailLine("Dispensed", details.dispensed_quantity) +
      detailLine("Shortage", details.shortage_quantity) +
      detailLine("Requested by", request.created_by_name || "Unknown") +
      detailLine("Created", formatDate(request.created_at)) +
    `</div>` +
    resolution +
    `<div class="user-request-actions">${action}</div>`;
  if (isMissingPrice && request.status === "open") {
    const priceInput = card.querySelector(".user-request-price-input");
    const linkInput = card.querySelector(".user-request-link-input");
    if (request.item_price !== null && request.item_price !== undefined) {
      priceInput.value = request.item_price;
    }
    if (request.item_product_link) linkInput.value = request.item_product_link;
  }
  return card;
}

function renderRequests(requests) {
  listEl.replaceChildren();
  for (const request of requests) listEl.appendChild(buildRequestCard(request));
  const status = statusEl.value;
  if (!requests.length) {
    setMessage(messageEl, `No ${status} user requests.`, "success");
  } else {
    setMessage(
      messageEl,
      `${requests.length} ${status} request${requests.length === 1 ? "" : "s"}.`,
      ""
    );
  }
}

export async function loadUserRequests() {
  if (!listEl) return;
  const status = statusEl.value || "open";
  setMessage(messageEl, `Loading ${status} requests...`, "");
  try {
    renderRequests(await apiListUserRequests(status));
  } catch (err) {
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load User Requests."), "error");
  }
}

if (statusEl) statusEl.addEventListener("change", loadUserRequests);
if (refreshBtn) refreshBtn.addEventListener("click", loadUserRequests);

if (listEl) {
  listEl.addEventListener("click", async (event) => {
    const priceButton = event.target.closest(".user-request-price-save");
    if (priceButton) {
      const card = priceButton.closest(".user-request-card");
      const input = card.querySelector(".user-request-price-input");
      const linkInput = card.querySelector(".user-request-link-input");
      const rawPrice = input.value.trim();
      const price = Number(rawPrice);
      if (!rawPrice || !Number.isFinite(price) || price <= 0) {
        setMessage(messageEl, "Enter an item price greater than $0.00.", "error");
        input.focus();
        return;
      }
      const productLink = linkInput.value.trim();
      if (!productLink || !linkInput.checkValidity()) {
        setMessage(messageEl, "Enter a valid product link.", "error");
        linkInput.focus();
        return;
      }

      priceButton.disabled = true;
      try {
        await apiUpdateItem(card.dataset.itemId, {
          price,
          product_link: productLink,
        });
        await loadUserRequests();
      } catch (err) {
        priceButton.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not save that item price."), "error");
      }
      return;
    }

    const button = event.target.closest(".user-request-action");
    if (!button) return;
    const card = button.closest(".user-request-card");
    const targetStatus = button.dataset.status;
    const verb = targetStatus === "resolved" ? "resolve" : "reopen";
    if (!(await confirmDialog(`${verb[0].toUpperCase()}${verb.slice(1)} this user request?`))) return;

    button.disabled = true;
    try {
      await apiUpdateUserRequest(card.dataset.id, { status: targetStatus });
      await loadUserRequests();
    } catch (err) {
      button.disabled = false;
      setMessage(messageEl, friendlyError(err, `Could not ${verb} that request.`), "error");
    }
  });
}
