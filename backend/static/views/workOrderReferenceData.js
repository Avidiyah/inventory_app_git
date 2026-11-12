// Work Orders: reference data.
//
// Layer: owns the item and user lists the card body needs. They live here
// rather than in the list module because ESM bindings are read-only across a
// module boundary -- a sibling can read `allItems`, but only the module that
// declares it can refill it.

import { apiListItems, apiListUsers } from "../api.js";
import { canBeWorkOrderSupervisor, canBeWorkOrderAssignee } from "../roles.js";
import { isSupervisorPlus } from "./workOrderPresenters.js";

// Reference lists are reused during interactions within one visit (for example,
// debounced Work Order searches), then refreshed when nav.js activates the page
// again so item and user changes made elsewhere cannot remain stale.
let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let allSupers = [];
let usersLoaded = false;
// In-flight loads, shared by concurrent callers (see ensureReferenceData).
let itemsRequest = null;
let usersRequest = null;
// The reference half of the reset. workOrderFilters.js listens for the same
// event and resets only the filter-options flag it owns.
document.addEventListener("user-names-updated", () => {
  allTechs = [];
  allSupers = [];
  usersLoaded = false;
  usersRequest = null;
});

export function getAllItems() { return allItems; }
export function getAllTechnicians() { return allTechs; }
export function getAllSupervisors() { return allSupers; }
// Import and enrichment both invalidate the user lists so a re-import reflects
// fresh data. The flag, not the arrays: the next ensureReferenceData refetches.
export function invalidateUsers() { usersLoaded = false; usersRequest = null; }

// Item and user reference lists that the card *body* needs: the add-material
// search reads `allItems`, the technician picker reads `allTechs`/`allSupers`.
//
// Shared by the list load and the card-page load. A cold deep link paints a
// card body without ever rendering the list, and empty lists there are a
// picker that silently matches nothing rather than an error the user can act
// on. Failures stay swallowed, as before: the card is still worth showing.
//
// Items and users load in parallel, and a call made while a load is in flight
// shares it rather than starting a second one. That is how a card page opened
// right after a page-entry refresh paints with the refreshed users list: it
// awaits `ensureUsers()`, which hands back the refresh's request.
export function ensureReferenceData({ refresh = false } = {}) {
  if (!itemsRequest && (refresh || !itemsLoaded)) {
    const req = apiListItems().then(
      (items) => { allItems = items; itemsLoaded = true; },
      () => { allItems = []; },
    ).finally(() => { if (itemsRequest === req) itemsRequest = null; });
    itemsRequest = req;
  }
  return Promise.all([itemsRequest, ensureUsers({ refresh })]).then(() => {});
}

// The card's Team Lead picker reads the supervisor list at paint time, so a
// card must not paint before this settles (an empty list saves as Unassigned).
export function ensureUsers({ refresh = false } = {}) {
  if (!usersRequest && (refresh || !usersLoaded) && isSupervisorPlus()) {
    const req = apiListUsers().then(
      (users) => {
        allTechs = users.filter((u) => canBeWorkOrderAssignee(u.role));
        allSupers = users.filter((u) => canBeWorkOrderSupervisor(u.role));
        usersLoaded = true;
      },
      () => { allTechs = []; allSupers = []; },
    ).finally(() => { if (usersRequest === req) usersRequest = null; });
    usersRequest = req;
  }
  return usersRequest || Promise.resolve();
}

// The in-flight items load, or null once settled. Lets a reader of
// `getAllItems()` tell "not loaded yet" from "no such item".
export function itemsLoading() { return itemsRequest; }
