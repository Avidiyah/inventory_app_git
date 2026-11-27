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
import { morphInto } from "../morph.js";
import { patchBodyLive } from "./workOrderLiveBody.js";

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
  takePendingSoloId,
  takePendingSoloNumber,
} from "./workOrderRouting.js";
import {
  peekHtml,
  renderBody,
  summaryHtml,
} from "./workOrderCardHtml.js";
import {
  SORT_STORAGE_KEY,
  SORT_VALUES,
  currentFilters,
  getSortDir,
  invalidateFilterOptions,
  isFilterOptionsLoaded,
  listParams,
  loadFilterOptions,
  renderSortControl,
  resetFilterControls,
  selectFilterValue,
  setSortDir,
} from "./workOrderFilters.js";
import {
  hideResultCount,
  installFilterChips,
  renderFilterChips,
  renderResultCount,
} from "./workOrderFilterChips.js";
import {
  ensureReferenceData,
  ensureUsers,
  getAllItems,
} from "./workOrderReferenceData.js";
import {
  isAdminPlus,
  isSupervisorPlus,
  statusLabel,
  workOrderCardClass,
} from "./workOrderPresenters.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const mineFilter = document.getElementById("work-orders-mine-filter");
const statusFilter = document.getElementById("work-orders-status-filter");
const serviceTypeFilter = document.getElementById("work-orders-service-filter");
const priorityFilter = document.getElementById("work-orders-priority-filter");
const supervisorFilter = document.getElementById("work-orders-supervisor-filter");
const technicianFilterField = document.getElementById("work-orders-technician-field");
const technicianFilter = document.getElementById("work-orders-technician-filter");
const communityFilter = document.getElementById("work-orders-community-filter");
const scheduledDateFilter = document.getElementById("work-orders-date-filter");
const searchInput = document.getElementById("work-orders-search");
const clearFiltersBtn = document.getElementById("work-orders-clear-filters");
const scopeSeg = document.getElementById("work-orders-scope");
const filtersCountEl = document.getElementById("work-orders-filters-count");
const filtersBtn = document.getElementById("work-orders-filters-btn");
const filtersPanel = document.getElementById("work-orders-advanced");
const sortSeg = document.getElementById("work-orders-sort");
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

// Exported so workOrderRetry.js can piggyback a reconnect check on the same
// socket subscription rather than opening a second one just for that.
export const STATUS_CHANGED_EVENT = "work_order.status.changed";
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
  const pendingSoloId = takePendingSoloId();
  if (pendingSolo !== null) {
    const number = pendingSolo;
    // No list will be rendered on this path, so a remembered offset would sit
    // armed and fire on some later, unrelated render.
    clearPendingListScrollY();
    // Not awaited: the open below paints its skeleton at once and waits for
    // this refresh's users list (shared in flight) together with the card.
    void ensureReferenceData({ refresh: refreshReferenceData });
    // With an id in hand the card is fetched directly: the number path
    // resolves through the live list, which never lists an SMR order.
    if (pendingSoloId) await openWorkOrderPage({ id: pendingSoloId, number });
    else await openWorkOrderPageByNumber(number);
    return;
  }

  // Rendering the list is the definition of leaving the card page. Placed
  // here rather than at each call site so a path added later cannot forget it
  // and strand a /workorder_card/ URL over a list.
  exitSolo();

  const archivedLookupToken = ++archivedSearchToken;
  // The cards need neither the catalogue nor the dropdown choices, so the list
  // is requested at once and both load beside it. ensureUsers() below shares
  // the users request ensureReferenceData just started; the technician
  // dropdown reads that roster, so it must land before the options fill in.
  void ensureReferenceData({ refresh: refreshReferenceData });
  if (refreshReferenceData) invalidateFilterOptions();
  if (!isFilterOptionsLoaded()) {
    ensureUsers().then(loadFilterOptions).then(
      (dropped) => {
        // A repopulate emptied a selection the list above was sent with: ask
        // again so the dropdowns and the cards agree. Not over a card page.
        if (dropped && !isSoloActive()) loadWorkOrders();
      },
      () => {
        // The card list is still useful if the small options request fails. Keep
        // the existing selections/placeholders and retry on the next page entry.
        invalidateFilterOptions();
      },
    );
  }
  if (exportBtn) exportBtn.hidden = !isAdminPlus();
  if (technicianFilterField) technicianFilterField.hidden = !isSupervisorPlus();

  const filters = currentFilters();
  try {
    let cards = await apiListWorkOrders(listParams());
    // Latest request wins: a newer load owns the screen.
    if (archivedLookupToken !== archivedSearchToken) return;
    if (pendingFocusId && !cards.some((c) => c.id === pendingFocusId)) {
      resetFilterControls();
      cards = await apiListWorkOrders({ limit: null, sort: getSortDir() });
      if (archivedLookupToken !== archivedSearchToken) return;
    }
    renderCards(cards, { flash: background });
    renderFilterChips();
    renderScope();
    renderResultCount({ count: cards.length });
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
      await offerRestoreForExactArchivedSearch(filters.textQ, archivedLookupToken);
    }
  } catch (err) {
    if (archivedLookupToken !== archivedSearchToken) return;
    // A socket-driven refresh must stay silent on failure (spec section 6):
    // leave the existing list exactly as it was rather than wipe it out from
    // under a user who never asked for this reload. The user-initiated path
    // (background=false) keeps today's error behavior unchanged.
    clearPendingListScrollY();
    if (background) return;
    listEl.innerHTML = "";
    renderFilterChips();
    renderScope();
    hideResultCount();
    setMessage(listMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

// One path for first draw, filter change and live update: build the tree
// detached, then patch the list in place, so an opened preview, a folded group,
// focus and scroll position survive. Only a live update (`flash`) highlights
// what changed; a filter the user just changed would light every card it adds.
function renderCards(cards, { flash = false } = {}) {
  // Anything other than a previous list draw (the card page, a skeleton) is
  // wiped, not patched: a card-page card patched into a group would keep its
  // own listeners, including the one that stops its summary folding.
  if ([...listEl.children].some((el) => !el.matches(".wo-group, .hint"))) listEl.innerHTML = "";
  const tree = document.createElement("div");
  if (cards.length) appendGroupedCards(tree, cards, (c) => buildCard(c));
  else tree.innerHTML = `<p class="hint">No work orders match.</p>`;
  morphInto(listEl, tree.childNodes, {
    flashSelector: flash ? "details.wo-card" : null,
    flashKey: (el) => el.querySelector("summary.wo-summary")?.textContent ?? "",
  });
}

// One tap handler per list. Patched-in cards are copies without handlers, and
// the id and number are read off the card at tap time, so Open always acts on
// the data now on screen. `onclick`, not addEventListener: mounting the same
// container twice must not open twice.
function installListTaps(container, onOpen = null) {
  container.onclick = (event) => {
    const cardEl = event.target.closest("[data-peek-open]")?.closest("details.wo-card");
    if (!cardEl) return;
    const card = { id: cardEl.dataset.id, number: cardEl.dataset.number };
    if (onOpen) onOpen(card);
    else void openWorkOrderPage(card);
  };
}
if (listEl) installListTaps(listEl);

// Status groups, in the order a crew works them (user 2026-11-14). Each group
// is a native <details>; Completed starts folded unless it is all there is.
// Order within a group is the server's (the sort control's).
const GROUP_ORDER = ["in_progress", "assigned", "planned", "created", "on_hold", "ready_to_complete", "review", "completed"];
const FOLDED_GROUPS = new Set(["completed"]);

function groupKey(card) {
  return card.smr ? "smr" : card.status;
}

function appendGroupedCards(container, cards, build, idPrefix = "wo") {
  const groups = new Map();
  for (const card of cards) {
    const key = groupKey(card);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(card);
  }
  const keys = [
    ...GROUP_ORDER.filter((key) => groups.has(key)),
    ...[...groups.keys()].filter((key) => !GROUP_ORDER.includes(key)),
  ];
  for (const key of keys) {
    const group = document.createElement("details");
    group.className = `wo-group wo-group-${key}`;
    group.dataset.status = key;
    group.id = `${idPrefix}-group-${key}`;
    group.open = !(FOLDED_GROUPS.has(key) && keys.length > 1);
    const label = key === "smr" ? "SMR" : statusLabel(key);
    group.innerHTML =
      `<summary class="wo-group-head"><span class="wo-group-dot" aria-hidden="true"></span>` +
      `<span>${escapeHtml(label)}</span><span class="wo-group-count">· ${groups.get(key).length}</span></summary>` +
      `<div class="wo-group-cards"></div>`;
    const list = group.querySelector(".wo-group-cards");
    groups.get(key).forEach((card) => list.appendChild(build(card)));
    container.appendChild(group);
  }
}

// One work order changed. A list card rewrites its summary, status class and
// preview; the card page's card takes a live refresh instead.
//
// A 404 means the work order left this user's view: archived (every recognised
// role sees every live work order). The row goes. Only 404 removes a card; a network blip
// rejects without a `status` field and must leave the list alone.
async function refreshCardSummary(cardEl) {
  if (isSoloActive()) {
    requestLiveRefresh(cardEl);
    return;
  }
  let detail;
  try {
    detail = await apiGetWorkOrder(cardEl.dataset.id);
  } catch (err) {
    if (err?.status !== 404) return;
    cardEl.remove();
    if (!listEl.querySelector("details.wo-card")) {
      listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    }
    return;
  }
  const summary = cardEl.querySelector("summary.wo-summary");
  const before = summary?.textContent;
  if (summary) summary.innerHTML = summaryHtml(detail);
  setCardClass(cardEl, detail);
  cardEl.classList.toggle("just-changed", before !== summary?.textContent);
  // A status change moves the card to another group, which only a reload
  // places correctly (the server owns the order within a group).
  const group = cardEl.closest(".wo-group");
  if (group && group.dataset.status !== groupKey(detail)) {
    runOrDeferListRefresh();
    return;
  }
  const peek = cardEl.querySelector(".wo-body");
  if (peek) peek.innerHTML = peekHtml(detail);
}

// --- live refresh (the card page) --------------------------------------------
//
// One fetch per card at a time: a request while one runs sets `rerun`, and the
// running one goes once more when it finishes, so responses apply in order.
// A response a newer paint overtook (the user's own save) is dropped and
// refetched; one for a card no longer on screen is ignored.
const paintCounts = new WeakMap();
const liveRuns = new WeakMap();

function requestLiveRefresh(cardEl) {
  const run = liveRuns.get(cardEl);
  if (run) {
    run.rerun = true;
    return;
  }
  const state = { rerun: false };
  liveRuns.set(cardEl, state);
  void (async () => {
    try {
      do {
        state.rerun = false;
        await liveRefreshPass(cardEl);
      } while (state.rerun && cardEl.isConnected);
    } finally {
      liveRuns.delete(cardEl);
    }
  })();
}

async function liveRefreshPass(cardEl) {
  for (;;) {
    const painted = paintCounts.get(cardEl) ?? 0;
    let detail;
    try {
      // Quiet: a background refresh never signs the user out mid-typing.
      detail = await apiGetWorkOrder(cardEl.dataset.id, { quiet401: true });
    } catch (err) {
      // Archived. Wiping to the list's "No work orders match." would leave a
      // page with no card and no way back. 401 and network failures: nothing.
      if (err?.status === 404 && cardEl.isConnected) renderSoloError("This work order is no longer available.");
      return;
    }
    if (!cardEl.isConnected) return;
    if ((paintCounts.get(cardEl) ?? 0) !== painted) continue;
    const summary = cardEl.querySelector(":scope > summary.wo-summary");
    if (summary) summary.innerHTML = summaryHtml(detail);
    setCardClass(cardEl, detail);
    const bodyEl = cardEl.open ? cardEl.querySelector(":scope > .wo-body") : null;
    if (!bodyEl) {
      delete cardEl.dataset.loaded;
      return;
    }
    const { deferred } = patchBodyLive(detail, bodyEl, cardEl);
    cardEl.dataset.loaded = "1";
    if (deferred) cardEl.dataset.missedUpdate = "1";
    else delete cardEl.dataset.missedUpdate;
    return;
  }
}

// The editor sections inside a card body. A card holding any of them open is
// "held": workOrderRetry.js offers to reopen it after a re-login. A live
// update no longer waits for these (workOrderLiveBody.js patches around what
// the user touched). The technician combobox renders inside `.wo-edit-card`.
const EDITOR_SECTIONS =
  ".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section";

function isHeld(cardEl) {
  return Array.from(cardEl.querySelectorAll(EDITOR_SECTIONS)).some((s) => s.open);
}

// Read by workOrderRetry.js when a 401 is about to hide the app, to find
// which card (if any) has unsent input worth resuming after re-login.
export function heldWorkOrderCards() {
  if (!listEl) return [];
  return Array.from(listEl.querySelectorAll("details.wo-card")).filter(isHeld);
}

function runOrDeferListRefresh() {
  if (isSoloActive()) {
    // A list refetch would replace the card page with the list -- silently,
    // with the card's URL still in the address bar. On a card page the only
    // row that can matter is the one on screen, so refresh that instead.
    const cardEl = listEl.querySelector("details.wo-card");
    if (cardEl) requestLiveRefresh(cardEl);
    return;
  }
  void loadWorkOrders({ background: true });
}

function buildCard(card, { solo = false, idPrefix = "wo" } = {}) {
  const el = document.createElement("details");
  el.className = workOrderCardClass(card);
  // What the list patcher matches on; the prefix differs per list because the
  // page list and the User Hub list can be in the document together.
  el.id = `${idPrefix}-card-${card.id}`;
  el.dataset.id = card.id;
  // Read by workOrderRetry.js's held-editor capture, which only has the DOM
  // to work from -- a 401 can land mid-edit with no other handle on "which
  // work order was this".
  el.dataset.number = card.number;

  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  summary.innerHTML = summaryHtml(card);

  const body = document.createElement("div");
  body.className = "wo-body";

  el.appendChild(summary);
  el.appendChild(body);

  // Being *the* solo card is a property of this card, passed in by
  // `showSoloCard`. It used to read the module-global `soloActive`, which
  // silently broke every other list: `exitSolo` runs only inside
  // `loadWorkOrders`, so leaving the card page for the User Hub left the flag
  // set, and the hub's own cards (built by `mountWorkOrderList`, a different
  // container on a different page) went dead on click until the Work Orders
  // page was visited again.
  if (solo) {
    body.innerHTML = skeletonCard({ lines: 3, hasHeader: false });
    el.addEventListener("toggle", () => {
      if (el.open && !el.dataset.loaded) openDetail(card.id, body, el);
    });
    // The card page's own card is not collapsible: there is nothing to
    // collapse to. `preventDefault` covers Enter and Space too, which both
    // dispatch a click on a focused summary.
    summary.addEventListener("click", (event) => event.preventDefault());
    return el;
  }

  // A list card opens in place as a preview built from the row it already
  // has (user 2026-11-14); its button goes to the full card through the
  // list's one tap handler (`installListTaps`).
  body.innerHTML = peekHtml(card);
  return el;
}

// Every className write goes through workOrderCardClass (it keeps the urgent
// fire); the card page's `wo-solo` modifier rides along.
function setCardClass(cardEl, card) {
  const solo = cardEl.classList.contains("wo-solo");
  cardEl.className = workOrderCardClass(card) + (solo ? " wo-solo" : "");
}

async function openDetail(workOrderId, bodyEl, cardEl) {
  try {
    paintDetail(await apiGetWorkOrder(workOrderId), bodyEl, cardEl);
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this work order."))}</p>`;
  }
}

// --- card page render ------------------------------------------------------

// Called from the Admin weekly report (hubReport.js) for a *closed* row. A
// closed work order has no card page to open -- this list hides archived rows
// -- so route to its exact number instead and let the shipped "Work Order has
// been closed. Restore?" prompt fire. Resets every other control first, for the
// same reason the tile and graph entry points above do: a stale status or
// community filter left over from a previous visit would hide the very row we
// just navigated to. Does not fetch; `showPage("work-orders")` does that.
export function openWorkOrdersByNumberSearch(number) {
  resetFilterControls();
  if (searchInput) searchInput.value = number;
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
}

// Called from the User Hub's Graphs tab (hubGraphs.js via userHub.js) by a
// pie's red "View N work orders" button. Same shape as
// `openWorkOrdersFilteredByStatus` -- reset every other filter first, so a
// graph always lands on exactly that pie's list and nothing carries over
// from a previous visit.
//
// All four set the same dropdowns the page's own controls do, through
// `selectFilterValue` because the three fetched dropdowns are usually still
// empty when this runs. `priority` is the exact-vendor-text "Priority"
// control, not the coarser high/medium "Priority level" one: the Graphs pies
// are cut from raw priority text, so their labels round-trip through this
// filter exactly.
export function openWorkOrdersFilteredByDistribution({
  community = null,
  communityLabel = null,
  serviceType = null,
  priority = null,
  status = null,
} = {}) {
  resetFilterControls();
  selectFilterValue(communityFilter, community, communityLabel || community);
  selectFilterValue(serviceTypeFilter, serviceType);
  selectFilterValue(priorityFilter, priority);
  if (status && statusFilter) statusFilter.value = status;
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
// scheduledDate, q, mine, limit} shape that function already accepts). Every
// role sees every work order server-side, so the Technician and Team Lead
// callers both pass `{ mine: true }` -- routed to me or assigned to me -- and
// the Admin caller passes nothing.
export function mountWorkOrderList({ container, lockedFilter = null, onOpen } = {}) {
  installListTaps(container, onOpen);
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
    appendGroupedCards(container, cards, (card) => buildCard(card, { idPrefix: "hubwo" }), "hubwo");
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
  if (!cardEl) return;

  // A live response fetched before this paint is older than it.
  paintCounts.set(cardEl, (paintCounts.get(cardEl) ?? 0) + 1);
  cardEl.dataset.loaded = "1";
  setCardClass(cardEl, detail);
  // The header follows every save: status, priority, schedule (Overdue),
  // location, crew and item count are all edited on this card.
  const summary = cardEl.querySelector(":scope > summary.wo-summary");
  if (summary) summary.innerHTML = summaryHtml(detail);
  // This repaint already reflects the latest data, so an update a live patch
  // left stale is now satisfied -- every repaint path (Cancel, Save details,
  // materials/labor actions, initial expansion) routes through here.
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

// One search box over number, location and task (user 2026-11-14). Live as you
// type (100 ms debounce, user 2026-11-13); Enter searches at once. The
// archived-number prompt still fires when the text is an exact closed number.
let woSearchDebounce = null;
function runWorkOrderNumberSearch() {
  loadWorkOrders({ checkArchivedSearch: true });
}

if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(woSearchDebounce);
    woSearchDebounce = setTimeout(runWorkOrderNumberSearch, 100);
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(woSearchDebounce);
      runWorkOrderNumberSearch();
    }
  });
}

[mineFilter, statusFilter, serviceTypeFilter, priorityFilter, supervisorFilter, technicianFilter, communityFilter, scheduledDateFilter].forEach((control) => {
  if (!control) return;
  control.addEventListener("change", () => {
    loadWorkOrders();
  });
});

if (sortSeg) {
  renderSortControl();
  sortSeg.addEventListener("click", (event) => {
    const value = event.target.closest("[data-sort]")?.dataset.sort;
    if (!SORT_VALUES.has(value) || value === getSortDir()) return;
    setSortDir(value);
    renderSortControl();
    try {
      localStorage.setItem(SORT_STORAGE_KEY, getSortDir());
    } catch {
      // Best effort only.
    }
    loadWorkOrders();
  });
}

// The Advanced search bar shows and hides the panel in its box.
if (filtersBtn && filtersPanel) {
  filtersBtn.addEventListener("click", () => {
    filtersPanel.hidden = !filtersPanel.hidden;
    filtersBtn.setAttribute("aria-expanded", String(!filtersPanel.hidden));
  });
}

function cancelSearchDebounces() {
  clearTimeout(woSearchDebounce);
}

function clearFilters(keepScope = false) {
  const mine = mineFilter?.checked;
  cancelSearchDebounces();
  resetFilterControls();
  if (keepScope && mineFilter) mineFilter.checked = mine;
  loadWorkOrders();
}

// The panel's Clear filters resets its fields and the WO# search but leaves the
// My Work Orders / All scope where the user put it. The chips' Clear all (below)
// still widens everything.
if (clearFiltersBtn) clearFiltersBtn.addEventListener("click", () => clearFilters(true));

// Scope toggle (My Work Orders | All) and the Advanced search bar's count. The
// toggle and the panel's checkbox are one setting: `mineFilter` stays the source of truth and renderScope()
// mirrors it after every load.
function renderScope() {
  if (scopeSeg) {
    scopeSeg.querySelectorAll("[data-scope]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String((btn.dataset.scope === "mine") === Boolean(mineFilter?.checked)));
    });
  }
  if (filtersCountEl) {
    // Everything the panel holds, bar the scope checkbox (search is on the page).
    const { mine, textQ, ...inPanel } = currentFilters();
    const count = Object.values(inPanel).filter(Boolean).length;
    filtersCountEl.textContent = ` · ${count}`;
    filtersCountEl.hidden = count === 0;
  }
}

if (scopeSeg && mineFilter) {
  mineFilter.addEventListener("change", renderScope);
  scopeSeg.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-scope]");
    if (!btn || (btn.dataset.scope === "mine") === mineFilter.checked) return;
    mineFilter.checked = btn.dataset.scope === "mine";
    renderScope();
    mineFilter.dispatchEvent(new Event("change"));
  });
}
renderScope();

// A chip's x has already reset its one control; reload the way a filter
// change does. A pending keyword debounce would otherwise fire a second,
// stale load after this one.
installFilterChips({
  onRemove: () => {
    cancelSearchDebounces();
    loadWorkOrders();
  },
  onClearAll: () => clearFilters(),
});

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
  return refreshCardSummary(cardEl);
});

// Catch-up: a live patch left something stale because the user was on it (an
// open Edit details, a focused field). Closing a section or leaving a field
// asks again. `toggle` does not bubble, so it listens in the capture phase.
// Only a close counts: opening leaves nothing to catch up on.
function catchUp(event) {
  if (event.type === "toggle" && event.target.open) return;
  const cardEl = event.target.closest?.("details.wo-card");
  if (cardEl?.dataset.missedUpdate === "1") requestLiveRefresh(cardEl);
}
if (listEl) {
  listEl.addEventListener("toggle", catchUp, true);
  listEl.addEventListener("focusout", catchUp);
}

// Routing's three list dependencies, handed over once. Placed last so every
// function it names is defined.
installWorkOrderRouting({ buildCard, paintDetail, loadWorkOrders });
