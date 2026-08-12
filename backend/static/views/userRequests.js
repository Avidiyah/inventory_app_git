// View: Admin/Owner operational User Requests queue.
//
// Layer: views. Owns loading, filtering, and every interaction on the page;
// markup lives in `userRequestCards.js`.
//
// Three request types share one queue and one resolution model — requests are
// resolved, never deleted:
//   inventory_recount  -- an in-app item's recorded count is short
//   missing_item_price -- a work-order material has no price / product link
//   item_request       -- the material has no catalogue row at all
//
// Each type resolves through the fix that actually answers it, so the page is
// where the real-world discrepancy gets closed rather than merely acknowledged.

import {
  apiCreateCorrection,
  apiFulfillItemRequest,
  apiListItems,
  apiListRequestSiblings,
  apiListUserRequests,
  apiUpdateItem,
  apiUpdateUserRequest,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import {
  buildRequestCard,
  editFormHtml,
  fulfillFormHtml,
  itemChoiceHtml,
  siblingsHtml,
} from "./userRequestCards.js";

const statusEl = document.getElementById("user-requests-status");
const typeEl = document.getElementById("user-requests-type");
const refreshBtn = document.getElementById("user-requests-refresh");
const listEl = document.getElementById("user-requests-list");
const messageEl = document.getElementById("user-requests-message");

// The last loaded set, kept so the Type filter can narrow without refetching
// and so a card can be re-rendered from its source data on Cancel.
let loaded = [];

function visibleRequests() {
  const type = typeEl ? typeEl.value : "all";
  return type === "all"
    ? loaded
    : loaded.filter((request) => request.request_type === type);
}

function requestById(id) {
  return loaded.find((request) => request.id === id) || null;
}

function render() {
  const requests = visibleRequests();
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
    loaded = await apiListUserRequests(status);
    render();
  } catch (err) {
    loaded = [];
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load User Requests."), "error");
  }
}

if (statusEl) statusEl.addEventListener("change", loadUserRequests);
if (typeEl) typeEl.addEventListener("change", render);
if (refreshBtn) refreshBtn.addEventListener("click", loadUserRequests);

// --- panel helpers -------------------------------------------------------

function panelOf(card) {
  return card.querySelector(".user-request-panel");
}

function closePanel(card) {
  panelOf(card).innerHTML = "";
}

// --- fulfilment ----------------------------------------------------------

async function openFulfillPanel(card) {
  const request = requestById(card.dataset.id);
  if (!request) return;
  const panel = panelOf(card);
  panel.innerHTML = fulfillFormHtml(request);

  // Siblings load after the form paints so the Admin can start typing
  // immediately; a failure here must not block the fulfilment itself.
  const box = panel.querySelector(".user-request-siblings");
  try {
    box.innerHTML = siblingsHtml(await apiListRequestSiblings(request.id));
  } catch {
    box.innerHTML = `<p class="hint">Could not check for related requests. Fulfilling will close this one only.</p>`;
  }
}

function fulfillPayload(panel) {
  const mode = panel.querySelector(".user-request-mode:checked").value;
  const siblingIds = Array.from(
    panel.querySelectorAll(".user-request-sibling-check:checked")
  ).map((box) => box.value);

  if (mode === "link") {
    const itemId = panel.dataset.pickedItemId || null;
    if (!itemId) return { error: "Search and pick an item first." };
    return { itemId, siblingIds };
  }

  const barcode = panel.querySelector(".user-request-new-barcode").value.trim();
  const name = panel.querySelector(".user-request-new-name").value.trim();
  const location = panel.querySelector(".user-request-new-location").value.trim();
  if (!barcode) return { error: "Enter a barcode for the new item." };
  if (!name) return { error: "Enter a name for the new item." };
  if (!location) return { error: "Enter a location for the new item." };

  const rawPrice = panel.querySelector(".user-request-new-price").value.trim();
  const rawLink = panel.querySelector(".user-request-new-link").value.trim();
  return {
    newItem: {
      barcode,
      name,
      location,
      quantity: Number(panel.querySelector(".user-request-new-qty").value || 0),
      price: rawPrice ? Number(rawPrice) : null,
      product_link: rawLink || null,
    },
    siblingIds,
  };
}

// --- delegation ----------------------------------------------------------

if (listEl) {
  // Live item search inside an open fulfilment panel.
  let searchTimer = null;
  listEl.addEventListener("input", (event) => {
    const input = event.target.closest(".user-request-item-search");
    if (!input) return;
    const panel = input.closest(".user-request-panel");
    const results = panel.querySelector(".user-request-item-results");
    delete panel.dataset.pickedItemId;
    panel.querySelector(".user-request-picked").textContent = "";

    const query = input.value.trim();
    clearTimeout(searchTimer);
    if (!query) {
      results.innerHTML = "";
      return;
    }
    searchTimer = setTimeout(async () => {
      try {
        const items = await apiListItems({ query });
        results.innerHTML = items.length
          ? items.slice(0, 8).map(itemChoiceHtml).join("")
          : `<p class="hint">No catalogue item matches that. Switch to "Create a new item".</p>`;
      } catch (err) {
        results.innerHTML = `<p class="error">${escapeHtml(
          friendlyError(err, "Could not search items.")
        )}</p>`;
      }
    }, 250);
  });

  listEl.addEventListener("change", (event) => {
    const mode = event.target.closest(".user-request-mode");
    if (!mode) return;
    const panel = mode.closest(".user-request-panel");
    const linking = mode.value === "link";
    panel.querySelector(".user-request-link-pane").hidden = !linking;
    panel.querySelector(".user-request-create-pane").hidden = linking;
  });

  listEl.addEventListener("click", async (event) => {
    const card = event.target.closest(".user-request-card");
    if (!card) return;

    // --- pick an item in the fulfilment panel ---------------------------
    const pick = event.target.closest(".user-request-item-pick");
    if (pick) {
      const panel = pick.closest(".user-request-panel");
      panel.dataset.pickedItemId = pick.dataset.itemId;
      panel.querySelector(".user-request-picked").textContent =
        `Selected: ${pick.dataset.itemName}`;
      panel.querySelector(".user-request-item-results").innerHTML = "";
      return;
    }

    // --- open / close panels --------------------------------------------
    if (event.target.closest(".user-request-fulfill-open")) {
      await openFulfillPanel(card);
      return;
    }
    if (event.target.closest(".user-request-edit-open")) {
      const request = requestById(card.dataset.id);
      if (request) panelOf(card).innerHTML = editFormHtml(request);
      return;
    }
    if (
      event.target.closest(".user-request-fulfill-cancel") ||
      event.target.closest(".user-request-edit-cancel")
    ) {
      closePanel(card);
      return;
    }

    // --- save an edit ----------------------------------------------------
    const editSave = event.target.closest(".user-request-edit-save");
    if (editSave) {
      const panel = panelOf(card);
      const message = panel.querySelector(".user-request-edit-message").value.trim();
      if (!message) {
        setMessage(messageEl, "The message cannot be blank.", "error");
        return;
      }
      let details = null;
      if (card.dataset.requestType === "item_request") {
        const text = panel.querySelector(".user-request-edit-text").value.trim();
        if (!text) {
          setMessage(messageEl, "Describe the item that was searched for.", "error");
          return;
        }
        details = {
          searched_text: text,
          quantity: panel.querySelector(".user-request-edit-qty").value.trim() || "1",
          note: panel.querySelector(".user-request-edit-note").value.trim() || null,
        };
      }

      editSave.disabled = true;
      try {
        await apiUpdateUserRequest(card.dataset.id, { message, details });
        await loadUserRequests();
      } catch (err) {
        editSave.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not save those changes."), "error");
      }
      return;
    }

    // --- fulfil an item request -----------------------------------------
    const fulfillSave = event.target.closest(".user-request-fulfill-save");
    if (fulfillSave) {
      const panel = panelOf(card);
      const payload = fulfillPayload(panel);
      if (payload.error) {
        setMessage(messageEl, payload.error, "error");
        return;
      }
      const extra = payload.siblingIds.length
        ? ` This will also close ${payload.siblingIds.length} related request${
            payload.siblingIds.length === 1 ? "" : "s"
          } and add the material to their work orders.`
        : "";
      if (!(await confirmDialog(`Fulfil this item request?${extra}`))) return;

      fulfillSave.disabled = true;
      try {
        const result = await apiFulfillItemRequest(card.dataset.id, payload);
        await loadUserRequests();
        if (result && result.skipped && result.skipped.length) {
          setMessage(messageEl, result.skipped.join(" "), "error");
        }
      } catch (err) {
        fulfillSave.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not fulfil that request."), "error");
      }
      return;
    }

    // --- correct a short count -------------------------------------------
    const countSave = event.target.closest(".user-request-count-save");
    if (countSave) {
      const input = card.querySelector(".user-request-count-input");
      const reasonInput = card.querySelector(".user-request-count-reason");
      const raw = input.value.trim();
      const quantity = Number(raw);
      if (!raw || !Number.isFinite(quantity) || quantity < 0) {
        setMessage(messageEl, "Enter the corrected count (zero or more).", "error");
        input.focus();
        return;
      }
      const reason = reasonInput.value.trim();
      if (!reason) {
        setMessage(messageEl, "Enter a reason for the correction.", "error");
        reasonInput.focus();
        return;
      }

      countSave.disabled = true;
      try {
        // The correction resolves the recount request server-side, in the same
        // commit as the stock write.
        await apiCreateCorrection({
          itemId: card.dataset.itemId,
          newQuantity: quantity,
          reason,
        });
        await loadUserRequests();
      } catch (err) {
        countSave.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not save that count."), "error");
      }
      return;
    }

    // --- save a price + product link --------------------------------------
    const priceButton = event.target.closest(".user-request-price-save");
    if (priceButton) {
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
        await apiUpdateItem(card.dataset.itemId, { price, product_link: productLink });
        await loadUserRequests();
      } catch (err) {
        priceButton.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not save that item price."), "error");
      }
      return;
    }

    // --- resolve / reopen --------------------------------------------------
    const button = event.target.closest(".user-request-action");
    if (!button) return;
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
