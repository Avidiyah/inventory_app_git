// View: top-level page router for the SPA.
//
// Layer: views. Wires the nav buttons in `index.html` to the
// `.page` sections, toggling the `active` class so CSS shows the
// right one. Data-driven pages trigger their own loads on
// activation so the view never shows stale rows after a write
// elsewhere in the SPA.

import { loadTxnItems } from "./transactions.js";
import { loadHistory } from "./history.js";
import { loadItems } from "./items.js";
import { loadUsers } from "./users.js";

const navButtons = document.querySelectorAll(".nav-btn");
const pages = document.querySelectorAll(".page");

// Which roles may see each page. This is the single source of truth for
// nav visibility AND for the post-login boot in `auth.js`. It mirrors
// the backend route gates; the backend still enforces them.
export const PAGE_ACCESS = {
  "create-item": ["owner", "admin"],
  "saved-items": ["owner", "admin", "supervisor", "technician"],
  "create-user": ["owner", "admin", "supervisor"],
  "saved-users": ["owner", "admin", "supervisor"],
  "transaction": ["owner", "admin", "supervisor"],
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
  pages.forEach(page => {
    page.classList.toggle("active", page.id === `${pageName}-page`);
  });
  navButtons.forEach(btn => {
    btn.classList.toggle("active", btn.dataset.page === pageName);
  });

  if (pageName === "transaction") {
    loadTxnItems();
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
