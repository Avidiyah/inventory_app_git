// View: the User Hub's Home tab -- the hub's first tab and the app's landing
// surface.
//
// Layer: views. Two independent blocks, deliberately not merged: the
// attendance punch (am I at work?) and the work-order clock (what am I
// charging?). Blurring them is the single most likely way this feature ships
// subtly wrong -- see the spec's Time Semantics section.
//
// The clock is not rendered here. userHub.js reparents the existing
// `#hub-clock-mount` node into `#hub-home-clock-slot` after every render, so
// hubClock.js keeps its own state and wiring.

import {
  apiAddAttendancePunch, apiDeleteAttendancePunch, apiEditAttendancePunch, apiPunchIn, apiPunchOut,
} from "../api.js";
import { escapeHtml, formatHm, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
import { getCurrentUser } from "../state.js";
import { mountPunchEditor } from "./hubAttendancePunchEditor.js";
import { timeLabel } from "./hubWeek.js";

let container = null;
let hub = null;
let attendance = null;
let skewMs = 0;
let refreshCallback = null;

function nowWithSkew() {
  return Date.now() + skewMs;
}

function punchElapsedMinutes() {
  if (!attendance?.open_punch) return 0;
  return (nowWithSkew() - new Date(attendance.open_punch.started_at).getTime()) / 60000;
}

function shortTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function errorPunchHtml() {
  return `
    <section class="hub-punch hub-punch-error">
      <p class="hub-punch-status">Could not load your shift.</p>
      <button type="button" class="secondary-btn hub-punch-retry" data-action="hub-punch-retry">Retry</button>
    </section>`;
}

function onShiftHtml() {
  const punch = attendance.open_punch;
  return `
    <section class="hub-punch hub-punch-on">
      <p class="hub-punch-status"><span class="hub-punch-dot"></span> ON SHIFT</p>
      <div class="hub-punch-row">
        <div>
          <p class="hub-punch-hero">${escapeHtml(formatHm(punchElapsedMinutes()))}</p>
          <p class="hub-punch-started">punched in ${escapeHtml(shortTime(punch.started_at))}</p>
        </div>
        <button type="button" class="hub-punch-btn" data-action="hub-punch-out">Punch out</button>
      </div>
      <p class="hub-punch-message" id="hub-punch-message"></p>
    </section>`;
}

function offShiftHtml() {
  return `
    <section class="hub-punch hub-punch-off">
      <p class="hub-punch-status">&#9675; Not punched in</p>
      <div class="hub-punch-row">
        <p class="hub-punch-today">Today <strong>${escapeHtml(formatHm(attendance.clocked_minutes_today))}</strong></p>
        <button type="button" class="hub-punch-btn" data-action="hub-punch-in">Punch in</button>
      </div>
      <p class="hub-punch-message" id="hub-punch-message"></p>
    </section>`;
}

function punchHtml() {
  if (!attendance) return errorPunchHtml();
  if (!attendance.open_punch) return offShiftHtml();
  return onShiftHtml();
}

// The worker's own open-week punches, each editable (the server refuses
// anything outside the open week). Tags are the Self/Admin edit marks.
function weekPunchRowHtml(p) {
  const day = new Date(p.started_at).toLocaleDateString([], {
    weekday: "short", month: "short", day: "numeric", timeZone: "America/Chicago",
  });
  const span = `${timeLabel(p.started_at)} – ${p.ended_at ? timeLabel(p.ended_at) : "running"}`;
  const minutes = p.ended_at ? formatHm((new Date(p.ended_at) - new Date(p.started_at)) / 60000) : "";
  const tags = (p.tags || []).map((t) =>
    ` <span class="day-tl-tag day-tl-tag-${t}">${t === "self" ? "Self" : "Admin"}-edited</span>`).join("");
  const flag = p.needs_review ? ` <span class="hub-home-punch-flag">⚠ needs review</span>` : "";
  return `<li class="hub-home-punch-row">
      <span>${escapeHtml(day)}</span> <span>${escapeHtml(span)}</span> <span>${escapeHtml(minutes)}</span>${tags}${flag}
      <button type="button" class="secondary-btn" data-action="hub-home-edit-punch" data-punch="${escapeHtml(p.id)}">Edit</button>
    </li>`;
}

function weekPunchesHtml() {
  if (!attendance) return "";
  const rows = (attendance.week_punches || []).map(weekPunchRowHtml).join("");
  // A <section> for the panel surface and text colour the other Home cards get.
  return `<section class="hub-home-week-punches"><details>
      <summary>This week's punches</summary>
      <ul class="hub-home-punch-list">${rows}</ul>
      <button type="button" class="secondary-btn" data-action="hub-home-add-punch">+ Add punch</button>
      <div class="hub-home-punch-editor"></div>
    </details></section>`;
}

// One editor at a time; a refresh repaints Home and so closes it.
function openPunchEditor(punchId) {
  const host = container.querySelector(".hub-home-punch-editor");
  const punch = (attendance.week_punches || []).find((p) => p.id === punchId) || null;
  async function save(work) {
    try {
      await work();
    } catch (err) {
      const message = host.querySelector(".punch-editor-message");
      message.className = "punch-editor-message error";
      message.textContent = friendlyError(err, "Could not save that punch.");
      return;
    }
    if (refreshCallback) await refreshCallback();
  }
  mountPunchEditor(host, {
    punch,
    date: punch ? punch.started_at.slice(0, 10) : attendance.day,
    onSave: (values) => save(() => (punch
      ? apiEditAttendancePunch(punch.id, values)
      : apiAddAttendancePunch({ userId: getCurrentUser().id, ...values }))),
    onDelete: (reason) => save(() => apiDeleteAttendancePunch(punch.id, reason)),
    onCancel: () => host.replaceChildren(),
  });
}

// Today's own numbers, the same three the Dashboard tab leads with -- Home
// answers "what is in front of me" without a tab switch.
function countsHtml() {
  const counts = hub.counts;
  return `
    <div class="hub-tile-grid">
      <section class="hub-tile"><p class="hub-tile-label">Assigned to me</p><p class="hub-tile-value">${escapeHtml(String(counts.assigned))}</p><p class="hub-tile-sub">work orders</p></section>
      <section class="hub-tile"><p class="hub-tile-label">In progress</p><p class="hub-tile-value">${escapeHtml(String(counts.in_progress))}</p></section>
      <section class="hub-tile"><p class="hub-tile-label">Ready to complete</p><p class="hub-tile-value">${escapeHtml(String(counts.ready_to_complete))}</p></section>
    </div>`;
}

async function run(action, message) {
  const status = document.getElementById("hub-punch-message");
  try {
    await action();
  } catch (err) {
    setMessage(status, friendlyError(err, message), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

export function mountHubHome(mountEl, hubPayload, attendancePayload, { onChanged } = {}) {
  container = mountEl;
  hub = hubPayload;
  attendance = attendancePayload;
  skewMs = new Date(hubPayload.server_now).getTime() - Date.now();
  refreshCallback = onChanged || null;

  container.innerHTML = `
    ${punchHtml()}
    ${weekPunchesHtml()}
    <div id="hub-home-clock-slot"></div>
    ${countsHtml()}`;

  if (!container.dataset.wired) {
    container.dataset.wired = "1";
    container.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "hub-punch-in") void run(apiPunchIn, "Could not punch in.");
      else if (action === "hub-punch-out") void run(apiPunchOut, "Could not punch out.");
      else if (action === "hub-punch-retry" && refreshCallback) void refreshCallback();
      else if (action === "hub-home-edit-punch") openPunchEditor(event.target.closest("[data-punch]").dataset.punch);
      else if (action === "hub-home-add-punch") openPunchEditor(null);
    });
  }
}
