// View: User Hub tab shell.
//
// Layer: views. The landing page for every role (D4). Owns the one GET /hub
// fetch every tab reads from, the persistent clock widget above the tabs
// (mounted once, refreshed on every reload), switching between the
// role-scoped tab bodies, and -- for supervisor+ viewers -- the crew board's
// freshness plus the lazily fetched Timesheets tab (spec §5.3, §6.2).
// Admin dashboards are P4; every role below TechFM OA sees this same shape
// for now, built from the same role-agnostic GET /hub payload.

import { apiGetHub, apiGetHubAdmin, apiGetHubCrew, apiGetHubTimesheets } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { roleAtLeast } from "../roles.js";
import { mountHubClock, startHubClockTicking, stopHubClockTicking } from "./hubClock.js";
import { mountHubDashboard, mountHubWorkOrders } from "./hubTechnician.js";
import { mountHubCrew } from "./hubSupervisor.js";
import { mountHubAdminSummary } from "./hubAdmin.js";
import { mountHubTimesheets } from "./hubTimesheets.js";

const HUB_PAGE = "user-hub";
const LABOR_SESSION_CHANGED_EVENT = "labor.session.changed";

// Spec §6.2: while the hub is the active page and the tab is visible, a full
// crew refetch every 60 seconds -- a safety net for a dropped envelope, on
// top of (not instead of) the `labor.session.changed` subscription below.
const CREW_SAFETY_REFRESH_MS = 60000;

const tabButtons = document.querySelectorAll(".hub-tab");
const tabPanels = {
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  timesheets: document.getElementById("hub-tabpanel-timesheets"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
};
const clockMount = document.getElementById("hub-clock-mount");
const timesheetsTabButton = document.getElementById("hub-tab-timesheets");

let activeTab = "dashboard";
let latestPayload = null;
let latestCrewPayload = null;
let crewRequestId = 0;
let crewSafetyTimer = null;
let latestAdminPayload = null;
let adminRequestId = 0;
let latestTimesheetPayload = null;
let timesheetRange = null;
let timesheetRequestId = 0;
let loadedUserId = null;

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

function adminMount() {
  return tabPanels.dashboard.querySelector("#hub-admin-mount");
}

function viewerCanSeeAdminTiles() {
  return Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, "techfm_oa");
}

// D16 (spec §5.4): the crew board is absent -- not an empty state -- for a
// viewer who isn't personally routed as the supervisor on at least one live
// work order. A plain Supervisor keeps P3a's original always-shown
// behavior, since an empty board is meaningful information about their own
// team; this only changes what an admin+ viewer with zero led work orders
// sees. The condition itself has no role special-case (spec's own wording):
// it reads `led.total`, the same field either viewer's payload carries.
function crewBoardShouldRender(payload) {
  return latestPayload?.user.role === "supervisor" || payload.led.total > 0;
}

// Repaints the crew board from whatever was last fetched, without a network
// call -- used after `mountHubDashboard` rebuilds the tab body (which wipes
// `#hub-crew-mount`) and on every tab switch back to Dashboard.
function renderCrew() {
  if (!latestCrewPayload) return;
  const mount = crewMount();
  if (!mount) return;
  if (!crewBoardShouldRender(latestCrewPayload)) {
    mount.innerHTML = "";
    return;
  }
  mountHubCrew(mount, latestCrewPayload, { isAdminPlus: viewerCanSeeAdminTiles() });
}

function renderAdmin() {
  if (!latestAdminPayload) return;
  const mount = adminMount();
  if (mount) mountHubAdminSummary(mount, latestAdminPayload);
}

function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderCrew();
    renderAdmin();
  } else if (activeTab === "timesheets") {
    if (latestTimesheetPayload) {
      mountHubTimesheets(tabPanels.timesheets, latestTimesheetPayload, {
        onWeekChange: (start, end) => void loadTimesheets({ start, end }),
        isAdminPlus: viewerCanSeeAdminTiles(),
      });
    } else {
      void loadTimesheets(timesheetRange || {});
    }
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}

function setTimesheetsTabVisible(visible) {
  if (!timesheetsTabButton) return;
  timesheetsTabButton.hidden = !visible;
  timesheetsTabButton.classList.toggle("hidden", !visible);
}

function showTimesheetLoadError(mount, err, requestedRange) {
  const message = escapeHtml(friendlyError(err, "Could not load timesheets."));
  let status = mount.querySelector(".hub-timesheet-message");
  if (!status) {
    mount.innerHTML = `<div class="hub-timesheet-load-error"><p class="hub-timesheet-message error"></p></div>`;
    status = mount.querySelector(".hub-timesheet-message");
  }
  status.className = "hub-timesheet-message error";
  status.innerHTML = `${message} <button type="button" class="secondary-btn hub-timesheet-retry">Retry</button>`;
  status.querySelector(".hub-timesheet-retry")?.addEventListener("click", () => {
    void loadTimesheets(requestedRange);
  });
}

async function loadTimesheets({ start = null, end = null } = {}) {
  const mount = tabPanels.timesheets;
  if (!mount) return;
  const requestedRange = { start, end };
  const requestId = ++timesheetRequestId;
  const existingStatus = mount.querySelector(".hub-timesheet-message");
  if (latestTimesheetPayload && existingStatus) {
    existingStatus.className = "hub-timesheet-message";
    existingStatus.textContent = "Loading…";
  } else {
    mount.innerHTML = `<p class="hint hub-timesheet-message">Loading…</p>`;
  }
  try {
    const payload = await apiGetHubTimesheets({ start, end });
    if (requestId !== timesheetRequestId) return;
    latestTimesheetPayload = payload;
    timesheetRange = { start: payload.range.start, end: payload.range.end };
    mountHubTimesheets(mount, payload, {
      onWeekChange: (rangeStart, rangeEnd) =>
        void loadTimesheets({ start: rangeStart, end: rangeEnd }),
      isAdminPlus: viewerCanSeeAdminTiles(),
    });
  } catch (err) {
    if (requestId !== timesheetRequestId) return;
    showTimesheetLoadError(mount, err, requestedRange);
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
    renderCrew();
  } catch (err) {
    if (requestId !== crewRequestId) return;
    if (background) return;
    mount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your crew.")}</p>`;
  }
}

// Mirrors `refreshCrew` -- same background/foreground error-handling split.
async function refreshAdmin({ background = false } = {}) {
  const mount = adminMount();
  if (!mount) return;
  const requestId = ++adminRequestId;
  try {
    const payload = await apiGetHubAdmin();
    if (requestId !== adminRequestId) return;
    latestAdminPayload = payload;
    mountHubAdminSummary(mount, payload);
  } catch (err) {
    if (requestId !== adminRequestId) return;
    if (background) return;
    mount.innerHTML = `<p class="error">${friendlyError(err, "Could not load the company summary.")}</p>`;
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
    if (viewerCanSeeAdminTiles()) void refreshAdmin({ background: true });
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
  let payload;
  try {
    payload = await apiGetHub();
  } catch (err) {
    clockMount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your hub.")}</p>`;
    return;
  }
  const nextUserId = String(payload.user.id);
  const userChanged = loadedUserId !== nextUserId;
  const canViewSupervisorTabs = roleAtLeast(payload.user.role, "supervisor");
  const canViewAdminTiles = roleAtLeast(payload.user.role, "techfm_oa");
  if (userChanged || !canViewSupervisorTabs) {
    latestCrewPayload = null;
    latestTimesheetPayload = null;
    timesheetRange = null;
    crewRequestId += 1;
    timesheetRequestId += 1;
    tabPanels.timesheets.replaceChildren();
  }
  if (userChanged || !canViewAdminTiles) {
    latestAdminPayload = null;
    adminRequestId += 1;
  }
  if (userChanged) activeTab = "dashboard";
  if (!canViewSupervisorTabs && activeTab === "timesheets") activeTab = "dashboard";
  loadedUserId = nextUserId;
  latestPayload = payload;
  setTimesheetsTabVisible(canViewSupervisorTabs);
  // P4 Tab 3 (spec §5.4): for a techfm_oa+ viewer this tab is an embedded,
  // unscoped company-wide list -- `apiListWorkOrders` already returns every
  // live work order for that role tier (`_scoped_to_user`), so "My Work
  // Orders (0)" would misreport both the scope and the count.
  document.getElementById("hub-tab-work-orders").textContent = canViewAdminTiles
    ? "Work Orders"
    : `My Work Orders (${latestPayload.counts.assigned})`;
  mountHubClock(clockMount, latestPayload, { onChanged: refreshUserHub });
  showTab(activeTab);

  if (canViewSupervisorTabs) {
    await refreshCrew();
    startCrewSafetyRefresh();
  } else {
    stopCrewSafetyRefresh();
  }

  if (canViewAdminTiles) {
    await refreshAdmin();
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
  void refreshCrew({ background: true });
  if (viewerCanSeeAdminTiles()) void refreshAdmin({ background: true });
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
