// View: top-level page router for the SPA.
//
// Layer: views. Wires the nav buttons in `index.html` to the
// `.page` sections, toggling the `active` class so CSS shows the
// right one. Data-driven pages trigger their own loads on
// activation so the view never shows stale rows after a write
// elsewhere in the SPA.

import { enterTransactionPage } from "./transactions.js";
import { loadHistory } from "./history.js";
import { loadItems } from "./items.js";
import { loadUsers } from "./users.js";
import { txnScanner } from "./scan.js";
import { itemsScanner } from "./items.js";

const navButtons = document.querySelectorAll(".nav-btn");
const pages = document.querySelectorAll(".page");

// Page-scoped scanners. Drives camera-lifecycle hooks below: stop on
// page-leave / tab-hide, refresh permission state on page-enter. Add
// new entries here as more pages adopt live capture (Saved Items in
// Phase 3 PR2). See docs/plan-live-capture.md.
const SCANNERS_BY_PAGE = {
  "transaction": txnScanner,
  "saved-items": itemsScanner,
};

let activePage = null;

// Tab-hide -> stop every active camera. The user has navigated away
// from the tab; releasing the camera also turns off the torch LED and
// the recording indicator. We do NOT reset() -- if they tab back, the
// section still has whatever message/chooser state it had before.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) return;
  for (const scanner of Object.values(SCANNERS_BY_PAGE)) {
    if (scanner && typeof scanner.stopLive === "function") scanner.stopLive();
  }
});

// Which roles may see each page. This is the single source of truth for
// nav visibility AND for the post-login boot in `auth.js`. It mirrors
// the backend route gates; the backend still enforces them.
export const PAGE_ACCESS = {
  "create-item": ["owner", "admin"],
  "saved-items": ["owner", "admin", "supervisor", "technician"],
  "create-user": ["owner", "admin", "supervisor"],
  "saved-users": ["owner", "admin", "supervisor"],
  // Technicians get scan-and-go too, but dispense-only (enforced server-side
  // in roles.can_transact; the UI hides the Stock toggle for them).
  "transaction": ["owner", "admin", "supervisor", "technician"],
  "history": ["owner", "admin", "supervisor"],
};

export function canAccessPage(role, pageName) {
  return (PAGE_ACCESS[pageName] || []).includes(role);
}

// Hide (not disable) every nav button the role may not use. Forbidden
// pages simply do not appear.
export function applyRoleVisibility(role) {
  navButtons.forEach(btn => {
    btn.hidden = !canAccessPage(role, btn.dataset.page);
  });
}

export function showPage(pageName) {
  // Camera lifecycle: stop + reset the leaving page's scanner (if any)
  // before swapping the active section, then refresh the entering
  // page's permission state. reset() also calls stopLive() internally.
  const leaving = SCANNERS_BY_PAGE[activePage];
  if (leaving && activePage !== pageName) leaving.reset();

  pages.forEach(page => {
    page.classList.toggle("active", page.id === `${pageName}-page`);
  });
  navButtons.forEach(btn => {
    btn.classList.toggle("active", btn.dataset.page === pageName);
  });
  activePage = pageName;

  const entering = SCANNERS_BY_PAGE[pageName];
  if (entering) entering.refreshPermissionState();

  if (pageName === "transaction") {
    enterTransactionPage();
  } else if (pageName === "history") {
    loadHistory();
  } else if (pageName === "saved-items") {
    loadItems();
  } else if (pageName === "saved-users") {
    loadUsers();
  }
}

navButtons.forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});
