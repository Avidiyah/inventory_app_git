// View: Admin/Owner operational User Requests queue.
//
// Layer: views. Owns loading, filtering, and every interaction on the page;
// markup lives in `userRequestCards.js`.
//
// Four request types share one queue and one resolution model — requests are
// resolved, never deleted:
//   material_request   -- a catalogue item the shelf does not have
//   inventory_recount  -- an in-app item's recorded count is short
//   missing_item_price -- a work-order material has no price / product link
//   catalogue_request  -- the material has no catalogue row at all
//
// Each type resolves through the fix that actually answers it, so the page is
// where the real-world discrepancy gets closed rather than merely acknowledged.

import {
  apiCreateCorrection,
  apiFulfillCatalogueRequest,
  apiListItems,
  apiListRequestSiblings,
  apiListUserRequestCounts,
  apiListUserRequests,
  apiMarkRequestStocked,
  apiUpdateItem,
  apiUpdateUserRequest,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { isDirty, keepPlace, morphInto } from "../morph.js";
import { subscribe } from "../realtime.js";
import {
  buildRequestCard,
  closeFormHtml,
  editFormHtml,
  fulfillFormHtml,
  highlightItemCard,
  itemChoiceHtml,
  requestTypeLabel,
  siblingsHtml,
} from "./userRequestCards.js";
import { editPayload, fulfillPayload } from "./userRequestsForms.js";

const statusEl = document.getElementById("user-requests-status");
const tabsEl = document.getElementById("user-requests-tabs");
const refreshBtn = document.getElementById("user-requests-refresh");
const listEl = document.getElementById("user-requests-list");
const messageEl = document.getElementById("user-requests-message");

const USER_REQUESTS_PAGE = "user-requests";
const USER_REQUEST_CHANGED_EVENT = "user_request.changed";
const STATUS_OPTIONS = {
  material_request: [["open", "Open"], ["stocked", "Stocked"], ["resolved", "Resolved"]],
  default: [["open", "Open"], ["resolved", "Resolved"]],
};
let activeType = "material_request";

// Admin Review's unpriced-item picker sets this before navigating here; the
// next render highlights that item's request once, then clears it.
let pendingFocus = null;

// The last loaded set (already narrowed to `activeType` by the server), kept
// so a card can be re-rendered from its source data on Cancel.
let loaded = [];

// Newest load wins; a tab or status change makes the next draw a first draw
// (a new list, so nothing glows and no panel carries over).
let loadSeq = 0;
let resetPending = false;
// The count line as last written, so a live update rewrites only a count and
// never an action's message.
let countText = "";

const FIELDS = "input, select, textarea";
const DROPPED = "A request you were working on was closed or moved by someone else.";

function rebuildStatusOptions() {
  const options = STATUS_OPTIONS[activeType] || STATUS_OPTIONS.default;
  const current = statusEl.value;
  statusEl.innerHTML = options
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  statusEl.value = options.some(([v]) => v === current) ? current : "open";
}

function selectTab(type) {
  activeType = type;
  tabsEl.querySelectorAll(".hub-tab").forEach((btn) => {
    const on = btn.dataset.requestType === type;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", String(on));
  });
  rebuildStatusOptions();
}

async function refreshCounts() {
  try {
    const counts = await apiListUserRequestCounts();
    tabsEl.querySelectorAll(".hub-tab").forEach((btn) => {
      const open = counts[btn.dataset.requestType]?.open || 0;
      btn.querySelector(".user-requests-tab-count").textContent = open ? `(${open})` : "";
    });
  } catch {
    // Counts are decoration; the list is the truth.
  }
}

function visibleRequests() {
  return loaded;
}

function requestById(id) {
  return loaded.find((request) => request.id === id) || null;
}

// Missing price / link on Open; nav.js's page loader does the load itself.
export function focusMissingPriceRequest({ itemId, itemName = "" }) {
  if (!statusEl || !tabsEl) return;
  selectTab("missing_item_price");
  statusEl.value = "open";
  resetPending = true;
  pendingFocus = { itemId: String(itemId), itemName };
}

// A card's own text, its panel left out: opening a panel must not glow it.
const cardText = (card) => [...card.children]
  .filter((child) => !child.matches(".user-request-panel")).map((child) => child.textContent).join("\n");

// An open panel and a focused or typed field are the user's: a patch leaves
// them. A card the server removed goes regardless (rule 7, never silently).
function skip(el) {
  if (el.matches(".user-request-panel")) return el.children.length > 0;
  return el.matches(FIELDS) && (el === document.activeElement || isDirty(el));
}

function render({ live }) {
  const requests = visibleRequests();
  if (resetPending) listEl.replaceChildren();
  resetPending = false;
  const tree = document.createElement("div");
  for (const request of requests) tree.appendChild(buildRequestCard(request));
  // A card being saved by this page is expected to change or leave.
  const held = [
    ...[...listEl.querySelectorAll(".user-request-panel")].filter((panel) => panel.children.length),
    ...[...listEl.querySelectorAll(FIELDS)].filter((f) => !f.closest(".user-request-panel") && isDirty(f)),
  ].filter((el) => !el.closest("[data-saving]"));
  const restore = keepPlace(listEl);
  morphInto(listEl, tree.childNodes, { skip, flashSelector: ".user-request-card", flashKey: cardText });
  restore();

  const focus = pendingFocus;
  pendingFocus = null;
  if (held.some((el) => !el.isConnected)) {
    setMessage(messageEl, DROPPED, "error");
    return;
  }
  if (focus && !highlightItemCard(listEl, focus.itemId)) {
    const name = focus.itemName || "that item";
    setMessage(messageEl, `No open missing-price request for ${name} — edit its price on the Items page.`, "error");
    return;
  }
  if (live && messageEl.textContent && messageEl.textContent !== countText) return;

  const status = statusEl.value;
  const label = requestTypeLabel(activeType).toLowerCase();
  if (!requests.length) {
    setMessage(messageEl, `No ${status} ${label}s.`, "success");
  } else {
    setMessage(
      messageEl,
      `${requests.length} ${status} request${requests.length === 1 ? "" : "s"}.`,
      ""
    );
  }
  countText = messageEl.textContent;
}

// `live`: a socket signal, not a user action -- no "Loading" line, and an
// action's message stays.
export async function loadUserRequests({ live = false } = {}) {
  if (!listEl) return;
  const seq = ++loadSeq;
  const status = statusEl.value || "open";
  if (!live) {
    setMessage(messageEl, `Loading ${status} requests...`, "");
    countText = messageEl.textContent;
  }
  try {
    const fresh = await apiListUserRequests(status, activeType);
    if (seq !== loadSeq) return;
    loaded = fresh;
    render({ live });
    void refreshCounts();
  } catch (err) {
    if (seq !== loadSeq) return;
    loaded = [];
    pendingFocus = null;
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load User Requests."), "error");
  }
}

const reload = () => loadUserRequests();
const reloadNewList = () => {
  resetPending = true;
  return loadUserRequests();
};

if (statusEl) statusEl.addEventListener("change", reloadNewList);
if (refreshBtn) refreshBtn.addEventListener("click", reload);
if (tabsEl && statusEl) {
  tabsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".hub-tab[data-request-type]");
    if (!btn) return;
    selectTab(btn.dataset.requestType);
    void reloadNewList();
  });
  // Status options must match the default tab before the first load.
  selectTab(activeType);
}

// --- panel helpers -------------------------------------------------------

function panelOf(card) {
  return card.querySelector(".user-request-panel");
}

function closePanel(card) {
  panelOf(card).innerHTML = "";
}

// One own save: mark the card (its leaving is this page's doing, not someone
// else's), close its panel on success, reload through the one render path.
async function save(card, button, call, failText) {
  button.disabled = true;
  card.dataset.saving = "";
  try {
    const result = await call();
    closePanel(card);
    await loadUserRequests();
    return result || {};
  } catch (err) {
    button.disabled = false;
    delete card.dataset.saving;
    setMessage(messageEl, friendlyError(err, failText), "error");
    return null;
  }
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
    if (event.target.closest(".user-request-close-open")) {
      panelOf(card).innerHTML = closeFormHtml();
      return;
    }
    if (
      event.target.closest(".user-request-fulfill-cancel") ||
      event.target.closest(".user-request-edit-cancel") ||
      event.target.closest(".user-request-close-cancel")
    ) {
      closePanel(card);
      return;
    }

    // --- close a catalogue request without fulfilling --------------------
    const closeSave = event.target.closest(".user-request-close-save");
    if (closeSave) {
      const reasonInput = panelOf(card).querySelector(".user-request-close-reason");
      const reason = reasonInput.value.trim();
      if (!reason) {
        setMessage(messageEl, "Enter a reason for closing this request.", "error");
        reasonInput.focus();
        return;
      }
      await save(card, closeSave, () => apiUpdateUserRequest(card.dataset.id, { status: "resolved", resolutionNote: reason }), "Could not close that request.");
      return;
    }

    // --- save an edit ----------------------------------------------------
    const editSave = event.target.closest(".user-request-edit-save");
    if (editSave) {
      const panel = panelOf(card);
      const payload = editPayload(card, panel);
      if (payload.error) {
        setMessage(messageEl, payload.error, "error");
        return;
      }

      await save(card, editSave, () => apiUpdateUserRequest(card.dataset.id, { message: payload.message, details: payload.details }), "Could not save those changes.");
      return;
    }

    // --- fulfil a catalogue request -----------------------------------------
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
      if (!(await confirmDialog(`Fulfil this catalogue request?${extra}`))) return;

      const result = await save(card, fulfillSave,
        () => apiFulfillCatalogueRequest(card.dataset.id, payload), "Could not fulfil that request.");
      if (result?.skipped?.length) setMessage(messageEl, result.skipped.join(" "), "error");
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

      // The correction resolves the recount request server-side, in the same
      // commit as the stock write.
      await save(card, countSave, () => apiCreateCorrection({ itemId: card.dataset.itemId, newQuantity: quantity, reason }), "Could not save that count.");
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

      await save(card, priceButton, () => apiUpdateItem(card.dataset.itemId, { price, product_link: productLink }), "Could not save that item price.");
      return;
    }

    // --- mark a material request stocked (manual fire) --------------------
    const stockBtn = event.target.closest(".user-request-stock");
    if (stockBtn) {
      if (!(await confirmDialog("Mark this item as stocked and notify the crew?"))) return;
      await save(card, stockBtn, () => apiMarkRequestStocked(card.dataset.id), "Could not mark that request stocked.");
      return;
    }

    // --- resolve / reopen --------------------------------------------------
    const button = event.target.closest(".user-request-action");
    if (!button) return;
    const targetStatus = button.dataset.status;
    const verb = button.dataset.verb || (targetStatus === "resolved" ? "resolve" : "reopen");
    if (!(await confirmDialog(`${verb[0].toUpperCase()}${verb.slice(1)} this user request?`))) return;

    const resolutionNote = verb === "remove" ? "Removed from the queue." : undefined;
    await save(card, button, () => apiUpdateUserRequest(card.dataset.id, { status: targetStatus, resolutionNote }), `Could not ${verb} that request.`);
  });
}

// Any request moved: reload when this page is showing. Background reload --
// a socket signal, not a user action.
subscribe(USER_REQUEST_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== USER_REQUESTS_PAGE) return;
  void loadUserRequests({ live: true });
});
