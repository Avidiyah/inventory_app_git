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
import { loadStages } from "./massStage.js";
import { loadWorkOrders } from "./workOrders.js";
import { loadAdminReview } from "./adminReview.js";
import { loadUserRequests } from "./userRequests.js";
import { loadTools, toolsScanner } from "./tools.js";
import { txnScanner } from "./scan.js";
import { itemsScanner } from "./items.js";

const navButtons = document.querySelectorAll(".nav-btn");
const pages = document.querySelectorAll(".page");

// Page-scoped scanners. Drives camera-lifecycle hooks below: stop on
// page-leave / tab-hide, refresh permission state on page-enter. Add
// new entries here as more pages adopt live capture. See docs/current-state.md.
const SCANNERS_BY_PAGE = {
  "transaction": txnScanner,
  "saved-items": itemsScanner,
  "tools": toolsScanner,
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
  "mass-stage": ["owner", "admin", "supervisor"],
  // Work Orders is technician-facing (server scopes to assigned/created/all).
  "work-orders": ["owner", "admin", "supervisor", "technician"],
  // Operational exceptions such as inventory recounts are managed by Admin+.
  "user-requests": ["owner", "admin"],
  // Final billing/close queue. Cost detail and archive are Admin/Owner-only.
  "admin-review": ["owner", "admin"],
  // Tools: every role sees its user-first custody card and can check in;
  // Admin+ can search active users and check out tools. The server retains
  // the existing Admin+ checkout gate and authenticated-user return gate.
  "tools": ["owner", "admin", "supervisor", "technician"],
  "history": ["owner", "admin", "supervisor"],
};

export function canAccessPage(role, pageName) {
  return (PAGE_ACCESS[pageName] || []).includes(role);
}

// Where each role lands right after sign-in, chosen so the first screen is
// that role's usual first job: technicians scan (Transaction), supervisors
// run the board (Work Orders), admins/owners review activity (History).
// Consumed by `auth.js`; every entry must also be allowed by PAGE_ACCESS
// above (landingPageForRole falls back if it is not).
const LANDING_PAGE_BY_ROLE = {
  technician: "transaction",
  supervisor: "work-orders",
  admin: "history",
  owner: "history",
};

const DEFAULT_LANDING_PAGE = "transaction";

// The post-login page for `role`, guarded so an unknown role -- or a landing
// page the role cannot actually reach -- still opens somewhere usable.
export function landingPageForRole(role) {
  const page = LANDING_PAGE_BY_ROLE[role];
  if (page && canAccessPage(role, page)) return page;
  return DEFAULT_LANDING_PAGE;
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
    // Find Item resets its visible results on every activation. It makes no
    // initial item request; full rows require Search / Load All / Scan.
    loadItems();
  } else if (pageName === "saved-users") {
    loadUsers();
  } else if (pageName === "mass-stage") {
    loadStages({ refreshReferenceData: true });
  } else if (pageName === "work-orders") {
    loadWorkOrders({ refreshReferenceData: true });
  } else if (pageName === "user-requests") {
    loadUserRequests();
  } else if (pageName === "admin-review") {
    loadAdminReview();
  } else if (pageName === "tools") {
    loadTools();
  }
}

navButtons.forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});
