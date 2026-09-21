// View: the User Hub's Timesheets tabpanel.
//
// Layer: views. Owns the panel's shell, its sub-nav, and both sub-features'
// lazy loads, caches and request counters -- the machinery that used to live
// in userHub.js beside four other tabs' copies of it.
//
// Two sub-features, both **Admin+**, because this tab is the pay record (D1):
//   hours   -- P2's clocked-hours grid with the audited punch editor.
//   compare -- P4a's **Charged vs clocked** grid, under P4b's live roster.
//
// Both read **one** payload from `GET /hub/attendance/week`, held in a single
// cache below. That is not an optimisation: two features fetching their own
// week could show payroll two different answers, and nothing downstream would
// notice the disagreement. The roster is the exception -- its own payload from
// `GET /hub/attendance/live`, on its own cadence, because "now" is a different
// question from "this week".
//
// `GET /hub/timesheets` and the Supervisor crew grid it fed are gone (D6);
// a Supervisor keeps the Dashboard crew board.
//
// The shell is built once and `initSubNav` wired once -- rebuilding the
// panel's innerHTML would drop that listener. Each feature renders into its
// own `.feature-panel`, so a repaint of one never disturbs the other.

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
import { mountHubAttendanceCompare } from "./hubAttendanceCompare.js";
import { mountHubAttendanceHours } from "./hubAttendanceHours.js";
import { destroyHubAttendanceRoster } from "./hubAttendanceRoster.js";
import { initSubNav } from "./subnav.js";

let viewerRole = null;

// One cache for both Admin features -- see the header.
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

function featurePanel(panelEl, feature) {
  return panelEl.querySelector(`.feature-panel[data-feature="${feature}"]`);
}

function buildShell(panelEl, role) {
  panelEl.innerHTML = `<nav class="sub-nav hub-sub-nav" aria-label="Timesheet views">
      <button type="button" class="sub-nav-btn active" data-feature="hours">Hours</button>
      <button type="button" class="sub-nav-btn" data-feature="compare">Charged vs clocked</button>
    </nav>
    <section class="feature-panel" data-feature="hours"></section>
    <section class="feature-panel" data-feature="compare" hidden></section>`;
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
  mountHubAttendanceCompare(mount, weekPayload, {
    onWeekChange: changeWeek(panelEl),
    live: livePayload,
  });
}

// A roster failure is deliberately silent: it leaves `livePayload` null, the
// comparison renders without its strip, and the next poll tries again. The
// alternative -- replacing a working grid with a retry box because a
// decorative strip 500'd -- is worse.
async function loadLive(panelEl) {
  const requestId = ++liveRequestId;
  try {
    const payload = await apiGetHubAttendanceLive();
    if (requestId !== liveRequestId) return;
    livePayload = payload;
    if (panelEl.dataset.activeFeature === "compare") renderCompare(panelEl);
  } catch (_err) {
    if (requestId !== liveRequestId) return;
  }
}

// Called by userHub.js on the hub's existing 60-second safety timer and on
// an `attendance.changed` envelope. A no-op unless the comparison is the
// open sub-tab: nothing else on screen reads either payload.
export function refreshTimesheetsLive(panelEl = hostPanel) {
  if (!panelEl || panelEl.dataset.activeFeature !== "compare") return;
  void loadLive(panelEl);
  void loadWeek(panelEl);
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

// --- The tab's two entry points ------------------------------------------

// Repaint from cache, or lazily fetch the first time a feature is opened.
// Both the sub-nav's `onShow` and a tab re-entry come through here, so
// switching back to a sub-tab already loaded never starts a second request.
function showFeature(panelEl, feature) {
  // The strip only exists on the comparison. Leaving that sub-tab takes its
  // tick with it: an interval running behind a hidden panel is a timer this
  // module would then have to remember to stop somewhere else.
  if (feature !== "compare") destroyHubAttendanceRoster();
  if (weekPayload) renderWeek(panelEl);
  else void loadWeek(panelEl);
  if (feature === "compare" && !livePayload) void loadLive(panelEl);
}

// Called on every render of the Timesheets tab. Builds the shell the first
// time (and whenever the viewer's role changes what the shell contains),
// then repaints or lazily loads whichever feature is showing.
export function renderTimesheetsTab(panelEl, { role } = {}) {
  if (!panelEl) return;
  viewerRole = role;
  hostPanel = panelEl;
  if (panelEl.dataset.timesheetsRole !== role || !panelEl.querySelector(".feature-panel")) {
    buildShell(panelEl, role);
  }
  showFeature(panelEl, panelEl.dataset.activeFeature || "hours");
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
  delete panelEl.dataset.activeFeature;
  panelEl.replaceChildren();
}

// Spec §6: this sub-tab owns the `attendance.changed` subscription. Every
// punch write emits it (audience Admin), so a technician punching out moves
// the strip without waiting out the 60-second poll. Background by nature --
// a socket signal, not a user action -- and inert unless the comparison is
// the open sub-tab.
subscribe("attendance.changed", ({ activePage }) => {
  if (activePage !== "user-hub") return;
  refreshTimesheetsLive();
});
