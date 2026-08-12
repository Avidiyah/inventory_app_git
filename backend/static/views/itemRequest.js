// View: file an Item Request from a search that found nothing.
//
// Layer: views. Mounted at two empty states -- the Work Orders card's
// add-material picker and Find Item's results table -- so a user who cannot
// find a material can report it without leaving what they were doing.
//
// Scope note: this is for material with NO catalogue row. An in-app item
// sitting at zero is still findable (`list_items` filters on `archived_at`,
// never on quantity), and a short count is an `inventory_recount` request
// raised automatically by the dispense. Nothing here touches that case.
//
// Rendered as an HTML string rather than a DOM node because both host views
// build their empty states with `innerHTML`; a document-level delegated
// listener then owns every interaction, so hosts need no per-instance wiring.

import { apiCreateItemRequest } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";

// Where the prompt is allowed to submit from. Kept explicit so a typo in a
// host view fails loudly here instead of writing a junk `source` server-side.
const SOURCES = new Set(["work_orders", "find_item"]);

export function itemRequestPromptHtml({
  searchedText,
  workOrderId = null,
  source,
}) {
  if (!SOURCES.has(source)) {
    throw new Error(`itemRequestPromptHtml: unknown source ${source}`);
  }
  const text = (searchedText || "").trim();
  if (!text) return "";

  return `<div class="item-request" data-source="${escapeHtml(source)}"${
    workOrderId ? ` data-work-order-id="${escapeHtml(workOrderId)}"` : ""
  } data-searched-text="${escapeHtml(text)}">
      <button type="button" class="secondary-btn item-request-open">
        Can't find it? Request this item
      </button>
    </div>`;
}

function formHtml(searchedText) {
  return `<div class="item-request-form">
      <p class="hint">Send this to Admins to add to the catalogue.</p>
      <label class="item-request-label">Item you searched for
        <input type="text" class="item-request-text" value="${escapeHtml(searchedText)}" maxlength="200">
      </label>
      <label class="item-request-label">Quantity needed
        <input type="number" class="item-request-qty" value="1" min="0.01" step="any" inputmode="decimal">
      </label>
      <label class="item-request-label">Note (optional)
        <input type="text" class="item-request-note" maxlength="500" placeholder="e.g. sweat type, not press">
      </label>
      <div class="item-request-actions">
        <button type="button" class="item-request-submit">Send request</button>
        <button type="button" class="secondary-btn item-request-cancel">Cancel</button>
      </div>
      <p class="item-request-message" aria-live="polite"></p>
    </div>`;
}

function setLocalMessage(container, text, kind) {
  const el = container.querySelector(".item-request-message");
  if (!el) return;
  el.textContent = text;
  el.className = `item-request-message${kind ? ` ${kind}` : ""}`;
}

document.addEventListener("click", async (event) => {
  const container = event.target.closest(".item-request");
  if (!container) return;

  if (event.target.closest(".item-request-open")) {
    container.innerHTML = formHtml(container.dataset.searchedText || "");
    container.querySelector(".item-request-text")?.focus();
    return;
  }

  if (event.target.closest(".item-request-cancel")) {
    container.innerHTML = `<button type="button" class="secondary-btn item-request-open">
        Can't find it? Request this item
      </button>`;
    return;
  }

  const submit = event.target.closest(".item-request-submit");
  if (!submit) return;

  const textInput = container.querySelector(".item-request-text");
  const qtyInput = container.querySelector(".item-request-qty");
  const searchedText = textInput.value.trim();
  if (!searchedText) {
    setLocalMessage(container, "Describe the item you need.", "error");
    textInput.focus();
    return;
  }
  const quantity = Number(qtyInput.value);
  if (!Number.isFinite(quantity) || quantity <= 0) {
    setLocalMessage(container, "Enter a quantity greater than zero.", "error");
    qtyInput.focus();
    return;
  }

  submit.disabled = true;
  setLocalMessage(container, "Sending…", "");
  try {
    await apiCreateItemRequest({
      searchedText,
      quantity,
      note: container.querySelector(".item-request-note").value.trim() || null,
      workOrderId: container.dataset.workOrderId || null,
      source: container.dataset.source,
    });
    // Replace the whole prompt: re-submitting the same search would file a
    // second request for the same material on the same work order.
    container.innerHTML =
      `<p class="item-request-sent success">Request sent to Admins for review.</p>`;
  } catch (err) {
    submit.disabled = false;
    setLocalMessage(
      container,
      friendlyError(err, "Could not send that request."),
      "error"
    );
  }
});
