// View: User Hub tab shell.
//
// Layer: views. The landing page for every role (D4). Owns the one GET /hub
// fetch every tab reads from, the persistent clock widget above the tabs
// (mounted once, refreshed on every reload), and switching between the
// Dashboard and My Work Orders tab bodies. Role-specific dashboards
// (Supervisor/Admin) are P3/P4; every role sees this same shape for now,
// built from the same role-agnostic payload GET /hub already returns.

import { apiGetHub } from "../api.js";
import { friendlyError } from "../format.js";
import { mountHubClock, stopHubClockTicking } from "./hubClock.js";
import { mountHubDashboard, mountHubWorkOrders } from "./hubTechnician.js";

const tabButtons = document.querySelectorAll(".hub-tab");
const tabPanels = {
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
};
const clockMount = document.getElementById("hub-clock-mount");

let activeTab = "dashboard";
let latestPayload = null;

function showTab(name) {
  activeTab = name;
  tabButtons.forEach((btn) => {
    const on = btn.dataset.hubTab === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", String(on));
  });
  Object.entries(tabPanels).forEach(([key, panel]) => {
    panel.hidden = key !== name;
    panel.classList.toggle("active", key === name);
  });
  if (latestPayload) renderActiveTab();
}

function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.hubTab));
});

// Called by nav.js on every activation of the hub page. A fresh fetch on
// every entry (not a cache) matches the rest of the app's data-driven pages
// (loadWorkOrders, loadTools, ...) -- the hub is exactly the kind of page
// where "stale since I last looked" is the failure mode to avoid.
export async function loadUserHub() {
  try {
    latestPayload = await apiGetHub();
  } catch (err) {
    clockMount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your hub.")}</p>`;
    return;
  }
  document.getElementById("hub-tab-work-orders").textContent =
    `My Work Orders (${latestPayload.counts.assigned})`;
  mountHubClock(clockMount, latestPayload, { onChanged: refreshUserHub });
  renderActiveTab();
}

// Exposed so hubClock.js can ask for a fresh payload after a Start/Stop
// action changes the running session -- one fetch serves the clock and
// both tabs, so a start/stop refreshes all three consistently rather than
// only the widget that triggered it.
export async function refreshUserHub() {
  await loadUserHub();
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopHubClockTicking();
});
