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
  apiLookupWorkOrder,
  apiRestoreWorkOrder,
} from "../api.js";
import {
  escapeHtml,
  friendlyError,
} from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";

import { mountWorkOrderRequests } from "./workOrderRequests.js";

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
  renderBody,
  summaryHtml,
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
} from "./workOrderReferenceData.js";
import {
  isAdminPlus,
  statusLabel,
  priorityBadgeClass,
  workOrderCardClass,
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
const moreEl = document.getElementById("work-orders-more");
// The filters/search block. Hidden in solo mode ("card page"), where the list
// holds one work order and there is nothing to filter.
const controlsSection = document.getElementById("work-orders-controls-section");

// The Work Orders page's own export button. The Integrations page controls
// live in workOrderIntegrations.js; this one is hidden on every list load.
const exportBtn = document.getElementById("wo-export-btn");

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

export async function refreshCard(cardEl, reopenSelector = null) {
  const body = cardEl.querySelector(".wo-body");
  await openDetail(cardEl.dataset.id, body, cardEl);
  if (reopenSelector) {
    const section = cardEl.querySelector(reopenSelector);
    if (section) section.open = true;
  }
}

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
