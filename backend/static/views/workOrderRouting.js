// Work Orders: card-page routing.
//
// Layer: owns card-page ("solo") mode -- the /workorder_card/ URL, the chrome
// around a single card, the list's scroll stamp and restore, and popstate in
// both directions.
//
// The one injected seam in the group. Routing and the list call each other
// (loadWorkOrders opens a pending card page; Back returns to the list), so an
// import both ways would be a cycle. workOrderList.js hands its three
// functions over once, at the bottom of its own module body.

import { apiGetWorkOrder, apiListWorkOrders } from "../api.js";
import { setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { skeletonCard } from "../skeleton.js";
import { SECTION_SELECTOR, readDraft, takePendingResume } from "../workOrderDrafts.js";
import { ensureReferenceData, getAllItems } from "./workOrderReferenceData.js";
import { hoursInputValue } from "./workOrderPresenters.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const moreEl = document.getElementById("work-orders-more");
// The filters/search block. Hidden in solo mode ("card page"), where the list
// holds one work order and there is nothing to filter.
const controlsSection = document.getElementById("work-orders-controls-section");

let deps = null;
export function installWorkOrderRouting(next) { deps = next; }

export function isSoloActive() { return soloActive; }
// One-shot: the caller consumes the pending number and clears it, so two
// renders cannot both claim it.
export function takePendingSoloNumber() {
  const number = pendingSoloNumber;
  pendingSoloNumber = null;
  return number;
}
export function clearPendingListScrollY() { pendingListScrollY = null; }

// --- card page ("solo") mode ----------------------------------------------
//
// A work-order card opened from the list is shown as a page: the same
// `details.wo-card`, expanded, alone in `#work-orders-list`, with the filter
// and import sections hidden and a Back control above it.
//
// The card is NOT relocated, and must never be. Every interaction on it --
// status actions, notes, materials, labor, the billing editor, the technician
// picker -- is delegated off `listEl`, and the realtime subscriber finds cards
// by querying `listEl`. Rendering the detail into a different container leaves
// a card that looks correct and whose every button is dead, with no error.
//
// `soloActive` drives the chrome; `soloNumber` is the number in the URL and
// stays null when a deep link could not be resolved (renderSoloError).
let soloActive = false;

let soloNumber = null;

// Must match the FastAPI route in backend/app/main.py and the rate-limit
// exemption in backend/app/domain/rate_limit.py. These three strings are the
// whole contract.
const SOLO_PATH_PREFIX = "/workorder_card/";

// A number pending a card-page open, set before nav.js activates the page (see
// focusWorkOrderNumber / focusWorkOrder). loadWorkOrders consumes it instead of
// rendering the list, which is what keeps the two renders from racing.
let pendingSoloNumber = null;

// --- list scroll restoration ----------------------------------------------
//
// Opening a card wipes the list, so returning from one used to land at the top
// no matter where the user opened it from. The offset is stamped onto the
// *list's* history entry (`openWorkOrderPage`) and read back off it when
// `popstate` unwinds to that entry, which is why it survives Forward and a
// reload as well as the card's own Back control.
//
// The browser's own restoration cannot do this: it fires at `popstate`, when
// `loadWorkOrders` has not yet fetched the list and the document is one
// skeleton tall, so it clamps to 0 and then we would be fighting it. We own the
// restore instead, and say so.
if ("scrollRestoration" in window.history) {
  window.history.scrollRestoration = "manual";
}

// One-shot consumed by the next completed list render. Deliberately not read
// from `history.state` at the render site: nav entry, filter changes, and the
// realtime `background: true` refresh all reach the same render with the list
// entry still current, and must not jump the page.
let pendingListScrollY = null;

// Record where the list was standing, on the history entry that *is* the list.
// Called from `openWorkOrderPage` while that entry is still current -- the push
// to the card URL happens later, in `showSoloCard`.
function stampListScrollY() {
  // Already on a card page: the current entry is the card's, not the list's,
  // and there is no list offset to preserve. This is the cold-deep-link path
  // (`openWorkOrderPageByNumber`), which lands at the top by design.
  if (soloActive) return;
  window.history.replaceState(
    { ...(window.history.state || {}), woListScrollY: window.scrollY },
    ""
  );
}

// Consume the one-shot after a completed list render. Deferred a frame so the
// restored cards -- and the filter controls `exitSolo` just unhid -- have been
// laid out; scrolling before that clamps against a document that is still the
// wrong height. An offset past the end of a now-shorter list clamps to the
// bottom, which is the honest answer when the row that was there is gone.
export function restoreListScrollY() {
  const y = pendingListScrollY;
  pendingListScrollY = null;
  if (y === null) return;
  window.requestAnimationFrame(() => window.scrollTo(0, y));
}

// The work-order number in `pathname`, or null if it is not a card-page URL.
export function soloNumberFromPath(pathname = window.location.pathname) {
  if (!pathname.startsWith(SOLO_PATH_PREFIX)) return null;
  const raw = pathname.slice(SOLO_PATH_PREFIX.length);
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    // A malformed %-escape is not a work order number. Treat it as no link
    // rather than throwing out of a boot path.
    return null;
  }
}

// Show/hide everything around the card. The Import/Export section now lives
// on its own Integrations page (see loadIntegrationsPage), so solo mode no
// longer needs to touch it -- it is already hidden whenever Work Orders
// isn't the active page.
function setSoloChrome(on) {
  if (controlsSection) controlsSection.hidden = on;
  if (moreEl) {
    if (on) moreEl.innerHTML = "";
    moreEl.hidden = true;
  }
}

// Leave card-page mode and put the address bar back. Called from the top of
// every path that renders the full list, so the browser can never show a
// /workorder_card/ URL for a page that is no longer showing that card. The URL
// is normalized even when solo mode was already off -- that covers navigating
// to another page and back while a stale card URL is in the bar.
export function exitSolo() {
  if (soloActive) setSoloChrome(false);
  soloActive = false;
  soloNumber = null;
  if (window.location.pathname.startsWith(SOLO_PATH_PREFIX)) {
    window.history.replaceState({}, "", "/");
  }
}

// The card page's own way back. It lives inside `listEl` (so it is cleared with
// the card) but outside any `.wo-card`, which the click delegation has to
// account for -- see the `back-to-work-orders` branch.
function soloBackControl() {
  const wrap = document.createElement("div");
  wrap.className = "wo-solo-back";
  wrap.innerHTML =
    `<button type="button" class="secondary-btn" data-action="back-to-work-orders">` +
    `&larr; Back to work orders</button>`;
  return wrap;
}

// Open one work order as a page. `number` is optional: a click from the list
// already has it, a Mass Stage hand-off has only an id, and either way the
// detail fetched here carries the authoritative number for the URL.
//
// One request, not two: the detail fetched here is painted directly rather
// than being re-fetched by `openDetail`, so opening a card page costs exactly
// what expanding a card used to.
export async function openWorkOrderPage({ id, number = null }) {
  // Before anything async and before `setSoloChrome`/the skeleton collapse the
  // document's height -- once the list is gone, `window.scrollY` has already
  // been clamped to 0 and the offset is unrecoverable.
  stampListScrollY();
  await ensureReferenceData();
  soloActive = true;
  soloNumber = number;
  setSoloChrome(true);
  if (listMessage) setMessage(listMessage, "", "");
  listEl.innerHTML = skeletonCard({ lines: 6 });

  let detail;
  try {
    detail = await apiGetWorkOrder(id);
  } catch (err) {
    renderSoloError(friendlyError(err, "Could not open this work order."));
    return;
  }
  showSoloCard(detail);
}

// Open a card page from a work-order NUMBER -- a refreshed page, a bookmark,
// or a pasted link, where the id is not known.
//
// Resolved through the ordinary list search rather than `/work-orders/lookup`:
// lookup is Supervisor+, so a technician following a link to their own
// assigned work order would get a 403 -- the exact person the link is usually
// for. The list route is open to any session and already server-scoped, so it
// answers "may this caller see it" as a side effect of answering "does it
// exist". It partial-matches, so the exact number is chosen here.
export async function openWorkOrderPageByNumber(number) {
  await ensureReferenceData();
  soloActive = true;
  soloNumber = number;
  setSoloChrome(true);
  if (listMessage) setMessage(listMessage, "", "");
  listEl.innerHTML = skeletonCard({ lines: 6 });

  let matches;
  try {
    matches = await apiListWorkOrders({ q: number });
  } catch (err) {
    renderSoloError(friendlyError(err, "Could not open this work order."));
    return;
  }

  const match =
    matches.find((c) => c.number === number) ||
    matches.find((c) => c.number.toLowerCase() === number.toLowerCase());
  if (!match) {
    // Archived, or outside this caller's scope. `/work-orders/lookup` could
    // tell those apart but is Supervisor+, so say the one thing that is true
    // for every role rather than guess.
    renderSoloError(`Work order ${number} is not available.`);
    return;
  }
  await openWorkOrderPage({ id: match.id, number: match.number });
}

// Queue a card page to open the next time the Work Orders page loads. Used by
// the post-login boot: nav.js's `showPage` triggers `loadWorkOrders`, which
// consumes this instead of rendering the list, so the two cannot race.
export function focusWorkOrderNumber(number) {
  pendingSoloNumber = number;
}

// Render `detail` as the only card in the list, expanded, with a Back control
// above it. The element is exactly what `buildCard` produces -- same tag, same
// classes, same `data-id`, same parent -- plus a `.wo-solo` presentation
// modifier, so delegation, the realtime subscriber, and every repaint path
// keep working untouched.
function showSoloCard(detail) {
  soloActive = true;
  soloNumber = detail.number;
  setSoloChrome(true);

  const path = SOLO_PATH_PREFIX + encodeURIComponent(detail.number);
  if (window.location.pathname !== path) {
    // `{ solo: ... }` marks entries this module pushed, which is how the Back
    // control knows whether `history.back()` would leave the app entirely (a
    // cold deep link has a null state).
    window.history.pushState({ solo: detail.number }, "", path);
  }

  listEl.innerHTML = "";
  listEl.appendChild(soloBackControl());
  const cardEl = deps.buildCard(detail, { solo: true });
  cardEl.classList.add("wo-solo");
  listEl.appendChild(cardEl);
  // Paint before opening. `paintDetail` sets `dataset.loaded`, so `buildCard`'s
  // own toggle listener sees a loaded card and does not fetch it a second time
  // -- this does not rely on when the async `toggle` event happens to fire.
  deps.paintDetail(detail, cardEl.querySelector(".wo-body"), cardEl);
  cardEl.open = true;
  applyPendingSectionResume(cardEl, detail);
}

// Consumes the one-shot a 401 left behind (see workOrderRetry.js's
// captureHeldEditorForResume) so a forced re-login lands the operator back on
// the exact editor they were mid-entry on, with what they'd typed still
// there, instead of a blank work order they have to find and reopen by hand.
// Runs on every solo open, deep-linked or not; it is a no-op unless this
// open is the one the resume was waiting for.
function applyPendingSectionResume(cardEl, detail) {
  const resume = takePendingResume();
  if (!resume || resume.number !== detail.number) return;
  const selector = SECTION_SELECTOR[resume.section];
  const section = selector && cardEl.querySelector(selector);
  if (!section) return;
  section.open = true;
  const draft = readDraft(detail.id, resume.section);
  if (draft) fillDraftFields(section, draft);
  setMessage(cardEl.querySelector(".wo-message"), "Reconnecting — saving what you entered before you lost connection.", "");
}

// Best-effort field repopulation, scoped to the values that are a single,
// unambiguous input: labor hours, an existing row's hours/quantity, and
// notes text. `save-details` (the multi-field edit card, including the
// technician picker) is left for the operator to re-enter -- its own replay
// in workOrderRetry.js still saves it automatically either way.
function fillDraftFields(section, draft) {
  const { action, payload, targetId } = draft;
  if (action === "add-labor") {
    const hours = section.querySelector(".wo-new-labor-hours");
    if (hours) hours.value = hoursInputValue(payload.minutes);
    const tech = section.querySelector(".wo-labor-technician");
    if (tech && payload.technicianId) tech.value = payload.technicianId;
  } else if (action === "edit-labor") {
    const row = section.querySelector(`.wo-labor-entry[data-labor-id="${targetId}"]`);
    const hours = row?.querySelector(".wo-labor-hours");
    if (hours) hours.value = hoursInputValue(payload.minutes);
  } else if (action === "add-item") {
    const container = section.querySelector(".wo-add-item");
    if (!container) return;
    container.dataset.itemId = payload.itemId;
    const name = getAllItems().find((it) => it.id === payload.itemId)?.name;
    const search = container.querySelector(".ms-item-search");
    if (search && name) search.value = name;
    const qty = container.querySelector(".wo-item-qty");
    if (qty) qty.value = payload.quantity;
  } else if (action === "edit-item") {
    const row = section.querySelector(`.wo-item[data-wo-item-id="${targetId}"]`);
    const qty = row?.querySelector(".wo-line-qty");
    if (qty) qty.value = payload.quantity;
  } else if (action === "save-notes") {
    const notes = section.querySelector(".wo-notes-input");
    if (notes) notes.value = payload.notes;
  }
}

// A card page that has no card: the work order could not be fetched, could not
// be resolved from a link, or has just left this user's view. It still needs
// its own Back control -- the filters are hidden, and a cold deep link has no
// history entry to go back to.
export function renderSoloError(message) {
  soloActive = true;
  soloNumber = null;
  setSoloChrome(true);
  listEl.innerHTML = "";
  listEl.appendChild(soloBackControl());
  const p = document.createElement("p");
  p.className = "error";
  p.textContent = message;
  listEl.appendChild(p);
}

// Browser Back/Forward between the list and a card page. The card page is the
// SPA's only routed URL, so this handles both directions itself.
//
// The active-page check reads the DOM rather than importing `getActivePage`
// from nav.js: nav.js already imports this module, and the cycle is not worth
// one boolean. Popstate while some other page is showing is ignored -- the
// stale URL is harmless and `exitSolo` normalizes it on the next list render.
window.addEventListener("popstate", () => {
  if (!listEl) return;
  const workOrdersPage = document.getElementById("work-orders-page");
  if (!workOrdersPage?.classList.contains("active")) return;

  const number = soloNumberFromPath();
  if (number === null) {
    if (!soloActive) return;
    // Read off the entry being restored -- the list entry `openWorkOrderPage`
    // stamped on the way out. Arming it here rather than inside the render is
    // what keeps every other caller of `loadWorkOrders` from jumping the page.
    const y = window.history.state?.woListScrollY;
    pendingListScrollY = typeof y === "number" ? y : null;
    void deps.loadWorkOrders();  // exits solo mode itself
    return;
  }
  if (soloActive && number === soloNumber) return;
  void openWorkOrderPageByNumber(number);
});
