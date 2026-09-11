// View: Work Orders page.
//
// Layer: views. Owns the Work Orders page: a server-scoped list of standalone
// work orders (identity = number). Work orders are IMPORT-ONLY -- the Admin+ CSV
// import is the only way one appears; there is no create form. The CSV import,
// NetFacilities/Langston University card, and "For Client" export render on
// the separate Integrations page (loadIntegrationsPage, pages/integrations.html)
// but are still owned by this module, since they share state with the list
// below. Admin+ can export the current filtered list as the operational CSV
// from this page. Admin+ Edit details includes imported metadata;
// Supervisor sees only routing, technicians, and status, and also manages labor,
// entry mode, and material corrections. Assigned Technicians/Supervisors get a
// narrow Set In-Progress -> Mark Completed walkthrough plus an In-Progress-only
// Place On-Hold action and On-Hold-only Resume In-Progress action outside the
// unchanged editor; Technicians can also save notes and add new materials.
// Admin+ can archive any live work order directly from its expanded card. An
// exact-number search for a closed row offers the explicit restore workflow.
// Reached via the nav button or a Unit click in the Mass Stage tree (which calls
// `focusWorkOrder` before switching pages).

import {
  apiListWorkOrders,
  apiGetWorkOrder,
  apiUpdateWorkOrder,
  apiStartWorkOrderTracking,
  apiStopWorkOrderTracking,
  apiCompleteWorkOrder,
  apiHoldWorkOrder,
  apiResumeWorkOrder,
  apiAddWorkOrderItem,
  apiUpdateWorkOrderItem,
  apiSetWorkOrderItemBilling,
  apiDeleteWorkOrderItem,
  apiAddWorkOrderLabor,
  apiUpdateWorkOrderLabor,
  apiDeleteWorkOrderLabor,
  apiArchiveWorkOrder,
  apiLookupWorkOrder,
  apiRestoreWorkOrder,
  apiImportWorkOrders,
  apiStartNetFacilitiesEnrichment,
  apiGetNetFacilitiesEnrichment,
  apiGetNetFacilitiesCloudSession,
  apiStartNetFacilitiesCloudAuthentication,
  apiCancelNetFacilitiesCloudAuthentication,
  apiImportNetFacilitiesCloudDownload,
  apiExportWorkOrders,
} from "../api.js";
import {
  escapeHtml,
  friendlyError,
  filterRanked,
} from "../format.js";
import { setMessage, confirmDialog, messageDialog } from "../dom.js";
import { catalogueRequestPromptHtml } from "./catalogueRequest.js";
import { mountWorkOrderRequests } from "./workOrderRequests.js";
import { openBillingEditor } from "./billingEditor.js";
import { subscribe } from "../realtime.js";
import { skeletonCard } from "../skeleton.js";
import {
  clearPendingListScrollY,
  exitSolo,
  installWorkOrderRouting,
  isSoloActive,
  openWorkOrderPage,
  openWorkOrderPageByNumber,
  renderSoloError,
  restoreListScrollY,
  takePendingSoloNumber,
} from "./workOrderRouting.js";
import {
  closeCombo,
  closeTechnicianResults,
  emptyTechnicianSelectionHtml,
  renderBody,
  renderTechnicianSearch,
  summaryHtml,
  technicianSelectionHtml,
} from "./workOrderCardHtml.js";
import {
  RECENT_LIMIT,
  SORT_STORAGE_KEY,
  SORT_VALUES,
  currentFilters,
  getShowAll,
  getSortDir,
  hasActiveFilters,
  invalidateFilterOptions,
  isFilterOptionsLoaded,
  listParams,
  loadFilterOptions,
  renderSortControl,
  resetFilterControls,
  setShowAll,
  setSortDir,
} from "./workOrderFilters.js";
import {
  ensureReferenceData,
  getAllItems,
  invalidateUsers,
} from "./workOrderReferenceData.js";
import {
  isAdminPlus,
  notesLogContentsHtml,
  hoursToMinutes,
  statusLabel,
  priorityBadgeClass,
  workOrderCardClass,
  modeLabel,
  placeMeta,
  assignedNames,
} from "./workOrderPresenters.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const statusFilter = document.getElementById("work-orders-status-filter");
const serviceTypeFilter = document.getElementById("work-orders-service-filter");
const priorityFilter = document.getElementById("work-orders-priority-filter");
const supervisorFilter = document.getElementById("work-orders-supervisor-filter");
const communityFilter = document.getElementById("work-orders-community-filter");
const scheduledDateFilter = document.getElementById("work-orders-date-filter");
const searchInput = document.getElementById("work-orders-search");
const searchBtn = document.getElementById("work-orders-search-btn");
const locationSearchInput = document.getElementById("work-orders-location-search");
const taskSearchInput = document.getElementById("work-orders-task-search");
const clearFiltersBtn = document.getElementById("work-orders-clear-filters");
const sortSeg = document.getElementById("work-orders-sort");
const exportMessage = document.getElementById("work-orders-export-message");
const moreEl = document.getElementById("work-orders-more");
// The filters/search block. Hidden in solo mode ("card page"), where the list
// holds one work order and there is nothing to filter.
const controlsSection = document.getElementById("work-orders-controls-section");

const importSection = document.getElementById("integrations-import-section");
const importFile = document.getElementById("wo-import-file");
const importBtn = document.getElementById("wo-import-btn");
const importMessage = document.getElementById("wo-import-message");
const netFacilitiesStatus = document.getElementById("wo-netfacilities-status");
const netFacilitiesEnrichBtn = document.getElementById("wo-netfacilities-enrich-btn");
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
const exportScope = document.getElementById("wo-export-scope");
const exportBtn = document.getElementById("wo-export-btn");
const exportClientBtn = document.getElementById("wo-export-client-btn");

let netFacilitiesPollingJobId = null;
// Work order id to expand once the list renders (set by a Mass Stage tree click).
let pendingFocusId = null;










// A second one-shot, deliberately independent of `pendingSoloNumber`: the solo
// lookup above returns before the archived-number prompt, so a caller that
// wants the "Work Order has been closed. Restore?" path needs its own flag.
// Consumed by the next `loadWorkOrders` -- the one `showPage` triggers on page
// entry -- as `checkArchivedSearch`. Set by `openWorkOrdersByNumberSearch`.
let pendingArchivedCheck = false;





const STATUS_CHANGED_EVENT = "work_order.status.changed";
const WORK_ORDERS_PAGE = "work-orders";

export function focusWorkOrder(workOrderId) {
  pendingFocusId = workOrderId;
}





































// --- list ----------------------------------------------------------------

// Incremented as each list load begins so a slower lookup from an older search
// cannot open a prompt after the operator has already typed something else.
let archivedSearchToken = 0;
let archivedSearchPromptOpen = false;

async function offerRestoreForExactArchivedSearch(number, token) {
  if (!isAdminPlus() || !number) return;

  let info;
  try {
    // Lookup uses the work-order identity rule (trimmed + case-insensitive), not
    // the list endpoint's substring match. An archived result is therefore an
    // exact match for the number currently in the search box.
    info = await apiLookupWorkOrder(number);
  } catch {
    return; // Courtesy lookup: a failure must not disturb the live list search.
  }

  const currentNumber = searchInput ? searchInput.value.trim() : "";
  if (
    token !== archivedSearchToken ||
    currentNumber.toLowerCase() !== number.toLowerCase() ||
    !info?.found ||
    !info.archived ||
    archivedSearchPromptOpen
  ) {
    return;
  }

  archivedSearchPromptOpen = true;
  try {
    const restore = await confirmDialog("Work Order has been closed.", {
      confirmText: "Restore",
      cancelText: "Close",
    });
    if (!restore) return;
    await apiRestoreWorkOrder(info.id);
    await loadWorkOrders();
  } catch (err) {
    setMessage(
      listMessage,
      friendlyError(err, "Could not restore that work order."),
      "error"
    );
  } finally {
    archivedSearchPromptOpen = false;
  }
}

export async function loadWorkOrders({
  refreshReferenceData = false,
  checkArchivedSearch = false,
  background = false,
} = {}) {
  // Any completed full load -- nav entry, filter change, Show all, Clear
  // filters, or this call itself -- genuinely satisfies a pending deferred
  // refresh, so this states a truth rather than defends against a bug.
  deferredListRefresh = false;

  // Promote the one-shot before the solo branch below can return early: a
  // number-search request arrives via `openWorkOrdersByNumberSearch`, which
  // never sets `pendingSoloNumber`, so the two paths cannot both be pending.
  if (pendingArchivedCheck) {
    pendingArchivedCheck = false;
    checkArchivedSearch = true;
  }

  // A pending card-page open wins: rendering the list first and the card
  // second is the same two renders racing, and whichever settled last would
  // win. nav.js calls this on page entry, so consuming the request here is the
  // one place both orderings can be serialized.
  const pendingSolo = takePendingSoloNumber();
  if (pendingSolo !== null) {
    const number = pendingSolo;
    // No list will be rendered on this path, so a remembered offset would sit
    // armed and fire on some later, unrelated render.
    clearPendingListScrollY();
    await ensureReferenceData({ refresh: refreshReferenceData });
    await openWorkOrderPageByNumber(number);
    return;
  }

  // Rendering the list is the definition of leaving the card page. Placed
  // here rather than at each call site so a path added later cannot forget it
  // and strand a /workorder_card/ URL over a list.
  exitSolo();

  const archivedLookupToken = ++archivedSearchToken;
  await ensureReferenceData({ refresh: refreshReferenceData });
  if (refreshReferenceData) invalidateFilterOptions();
  if (!isFilterOptionsLoaded()) {
    try {
      await loadFilterOptions();
    } catch {
      // The card list is still useful if the small options request fails. Keep
      // the existing selections/placeholders and retry on the next page entry.
      invalidateFilterOptions();
    }
  }
  if (exportBtn) exportBtn.hidden = !isAdminPlus();

  const filters = currentFilters();
  // The cap applies only to a completely unfiltered browse. Any advanced filter
  // is a search and must return the complete matching set.
  const capped = !hasActiveFilters() && !getShowAll() && !pendingFocusId;
  const limit = capped ? RECENT_LIMIT : null;
  try {
    let cards = await apiListWorkOrders({ ...listParams(), limit });
    if (pendingFocusId && !cards.some((c) => c.id === pendingFocusId)) {
      resetFilterControls();
      setShowAll(false);
      cards = await apiListWorkOrders({ limit: null, sort: getSortDir() });
    }
    renderCards(cards);
    renderMoreControl(capped, cards.length);
    setMessage(listMessage, "", "");
    // The list is on screen and final: the only point at which a remembered
    // offset means anything. Below the focus branch's `openWorkOrderPage`
    // return would be too late; above `renderCards` would be too early.
    restoreListScrollY();
    if (pendingFocusId) {
      const focused = cards.find((c) => c.id === pendingFocusId);
      pendingFocusId = null;
      if (focused) {
        // Cards are pages now. Expanding a row here would drop the user
        // mid-list at a card they then have to scroll to -- the thing this
        // change exists to remove. The list was fetched (and filters reset if
        // needed) above, so this is the id/number resolution as well.
        //
        // Returns before the archived-number prompt below: `checkArchivedSearch`
        // is only ever set by the number-search path, and a Mass Stage focus
        // never sets it.
        await openWorkOrderPage({ id: focused.id, number: focused.number });
        return;
      }
    }
    if (checkArchivedSearch) {
      await offerRestoreForExactArchivedSearch(filters.q, archivedLookupToken);
    }
  } catch (err) {
    // A socket-driven refresh must stay silent on failure (spec section 6):
    // leave the existing list exactly as it was rather than wipe it out from
    // under a user who never asked for this reload. The user-initiated path
    // (background=false) keeps today's error behavior unchanged.
    clearPendingListScrollY();
    if (background) return;
    listEl.innerHTML = "";
    if (moreEl) {
      moreEl.hidden = true;
      moreEl.innerHTML = "";
    }
    setMessage(listMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

// Called by nav.js on entry to the Integrations page. Owns the role gate on
// the NetFacilities/Langston University card and refreshes its session state
// -- the counterpart of the importSection/netFacilities handling loadWorkOrders
// used to do when the card lived on the Work Orders page.
export async function loadIntegrationsPage() {
  if (importSection) importSection.hidden = !isAdminPlus();
  if (!isAdminPlus()) return;
  void refreshNetFacilitiesCloudSession();
}

function renderCards(cards) {
  listEl.innerHTML = "";
  if (!cards.length) {
    listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    return;
  }
  cards.forEach((c) => listEl.appendChild(buildCard(c)));
}

// The "Show all" / "Show recent only" control beneath the list. Only meaningful on
// a plain (not search-driven) browse:
//  - a capped browse that filled the page (>= RECENT_LIMIT rows) may have more
//    beyond the cap, so offer "Show all". (An exact-RECENT_LIMIT total just reloads
//    the same rows on click -- harmless.)
//  - when showing all, offer "Show recent only" to return to the fast view.
//  - during a search, or a short capped page, show nothing.
function renderMoreControl(capped, shownCount) {
  if (!moreEl) return;
  if (getShowAll() && !hasActiveFilters()) {
    moreEl.innerHTML =
      `<button type="button" class="secondary-btn" id="wo-show-recent">Show recent only</button>`;
    moreEl.hidden = false;
  } else if (capped && shownCount >= RECENT_LIMIT) {
    moreEl.innerHTML = `<button type="button" id="wo-show-all">Show all work orders</button>`;
    moreEl.hidden = false;
  } else {
    moreEl.innerHTML = "";
    moreEl.hidden = true;
  }
}

if (moreEl) {
  moreEl.addEventListener("click", (event) => {
    if (event.target.id === "wo-show-all") {
      setShowAll(true);
      loadWorkOrders();
    } else if (event.target.id === "wo-show-recent") {
      setShowAll(false);
      loadWorkOrders();
    }
  });
}


// One work order changed. Rewrite that card's summary and status class, and,
// if the card is expanded and not held, its body too, so the badge and the
// body's status actions never disagree. A held card's editor is never
// touched -- the caller filters those out before calling this.
//
// A 404 means the work order left this user's view: archived, or unassigned
// from them. Either way the row goes. Only 404 removes a card; a network blip
// rejects without a `status` field and must leave the list alone.
async function refreshCardSummary(cardEl) {
  let detail;
  try {
    detail = await apiGetWorkOrder(cardEl.dataset.id);
  } catch (err) {
    if (err?.status !== 404) return;
    if (isSoloActive()) {
      // The card page's only card just left this user's view -- archived, or
      // unassigned from them. Wiping to the list's "No work orders match."
      // would leave a page with no card and no way back.
      renderSoloError("This work order is no longer available.");
      return;
    }
    cardEl.remove();
    if (!listEl.querySelector("details.wo-card")) {
      listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    }
    return;
  }
  const summary = cardEl.querySelector("summary.wo-summary");
  if (summary) summary.innerHTML = summaryHtml(detail);
  cardEl.className = workOrderCardClass(detail);

  // A badge alone is not enough: an expanded, non-held card still shows its
  // body, and the body's status actions (renderBody picks them off
  // detail.status) must not fall out of sync with the badge just repainted
  // above -- that is exactly the "Completed" badge over a live "Mark
  // Completed" button spec section 5 exists to prevent.
  //
  // `paintDetail` reuses the detail already fetched above rather than going
  // back to the server, so this stays one request and inherits no second
  // failure path. Held cards are never reached here -- both callers guard for
  // it -- and the re-check below closes the window where an editor opened
  // while the fetch was in flight.
  const bodyEl =
    cardEl.open && !isHeld(cardEl) ? cardEl.querySelector(".wo-body") : null;
  if (bodyEl) {
    paintDetail(detail, bodyEl, cardEl);
  } else {
    // Collapsed, held, or bodyless: drop the loaded flag so the next expansion
    // re-fetches instead of showing a body that is now stale.
    delete cardEl.dataset.loaded;
  }
}

// The four editor sections inside a card body. A card holding any of them open
// is "held": nothing refreshes it, because rewriting it would discard an unsaved
// note, a material quantity, labor hours, or a technician selection in progress.
// The technician combobox needs no entry -- it renders inside `.wo-edit-card`.
const EDITOR_SECTIONS =
  ".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section";

function isHeld(cardEl) {
  return Array.from(cardEl.querySelectorAll(EDITOR_SECTIONS)).some((s) => s.open);
}

function anyCardHeld() {
  if (!listEl) return false;
  return Array.from(listEl.querySelectorAll("details.wo-card")).some(isHeld);
}

// A full list refetch rebuilds every card (renderCards clears the list), so it
// must never run while an editor is open. Restore and reconnect are both rare,
// so deferring until the last hold clears costs nothing.
let deferredListRefresh = false;

function runOrDeferListRefresh() {
  if (isSoloActive()) {
    // A list refetch would replace the card page with the list -- silently,
    // with the card's URL still in the address bar. On a card page the only
    // row that can matter is the one on screen, so refresh that instead. A
    // held card defers exactly as it does in the list.
    const cardEl = listEl.querySelector("details.wo-card");
    if (!cardEl) return;
    if (isHeld(cardEl)) {
      cardEl.dataset.missedUpdate = "1";
      return;
    }
    void refreshCardSummary(cardEl);
    return;
  }
  if (anyCardHeld()) {
    deferredListRefresh = true;
    return;
  }
  deferredListRefresh = false;
  void loadWorkOrders({ background: true });
}

function buildCard(card, { onOpen, solo = false } = {}) {
  const el = document.createElement("details");
  el.className = workOrderCardClass(card);
  el.dataset.id = card.id;

  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  summary.innerHTML = summaryHtml(card);

  const body = document.createElement("div");
  body.className = "wo-body";
  body.innerHTML = skeletonCard({ lines: 3, hasHeader: false });

  el.appendChild(summary);
  el.appendChild(body);
  el.addEventListener("toggle", () => {
    if (el.open && !el.dataset.loaded) openDetail(card.id, body, el);
  });
  summary.addEventListener("click", (event) => {
    // Cards navigate rather than expand in place. `preventDefault` suppresses
    // the native toggle, and covers the keyboard path with it: Enter and Space
    // on a focused summary both dispatch a click, so there is no second path
    // to intercept. It also makes the card page's own card non-collapsible,
    // which is right -- there is nothing to collapse to.
    event.preventDefault();
    // Being *the* solo card is a property of this card, passed in by
    // `showSoloCard`. It used to read the module-global `soloActive`, which
    // silently broke every other list: `exitSolo` runs only inside
    // `loadWorkOrders`, so leaving the card page for the User Hub left the
    // flag set, and the hub's own cards (built by `mountWorkOrderList`, a
    // different container on a different page) went dead on click until the
    // Work Orders page was visited again.
    if (solo) return;
    if (onOpen) {
      onOpen(card);
      return;
    }
    void openWorkOrderPage({ id: card.id, number: card.number });
  });
  return el;
}

async function openDetail(workOrderId, bodyEl, cardEl) {
  try {
    paintDetail(await apiGetWorkOrder(workOrderId), bodyEl, cardEl);
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this work order."))}</p>`;
  }
}

// --- card page render ------------------------------------------------------




// Called from the Admin daily report (hubReport.js) for a *closed* row. A
// closed work order has no card page to open -- this list hides archived rows
// -- so route to its exact number instead and let the shipped "Work Order has
// been closed. Restore?" prompt fire. Resets every other control first, for the
// same reason the tile and graph entry points above do: a stale status or
// community filter left over from a previous visit would hide the very row we
// just navigated to. Does not fetch; `showPage("work-orders")` does that.
export function openWorkOrdersByNumberSearch(number) {
  resetFilterControls();
  if (searchInput) searchInput.value = number;
  setShowAll(false);
  pendingArchivedCheck = true;
}

// Called from the Admin Dashboard's pipeline tiles (hubAdmin.js). Sets the
// status filter and clears every other one, so the tile always lands on
// exactly that status's full company-wide list -- never a stale filter left
// over from the last time someone visited this page. Does not itself fetch:
// `showPage("work-orders")` (nav.js) already calls `loadWorkOrders` on every
// page entry, and that reads these dropdowns' live values.
export function openWorkOrdersFilteredByStatus(status) {
  resetFilterControls();
  if (statusFilter) statusFilter.value = status;
  setShowAll(false);
}

// Called from the User Hub's Graphs tab (hubGraphs.js via userHub.js), one
// click each on a donut slice, a legend row, or a card's "View all". Same
// shape as `openWorkOrdersFilteredByStatus` -- reset every other filter
// first, so a graph always lands on exactly that slice's full company-wide
// list and nothing carries over from a previous visit.
//
// All four set the same dropdowns the page's own controls do. `priority` is
// the exact-vendor-text "Priority" control, not the coarser high/medium
// "Priority level" one: the Graphs cards are cut from raw priority text, so
// their labels round-trip through this filter exactly.
export function openWorkOrdersFilteredByDistribution({
  community = null,
  serviceType = null,
  priority = null,
  status = null,
} = {}) {
  resetFilterControls();
  if (community && communityFilter) communityFilter.value = community;
  if (serviceType && serviceTypeFilter) serviceTypeFilter.value = serviceType;
  if (priority && priorityFilter) priorityFilter.value = priority;
  if (status && statusFilter) statusFilter.value = status;
  setShowAll(false);
}

// A second, independent card-list renderer for a container other than
// `#work-orders-list` -- the User Hub's "My Work Orders" tab (spec §4.4).
// Deliberately does NOT reuse listEl, the six delegated listeners, solo
// mode, held-card tracking, or the realtime subscriber: none of that
// machinery is reachable from a *collapsed* card (see this plan's Global
// Constraints for why), and a collapsed card is all this ever renders --
// a click hands off to `onOpen` instead of expanding in place, exactly like
// the standalone page's own collapsed cards already do via `openWorkOrderPage`.
//
// `lockedFilter` is forwarded to `apiListWorkOrders` as-is (the same
// {status, serviceType, supervisorId, assignedToId, community, priority,
// scheduledDate, q, mine, limit} shape that function already accepts). The
// technician's own scope needs no filter at all -- `apiListWorkOrders` is
// already scoped server-side per role (`_scoped_to_user`), so an unfiltered
// call already returns exactly "my work orders" for a Technician. The
// Supervisor caller passes `{ mine: true }` -- routed to me or assigned to
// me -- and the Admin caller passes nothing.
export function mountWorkOrderList({ container, lockedFilter = null, onOpen } = {}) {
  async function refresh() {
    container.innerHTML = skeletonCard({ lines: 1 }).repeat(3);
    let cards;
    try {
      cards = await apiListWorkOrders(lockedFilter || {});
    } catch (err) {
      container.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load work orders."))}</p>`;
      return;
    }
    container.innerHTML = "";
    if (!cards.length) {
      container.innerHTML = `<p class="hint">No work orders match.</p>`;
      return;
    }
    cards.forEach((card) => container.appendChild(buildCard(card, { onOpen })));
  }
  return { refresh };
}



// Paint one already-fetched work order into its card.
//
// Split out of `openDetail` so a caller holding a fresh detail can repaint
// without a second round-trip. That matters for more than bandwidth: a second
// fetch carries a second failure path, and `openDetail`'s is deliberately loud
// (it writes an error into the body). Loud is right when a user clicked to
// expand a card; it is wrong for a socket-driven refresh the user never asked
// for, and it would stick -- `dataset.loaded` only advances on success, so
// collapsing and re-expanding would not retry.
function paintDetail(detail, bodyEl, cardEl) {
  renderBody(detail, bodyEl);
  if (cardEl) void mountWorkOrderRequests(cardEl, detail, { items: getAllItems() });
  if (!cardEl) return;

  cardEl.dataset.loaded = "1";
  cardEl.className = workOrderCardClass(detail);
  const badge = cardEl.querySelector(".wo-status");
  if (badge) {
    badge.className = `wo-status wo-status-${detail.status}`;
    badge.textContent = statusLabel(detail.status);
  }
  // Priority is edited in this card's own editor, so the pill has to follow a
  // save the way the status badge does. Without this a work order just marked
  // Urgent would pulse its card outline while the pill beside it still read
  // the old level.
  const priorityPill = cardEl.querySelector(".wo-priority");
  if (priorityPill) {
    priorityPill.className = priorityBadgeClass(detail);
    priorityPill.textContent = detail.priority || "No priority";
  }
  const meta = cardEl.querySelector(".wo-meta");
  if (meta) {
    const place = placeMeta(detail);
    const technicianNames = assignedNames(detail);
    const assignee = technicianNames.length ? ` · ${technicianNames.join(", ")}` : "";
    meta.textContent = `${place ? place + " · " : ""}${detail.items.length} items${assignee}`;
  }
  // This repaint already reflects the latest data, so any missed socket
  // update while the card was held is now satisfied -- every repaint path
  // (Cancel, Save details, materials/labor actions, initial expansion)
  // routes through here.
  delete cardEl.dataset.missedUpdate;
}

// --- detail rendering ----------------------------------------------------



async function refreshCard(cardEl, reopenSelector = null) {
  const body = cardEl.querySelector(".wo-body");
  await openDetail(cardEl.dataset.id, body, cardEl);
  if (reopenSelector) {
    const section = cardEl.querySelector(reopenSelector);
    if (section) section.open = true;
  }
}

// --- add-material search (input delegation) ------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
  if (input.classList.contains("wo-tech-search")) {
    renderTechnicianSearch(input);
    return;
  }
  if (!input.classList.contains("ms-item-search")) return;
  const container = input.closest(".wo-add-item");
  const results = container.querySelector(".ms-item-results");
  delete container.dataset.itemId;
  delete container.dataset.materialRequestId;
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = filterRanked(
    getAllItems(),
    (it) => [it.name, it.barcode],
    q
  ).slice(0, 8);
  // No match means the catalogue has no row for what they typed, so offer to
  // report it. The work order travels with the request: fulfilling it later
  // logs the material back onto this job retroactively.
  const cardEl = input.closest(".wo-card");
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-action="pick-item" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>` +
      catalogueRequestPromptHtml({
        searchedText: input.value.trim(),
        workOrderId: cardEl ? cardEl.dataset.id : null,
        source: "work_orders",
      });
  results.hidden = false;
});

// --- actions (click delegation) ------------------------------------------

listEl.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;

  if (action === "pick-item") {
    const container = btn.closest(".wo-add-item");
    container.dataset.itemId = btn.dataset.itemId;
    delete container.dataset.materialRequestId;
    container.querySelector(".ms-item-search").value = btn.dataset.itemName;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    container.querySelector(".wo-item-qty").focus();
    return;
  }

  if (action === "pick-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    const technicianId = btn.dataset.technicianId;
    if (!list.querySelector(`[data-technician-id="${technicianId}"]`)) {
      list.querySelector(".wo-tech-empty")?.remove();
      list.insertAdjacentHTML(
        "beforeend",
        technicianSelectionHtml(technicianId, btn.dataset.technicianName)
      );
    }
    const input = picker.querySelector(".wo-tech-search");
    input.value = "";
    closeTechnicianResults(picker);
    input.focus();
    return;
  }

  if (action === "remove-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    btn.closest(".wo-tech-selected-row")?.remove();
    if (!list.querySelector(".wo-tech-selected-row")) {
      list.innerHTML = emptyTechnicianSelectionHtml();
    }
    picker.querySelector(".wo-tech-search")?.focus();
    return;
  }

  if (action === "toggle-combo") {
    const combo = btn.closest(".wo-combo");
    const list = combo.querySelector(".wo-combo-list");
    const opening = list.hidden;
    // Only one open at a time -- picking in one shouldn't leave another
    // combo's listbox stranded open behind it.
    listEl.querySelectorAll(".wo-combo").forEach((other) => {
      if (other !== combo) closeCombo(other);
    });
    list.hidden = !opening;
    btn.setAttribute("aria-expanded", String(opening));
    return;
  }

  if (action === "pick-combo-option") {
    const combo = btn.closest(".wo-combo");
    const nativeSelect = combo.querySelector(".wo-combo-native");
    const label = combo.querySelector(".wo-combo-trigger-label");
    nativeSelect.value = btn.dataset.value;
    label.textContent = btn.textContent;
    combo.querySelectorAll(".wo-combo-option").forEach((opt) => {
      opt.setAttribute("aria-selected", String(opt === btn));
    });
    closeCombo(combo);
    combo.querySelector(".wo-combo-trigger")?.focus();
    return;
  }

  if (action === "back-to-work-orders") {
    // Above the `.wo-card` lookup below: this control lives in the list but
    // outside any card, so the `if (!cardEl) return` guard would swallow it.
    if (window.history.state?.solo) {
      // We pushed this entry. Unwinding it keeps Back and Forward agreeing
      // with the button; `popstate` does the actual restore.
      window.history.back();
    } else {
      // A cold deep link: there is no entry of ours to pop, and calling
      // back() would leave the app. loadWorkOrders normalizes the URL itself
      // (exitSolo).
      void loadWorkOrders();
    }
    return;
  }

  if (action === "open-netfacilities-wo") {
    // Placeholder pending real NetFacilities integration on this button --
    // same destination the domain layer's work_order_task_fallback generates
    // (app/domain/work_orders.py) for an imported task with no real one yet.
    const url = `https://system.netfacilities.com/tools/viewworkorders/${encodeURIComponent(btn.dataset.number)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "start-tracking-wo") {
      await apiStartWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "stop-tracking-wo") {
      const stopped = await apiStopWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
      // Stopping the last clock on a job moves it On-Hold by itself. Without
      // saying so, the badge changing on its own reads as something going
      // wrong. Chosen from the refreshed row, so the message and the server
      // cannot disagree. Re-queried after the refresh: renderBody replaced the
      // old element.
      if (stopped?.status === "on_hold") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Work stopped. Nobody is charging, so this is now On-Hold.",
          "success"
        );
      }
    } else if (action === "notify-supervisor-wo") {
      let finished;
      try {
        finished = await apiCompleteWorkOrder(workOrderId);
      } catch (err) {
        // A co-worker's clock is still running: this is not a failure to
        // report inline, it's a rule the tapper needs to act on -- go find
        // that person -- so it gets the same pop-up treatment as the other
        // hard stop above rather than the quiet inline .wo-message text.
        if (
          err?.status === 400 &&
          err.detail === "All Users must Stop Charging before a Supervisor can be notified."
        ) {
          await messageDialog(err.detail);
          return;
        }
        throw err;
      }
      await refreshCard(cardEl);
      // A Technician's finish lands Ready to Complete, so the badge that
      // appears a moment later would otherwise read as a failed save. Chosen
      // from the row the server returned rather than from the role.
      if (finished?.status === "ready_to_complete") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Sent to your supervisor for review.",
          "success"
        );
      }
    } else if (action === "send-back-wo") {
      // Rejection means "go finish the job", so the crew is live again rather
      // than paused -- which keeps On-Hold meaning purely "nobody is on it".
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "hold-assigned-wo") {
      await apiHoldWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "resume-assigned-wo") {
      await apiResumeWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "complete-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "completed" });
      await refreshCard(cardEl);
    } else if (action === "review-wo") {
      if (!(await confirmDialog("Are you sure this work order is ready for Review?"))) return;
      await apiUpdateWorkOrder(workOrderId, { status: "review" });
      await refreshCard(cardEl);
    } else if (action === "reopen-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "archive-wo") {
      if (!(await confirmDialog(
        "Archive this work order? It will leave the active list and can be restored from History."
      ))) return;
      await apiArchiveWorkOrder(workOrderId);
      await loadWorkOrders();
    } else if (action === "cancel-edit") {
      // Re-fetch to throw away drafts and return the Edit details card to its
      // default collapsed state with the saved values restored.
      await refreshCard(cardEl);
    } else if (action === "save-details") {
      const body = cardEl.querySelector(".wo-body");
      // Only the fields the editor actually rendered: the legacy
      // community/building/unit inputs are absent on an imported work order,
      // and sending them as null would wipe values the editor never showed.
      const value = (selector) => {
        const el = body.querySelector(selector);
        return el ? el.value.trim() || null : undefined;
      };
      const patch = {
        status: value(".wo-edit-status"),
        location: value(".wo-edit-location"),
        service_type: value(".wo-edit-service-type"),
        schedule_date: value(".wo-edit-schedule-date"),
        output_to: value(".wo-edit-output-to"),
        vendor_assignee: value(".wo-edit-vendor"),
        description: value(".wo-edit-description"),
        priority: value(".wo-edit-priority"),
        supervisor_id: body.querySelector(".wo-edit-supervisor")?.value || null,
        expected_supervisor_id:
          body.querySelector(".wo-edit")?.dataset.originalSupervisorId || null,
        assigned_to_ids: Array.from(body.querySelectorAll(".wo-tech-selected-row")).map(
          (row) => row.dataset.technicianId
        ),
      };
      Object.keys(patch).forEach((k) => patch[k] === undefined && delete patch[k]);
      await apiUpdateWorkOrder(workOrderId, patch);
      await refreshCard(cardEl);
    } else if (action === "save-notes") {
      const notesInput = cardEl.querySelector(".wo-notes-input");
      const notesMessage = cardEl.querySelector(".wo-notes-message");
      const notes = notesInput.value.trim() || null;
      setMessage(notesMessage, "", "");
      if (!notes) {
        setMessage(notesMessage, "Enter a note before saving.", "error");
        return;
      }
      const updated = await apiUpdateWorkOrder(workOrderId, { notes });
      notesInput.value = "";
      const notesLog = cardEl.querySelector(".wo-notes-log");
      if (notesLog) notesLog.innerHTML = notesLogContentsHtml(updated.notes);
      setMessage(notesMessage, "Note saved.", "success");
      const notesSection = cardEl.querySelector(".wo-notes-section");
      if (notesSection) notesSection.open = false;
    } else if (action === "add-labor") {
      const section = btn.closest(".wo-labor-section");
      const technicianId = section.querySelector(".wo-labor-technician")?.value;
      const minutes = hoursToMinutes(section.querySelector(".wo-new-labor-hours")?.value);
      if (!technicianId) {
        setMessage(msg, "Assign and select a technician first.", "error");
        return;
      }
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiAddWorkOrderLabor(workOrderId, { technicianId, minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "edit-labor") {
      const row = btn.closest(".wo-labor-entry");
      const minutes = hoursToMinutes(row.querySelector(".wo-labor-hours")?.value);
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderLabor(workOrderId, row.dataset.laborId, { minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "remove-labor") {
      const row = btn.closest(".wo-labor-entry");
      if (!(await confirmDialog("Remove this labor entry from the work order?"))) return;
      await apiDeleteWorkOrderLabor(workOrderId, row.dataset.laborId);
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "add-item") {
      const container = btn.closest(".wo-add-item");
      const itemId = container.dataset.itemId;
      const qty = parseFloat(container.querySelector(".wo-item-qty").value);
      if (!itemId) {
        setMessage(msg, "Search and pick an item first.", "error");
        return;
      }
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      const addedLine = await apiAddWorkOrderItem(workOrderId, {
        itemId,
        quantity: qty,
        materialRequestId: container.dataset.materialRequestId || null,
      });
      delete container.dataset.materialRequestId;
      await refreshCard(cardEl, ".wo-materials-section");
      const refreshedMessage = cardEl.querySelector(".wo-message");
      if (Number(addedLine.item_quantity) < 0) {
        setMessage(refreshedMessage, "Item added. Please re-count stock.", "error");
      } else {
        setMessage(refreshedMessage, "Item added.", "success");
      }
    } else if (action === "edit-item") {
      const row = btn.closest(".wo-item");
      const qty = parseFloat(row.querySelector(".wo-line-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderItem(workOrderId, row.dataset.woItemId, { quantity: qty });
      await refreshCard(cardEl, ".wo-materials-section");
    } else if (action === "remove-item") {
      const row = btn.closest(".wo-item");
      if (!(await confirmDialog("Remove this material from the work order?"))) return;
      await apiDeleteWorkOrderItem(workOrderId, row.dataset.woItemId);
      await refreshCard(cardEl, ".wo-materials-section");
    }
  } catch (err) {
    if (
      err?.status === 409 &&
      typeof err.detail === "string" &&
      err.detail.startsWith("This Work Order was already assigned to ")
    ) {
      await messageDialog(err.detail);
      window.location.reload();
      return;
    }
    if (msg) setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
});

listEl.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (event.target.classList.contains("wo-tech-search")) {
    closeTechnicianResults(event.target.closest(".wo-tech-picker"));
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) closeCombo(combo);
});

listEl.addEventListener("focusout", (event) => {
  const picker = event.target.closest(".wo-tech-picker");
  if (picker) {
    setTimeout(() => {
      if (!picker.contains(document.activeElement)) closeTechnicianResults(picker);
    }, 0);
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) {
    setTimeout(() => {
      if (!combo.contains(document.activeElement)) closeCombo(combo);
    }, 0);
  }
});

// --- Inline line-billing editor (Admin/Owner) ----------------------------
//
// The editor UI is shared with History (`views/billingEditor.js`); here we
// just supply the line's numbers and how to persist the change, then refresh
// the card. The "Edit charge" button only renders for those who may see cost,
// so no extra role check is needed.
listEl.addEventListener("click", (event) => {
  const editBtn = event.target.closest(".wo-edit-charge-btn");
  if (!editBtn) return;

  const cell = editBtn.closest(".wo-line-charge");
  const row = editBtn.closest(".wo-item");
  const cardEl = editBtn.closest(".wo-card");
  if (!cell || !row || !cardEl) return;

  const workOrderId = cardEl.dataset.id;
  const woItemId = row.dataset.woItemId;
  openBillingEditor(cell, {
    quantity: Number(cell.dataset.quantity),
    billable: Number(cell.dataset.billable),
    onSave: async (value) => {
      await apiSetWorkOrderItemBilling(workOrderId, woItemId, value);
      await refreshCard(cardEl, ".wo-materials-section");  // repaint the card (line charge + total)
    },
  });
});

// Mode select change.
listEl.addEventListener("change", async (event) => {
  const sel = event.target;
  if (!sel.classList.contains("wo-mode-select")) return;
  const cardEl = sel.closest(".wo-card");
  if (!cardEl) return;
  const msg = cardEl.querySelector(".wo-message");
  try {
    await apiUpdateWorkOrder(cardEl.dataset.id, { entry_mode: sel.value });
    if (msg) setMessage(msg, `New entries will be ${modeLabel(sel.value).toLowerCase()}.`, "success");
  } catch (err) {
    if (msg) setMessage(msg, friendlyError(err, "Could not switch mode."), "error");
  }
});

// --- NetFacilities enrichment (Admin+) -----------------------------------
//
// One capability drives this card: the caller's own cloud session. The Enrich
// button below and the sign-in block that follows read the same
// `/cloud/session` response, so there is no second, parallel view of state.

const NETFACILITIES_SESSION_POLL_MS = 3000;

function netFacilitiesCountsMessage(job) {
  const counts = job && job.counts;
  if (!counts) return "NetFacilities enrichment did not return result counts.";
  return [
    `checked ${counts.fetched} of ${counts.candidates} candidate${counts.candidates === 1 ? "" : "s"}`,
    `${counts.descriptions_updated} Task/Symptom updated`,
    `${counts.priorities_updated} Priority updated`,
    `${counts.unchanged} unchanged`,
    `${counts.not_found} not found`,
    `${counts.permission_denied} permission denied`,
    `${counts.other_failures} other failure${counts.other_failures === 1 ? "" : "s"}`,
  ].join(" · ");
}

// Pure: one job snapshot -> the line the card shows and its message kind.
function describeNetFacilitiesJob(job) {
  if (job.state === "queued" || job.state === "running") {
    const currentRequest = job.current_work_order_number
      ? ` Currently requesting work order ${job.current_work_order_number}.`
      : "";
    return { text: `Seeking Task/Symptom and Priority in NetFacilities…${currentRequest}`, kind: "" };
  }
  if (job.state === "completed") {
    return { text: `NetFacilities enrichment completed: ${netFacilitiesCountsMessage(job)}.`, kind: "success" };
  }
  if (job.state === "authentication_required") {
    return {
      text: "NetFacilities authentication is missing or expired. Log in to NetFacilities, then click Import Tasks and Priority.",
      kind: "error",
    };
  }
  if (job.state === "timed_out") {
    return { text: `NetFacilities enrichment timed out with partial results: ${netFacilitiesCountsMessage(job)}.`, kind: "error" };
  }
  if (job.state === "cancelled") {
    return { text: "NetFacilities enrichment stopped when the app shut down.", kind: "error" };
  }
  return {
    text: "NetFacilities enrichment failed without changing unapproved work-order fields. Try again or log in again.",
    kind: "error",
  };
}

function renderNetFacilitiesJob(job) {
  if (!job || !netFacilitiesStatus) return;
  const described = describeNetFacilitiesJob(job);
  setMessage(netFacilitiesStatus, described.text, described.kind);
}

async function pollNetFacilitiesJob(jobId) {
  if (!jobId || netFacilitiesPollingJobId === jobId) return;
  netFacilitiesPollingJobId = jobId;
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    while (netFacilitiesPollingJobId === jobId) {
      const job = await apiGetNetFacilitiesEnrichment(jobId);
      renderNetFacilitiesJob(job);
      if (job.state !== "queued" && job.state !== "running") {
        if (job.state === "completed" || job.state === "timed_out") {
          invalidateUsers();
          invalidateFilterOptions();
          await loadWorkOrders();
        }
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not check NetFacilities enrichment progress."), "error");
    }
  } finally {
    if (netFacilitiesPollingJobId === jobId) netFacilitiesPollingJobId = null;
    // Re-enable the button directly rather than through a cloud-session
    // refresh, which would overwrite the result line the user just earned.
    if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = false;
  }
}

async function runNetFacilitiesEnrichment() {
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    const job = await apiStartNetFacilitiesEnrichment();
    renderNetFacilitiesJob(job);
    await pollNetFacilitiesJob(job.job_id);
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not start NetFacilities enrichment. Log in to NetFacilities, then try again."), "error");
    }
  }
}

if (netFacilitiesEnrichBtn) {
  netFacilitiesEnrichBtn.addEventListener("click", runNetFacilitiesEnrichment);
}


// --- Per-user NetFacilities cloud sign-in (Admin+, spec D2, D3, D7) -------
//
// Independent of the local flow above: any authorized user, on any device,
// signs into NetFacilities through a Steel cloud browser instead of the
// owner's Windows machine. Only rendered when the backend reports the
// capability as available (NETFACILITIES_CLOUD_AUTH_ENABLED and its
// prerequisites -- see cloud_config.py).

let netFacilitiesCloudPollTimer = null;

async function refreshNetFacilitiesCloudSession() {
  let capability;
  try {
    capability = await apiGetNetFacilitiesCloudSession();
  } catch {
    capability = null;
  }
  updateNetFacilitiesCloudControls(capability);
  return capability;
}

function updateNetFacilitiesCloudControls(capability) {
  const available = Boolean(capability && capability.available);
  const cloudStatus = capability && capability.status;
  const awaitingSignIn = Boolean(cloudStatus && cloudStatus.state === "awaiting_sign_in");
  const signedIn = Boolean(cloudStatus && cloudStatus.state === "signed_in");
  // E8: the fallback appears only when a capture is sitting unconsumed --
  // the chain normally consumes it before the next poll lands.
  const hasUnconsumedCsv = signedIn
    && Boolean(cloudStatus.last_download_filename)
    && !cloudStatus.capture_consumed;
  const chainStage = cloudStatus ? cloudStatus.chain_stage : null;

  if (netFacilitiesCloudSignInBtn) {
    netFacilitiesCloudSignInBtn.hidden = !available || awaitingSignIn || signedIn;
  }
  if (netFacilitiesCloudCancelBtn) {
    netFacilitiesCloudCancelBtn.hidden = !(awaitingSignIn || signedIn);
  }
  if (netFacilitiesCloudImportDownloadBtn) {
    netFacilitiesCloudImportDownloadBtn.hidden = !hasUnconsumedCsv;
  }
  // The Enrich button is driven by this one capability: enrichment runs
  // through the caller's own saved cloud session or not at all.
  if (netFacilitiesEnrichBtn) {
    netFacilitiesEnrichBtn.hidden = !available;
    netFacilitiesEnrichBtn.disabled = !(available && capability.has_saved_session)
      || Boolean(netFacilitiesPollingJobId);
  }
  // A job's own result line owns the status while it is polling.
  if (netFacilitiesStatus && !awaitingSignIn && !netFacilitiesPollingJobId) {
    if (!available) {
      setMessage(netFacilitiesStatus, capability ? capability.message : "NetFacilities status is unavailable. CSV import still works normally.", "");
    } else if (chainStage === "importing") {
      setMessage(netFacilitiesStatus, `Importing ${cloudStatus.last_download_filename}…`, "");
    } else if (chainStage === "imported" || chainStage === "enriching") {
      setMessage(netFacilitiesStatus, `${importSummary(cloudStatus.import_result)} Starting Task/Symptom and Priority…`, "success");
    } else if (chainStage === "done") {
      // The reconcile counts ride along in import_result, so this line and a
      // clicked import's line can never tell two different stories.
      setMessage(netFacilitiesStatus, `${importSummary(cloudStatus.import_result)} ${cloudStatus.enrichment_job_id ? "Enrichment is running." : "Enrichment is busy — click Import Tasks and Priority when it frees up."}`, "success");
    } else if (chainStage === "failed") {
      setMessage(netFacilitiesStatus, `${cloudStatus.import_error || "That import did not finish."} You are still signed in — export the right CSV in the NetFacilities window and it will import automatically.`, "error");
    } else if (signedIn) {
      if (hasUnconsumedCsv) {
        setMessage(netFacilitiesStatus, `Saved ${cloudStatus.last_download_filename}. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.`, "success");
      } else {
        setMessage(netFacilitiesStatus, "NetFacilities is open and logged in. Export the work-order CSV in that window — it imports and enriches on its own.", "success");
      }
    } else if (capability.has_saved_session) {
      setMessage(netFacilitiesStatus, "Saved NetFacilities login is ready. Choose a downloaded CSV to import it and seek Task/Symptom and Priority, or log in to export a fresh one.", "success");
    } else {
      setMessage(netFacilitiesStatus, capability.message, "");
    }
  }

  const chainRunning = Boolean(cloudStatus && ["importing", "imported", "enriching"].includes(cloudStatus.chain_stage));
  const shouldPoll = available && (awaitingSignIn || signedIn || chainRunning);
  if (shouldPoll && !netFacilitiesCloudPollTimer) {
    netFacilitiesCloudPollTimer = setInterval(
      refreshNetFacilitiesCloudSession,
      NETFACILITIES_SESSION_POLL_MS,
    );
  } else if (!shouldPoll && netFacilitiesCloudPollTimer) {
    clearInterval(netFacilitiesCloudPollTimer);
    netFacilitiesCloudPollTimer = null;
  }

  maybeHandleChainCompletion(cloudStatus).catch(() => {});
}

// One-shot handling of a finished chain observed through the session poll:
// reload the list the import changed, then hand the status line to the
// enrichment job's own poller. Keyed by attempt and stage so the poll (or a
// page re-entry) does not replay it, and set eagerly by the manual button,
// which already did both itself.
let handledChainCompletion = null;

async function maybeHandleChainCompletion(cloudStatus) {
  if (!cloudStatus || !["done", "failed"].includes(cloudStatus.chain_stage)) return;
  const key = `${cloudStatus.attempt_id}:${cloudStatus.chain_stage}`;
  if (handledChainCompletion === key) return;
  handledChainCompletion = key;
  if (cloudStatus.chain_stage !== "done") return;
  invalidateUsers();
  invalidateFilterOptions();
  await loadWorkOrders();
  if (cloudStatus.enrichment_job_id) {
    await pollNetFacilitiesJob(cloudStatus.enrichment_job_id);
  }
}

async function startNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = true;
  try {
    const status = await apiStartNetFacilitiesCloudAuthentication();
    if (status && status.live_view_url) {
      window.open(status.live_view_url, "_blank", "noopener");
    }
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not open a NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function cancelNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = true;
  try {
    await apiCancelNetFacilitiesCloudAuthentication();
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not close the NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function importNetFacilitiesCloudDownload() {
  if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    // The route now runs the whole chain the automatic path does (E8) --
    // import, session close, enrichment -- and returns the ceremony status,
    // not a bare import summary.
    const status = await apiImportNetFacilitiesCloudDownload();
    handledChainCompletion = `${status.attempt_id}:${status.chain_stage}`;
    if (status.chain_stage === "failed") {
      setMessage(importMessage, status.import_error || "Could not import the downloaded CSV.", "error");
    } else {
      await afterWorkOrderImport(status.import_result, { chainOwnsEnrichment: true });
      if (status.enrichment_job_id) {
        await pollNetFacilitiesJob(status.enrichment_job_id);
      }
    }
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
  } finally {
    if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

if (netFacilitiesCloudSignInBtn) {
  netFacilitiesCloudSignInBtn.addEventListener("click", startNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudCancelBtn) {
  netFacilitiesCloudCancelBtn.addEventListener("click", cancelNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudImportDownloadBtn) {
  netFacilitiesCloudImportDownloadBtn.addEventListener("click", importNetFacilitiesCloudDownload);
}

// --- CSV import (Admin+) --------------------------------------------------

// What one import did, as clauses joined by " · ", each appearing only when its
// count is non-zero. `supervisors_matched` counts new work orders only, so the
// match count never exceeds `created`.
function importSummary(r) {
  const clauses = [];
  if (r.created) {
    const noun = r.created === 1 ? "new work order" : "new work orders";
    clauses.push(`${r.created} ${noun}`);
    clauses.push(`${r.supervisors_matched} with a supervisor name match`);
  }
  if (!clauses.length) return "No new work orders.";
  return `${clauses.join(" · ")}.`;
}

// Everything that follows a successful import, whether the CSV was uploaded
// or captured from the cloud window: summary, list reload, then enrichment
// through the caller's own cloud session when they have one.
// `chainOwnsEnrichment` is true for the cloud path, where the server's
// capture chain starts enrichment itself (E8). Enriching again here would
// collide with that job, burn the chain's retry budget, and narrate a
// queue that is really our own duplicate.
async function afterWorkOrderImport(r, { chainOwnsEnrichment = false } = {}) {
  // Only the new work orders are worth reporting: re-imported numbers keep
  // their own routing, and rows the import passed over changed nothing.
  setMessage(importMessage, importSummary(r), "success");
  // Reset caches so a re-import reflects fresh data, then reload the list.
  invalidateUsers();
  invalidateFilterOptions();
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesCloudSession();
  const cloudStatus = capability && capability.status;
  if (
    !chainOwnsEnrichment
    && capability
    && capability.available
    && (capability.has_saved_session || (cloudStatus && cloudStatus.state === "signed_in"))
  ) {
    await runNetFacilitiesEnrichment();
  }
}

async function handleImport() {
  const file = importFile.files && importFile.files[0];
  if (!file) return;
  setMessage(importMessage, "Importing…", "");
  importBtn.disabled = true;
  try {
    const r = await apiImportWorkOrders(file);
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import that file."), "error");
  } finally {
    importBtn.disabled = false;
    importFile.value = "";  // allow re-selecting the same file
  }
}

if (importBtn) importBtn.addEventListener("click", () => importFile && importFile.click());
if (importFile) importFile.addEventListener("change", handleImport);

// --- CSV export (Admin+) --------------------------------------------------

// Label for the status the export dropdown is set to, for the result message.
function exportScopeLabel(scope) {
  const option = exportScope && [...exportScope.options].find(o => o.value === scope);
  return option ? option.textContent : scope;
}

async function downloadExport({ scope, variant, filters = {}, button, messageEl, label }) {
  setMessage(messageEl, "Preparing export…", "");
  if (button) button.disabled = true;
  try {
    const { blob, filename } = await apiExportWorkOrders(scope, { variant, filters });
    // An empty scope still returns a header-only file; say so rather than
    // handing over a CSV that looks broken.
    const headerOnly = blob.size > 0 && (await blob.text()).trim().split("\n").length <= 1;
    // Anchor + object URL is the only way to name a downloaded blob; revoke on
    // the next tick so the click has already consumed the URL.
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setMessage(
      messageEl,
      headerOnly
        ? `No work orders matched ${label} — downloaded an empty file.`
        : `Exported ${label} to ${filename}.`,
      headerOnly ? "" : "success",
    );
  } catch (err) {
    setMessage(messageEl, friendlyError(err, "Could not export work orders."), "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function handleFilteredExport() {
  const filters = currentFilters();
  await downloadExport({
    scope: filters.status || "all",
    variant: "full",
    filters,
    button: exportBtn,
    messageEl: exportMessage,
    label: "the current Work Orders filters",
  });
}

async function handleClientExport() {
  const scope = exportScope ? exportScope.value : "all";
  await downloadExport({
    scope,
    variant: "client",
    button: exportClientBtn,
    messageEl: importMessage,
    label: `${exportScopeLabel(scope)} client receipts`,
  });
}

if (exportBtn) exportBtn.addEventListener("click", handleFilteredExport);
if (exportClientBtn) exportClientBtn.addEventListener("click", handleClientExport);

// --- filter / search controls --------------------------------------------

// #16: search live-updates as you type (250 ms debounce), matching the
// History work-order filter so the two sibling pages behave the same way.
// The Search button and Enter stay as redundant explicit triggers -- nothing
// is removed, so no one loses the click-to-search workflow.
let woSearchDebounce = null;
function runWorkOrderNumberSearch() {
  loadWorkOrders({ checkArchivedSearch: true });
}

if (searchBtn) searchBtn.addEventListener("click", runWorkOrderNumberSearch);
if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(woSearchDebounce);
    woSearchDebounce = setTimeout(runWorkOrderNumberSearch, 250);
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(woSearchDebounce);
      runWorkOrderNumberSearch();
    }
  });
}

// The Location and Task/symptom keyword searches reuse the number bar's
// 250 ms debounce + immediate Enter, but run plain loadWorkOrders():
// checkArchivedSearch stays a number-search-only behavior, because only an
// exact number can name an archived work order.
function wireKeywordSearch(input) {
  if (!input) return () => {};
  let debounce = null;
  const run = () => loadWorkOrders();
  input.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(run, 250);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(debounce);
      run();
    }
  });
  return () => clearTimeout(debounce);
}
const cancelLocationSearchDebounce = wireKeywordSearch(locationSearchInput);
const cancelTaskSearchDebounce = wireKeywordSearch(taskSearchInput);
[statusFilter, serviceTypeFilter, priorityFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
  if (!control) return;
  control.addEventListener("change", () => {
    setShowAll(false);
    loadWorkOrders();
  });
});

if (sortSeg) {
  renderSortControl();
  sortSeg.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-sort]");
    if (!btn || !SORT_VALUES.has(btn.dataset.sort) || btn.dataset.sort === getSortDir()) return;
    setSortDir(btn.dataset.sort);
    try {
      localStorage.setItem(SORT_STORAGE_KEY, getSortDir());
    } catch {
      // Best effort only.
    }
    renderSortControl();
    loadWorkOrders();
  });
}

if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener("click", () => {
    clearTimeout(woSearchDebounce);
    cancelLocationSearchDebounce();
    cancelTaskSearchDebounce();
    resetFilterControls();
    setShowAll(false);
    loadWorkOrders();
  });
}

// Status invalidations for the card list. Like Admin Review, this refreshes only
// while its own page is active -- an inactive page needs no dirty flag because
// nav.js already performs a fresh REST load on entry (static/views/nav.js:154).
//
// An event for a work order that is not on screen is ignored. Chasing it with a
// list refetch would mean every technician's client reloading the whole list
// every time anyone changed a status anywhere. A work order newly *appearing*
// for someone is a membership change, which arrives as a null id instead.
subscribe(STATUS_CHANGED_EVENT, ({ activePage, envelope, reason }) => {
  if (activePage !== WORK_ORDERS_PAGE) return;
  if (!listEl) return;

  // A null id is a membership command (restore) and a reconnect means events
  // were missed while the socket was down. Both mean "the list itself may be
  // wrong", which only a refetch can settle -- deciding locally would duplicate
  // the server's ordering, row cap and filter semantics.
  if (reason === "reconnect" || !envelope?.id) {
    runOrDeferListRefresh();
    return;
  }

  const cardEl = listEl.querySelector(`details.wo-card[data-id="${envelope.id}"]`);
  if (!cardEl) return;
  if (isHeld(cardEl)) {
    // Catch up when the editor closes rather than yanking input away mid-edit.
    cardEl.dataset.missedUpdate = "1";
    return;
  }
  return refreshCardSummary(cardEl);
});

// `toggle` does not bubble, so this listens in the capture phase -- a delegated
// bubble-phase listener here would silently never fire.
if (listEl) {
  listEl.addEventListener(
    "toggle",
    () => {
      if (deferredListRefresh && !anyCardHeld()) {
        // Route through the single function that knows a socket-driven
        // refresh must be silent -- do not duplicate its background flag here.
        runOrDeferListRefresh();
        return;
      }

      const cards = Array.from(listEl.querySelectorAll("details.wo-card"));
      for (const cardEl of cards) {
        if (cardEl.dataset.missedUpdate !== "1" || isHeld(cardEl)) continue;
        delete cardEl.dataset.missedUpdate;
        void refreshCardSummary(cardEl);
      }
    },
    true
  );
}

// Routing's three list dependencies, handed over once. Placed last so every
// function it names is defined.
installWorkOrderRouting({ buildCard, paintDetail, loadWorkOrders });
