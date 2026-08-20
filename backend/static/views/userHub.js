// View: User Hub tab shell.
//
// Layer: views. The landing page for every role (D4). Owns the one GET /hub
// fetch every tab reads from, the persistent clock widget above the tabs
// (mounted once, refreshed on every reload), switching between the
// Dashboard and My Work Orders tab bodies, and -- for supervisor+ viewers --
// the crew board's own GET /hub/crew fetch and its freshness (spec §5.3, §6.2).
// Admin dashboards are P4; every role below TechFM OA sees this same shape
// for now, built from the same role-agnostic GET /hub payload.

import { apiGetHub, apiGetHubCrew } from "../api.js";
import { friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { roleAtLeast } from "../roles.js";
import { mountHubClock, startHubClockTicking, stopHubClockTicking } from "./hubClock.js";
import { mountHubDashboard, mountHubWorkOrders } from "./hubTechnician.js";
import { mountHubCrew } from "./hubSupervisor.js";

const HUB_PAGE = "user-hub";
const LABOR_SESSION_CHANGED_EVENT = "labor.session.changed";

// Spec §6.2: while the hub is the active page and the tab is visible, a full
// crew refetch every 60 seconds -- a safety net for a dropped envelope, on
// top of (not instead of) the `labor.session.changed` subscription below.
const CREW_SAFETY_REFRESH_MS = 60000;

const tabButtons = document.querySelectorAll(".hub-tab");
const tabPanels = {
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
};
const clockMount = document.getElementById("hub-clock-mount");

let activeTab = "dashboard";
let latestPayload = null;
let latestCrewPayload = null;
let crewRequestId = 0;
let crewSafetyTimer = null;

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

function crewMount() {
  return tabPanels.dashboard.querySelector("#hub-crew-mount");
}

// Repaints the crew board from whatever was last fetched, without a network
// call -- used after `mountHubDashboard` rebuilds the tab body (which wipes
// `#hub-crew-mount`) and on every tab switch back to Dashboard.
function renderCrew() {
  if (!latestCrewPayload) return;
  const mount = crewMount();
  if (mount) mountHubCrew(mount, latestCrewPayload);
}

function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderCrew();
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}

// `background: true` mirrors `adminReview.js::loadAdminReview` -- a
// socket-driven or safety-timer refresh keeps the last good board on
// failure rather than blanking it (spec §10); only the first, foreground
// fetch shows an inline error.
async function refreshCrew({ background = false } = {}) {
  const mount = crewMount();
  if (!mount) return;
  const requestId = ++crewRequestId;
  try {
    const payload = await apiGetHubCrew();
    if (requestId !== crewRequestId) return;
    latestCrewPayload = payload;
    mountHubCrew(mount, payload);
  } catch (err) {
    if (requestId !== crewRequestId) return;
    if (background) return;
    mount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your crew.")}</p>`;
  }
}

function stopCrewSafetyRefresh() {
  if (crewSafetyTimer !== null) {
    clearInterval(crewSafetyTimer);
    crewSafetyTimer = null;
  }
}

function startCrewSafetyRefresh() {
  stopCrewSafetyRefresh();
  crewSafetyTimer = setInterval(() => {
    if (document.hidden) return;
    void refreshCrew({ background: true });
  }, CREW_SAFETY_REFRESH_MS);
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

  if (roleAtLeast(latestPayload.user.role, "supervisor")) {
    await refreshCrew();
    startCrewSafetyRefresh();
  } else {
    stopCrewSafetyRefresh();
  }
}

// Exposed so hubClock.js can ask for a fresh payload after a Start/Stop
// action changes the running session -- one fetch serves the clock and
// both tabs, so a start/stop refreshes all three consistently rather than
// only the widget that triggered it.
export async function refreshUserHub() {
  await loadUserHub();
}

// A crew member's clock started or stopped -- always `id: null` (a
// membership change to the board, not one card's field), so any event or a
// reconnect (missed events while the socket was down) means "refetch."
// Background: this is a socket signal, not a user action.
subscribe(LABOR_SESSION_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== HUB_PAGE) return;
  return refreshCrew({ background: true });
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopHubClockTicking();
    stopCrewSafetyRefresh();
    return;
  }
  if (!document.getElementById("user-hub-page").classList.contains("active")) return;
  startHubClockTicking();
  if (latestPayload && roleAtLeast(latestPayload.user.role, "supervisor")) {
    startCrewSafetyRefresh();
  }
});
