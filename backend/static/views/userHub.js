// View: User Hub tab shell.
//
// Layer: views. The landing page for every role (D4). Owns the one GET /hub
// fetch every tab reads from, the persistent clock widget above the tabs
// (mounted once, refreshed on every reload), switching between the
// role-scoped tab bodies, and -- for supervisor+ viewers -- the crew board's
// freshness (spec §5.3, §6.2). TechFM OA+ additionally receives the lazy
// Admin summary and Graphs tab; Admin+ receives the report and the lazily
// fetched Timesheets tab, which is the pay record (D6); lower roles keep the
// role-agnostic GET /hub shape.

import { apiGetAttendanceMe, apiGetHub, apiGetHubAdmin, apiGetHubCrew, apiGetHubGraphs, apiGetHubReport } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { connectHubLive, createFeed, startHubLive, stopHubLive } from "./hubLive.js";
import { roleAtLeast } from "../roles.js";
import { mountHubClock, startHubClockTicking, stopHubClockTicking } from "./hubClock.js";
import { mountHubHome } from "./hubHome.js";
import {
  mountHubDashboard,
  mountHubWorkOrders,
  refreshHubWorkOrders,
} from "./hubTechnician.js";
import { mountHubPriorities } from "./hubPriorities.js";
import { mountHubCrew } from "./hubSupervisor.js";
import { mountHubAdminSummary } from "./hubAdmin.js";
import { startHubRosterTicking, stopHubRosterTicking } from "./hubAttendanceRoster.js";
import { refreshTimesheetsLive, renderTimesheetsTab, resetTimesheetsTab } from "./hubTimesheetsTab.js";
import { renderLeaderboardsTab, resetLeaderboardsTab } from "./hubLeaderboardsTab.js";
import { destroyHubGraphs, mountHubGraphs } from "./hubGraphs.js";
import { mountHubReport, renderReportError, renderReportSkeleton } from "./hubReport.js";
import { openWorkOrdersFilteredByDistribution } from "./workOrders.js";
import { showPage } from "./nav.js";
import { skeletonCard } from "../skeleton.js";
import { syncSectionPicker } from "./hubPicker.js";

const tabButtons = document.querySelectorAll(".hub-tab");
const tabPanels = {
  home: document.getElementById("hub-tabpanel-home"),
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  timesheets: document.getElementById("hub-tabpanel-timesheets"),
  leaderboards: document.getElementById("hub-tabpanel-leaderboards"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
  graphs: document.getElementById("hub-tabpanel-graphs"),
  report: document.getElementById("hub-tabpanel-report"),
};
const clockMount = document.getElementById("hub-clock-mount");
const timesheetsTabButton = document.getElementById("hub-tab-timesheets");
const leaderboardsTabButton = document.getElementById("hub-tab-leaderboards");
const graphsTabButton = document.getElementById("hub-tab-graphs");
const reportTabButton = document.getElementById("hub-tab-report");

let activeTab = "home";
let latestPayload = null;
let latestAttendance = null;
let latestCrewPayload = null;
// A foreground crew/admin failure, held until the Dashboard body exists to
// show it in. The fetches run while the hub is on Home, so the mount they
// would write into is usually not there yet -- without this the tab would
// open silently empty instead of explaining itself.
let crewError = null;
let adminError = null;
let latestAdminPayload = null;
let latestGraphsPayload = null;
let graphWeeks = 12;
let latestReportPayload = null;
// The Monday the Report tab is showing; null is the week in progress. Kept
// across tab re-entry (the re-fetch is for freshness, not a reset) and
// cleared with the rest of the report state on a user change.
let reportWeek = null;
let loadedUserId = null;

// Hub tabs are card grids, so their in-flight state is a grid of skeleton
// cards rather than one block -- the tab keeps roughly the height it will
// have once the payload lands, so the page doesn't jump on arrival.
function hubSkeletonGrid(cardCount = 4, { lines = 3 } = {}) {
  return `<div class="skel-grid">${skeletonCard({ lines }).repeat(cardCount)}</div>`;
}

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
  syncSectionPicker(name);
  if (latestPayload) renderActiveTab();
}

function crewMount() {
  return tabPanels.dashboard.querySelector("#hub-crew-mount");
}

function adminMount() {
  return tabPanels.dashboard.querySelector("#hub-admin-mount");
}

function priorityMount() {
  return tabPanels.dashboard.querySelector("#hub-priorities-mount");
}

function renderPriorities() {
  if (!latestPayload) return;
  const mount = priorityMount();
  if (!mount) return;
  mountHubPriorities(mount, {
    role: latestPayload.user.role,
    personal: latestPayload.priority,
    crew: latestCrewPayload?.priority,
    admin: latestAdminPayload?.priority,
  });
}

function viewerCanSeeAdminTiles() {
  return Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, "techfm_oa");
}

// Admin, not TechFM OA -- the one place this app draws the line above OA, and
// it matches `GET /hub/report`'s own floor. A TechFM OA holds the rest of the
// admin toolkit (the tiles above, Graphs, the work-order export) but not this.
function viewerIsAdmin() {
  return Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, "admin");
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
  const mount = crewMount();
  if (!mount) return;
  if (crewError) {
    mount.innerHTML = `<p class="error">${friendlyError(crewError, "Could not load your crew.")}</p>`;
    return;
  }
  if (!latestCrewPayload) return;
  if (!crewBoardShouldRender(latestCrewPayload)) {
    mount.innerHTML = "";
    renderPriorities();
    return;
  }
  mountHubCrew(mount, latestCrewPayload, { isAdminPlus: viewerCanSeeAdminTiles() });
  renderPriorities();
}

function renderAdmin() {
  const mount = adminMount();
  if (!mount) return;
  if (adminError) {
    mount.innerHTML = `<p class="error">${friendlyError(adminError, "Could not load the company summary.")}</p>`;
    return;
  }
  if (!latestAdminPayload) return;
  mountHubAdminSummary(mount, latestAdminPayload);
  renderPriorities();
}

// The clock node is reparented, not re-rendered: moving it preserves
// hubClock.js's state and its delegated listener (the property
// placeClockMount relied on when it moved the widget for Admins).
function renderHome() {
  if (!latestPayload) return;
  mountHubHome(tabPanels.home, latestPayload, latestAttendance, { onChanged: refreshUserHub });
  const slot = tabPanels.home.querySelector("#hub-home-clock-slot");
  if (slot) {
    clockMount.hidden = false;
    slot.appendChild(clockMount);
  }
  mountHubClock(clockMount, latestPayload, { onChanged: refreshUserHub });
}

function renderActiveTab() {
  if (activeTab === "home") {
    renderHome();
  } else if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderPriorities();
    renderCrew();
    renderAdmin();
  } else if (activeTab === "timesheets") {
    renderTimesheetsTab(tabPanels.timesheets, { role: latestPayload.user.role });
  } else if (activeTab === "leaderboards") {
    renderLeaderboardsTab(tabPanels.leaderboards);
  } else if (activeTab === "graphs") {
    if (latestGraphsPayload) renderGraphs();
    else void loadGraphs();
  } else if (activeTab === "report") {
    // Re-fetched on every tab re-entry, matching Graphs: the week in progress
    // does not need a socket, but it should not be stale either.
    if (latestReportPayload) renderReport();
    void loadReport({ background: Boolean(latestReportPayload) });
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}

function renderGraphs() {
  const mount = tabPanels.graphs;
  if (!mount || !latestGraphsPayload) return;
  // hubGraphs.js keeps what the viewer has open (grouping, pop-up, drill
  // path) across these re-mounts; `destroyHubGraphs` forgets it.
  mountHubGraphs(mount, latestGraphsPayload, {
    onWeekChange: (weeks) => {
      graphWeeks = weeks;
      void loadGraphs();
    },
    onDistributionClick: (filters) => {
      openWorkOrdersFilteredByDistribution(filters);
      showPage("work-orders");
    },
  });
}

// Timesheets is Team Lead+ (they edit hours); Leaderboards, which prices
// them, stays Admin+.
function setTabVisible(button, visible) {
  if (!button) return;
  button.hidden = !visible;
  button.classList.toggle("hidden", !visible);
}

function renderReport() {
  const mount = tabPanels.report;
  if (!mount || !latestReportPayload) return;
  mountHubReport(mount, latestReportPayload, {
    onSelectWeek: (week) => {
      reportWeek = week;
      void loadReport();
    },
  });
}

function showGraphLoadError(mount, err) {
  const message = escapeHtml(friendlyError(err, "Could not load graphs."));
  mount.innerHTML = `<div class="hub-graphs-load-error"><p class="error">${message}</p><button type="button" class="secondary-btn hub-graphs-retry">Retry</button></div>`;
  mount.querySelector(".hub-graphs-retry")?.addEventListener("click", () => void loadGraphs());
}

// One coalesced feed per payload (W7 rule 6). Events, reconnects and the
// 60 s timer reach them through hubLive.js; tab entries and own actions call
// them directly. A background failure keeps the last good render; only a
// foreground one paints an error.
const isRole = (min) => Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, min);

const personalFeed = createFeed(apiGetHub, (payload) => {
  latestPayload = payload;
  renderWorkOrdersTabLabel();
  if (activeTab === "dashboard") mountHubDashboard(tabPanels.dashboard, latestPayload);
  else if (activeTab === "work-orders") refreshHubWorkOrders();
  else if (activeTab === "home") renderHome();
  renderPriorities();
  renderCrew();
  renderAdmin();
}, { when: () => Boolean(latestPayload) });

const attendanceFeed = createFeed(apiGetAttendanceMe, (attendance) => {
  latestAttendance = attendance;
  if (activeTab === "home") renderHome();
}, { when: () => Boolean(latestPayload) });

const crewFeed = createFeed(apiGetHubCrew, (payload) => {
  latestCrewPayload = payload;
  crewError = null;
  renderCrew();
}, {
  when: () => isRole("supervisor"),
  onError: (err, { background }) => {
    if (background) return;
    crewError = err;
    renderCrew();
  },
});

const adminFeed = createFeed(apiGetHubAdmin, (payload) => {
  latestAdminPayload = payload;
  adminError = null;
  renderAdmin();
}, {
  when: () => viewerCanSeeAdminTiles(),
  onError: (err, { background }) => {
    if (background) return;
    adminError = err;
    renderAdmin();
  },
});

// A response for a range the viewer has since changed is dropped; the range
// change queued its own rerun.
async function fetchGraphs() {
  const asked = graphWeeks;
  const payload = await apiGetHubGraphs({ weeks: asked });
  return asked === graphWeeks ? payload : null;
}

const graphsFeed = createFeed(fetchGraphs, (payload) => {
  if (!payload) return;
  latestGraphsPayload = payload;
  graphWeeks = payload.weeks;
  if (activeTab === "graphs") renderGraphs();
}, {
  when: () => viewerCanSeeAdminTiles() && activeTab === "graphs",
  onError: (err, { background }) => {
    if (background || latestGraphsPayload) return;
    showGraphLoadError(tabPanels.graphs, err);
  },
});

// A refresh over an already-rendered report keeps the last good one.
const reportFeed = createFeed(() => apiGetHubReport({ week: reportWeek }), (payload) => {
  latestReportPayload = payload;
  if (activeTab === "report") renderReport();
}, {
  when: () => viewerIsAdmin() && activeTab === "report",
  onError: (err, { background }) => {
    if (background || latestReportPayload) return;
    renderReportError(tabPanels.report, err, () => void loadReport());
  },
});

// The crew mount may not exist yet (the hub opens on Home); the fetch still
// runs and `renderCrew` paints it when Dashboard opens.
function refreshCrew() {
  const mount = crewMount();
  if (mount && !latestCrewPayload) mount.innerHTML = skeletonCard({ lines: 4 });
  return crewFeed.run();
}

function loadGraphs({ background = false } = {}) {
  if (!latestGraphsPayload && !background && viewerCanSeeAdminTiles()) tabPanels.graphs.innerHTML = hubSkeletonGrid(4);
  return graphsFeed.run({ background });
}

function loadReport({ background = false } = {}) {
  if (!latestReportPayload && !background && viewerIsAdmin()) renderReportSkeleton(tabPanels.report);
  return reportFeed.run({ background });
}

connectHubLive({
  personal: personalFeed,
  attendance: attendanceFeed,
  crew: crewFeed,
  admin: adminFeed,
  graphs: graphsFeed,
  // Closed weeks are frozen records (spec rule 7): only the week in progress
  // follows events.
  report: { run: (opts) => (reportWeek === null ? reportFeed.run(opts) : Promise.resolve()) },
  // The Timesheets tab owns its `attendance.changed` subscription and its own
  // request guards; the timer and reconnect reach it here.
  timesheets: { run: () => { if (activeTab === "timesheets") refreshTimesheetsLive(tabPanels.timesheets); return Promise.resolve(); } },
});

// The count on the "My Work Orders" tab, rendered from whatever payload is
// current. Called on every path that replaces `latestPayload` -- the initial
// load *and* each background refresh -- because the number is the tab's only
// signal while the tab is closed, and a count that only updates on a full page
// re-entry is not a live count.
//
// `mine_total`, not `counts.assigned`: the latter is worker assignment alone,
// so a Supervisor whose work is all routed to them read "(0)" over a list that
// had cards in it. `mine_total` is built from the same predicate the tab's
// card list filters on (`work_orders.mine_predicate`).
//
// P4 Tab 3 (spec §5.4): for a techfm_oa+ viewer this tab is an embedded,
// unscoped company-wide list -- `apiListWorkOrders` already returns every live
// work order for that role tier (`_scoped_to_user`), so any personal count
// would misreport both the scope and the number. That tab keeps a bare label.
function renderWorkOrdersTabLabel() {
  const tab = document.getElementById("hub-tab-work-orders");
  if (!tab || !latestPayload) return;
  tab.textContent = viewerCanSeeAdminTiles()
    ? "Work Orders"
    : `My Work Orders (${latestPayload.mine_total})`;
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    showTab(btn.dataset.hubTab);
    if (btn.dataset.hubTab === "graphs") void loadGraphs({ background: Boolean(latestGraphsPayload) });
  });
});

// Called by nav.js on every activation of the hub page. A fresh fetch on
// every entry (not a cache) matches the rest of the app's data-driven pages
// (loadWorkOrders, loadTools, ...) -- the hub is exactly the kind of page
// where "stale since I last looked" is the failure mode to avoid.
// Select a tab from outside the hub (the work-order Back path, E8).
export function openHubTab(name) { showTab(name); }

export async function loadUserHub() {
  let payload;
  // A page entry is visible: lift a suspension left by a hide on another page.
  startHubClockTicking();
  // First entry only: Home is empty until the payload lands, so it gets
  // structure to look at. On a return visit the previous render is still
  // mounted and is better than a skeleton. Safe to overwrite: the clock
  // mount is only reparented into Home once `renderHome` has run, which
  // needs the payload this is waiting for.
  if (!latestPayload) tabPanels.home.innerHTML = hubSkeletonGrid(3);
  try {
    payload = await apiGetHub();
  } catch (err) {
    clockMount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your hub.")}</p>`;
    return;
  }
  const nextUserId = String(payload.user.id);
  const userChanged = loadedUserId !== nextUserId;
  const canViewSupervisorTabs = roleAtLeast(payload.user.role, "supervisor");
  // Team Leads edit anyone's hours, so they get Timesheets; the money tabs
  // (Leaderboards, Report) stay Admin+.
  const canViewTimesheets = canViewSupervisorTabs;
  const canViewLeaderboards = roleAtLeast(payload.user.role, "admin");
  const canViewAdminTiles = roleAtLeast(payload.user.role, "techfm_oa");
  const canViewReport = roleAtLeast(payload.user.role, "admin");
  if (userChanged || !canViewSupervisorTabs) {
    latestCrewPayload = null;
    crewError = null;
    crewFeed.reset();
  }
  if (userChanged || !canViewTimesheets) resetTimesheetsTab(tabPanels.timesheets);
  if (userChanged || !canViewLeaderboards) resetLeaderboardsTab(tabPanels.leaderboards);
  if (userChanged || !canViewAdminTiles) {
    latestAdminPayload = null;
    adminError = null;
    adminFeed.reset();
    latestGraphsPayload = null;
    graphsFeed.reset();
    graphWeeks = 12;
    destroyHubGraphs();
    tabPanels.graphs.replaceChildren();
  }
  // Reset with the admin state, not after `showTab`: otherwise a role change
  // renders the previous Admin's report for one frame.
  if (userChanged || !canViewReport) {
    latestReportPayload = null;
    reportFeed.reset();
    reportWeek = null;
    tabPanels.report.replaceChildren();
  }
  if (userChanged) {
    personalFeed.reset();
    attendanceFeed.reset();
    activeTab = "home";
    latestAttendance = null;
  }
  if (!canViewTimesheets && activeTab === "timesheets") activeTab = "home";
  if (!canViewLeaderboards && activeTab === "leaderboards") activeTab = "home";
  if (!canViewAdminTiles && activeTab === "graphs") activeTab = "home";
  if (!canViewReport && activeTab === "report") activeTab = "home";
  loadedUserId = nextUserId;
  latestPayload = payload;
  setTabVisible(timesheetsTabButton, canViewTimesheets);
  setTabVisible(leaderboardsTabButton, canViewLeaderboards);
  setTabVisible(graphsTabButton, canViewAdminTiles);
  setTabVisible(reportTabButton, canViewReport);
  renderWorkOrdersTabLabel();
  // Every role has a shift, Admin included. A failure is not fatal to the
  // page: hubHome renders a retry inside the punch card and the work-order
  // clock beside it still mounts.
  try {
    latestAttendance = await apiGetAttendanceMe();
  } catch (_err) {
    latestAttendance = null;
  }
  showTab(activeTab);

  if (canViewSupervisorTabs) {
    await refreshCrew();
  }
  startHubLive();

  if (canViewAdminTiles) {
    await adminFeed.run();
  }
}

// Exposed so hubClock.js can ask for a fresh payload after a Start/Stop
// action changes the running session -- one fetch serves the clock and
// both tabs, so a start/stop refreshes all three consistently rather than
// only the widget that triggered it.
export async function refreshUserHub() {
  await loadUserHub();
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopHubClockTicking();
    stopHubRosterTicking();
    stopHubLive();
    return;
  }
  if (!document.getElementById("user-hub-page").classList.contains("active")) return;
  startHubClockTicking();
  startHubRosterTicking();
  if (latestPayload) startHubLive();
});
