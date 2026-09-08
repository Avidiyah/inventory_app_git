// View: file a Catalogue Request from a search that found nothing.
//
// Layer: views. Mounted at three empty states -- the Work Orders card's
// add-material picker, Find Item's results table, and the Request card's
// item search -- so a user who cannot find a material can report it without
// leaving what they were doing.
//
// Scope note: this is for material with NO catalogue row. An in-app item
// sitting at zero is still findable (`list_items` filters on `archived_at`,
// never on quantity), and a short count is an `inventory_recount` request
// raised automatically by the dispense. Nothing here touches that case.
//
// Rendered as an HTML string rather than a DOM node because both host views
// build their empty states with `innerHTML`; a document-level delegated
// listener then owns every interaction, so hosts need no per-instance wiring.

import { apiCreateCatalogueRequest } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";

// Where the prompt is allowed to submit from. Kept explicit so a typo in a
// host view fails loudly here instead of writing a junk `source` server-side.
const SOURCES = new Set(["work_orders", "find_item", "request_card"]);

export function catalogueRequestPromptHtml({
  searchedText,
  workOrderId = null,
  source,
}) {
  if (!SOURCES.has(source)) {
    throw new Error(`catalogueRequestPromptHtml: unknown source ${source}`);
  }
  const text = (searchedText || "").trim();
  if (!text) return "";

  return `<div class="catalogue-request" data-source="${escapeHtml(source)}"${
    workOrderId ? ` data-work-order-id="${escapeHtml(workOrderId)}"` : ""
  } data-searched-text="${escapeHtml(text)}">
      <button type="button" class="secondary-btn catalogue-request-open">
        Can't find it? Request it for the catalogue
      </button>
    </div>`;
}

function formHtml(searchedText) {
  return `<div class="catalogue-request-form">
      <p class="hint">Send this to staff to add to the catalogue.</p>
      <label class="catalogue-request-label">Item you searched for
        <input type="text" class="catalogue-request-text" value="${escapeHtml(searchedText)}" maxlength="200">
      </label>
      <label class="catalogue-request-label">Quantity needed
        <input type="number" class="catalogue-request-qty" value="1" min="0.01" step="any" inputmode="decimal">
      </label>
      <label class="catalogue-request-label">Note (optional)
        <input type="text" class="catalogue-request-note" maxlength="500" placeholder="e.g. sweat type, not press">
      </label>
      <div class="catalogue-request-actions">
        <button type="button" class="catalogue-request-submit">Send request</button>
        <button type="button" class="secondary-btn catalogue-request-cancel">Cancel</button>
      </div>
      <p class="catalogue-request-message" aria-live="polite"></p>
    </div>`;
}

function setLocalMessage(container, text, kind) {
  const el = container.querySelector(".catalogue-request-message");
  if (!el) return;
  el.textContent = text;
  el.className = `catalogue-request-message${kind ? ` ${kind}` : ""}`;
}

document.addEventListener("click", async (event) => {
  const container = event.target.closest(".catalogue-request");
  if (!container) return;

  if (event.target.closest(".catalogue-request-open")) {
    container.innerHTML = formHtml(container.dataset.searchedText || "");
    container.querySelector(".catalogue-request-text")?.focus();
    return;
  }

  if (event.target.closest(".catalogue-request-cancel")) {
    container.innerHTML = `<button type="button" class="secondary-btn catalogue-request-open">
        Can't find it? Request it for the catalogue
      </button>`;
    return;
  }

  const submit = event.target.closest(".catalogue-request-submit");
  if (!submit) return;

  const textInput = container.querySelector(".catalogue-request-text");
  const qtyInput = container.querySelector(".catalogue-request-qty");
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
    await apiCreateCatalogueRequest({
      searchedText,
      quantity,
      note: container.querySelector(".catalogue-request-note").value.trim() || null,
      workOrderId: container.dataset.workOrderId || null,
      source: container.dataset.source,
    });
    // Replace the whole prompt: re-submitting the same search would file a
    // second request for the same material on the same work order.
    container.innerHTML =
      `<p class="catalogue-request-sent success">Catalogue request sent to staff.</p>`;
  } catch (err) {
    submit.disabled = false;
    setLocalMessage(
      container,
      friendlyError(err, "Could not send that request."),
      "error"
    );
  }
});
