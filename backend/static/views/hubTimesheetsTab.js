// View: the User Hub's Timesheets tabpanel -- one page, no sub-tabs.
//
// Layer: views. Owns the panel's shell and both payloads' lazy loads,
// caches and request counters. Admin+, because this is the pay record (D1).
//
// Top to bottom:
//   roster      -- who is on the clock now, from `GET /hub/attendance/live`
//   leaderboard -- the week's charged/uncharged hours and money, ranked; owns
//                  the page's week picker and CSV export
//   hours       -- the clocked-hours grid with the audited punch editor
//
// Leaderboard and hours read **one** payload from `GET /hub/attendance/week`:
// two features fetching their own week could show payroll two different
// answers. The roster is the exception -- "now" is a different question from
// "this week", polled and pushed on its own cadence.
//
// The shell is built once; each part renders into its own mount, so a roster
// repaint never disturbs an open punch editor.

import {
  apiAddAttendancePunch,
  apiDeleteAttendancePunch,
  apiEditAttendancePunch,
  apiGetHubAttendanceLive,
  apiGetHubAttendanceWeek,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { roleAtLeast } from "../roles.js";
import { skeletonCard } from "../skeleton.js";
import { mountHubAttendanceHours } from "./hubAttendanceHours.js";
import { destroyHubAttendanceRoster, mountHubAttendanceRoster } from "./hubAttendanceRoster.js";
import { mountHubTimesheetLeaderboard } from "./hubTimesheetLeaderboard.js";

let viewerRole = null;

// One cache for the leaderboard and the hours grid -- see the header.
let weekPayload = null;
let week = null;
let weekRequestId = 0;

// The roster's own cache, on its own cadence: the week is paged by hand and
// the strip is polled. Sharing one counter would let a week change discard
// a roster response that is still current.
let livePayload = null;
let liveRequestId = 0;
// The panel this module is mounted into, held so the module-level
// subscription below has something to refresh. Set on every render.
let hostPanel = null;

// userHub.js's own loading shape, kept identical here so the first paint is
// the one this tab has always had.
function skeletonGrid(cardCount = 2, { lines = 6 } = {}) {
  return `<div class="skel-grid">${skeletonCard({ lines }).repeat(cardCount)}</div>`;
}

function mountFor(panelEl, part) {
  return panelEl.querySelector(`.hub-timesheets-${part}`);
}

function buildShell(panelEl, role) {
  panelEl.innerHTML = `<div class="hub-timesheets-roster"></div>
    <div class="hub-timesheets-week"></div>`;
  panelEl.dataset.timesheetsRole = role;
}

// --- The attendance week: the leaderboard and Hours -----------------------

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

// Paint the leaderboard and the hours grid from the one cached week. Both
// mounts are (re)created here so a load error or skeleton that replaced the
// week area is cleared by the next good payload.
function renderWeek(panelEl) {
  const area = mountFor(panelEl, "week");
  if (!area || !weekPayload) return;
  area.innerHTML = `<div class="hub-timesheets-leaderboard"></div>
    <div class="hub-timesheets-hours"></div>`;
  mountHubTimesheetLeaderboard(mountFor(panelEl, "leaderboard"), weekPayload, {
    onWeekChange: changeWeek(panelEl),
  });
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
  mountHubAttendanceHours(mountFor(panelEl, "hours"), weekPayload, { weekNav: false, ...writes });
}

function changeWeek(panelEl) {
  return (nextWeek) => {
    week = nextWeek;
    void loadWeek(panelEl);
  };
}

function renderLive(panelEl) {
  const mount = mountFor(panelEl, "roster");
  if (mount && livePayload) mountHubAttendanceRoster(mount, livePayload);
}

// A roster failure is deliberately silent: it leaves the strip empty and the
// next poll tries again. Replacing a working page with a retry box because a
// decorative strip 500'd would be worse.
async function loadLive(panelEl) {
  const requestId = ++liveRequestId;
  try {
    const payload = await apiGetHubAttendanceLive();
    if (requestId !== liveRequestId) return;
    livePayload = payload;
    renderLive(panelEl);
  } catch (_err) {
    if (requestId !== liveRequestId) return;
  }
}

// Called by userHub.js on the hub's existing 60-second safety timer and on
// an `attendance.changed` envelope. Inert while the tab is hidden. The week
// is refetched only when no punch drill-down is open: a background repaint
// would otherwise close an Admin's editor mid-edit.
export function refreshTimesheetsLive(panelEl = hostPanel) {
  if (!panelEl || panelEl.hidden || !panelEl.querySelector(".hub-timesheets-week")) return;
  void loadLive(panelEl);
  if (!panelEl.querySelector(".hub-hours-detail-row")) void loadWeek(panelEl);
}

function showWeekError(panelEl, err) {
  const area = mountFor(panelEl, "week");
  if (!area) return;
  const message = escapeHtml(friendlyError(err, "Could not load clocked hours."));
  area.innerHTML = `<div class="hub-hours-load-error"><p class="hub-hours-message error">${message} <button type="button" class="secondary-btn hub-hours-retry">Retry</button></p></div>`;
  area.querySelector(".hub-hours-retry")?.addEventListener("click", () => {
    void loadWeek(panelEl);
  });
}

async function loadWeek(panelEl) {
  const area = mountFor(panelEl, "week");
  if (!area) return;
  const requestId = ++weekRequestId;
  if (!weekPayload) area.innerHTML = skeletonGrid();
  try {
    const payload = await apiGetHubAttendanceWeek({ week });
    if (requestId !== weekRequestId) return;
    weekPayload = payload;
    week = payload.week_start;
    renderWeek(panelEl);
  } catch (err) {
    if (requestId !== weekRequestId) return;
    showWeekError(panelEl, err);
  }
}

// --- The tab's entry points ----------------------------------------------

// Called on every render of the Timesheets tab. Builds the shell the first
// time (and whenever the viewer's role changes what the shell contains),
// then repaints or lazily loads.
export function renderTimesheetsTab(panelEl, { role } = {}) {
  if (!panelEl) return;
  viewerRole = role;
  hostPanel = panelEl;
  if (panelEl.dataset.timesheetsRole !== role || !panelEl.querySelector(".hub-timesheets-week")) {
    buildShell(panelEl, role);
  }
  // Repaint from cache, or lazily fetch the first time the tab is opened, so
  // re-entering the tab never starts a second week request.
  if (weekPayload) renderWeek(panelEl);
  else void loadWeek(panelEl);
  if (livePayload) renderLive(panelEl);
  else void loadLive(panelEl);
}

// A different person signed in, or this viewer no longer has the tab. Both
// caches go, both request counters move so an in-flight response for the
// previous viewer is discarded on arrival, the roster's tick is stopped, and
// the panel is emptied.
export function resetTimesheetsTab(panelEl) {
  weekPayload = null;
  week = null;
  weekRequestId += 1;
  livePayload = null;
  liveRequestId += 1;
  hostPanel = null;
  destroyHubAttendanceRoster();
  viewerRole = null;
  if (!panelEl) return;
  delete panelEl.dataset.timesheetsRole;
  panelEl.replaceChildren();
}

// Spec §6: this tab owns the `attendance.changed` subscription. Every punch
// write emits it (audience Admin), so a technician punching out moves the
// strip without waiting out the 60-second poll. Background by nature -- a
// socket signal, not a user action -- and inert unless this tab is showing.
subscribe("attendance.changed", ({ activePage }) => {
  if (activePage !== "user-hub") return;
  refreshTimesheetsLive();
});
