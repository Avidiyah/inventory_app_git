// View: the work-order card's Request section and its stocked Materials lines.
//
// Layer: views. Owns everything Material-Request-shaped inside a work-order
// card so `workOrders.js` (already 2,800 lines) gains only a mount call and
// two placeholders. Imports nothing from `workOrders.js` -- that module
// imports this one -- and reads `allItems` through the mount options.
//
// One fetch (`GET /work-orders/{id}/requests`) serves both surfaces: the
// "This work order's requests" list under the form, and the one-tap
// `Add requested material` lines above the Materials add row. Lines exist
// only while a request is `stocked`; an open request leaves Materials alone.
//
// Delegated document listeners, like `catalogueRequest.js`: the card body is
// rebuilt by `innerHTML` on every repaint, so per-instance wiring would leak.

import {
  apiCancelMaterialRequest,
  apiCreateMaterialRequest,
  apiListWorkOrderRequests,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, filterRanked, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { getCurrentUser } from "../state.js";
import { catalogueRequestPromptHtml } from "./catalogueRequest.js";

const USER_REQUEST_CHANGED_EVENT = "user_request.changed";

// Per-card reference data handed in by the mount call.
const itemsByCard = new WeakMap();

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function statusLabel(status) {
  if (status === "stocked") return "Stocked";
  if (status === "resolved") return "Resolved";
  return "Open";
}

function typeTag(type) {
  return type === "catalogue_request" ? "Catalogue" : "Material";
}

// --- markup ---------------------------------------------------------------

export function requestFormHtml() {
  return `<div class="wo-request-form">
      <p class="hint">Need a catalogue item the shelf does not have? Staff are notified as soon as you send it.</p>
      <div class="wo-request-row">
        <input type="text" class="wo-request-search" placeholder="Search item by name or barcode" autocomplete="off">
        <input type="number" class="wo-request-qty" value="1" min="0.01" step="any" inputmode="decimal" aria-label="Quantity needed">
      </div>
      <div class="wo-request-results scan-chooser" hidden></div>
      <p class="wo-request-onhand hint" aria-live="polite"></p>
      <input type="url" class="wo-request-link" placeholder="Product link (optional)" inputmode="url">
      <input type="text" class="wo-request-note" maxlength="500" placeholder="Note (optional)">
      <div class="wo-request-actions">
        <button type="button" data-request-action="send">Send request</button>
      </div>
      <p class="wo-request-message" aria-live="polite"></p>
    </div>`;
}

function requestLineHtml(request, currentUserId) {
  const details = request.details || {};
  const name =
    request.request_type === "catalogue_request"
      ? details.searched_text || "Unnamed item"
      : request.item_name || "Unknown item";
  const cancel =
    request.request_type === "material_request" &&
    request.status === "open" &&
    request.created_by_id === currentUserId
      ? `<button type="button" class="secondary-btn" data-request-action="cancel" data-request-id="${escapeHtml(request.id)}">Cancel</button>`
      : "";
  return `<div class="wo-request-line wo-request-${escapeHtml(request.status)}">
      <span class="wo-request-type">${escapeHtml(typeTag(request.request_type))}</span>
      <span class="wo-request-name">${escapeHtml(name)}</span>
      <span class="hint">qty ${escapeHtml(details.quantity || "1")}</span>
      <span class="wo-request-status">${escapeHtml(statusLabel(request.status))}</span>
      <span class="hint">${escapeHtml(request.created_by_name || "Unknown")} · ${escapeHtml(formatWhen(request.created_at))}</span>
      ${cancel}
    </div>`;
}

export function requestListHtml(requests, currentUserId) {
  const live = requests.filter((r) => r.status !== "resolved");
  const resolved = requests.filter((r) => r.status === "resolved");
  const liveHtml = live.length
    ? live.map((r) => requestLineHtml(r, currentUserId)).join("")
    : `<p class="hint">No open requests on this work order.</p>`;
  const resolvedHtml = resolved.length
    ? `<details class="wo-request-resolved-group"><summary class="hint">Show resolved (${resolved.length})</summary>${resolved
        .map((r) => requestLineHtml(r, currentUserId))
        .join("")}</details>`
    : "";
  return `<h4 class="wo-request-heading">This work order's requests</h4>${liveHtml}${resolvedHtml}`;
}

export function stockedLinesHtml(requests) {
  return requests
    .filter((r) => r.request_type === "material_request" && r.status === "stocked")
    .map((r) => {
      const details = r.details || {};
      return `<div class="wo-requested-line" data-request-id="${escapeHtml(r.id)}" data-item-id="${escapeHtml(r.item_id)}" data-item-name="${escapeHtml(r.item_name || "")}" data-quantity="${escapeHtml(details.quantity || "1")}">
          <span class="wo-requested-text">${escapeHtml(r.item_name || "Unknown item")} · requested ${escapeHtml(details.quantity || "1")} · on hand ${escapeHtml(r.item_quantity ?? "?")} · by ${escapeHtml(r.created_by_name || "Unknown")}</span>
          <button type="button" data-request-action="add-requested">Add requested material</button>
        </div>`;
    })
    .join("");
}

// --- mount ----------------------------------------------------------------

export async function mountWorkOrderRequests(cardEl, detail, { items = [] } = {}) {
  itemsByCard.set(cardEl, items);
  const section = cardEl.querySelector(".wo-request-section .wo-section-content");
  const lines = cardEl.querySelector(".wo-requested-lines");
  if (!section) return;
  section.innerHTML = requestFormHtml() + `<div class="wo-request-list"><p class="hint">Loading requests…</p></div>`;
  let requests = [];
  try {
    requests = await apiListWorkOrderRequests(detail.id);
  } catch (err) {
    section.querySelector(".wo-request-list").innerHTML =
      `<p class="error">${escapeHtml(friendlyError(err, "Could not load requests."))}</p>`;
    return;
  }
  const me = getCurrentUser()?.id || null;
  const list = section.querySelector(".wo-request-list");
  if (list) list.innerHTML = requestListHtml(requests, me);
  if (lines) lines.innerHTML = stockedLinesHtml(requests);
}

// --- search inside the Request form ----------------------------------------

document.addEventListener("input", (event) => {
  const input = event.target;
  if (!input.classList?.contains("wo-request-search")) return;
  const form = input.closest(".wo-request-form");
  const cardEl = input.closest(".wo-card");
  const results = form.querySelector(".wo-request-results");
  const onHand = form.querySelector(".wo-request-onhand");
  delete form.dataset.itemId;
  onHand.textContent = "";
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = filterRanked(itemsByCard.get(cardEl) || [], (it) => [it.name, it.barcode], q).slice(0, 8);
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-request-action="pick" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}" data-item-quantity="${escapeHtml(it.quantity)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>` +
      catalogueRequestPromptHtml({
        searchedText: input.value.trim(),
        workOrderId: cardEl ? cardEl.dataset.id : null,
        source: "request_card",
      });
  results.hidden = false;
});

// --- actions ------------------------------------------------------------------

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-request-action]");
  if (!btn) return;
  const action = btn.dataset.requestAction;
  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;

  if (action === "pick") {
    const form = btn.closest(".wo-request-form");
    form.dataset.itemId = btn.dataset.itemId;
    form.querySelector(".wo-request-search").value = btn.dataset.itemName;
    const results = form.querySelector(".wo-request-results");
    results.hidden = true;
    results.innerHTML = "";
    const onHand = Number(btn.dataset.itemQuantity);
    form.querySelector(".wo-request-onhand").textContent =
      onHand > 0 ? `${onHand} on hand — Staff will verify the count.` : `${onHand} on hand.`;
    form.querySelector(".wo-request-qty").focus();
    return;
  }

  if (action === "send") {
    const form = btn.closest(".wo-request-form");
    const msg = form.querySelector(".wo-request-message");
    const itemId = form.dataset.itemId;
    const qty = Number(form.querySelector(".wo-request-qty").value);
    const linkInput = form.querySelector(".wo-request-link");
    if (!itemId) {
      setMessage(msg, "Search and pick an item first.", "error");
      return;
    }
    if (!Number.isFinite(qty) || qty <= 0) {
      setMessage(msg, "Enter a quantity greater than zero.", "error");
      return;
    }
    if (linkInput.value.trim() && !linkInput.checkValidity()) {
      setMessage(msg, "Enter a valid product link.", "error");
      linkInput.focus();
      return;
    }
    btn.disabled = true;
    setMessage(msg, "Sending…", "");
    try {
      const result = await apiCreateMaterialRequest({
        itemId,
        workOrderId: cardEl.dataset.id,
        quantity: qty,
        productLink: linkInput.value.trim() || null,
        note: form.querySelector(".wo-request-note").value.trim() || null,
      });
      await mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
      const fresh = cardEl.querySelector(".wo-request-message");
      if (fresh) {
        setMessage(
          fresh,
          result.updated ? "Updated your earlier request." : "Request sent. Staff have been notified.",
          "success"
        );
      }
    } catch (err) {
      btn.disabled = false;
      setMessage(msg, friendlyError(err, "Could not send that request."), "error");
    }
    return;
  }

  if (action === "cancel") {
    if (!(await confirmDialog("Cancel this material request?"))) return;
    btn.disabled = true;
    try {
      await apiCancelMaterialRequest(btn.dataset.requestId);
      await mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
    } catch (err) {
      btn.disabled = false;
      const msg = cardEl.querySelector(".wo-message");
      if (msg) setMessage(msg, friendlyError(err, "Could not cancel that request."), "error");
    }
    return;
  }

  if (action === "add-requested") {
    // Prefill the existing add row and stamp the request id so the Add sends
    // it; the add itself stays `workOrders.js`'s job (entry mode, refresh).
    const line = btn.closest(".wo-requested-line");
    const container = cardEl.querySelector(".wo-add-item");
    if (!line || !container) return;
    container.dataset.itemId = line.dataset.itemId;
    container.dataset.materialRequestId = line.dataset.requestId;
    container.querySelector(".ms-item-search").value = line.dataset.itemName;
    const qty = container.querySelector(".wo-item-qty");
    qty.value = line.dataset.quantity;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    const materials = cardEl.querySelector(".wo-materials-section");
    if (materials) materials.open = true;
    qty.focus();
  }
});

// A request moved somewhere: refresh both surfaces on every open card that
// is not holding unsaved input. The envelope names a request, not a work
// order, so every open card refetches -- one small request each.
subscribe(USER_REQUEST_CHANGED_EVENT, () => {
  document.querySelectorAll("details.wo-card[open]").forEach((cardEl) => {
    const held = Array.from(
      cardEl.querySelectorAll(".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section")
    ).some((s) => s.open && s.querySelector("input:focus, textarea:focus"));
    if (held || !cardEl.querySelector(".wo-request-section")) return;
    void mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
  });
});
