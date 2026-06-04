// Foundation: shared mutable state for the SPA.
//
// Layer: foundation (depends on nothing). Imported by every view
// module so they can read each other's data without coupling --
// e.g. the transactions view reads the items cache to fill its
// dropdown without importing the items view. Keeping state here
// (rather than re-fetching) avoids redundant network calls and
// lets the views stay stateless.
//
// Convention: every field has a `get*` and `set*` accessor.
// Views never touch module-level `let`s directly.

let itemsCache = [];
let usersCache = [];
let selectedItemId = null;
let editingNotesItemId = null;

// The logged-in user: `{ id, username, role }` or null when logged out.
// Auth itself lives in the HttpOnly session cookie (not readable here);
// this is only the identity the views need to gate the UI. Deliberately
// NOT persisted to localStorage -- a page reload re-checks `/auth/me`.
let currentUser = null;

// Hard-coded page size for the history view. Backend caps at 100;
// 10 is plenty for the current UI density.
export const HISTORY_PAGE_SIZE = 10;

// History view's complete display state -- which tab is active,
// the current filter, and pagination position. Kept as one object
// so callers can patch fields without losing the rest.
const historyState = {
  tab: "all",
  itemId: null,
  userId: null,
  page: 1,
  totalPages: 1,
};

export function getItems() { return itemsCache; }
export function setItems(arr) { itemsCache = arr; }

export function getUsers() { return usersCache; }
export function setUsers(arr) { usersCache = arr; }

export function getSelectedItemId() { return selectedItemId; }
export function setSelectedItemId(id) { selectedItemId = id; }

export function getEditingNotesItemId() { return editingNotesItemId; }
export function setEditingNotesItemId(id) { editingNotesItemId = id; }

export function getCurrentUser() { return currentUser; }
export function setCurrentUser(user) { currentUser = user; }
// Convenience accessor used pervasively by the role-gated views.
export function getRole() { return currentUser ? currentUser.role : null; }

// History state is returned by copy so callers cannot mutate the
// internal object by reference. Use `updateHistoryState({...})`
// to write -- it shallow-merges the patch onto the live state.
export function getHistoryState() { return { ...historyState }; }
export function updateHistoryState(patch) { Object.assign(historyState, patch); }
