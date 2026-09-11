// Work Orders: reference data.
//
// Layer: owns the item and user lists the card body needs. They live here
// rather than in the list module because ESM bindings are read-only across a
// module boundary -- a sibling can read `allItems`, but only the module that
// declares it can refill it.

import { apiListItems, apiListUsers } from "../api.js";
import { canBeWorkOrderSupervisor, canBeWorkOrderTechnician } from "../roles.js";
import { isSupervisorPlus } from "./workOrderPresenters.js";

// Reference lists are reused during interactions within one visit (for example,
// debounced Work Order searches), then refreshed when nav.js activates the page
// again so item and user changes made elsewhere cannot remain stale.
let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let allSupers = [];
let usersLoaded = false;
// The reference half of the reset. workOrderFilters.js listens for the same
// event and resets only the filter-options flag it owns.
document.addEventListener("user-names-updated", () => {
  allTechs = [];
  allSupers = [];
  usersLoaded = false;
});

export function getAllItems() { return allItems; }
export function getAllTechnicians() { return allTechs; }
export function getAllSupervisors() { return allSupers; }
// Import and enrichment both invalidate the user lists so a re-import reflects
// fresh data. The flag, not the arrays: the next ensureReferenceData refetches.
export function invalidateUsers() { usersLoaded = false; }

// Item and user reference lists that the card *body* needs: the add-material
// search reads `allItems`, the technician picker reads `allTechs`/`allSupers`.
//
// Shared by the list load and the card-page load. A cold deep link paints a
// card body without ever rendering the list, and empty lists there are a
// picker that silently matches nothing rather than an error the user can act
// on. Failures stay swallowed, as before: the card is still worth showing.
export async function ensureReferenceData({ refresh = false } = {}) {
  if (refresh || !itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = [];
    }
  }
  if ((refresh || !usersLoaded) && isSupervisorPlus()) {
    try {
      const users = await apiListUsers();
      allTechs = users.filter((u) => canBeWorkOrderTechnician(u.role));
      allSupers = users.filter((u) => canBeWorkOrderSupervisor(u.role));
      usersLoaded = true;
    } catch {
      allTechs = [];
      allSupers = [];
    }
  }
}
