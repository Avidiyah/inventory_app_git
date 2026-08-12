// View helper: HTML for one User Request card, per request type.
//
// Layer: views (presentation only). Extracted from `userRequests.js` when the
// third request type arrived: that module now owns loading, filtering, and
// event delegation, and this one owns markup. No fetches happen here.
//
// The three types and what each card offers:
//   inventory_recount  -- frozen shortage snapshot, inline count correction
//   missing_item_price -- inline price + product link
//   item_request       -- inline fulfilment (link or create the item)
//
// Every type also gets an Edit mode for the request's own wording. A recount's
// audit numbers are deliberately NOT editable there -- see EDITABLE_DETAILS in
// services/user_requests.py.

import { escapeHtml, formatMoney } from "../format.js";

export function formatDate(value) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export function requestTypeLabel(type) {
  if (type === "inventory_recount") return "Stock recount";
  if (type === "missing_item_price") return "Missing price / link";
  if (type === "item_request") return "Item request";
  return type.replaceAll("_", " ");
}

function detailLine(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return `<span><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
}

// --- per-type body -------------------------------------------------------

function itemRequestBody(request, details) {
  const workOrders = request.work_order_number
    ? detailLine("Work order", request.work_order_number)
    : `<span class="hint">Reported from Find Item — no work order attached.</span>`;
  return (
    workOrders +
    detailLine("Quantity needed", details.quantity) +
    detailLine("Note", details.note) +
    detailLine("Requested by", request.created_by_name || "Unknown") +
    detailLine("Created", formatDate(request.created_at)) +
    (request.item_name ? detailLine("Added as", request.item_name) : "")
  );
}

function recountBody(request, details) {
  return (
    detailLine("Barcode", request.item_barcode) +
    detailLine("Work order", request.work_order_number) +
    detailLine("Recorded before", details.recorded_quantity_before) +
    detailLine("Dispensed", details.dispensed_quantity) +
    detailLine("Shortage", details.shortage_quantity) +
    detailLine("Requested by", request.created_by_name || "Unknown") +
    detailLine("Created", formatDate(request.created_at))
  );
}

function missingPriceBody(request, details) {
  const numbers = Array.isArray(details.work_order_numbers)
    ? details.work_order_numbers.join(", ")
    : request.work_order_number;
  return (
    detailLine("Barcode", request.item_barcode) +
    detailLine("Work orders", numbers) +
    detailLine("Requested by", request.created_by_name || "Unknown") +
    detailLine("Created", formatDate(request.created_at))
  );
}

// --- per-type actions ----------------------------------------------------

function itemRequestActions(request) {
  if (request.status !== "open") {
    return `<span class="hint">Fulfilled${
      request.item_name ? ` as ${escapeHtml(request.item_name)}` : ""
    }.</span>`;
  }
  const warning = request.work_order_archived
    ? `<p class="user-request-warning">⚠ ${escapeHtml(
        request.work_order_number || "That work order"
      )} is closed. The item will still be created, but it will not be added to the work order.</p>`
    : "";
  return (
    warning +
    `<button type="button" class="user-request-fulfill-open">Fulfil…</button>` +
    `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`
  );
}

function recountActions(request) {
  if (request.status !== "open") {
    return (
      `<button type="button" class="user-request-action secondary-btn" data-status="open">Reopen</button>` +
      `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`
    );
  }
  return (
    `<div class="user-request-count-fix">
       <label class="user-request-count-label">Correct count to
         <input type="number" class="user-request-count-input" min="0" step="any" placeholder="0" inputmode="decimal">
       </label>
       <label class="user-request-count-label">Reason
         <input type="text" class="user-request-count-reason" placeholder="Recounted the shelf">
       </label>
       <button type="button" class="user-request-count-save">Save count</button>
     </div>` +
    `<button type="button" class="user-request-action" data-status="resolved">Mark resolved</button>` +
    `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`
  );
}

function missingPriceActions(request) {
  if (request.status !== "open") {
    return (
      `<span class="hint">Resolved automatically when the item price and product link were added.</span>` +
      `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`
    );
  }
  return (
    `<label class="user-request-price-label">Price
       <input type="number" class="user-request-price-input" min="0.01" step="0.01" placeholder="0.00" inputmode="decimal">
     </label>` +
    `<label class="user-request-link-label">Product link
       <input type="url" class="user-request-link-input" placeholder="https://..." inputmode="url">
     </label>` +
    `<button type="button" class="user-request-price-save">Save price &amp; link</button>` +
    `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`
  );
}

// --- edit mode -----------------------------------------------------------

// Only the fields the backend whitelists per type. The recount snapshot is
// shown as static text with the reason it cannot be edited, so the rule is
// visible rather than merely enforced.
export function editFormHtml(request) {
  const details = request.details || {};
  const itemFields =
    request.request_type === "item_request"
      ? `<label class="user-request-label">Item searched for
           <input type="text" class="user-request-edit-text" maxlength="200" value="${escapeHtml(
             details.searched_text || ""
           )}">
         </label>
         <label class="user-request-label">Quantity needed
           <input type="number" class="user-request-edit-qty" min="0.01" step="any" value="${escapeHtml(
             details.quantity || "1"
           )}">
         </label>
         <label class="user-request-label">Note
           <input type="text" class="user-request-edit-note" maxlength="500" value="${escapeHtml(
             details.note || ""
           )}">
         </label>`
      : `<p class="hint">This request's recorded figures are a snapshot of what
           the system saw at the time and cannot be edited. You can reword the
           message below.</p>`;

  return `<div class="user-request-edit">
      ${itemFields}
      <label class="user-request-label">Message
        <input type="text" class="user-request-edit-message" value="${escapeHtml(
          request.message || ""
        )}">
      </label>
      <div class="user-request-actions">
        <button type="button" class="user-request-edit-save">Save changes</button>
        <button type="button" class="secondary-btn user-request-edit-cancel">Cancel</button>
      </div>
    </div>`;
}

// --- fulfilment ----------------------------------------------------------

export function fulfillFormHtml(request) {
  const details = request.details || {};
  return `<div class="user-request-fulfill">
      <div class="user-request-fulfill-mode">
        <label><input type="radio" name="fulfill-mode-${escapeHtml(
          request.id
        )}" value="link" class="user-request-mode" checked> Link an existing item</label>
        <label><input type="radio" name="fulfill-mode-${escapeHtml(
          request.id
        )}" value="create" class="user-request-mode"> Create a new item</label>
      </div>

      <div class="user-request-link-pane">
        <label class="user-request-label">Search the catalogue
          <input type="search" class="user-request-item-search" placeholder="Name or barcode" value="${escapeHtml(
            details.searched_text || ""
          )}" autocomplete="off">
        </label>
        <div class="user-request-item-results scan-chooser"></div>
        <p class="user-request-picked hint"></p>
      </div>

      <div class="user-request-create-pane" hidden>
        <label class="user-request-label">Barcode
          <input type="text" class="user-request-new-barcode" placeholder="Scan or type a code">
        </label>
        <label class="user-request-label">Name
          <input type="text" class="user-request-new-name" value="${escapeHtml(
            details.searched_text || ""
          )}">
        </label>
        <label class="user-request-label">Location
          <input type="text" class="user-request-new-location" placeholder="Shelf">
        </label>
        <label class="user-request-label">Quantity on hand
          <input type="number" class="user-request-new-qty" value="0" min="0" step="any">
        </label>
        <label class="user-request-label">Price
          <input type="number" class="user-request-new-price" min="0.01" step="0.01" placeholder="0.00">
        </label>
        <label class="user-request-label">Product link
          <input type="url" class="user-request-new-link" placeholder="https://...">
        </label>
      </div>

      <div class="user-request-siblings">
        <p class="hint">Checking for other open requests for this material…</p>
      </div>

      <div class="user-request-actions">
        <button type="button" class="user-request-fulfill-save">Fulfil &amp; close</button>
        <button type="button" class="secondary-btn user-request-fulfill-cancel">Cancel</button>
      </div>
    </div>`;
}

// The sibling set is PRE-CHECKED but confirmable. Matching is on free text a
// user typed on a phone, so a wrong match would retroactively bill material to
// another customer's work order -- cheap to uncheck, expensive to undo.
export function siblingsHtml(siblings) {
  if (!siblings.length) {
    return `<p class="hint">No other open requests match this material.</p>`;
  }
  const rows = siblings
    .map((sibling) => {
      const details = sibling.details || {};
      const where = sibling.work_order_number
        ? `${sibling.work_order_number}${
            sibling.work_order_archived ? " (closed — will be skipped)" : ""
          }`
        : "no work order";
      return `<label class="user-request-sibling">
          <input type="checkbox" class="user-request-sibling-check" value="${escapeHtml(
            sibling.id
          )}" checked>
          <span>"${escapeHtml(details.searched_text || "")}" — ${escapeHtml(
        where
      )}, qty ${escapeHtml(details.quantity || "1")}, ${escapeHtml(
        sibling.created_by_name || "Unknown"
      )}</span>
        </label>`;
    })
    .join("");
  return `<p class="user-request-siblings-title"><strong>Also close these ${
    siblings.length
  } request${siblings.length === 1 ? "" : "s"} for the same material?</strong></p>
    <p class="hint">Each is added to its own work order at its own quantity. Uncheck any that are not the same material.</p>
    ${rows}`;
}

// --- the card ------------------------------------------------------------

export function buildRequestCard(request) {
  const details = request.details || {};
  const card = document.createElement("article");
  card.className = `user-request-card user-request-${request.status} user-request-type-${request.request_type}`;
  card.dataset.id = request.id;
  card.dataset.itemId = request.item_id || "";
  card.dataset.requestType = request.request_type;

  let heading;
  let body;
  let actions;
  if (request.request_type === "item_request") {
    heading = details.searched_text || "Unnamed item";
    body = itemRequestBody(request, details);
    actions = itemRequestActions(request);
  } else if (request.request_type === "missing_item_price") {
    heading = request.item_name || "Unknown item";
    body = missingPriceBody(request, details);
    actions = missingPriceActions(request);
  } else {
    heading = request.item_name || "Unknown item";
    body = recountBody(request, details);
    actions = recountActions(request);
  }

  const resolution =
    request.status === "resolved"
      ? `<div class="user-request-resolution">${detailLine(
          "Resolved by",
          request.resolved_by_name || "Unknown"
        )}${detailLine("Resolved", formatDate(request.resolved_at))}${detailLine(
          "Note",
          request.resolution_note
        )}</div>`
      : "";

  card.innerHTML =
    `<div class="user-request-header">` +
    `<div><span class="user-request-type">${escapeHtml(
      requestTypeLabel(request.request_type)
    )}</span>` +
    `<h3>${escapeHtml(heading)}</h3></div>` +
    `<span class="user-request-status">${escapeHtml(request.status)}</span>` +
    `</div>` +
    `<p class="user-request-alert">${escapeHtml(request.message)}</p>` +
    `<div class="user-request-details">${body}</div>` +
    resolution +
    `<div class="user-request-actions">${actions}</div>` +
    `<div class="user-request-panel"></div>`;

  if (request.request_type === "missing_item_price" && request.status === "open") {
    const priceInput = card.querySelector(".user-request-price-input");
    const linkInput = card.querySelector(".user-request-link-input");
    if (request.item_price !== null && request.item_price !== undefined) {
      priceInput.value = request.item_price;
    }
    if (request.item_product_link) linkInput.value = request.item_product_link;
  }
  return card;
}

// Re-exported so the controller can render a picked item consistently.
export function itemChoiceHtml(item) {
  return `<button type="button" class="secondary-btn scan-choice-btn user-request-item-pick"
      data-item-id="${escapeHtml(item.id)}" data-item-name="${escapeHtml(item.name)}">
      ${escapeHtml(item.name)}
      <span class="ms-pick-barcode">${escapeHtml(item.barcode)}</span>
      <span class="hint">${escapeHtml(formatMoney(item.price) || "no price")}</span>
    </button>`;
}
