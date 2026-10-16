// View: the User Hub's Timesheets tabpanel -- one page, no sub-tabs.
//
// Layer: views. Owns the panel's shell and both payloads' lazy loads,
// caches and request counters. Admin+, because this is the pay record (D1).
//
// Top to bottom:
//   roster      -- who is on the clock now, from `GET /hub/attendance/live`
//   actions     -- Mark all reviewed and the CSV export (payroll actions)
//   days        -- the week picker and seven day cards; a card opens the
//                  day page in place (everyone clocked in, punch editor)
//
// The actions and the days read **one** payload from `GET /hub/attendance/week`.
// The ranked boards live on the Leaderboards tab. The roster is the exception -- "now" is a different question from
// "this week", polled and pushed on its own cadence.
//
// The shell is built once; each part renders into its own mount, so a roster
// repaint never disturbs an open punch editor.

import {
  apiAddAttendancePunch,
  apiClockOutAttendanceUser,
  apiDeleteAttendancePunch,
  apiExportHubAttendance,
  apiEditAttendancePunch,
  apiGetHubAttendanceLive,
  apiGetHubAttendanceWeek,
  apiReviewHubAttendanceWeek,
} from "../api.js";
import { messageDialog } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { roleAtLeast } from "../roles.js";
import { skeletonCard } from "../skeleton.js";
import { mondayOf, mountHubAttendanceDayPage, mountHubAttendanceDays } from "./hubAttendanceDay.js";
import { destroyHubAttendanceRoster, mountHubAttendanceRoster } from "./hubAttendanceRoster.js";
import { mountUserProfile } from "./userProfile.js";

let viewerRole = null;

// One cache for the actions and the hours grid -- see the header.
let weekPayload = null;
let week = null;
let weekRequestId = 0;
// One-shot confirmation for the next actions paint, set by "Mark all
// reviewed" -- the refetch remounts the actions and would wipe it.
let weekNotice = "";
// The profile mounted in place of the week area (E2): `{ user, week }` or
// null. While set, renderWeek and the background week refresh stand down.
let profileOpen = null;
// The day page mounted in place of the week area: an ISO date or null.
let dayOpen = null;

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

// --- The attendance week: the actions and Hours ---------------------------

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

function renderProfile(panelEl) {
  const area = mountFor(panelEl, "week");
  if (!area || !profileOpen) return;
  if (area.querySelector("#hub-timesheets-profile")) return;
  area.innerHTML = `<div id="hub-timesheets-profile"></div>`;
  mountUserProfile(area.firstElementChild, profileOpen.user, {
    week: profileOpen.week, page: "user-hub",
    onBack: () => {
      profileOpen = null;
      if (weekPayload) renderWeek(panelEl);
      else void loadWeek(panelEl);
    },
  });
}

function openProfile(panelEl, user, week) {
  profileOpen = { user, week };
  renderProfile(panelEl);
}

// The Back path from a work order (E8). The hub may not be on screen yet:
// the request is held in `profileOpen` and painted by the next
// renderTimesheetsTab. `user` is resolved from the cached week when
// possible; otherwise the profile paints its own heading from the payload.
export function openTimesheetsProfile(userId, { week: requested = null } = {}) {
  const row = weekPayload?.rows.find((r) => r.user?.id === userId);
  profileOpen = { user: row?.user ?? { id: userId }, week: requested };
  if (hostPanel && !hostPanel.hidden) renderProfile(hostPanel);
}

// Paint the actions and the hours grid from the one cached week. Both
// mounts are (re)created here so a load error or skeleton that replaced the
// week area is cleared by the next good payload.
function renderWeek(panelEl) {
  if (profileOpen) { renderProfile(panelEl); return; }
  const area = mountFor(panelEl, "week");
  if (!area || !weekPayload) return;
  const isAdmin = roleAtLeast(viewerRole, "admin");
  if (dayOpen) { renderDay(panelEl, isAdmin); return; }
  area.innerHTML = `<div class="hub-timesheets-actions"></div>
    <div class="hub-timesheets-days"></div>`;
  renderActions(panelEl, isAdmin);
  mountHubAttendanceDays(mountFor(panelEl, "days"), weekPayload, {
    onWeekChange: changeWeek(panelEl),
    onOpenDay: (date) => { dayOpen = date; renderWeek(panelEl); },
  });
}

function setActionStatus(panelEl, message, type = "") {
  const status = panelEl.querySelector(".hub-timesheets-message");
  if (!status) return;
  status.textContent = message;
  status.className = `hub-timesheets-message${type ? ` ${type}` : ""}`;
}

// The payroll actions: Mark all reviewed (Admin, when anything is
// reviewable) and the CSV export, plus the notice line they report into.
function renderActions(panelEl, isAdmin) {
  const reviewable = Number(weekPayload.reviewable_count) || 0;
  const reviewButton = isAdmin && reviewable
    ? `<button type="button" class="secondary-btn hub-timesheets-review-all">Mark all reviewed (${reviewable})</button>`
    : "";
  const mount = mountFor(panelEl, "actions");
  mount.innerHTML = `<div class="hub-timesheets-action-row">
      ${reviewButton}
      <button type="button" class="secondary-btn hub-timesheets-export">Export CSV</button>
    </div>
    <p class="hub-timesheets-message" aria-live="polite"></p>`;
  if (weekNotice) setActionStatus(panelEl, weekNotice, "success");
  weekNotice = "";
  mount.querySelector(".hub-timesheets-review-all")?.addEventListener("click", (event) => {
    event.currentTarget.disabled = true;
    setActionStatus(panelEl, "Marking reviewed…");
    void write(panelEl, () => reviewWeek());
  });
  mount.querySelector(".hub-timesheets-export").addEventListener("click", (event) => {
    void downloadCsv(panelEl, event.currentTarget);
  });
}

async function downloadCsv(panelEl, button) {
  button.disabled = true;
  setActionStatus(panelEl, "Preparing export…");
  try {
    const { blob, filename } = await apiExportHubAttendance({ week: weekPayload.week_start });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setActionStatus(panelEl, `Exported ${filename}.`, "success");
  } catch (err) {
    setActionStatus(panelEl, friendlyError(err, "Could not export attendance."), "error");
  } finally {
    button.disabled = false;
  }
}

// The day page (one date, everyone clocked in). Stepping past the week's
// edge moves the week and refetches; the page repaints from the new payload.
function renderDay(panelEl, isAdmin) {
  const area = mountFor(panelEl, "week");
  area.innerHTML = `<div class="hub-timesheets-day"></div>`;
  // The write callbacks are passed only to an Admin, and the grid
  // renders an affordance only for a callback it was given -- so the floor
  // is expressed once, here, rather than re-derived inside the view.
  const writes = isAdmin
    ? {
      onSavePunch: (id, values) => write(panelEl, () => apiEditAttendancePunch(id, values)),
      onAddPunch: (userId, values) => write(panelEl, () => apiAddAttendancePunch({ userId, ...values })),
      onDeletePunch: (id, reason) => write(panelEl, () => apiDeleteAttendancePunch(id, reason)),
      onClearReview: (id) => write(panelEl, () => apiEditAttendancePunch(id, { needsReview: false })),
      onToggleLunch: (id, waived) => write(panelEl, () => apiEditAttendancePunch(id, {
        lunchWaived: waived,
        reason: waived ? "Lunch removed by an Admin" : "Lunch restored by an Admin",
      })),
    }
    : {};
  mountHubAttendanceDayPage(area.firstElementChild, weekPayload, dayOpen, {
    ...writes,
    onBack: () => { dayOpen = null; renderWeek(panelEl); },
    onDayChange: (date) => {
      dayOpen = date;
      if (weekPayload.days.includes(date)) renderWeek(panelEl);
      else changeWeek(panelEl)(mondayOf(date));
    },
    onOpenProfile: isAdmin ? (user) => openProfile(panelEl, user, week) : undefined,
  });
}

async function reviewWeek() {
  const { punches, sessions } = await apiReviewHubAttendanceWeek({ week });
  const count = punches + sessions;
  weekNotice = `Marked ${count} ${count === 1 ? "item" : "items"} reviewed.`;
}

function changeWeek(panelEl) {
  return (nextWeek) => {
    week = nextWeek;
    void loadWeek(panelEl);
  };
}

function renderLive(panelEl) {
  const mount = mountFor(panelEl, "roster");
  if (!mount || !livePayload) return;
  const onClockOut = roleAtLeast(viewerRole, "admin")
    ? (userId) => clockOut(panelEl, userId)
    : null;
  mountHubAttendanceRoster(mount, livePayload, { onClockOut });
}

// Refetch both halves after: the strip loses the card, the grid closes the
// cell. A refusal goes to a dialog -- the strip has no message line.
async function clockOut(panelEl, userId) {
  try {
    await apiClockOutAttendanceUser(userId);
  } catch (err) {
    await messageDialog(friendlyError(err, "Could not clock them out."));
  }
  await Promise.all([loadLive(panelEl), loadWeek(panelEl)]);
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
  if (!profileOpen && !panelEl.querySelector(".punch-editor")) void loadWeek(panelEl);
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
  if (!weekPayload && !profileOpen) area.innerHTML = skeletonGrid();
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
  profileOpen = null;
  dayOpen = null;
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
