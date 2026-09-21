// View: the User Hub's Timesheets tabpanel.
//
// Layer: views. Owns the panel's shell, its sub-nav, and both sub-features'
// lazy loads, caches and request counters -- the machinery that used to live
// in userHub.js beside four other tabs' copies of it.
//
// Three sub-features today:
//   hours   -- P2's read-only clocked-hours grid, Admin+ only, because it is
//              the pay record (D1).
//   compare -- P4a's **Charged vs clocked** grid, Admin+ for the same reason.
//   crew    -- the existing Supervisor+ charged-time grid,
//              `GET /hub/timesheets`.
//
// `hours` and `compare` read **one** payload from `GET /hub/attendance/week`,
// held in a single cache below. That is not an optimisation: two features
// fetching their own week could show payroll two different answers, and
// nothing downstream would notice the disagreement.
//
// Below Admin there is no sub-nav: one button is not a navigation, and the
// crew grid then renders exactly as it did before this module existed. P4b
// removes `crew` and retires `GET /hub/timesheets` (D6).
//
// The shell is built once and `initSubNav` wired once -- rebuilding the
// panel's innerHTML would drop that listener. Each feature renders into its
// own `.feature-panel`, so a repaint of one never disturbs the other.

import {
  apiAddAttendancePunch,
  apiDeleteAttendancePunch,
  apiEditAttendancePunch,
  apiGetHubAttendanceWeek,
  apiGetHubTimesheets,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { skeletonCard } from "../skeleton.js";
import { mountHubAttendanceCompare } from "./hubAttendanceCompare.js";
import { mountHubAttendanceHours } from "./hubAttendanceHours.js";
import { mountHubTimesheets } from "./hubTimesheets.js";
import { initSubNav } from "./subnav.js";

let viewerRole = null;

// One cache for both Admin features -- see the header.
let weekPayload = null;
let week = null;
let weekRequestId = 0;

let crewPayload = null;
let crewRange = null;
let crewRequestId = 0;

// userHub.js's own loading shape, kept identical here so the crew grid's
// first paint is the one it has always been.
function skeletonGrid(cardCount = 2, { lines = 6 } = {}) {
  return `<div class="skel-grid">${skeletonCard({ lines }).repeat(cardCount)}</div>`;
}

function canSeeHours(role) {
  return roleAtLeast(role, "admin");
}

function featurePanel(panelEl, feature) {
  return panelEl.querySelector(`.feature-panel[data-feature="${feature}"]`);
}

function buildShell(panelEl, role) {
  const nav = canSeeHours(role)
    ? `<nav class="sub-nav hub-sub-nav" aria-label="Timesheet views">
         <button type="button" class="sub-nav-btn active" data-feature="hours">Hours</button>
         <button type="button" class="sub-nav-btn" data-feature="compare">Charged vs clocked</button>
         <button type="button" class="sub-nav-btn" data-feature="crew">Crew time</button>
       </nav>`
    : "";
  const adminPanels = canSeeHours(role)
    ? `<section class="feature-panel" data-feature="hours"></section>`
      + `<section class="feature-panel" data-feature="compare" hidden></section>`
    : "";
  panelEl.innerHTML = `${nav}${adminPanels}<section class="feature-panel" data-feature="crew"${canSeeHours(role) ? " hidden" : ""}></section>`;
  panelEl.dataset.timesheetsRole = role;
  delete panelEl.dataset.activeFeature;
  initSubNav(panelEl, {
    onShow: (feature) => showFeature(panelEl, feature),
    // The initial switch must not fetch at build time: the caller shows the
    // opening feature itself, right after the shell exists.
    fireInitialOnShow: false,
  });
}

// --- The attendance week: Hours and Charged vs clocked -------------------

// The write path is deliberately dumb: call, then refetch the week. The
// grid holds no optimistic state, so a 409 leaves exactly what the server
// last said on screen (spec §6: "refetch after an edit").
async function write(panelEl, work) {
  try {
    await work();
    await loadWeek(panelEl);
  } catch (err) {
    const message = panelEl.querySelector(".punch-editor-message");
    if (message) {
      message.className = "punch-editor-message error";
      message.textContent = friendlyError(err, "Could not save that punch.");
    } else {
      // No editor open -- a "Looks right" click, whose refusal has nowhere
      // else to go, so it replaces the grid with the retryable load error.
      showWeekError(panelEl, err);
    }
  }
}

function renderHours(panelEl) {
  const mount = featurePanel(panelEl, "hours");
  if (!mount || !weekPayload) return;
  // The four write callbacks are passed only to an Admin, and the grid
  // renders an affordance only for a callback it was given -- so the floor
  // is expressed once, here, rather than re-derived inside the view.
  const writes = roleAtLeast(viewerRole, "admin")
    ? {
      onSavePunch: (id, values) => write(panelEl, () => apiEditAttendancePunch(id, values)),
      onAddPunch: (userId, values) => write(panelEl, () => apiAddAttendancePunch({ userId, ...values })),
      onDeletePunch: (id, reason) => write(panelEl, () => apiDeleteAttendancePunch(id, reason)),
      onClearReview: (id) => write(panelEl, () => apiEditAttendancePunch(id, { needsReview: false })),
    }
    : {};
  mountHubAttendanceHours(mount, weekPayload, {
    onWeekChange: changeWeek(panelEl),
    ...writes,
  });
}

// Both Admin features page the week through the same setter, so a step taken
// in one is already taken when the other is opened.
function changeWeek(panelEl) {
  return (nextWeek) => {
    week = nextWeek;
    void loadWeek(panelEl);
  };
}

function renderCompare(panelEl) {
  const mount = featurePanel(panelEl, "compare");
  if (!mount || !weekPayload) return;
  mountHubAttendanceCompare(mount, weekPayload, { onWeekChange: changeWeek(panelEl) });
}

// Paint whichever Admin feature is showing, from the one cached week.
function renderWeek(panelEl) {
  if (panelEl.dataset.activeFeature === "compare") renderCompare(panelEl);
  else renderHours(panelEl);
}

// Rendered into whichever Admin feature is showing: a failed load reported
// into a hidden panel is a blank sub-tab with no explanation.
function showWeekError(panelEl, err, feature = panelEl.dataset.activeFeature) {
  const mount = featurePanel(panelEl, feature === "compare" ? "compare" : "hours");
  if (!mount) return;
  const message = escapeHtml(friendlyError(err, "Could not load clocked hours."));
  mount.innerHTML = `<div class="hub-hours-load-error"><p class="hub-hours-message error">${message} <button type="button" class="secondary-btn hub-hours-retry">Retry</button></p></div>`;
  mount.querySelector(".hub-hours-retry")?.addEventListener("click", () => {
    void loadWeek(panelEl);
  });
}

async function loadWeek(panelEl) {
  const feature = panelEl.dataset.activeFeature === "compare" ? "compare" : "hours";
  const mount = featurePanel(panelEl, feature);
  if (!mount) return;
  const requestId = ++weekRequestId;
  if (!weekPayload) mount.innerHTML = skeletonGrid();
  try {
    const payload = await apiGetHubAttendanceWeek({ week });
    if (requestId !== weekRequestId) return;
    weekPayload = payload;
    week = payload.week_start;
    renderWeek(panelEl);
  } catch (err) {
    if (requestId !== weekRequestId) return;
    showWeekError(panelEl, err, feature);
  }
}

// --- Crew time (unchanged behaviour, moved) ------------------------------

function renderCrew(panelEl) {
  const mount = featurePanel(panelEl, "crew");
  if (!mount || !crewPayload) return;
  mountHubTimesheets(mount, crewPayload, {
    onWeekChange: (start, end) => void loadCrew(panelEl, { start, end }),
    isAdminPlus: roleAtLeast(viewerRole, "techfm_oa"),
  });
}

function showCrewError(panelEl, err, requestedRange) {
  const mount = featurePanel(panelEl, "crew");
  if (!mount) return;
  const message = escapeHtml(friendlyError(err, "Could not load timesheets."));
  let status = mount.querySelector(".hub-timesheet-message");
  if (!status) {
    mount.innerHTML = `<div class="hub-timesheet-load-error"><p class="hub-timesheet-message error"></p></div>`;
    status = mount.querySelector(".hub-timesheet-message");
  }
  status.className = "hub-timesheet-message error";
  status.innerHTML = `${message} <button type="button" class="secondary-btn hub-timesheet-retry">Retry</button>`;
  status.querySelector(".hub-timesheet-retry")?.addEventListener("click", () => {
    void loadCrew(panelEl, requestedRange);
  });
}

async function loadCrew(panelEl, { start = null, end = null } = {}) {
  const mount = featurePanel(panelEl, "crew");
  if (!mount) return;
  const requestedRange = { start, end };
  const requestId = ++crewRequestId;
  const existingStatus = mount.querySelector(".hub-timesheet-message");
  if (crewPayload && existingStatus) {
    existingStatus.className = "hub-timesheet-message";
    existingStatus.textContent = "Loading…";
  } else if (!crewPayload) {
    mount.innerHTML = skeletonGrid();
  }
  try {
    const payload = await apiGetHubTimesheets({ start, end });
    if (requestId !== crewRequestId) return;
    crewPayload = payload;
    crewRange = { start: payload.range.start, end: payload.range.end };
    renderCrew(panelEl);
  } catch (err) {
    if (requestId !== crewRequestId) return;
    showCrewError(panelEl, err, requestedRange);
  }
}

// --- The tab's two entry points ------------------------------------------

// Repaint from cache, or lazily fetch the first time a feature is opened.
// Both the sub-nav's `onShow` and a tab re-entry come through here, so
// switching back to a sub-tab already loaded never starts a second request.
function showFeature(panelEl, feature) {
  if (feature === "hours" || feature === "compare") {
    if (weekPayload) renderWeek(panelEl);
    else void loadWeek(panelEl);
  } else if (crewPayload) {
    renderCrew(panelEl);
  } else {
    void loadCrew(panelEl, crewRange || {});
  }
}

// Called on every render of the Timesheets tab. Builds the shell the first
// time (and whenever the viewer's role changes what the shell contains),
// then repaints or lazily loads whichever feature is showing.
export function renderTimesheetsTab(panelEl, { role } = {}) {
  if (!panelEl) return;
  viewerRole = role;
  if (panelEl.dataset.timesheetsRole !== role || !panelEl.querySelector(".feature-panel")) {
    buildShell(panelEl, role);
  }
  showFeature(panelEl, panelEl.dataset.activeFeature || (canSeeHours(role) ? "hours" : "crew"));
}

// A different person signed in, or this viewer no longer has the tab. Both
// caches go, both request counters move so an in-flight response for the
// previous viewer is discarded on arrival, and the panel is emptied.
export function resetTimesheetsTab(panelEl) {
  weekPayload = null;
  week = null;
  weekRequestId += 1;
  crewPayload = null;
  crewRange = null;
  crewRequestId += 1;
  viewerRole = null;
  if (!panelEl) return;
  delete panelEl.dataset.timesheetsRole;
  delete panelEl.dataset.activeFeature;
  panelEl.replaceChildren();
}
