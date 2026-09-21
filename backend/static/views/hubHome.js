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

import { apiPunchIn, apiPunchOut, apiSelfClosePunch } from "../api.js";
import { escapeHtml, formatHm, friendlyError } from "../format.js";
import { promptTime, setMessage } from "../dom.js";

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

function shortDay(iso) {
  return new Date(iso).toLocaleDateString([], { weekday: "long" });
}

function errorPunchHtml() {
  return `
    <section class="hub-punch hub-punch-error">
      <p class="hub-punch-status">Could not load your shift.</p>
      <button type="button" class="secondary-btn hub-punch-retry" data-action="hub-punch-retry">Retry</button>
    </section>`;
}

// D5: a punch left open from an earlier day. No auto-close (D4), so the only
// way forward is the technician stating when they actually left -- flagged
// for an Admin rather than guessed at.
function stalePunchHtml() {
  const punch = attendance.open_punch;
  return `
    <section class="hub-punch hub-punch-on hub-punch-stale">
      <p class="hub-punch-status">&#9888; Still punched in from ${escapeHtml(shortDay(punch.started_at))}, ${escapeHtml(shortTime(punch.started_at))}</p>
      <p class="hub-punch-note">Tell us when you actually left. A supervisor will check it.</p>
      <button type="button" class="hub-punch-btn" data-action="hub-punch-self-close">Close it</button>
      <p class="hub-punch-message" id="hub-punch-message"></p>
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
  return attendance.open_punch.stale ? stalePunchHtml() : onShiftHtml();
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

async function handleSelfClose() {
  const punch = attendance?.open_punch;
  if (!punch) return;
  // The prompt opens on the punch's OWN day, not today: a Date built from
  // `started_at` carries that day, and promptTime never leaves it.
  const chosen = await promptTime({
    title: "When did you leave?",
    help: `You punched in ${shortDay(punch.started_at)} at ${shortTime(punch.started_at)}.`,
    initial: new Date(punch.started_at),
  });
  if (!chosen) return;
  await run(() => apiSelfClosePunch(chosen.toISOString()), "Could not close that shift.");
}

export function mountHubHome(mountEl, hubPayload, attendancePayload, { onChanged } = {}) {
  container = mountEl;
  hub = hubPayload;
  attendance = attendancePayload;
  skewMs = new Date(hubPayload.server_now).getTime() - Date.now();
  refreshCallback = onChanged || null;

  container.innerHTML = `
    ${punchHtml()}
    <div id="hub-home-clock-slot"></div>
    ${countsHtml()}`;

  if (!container.dataset.wired) {
    container.dataset.wired = "1";
    container.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "hub-punch-in") void run(apiPunchIn, "Could not punch in.");
      else if (action === "hub-punch-out") void run(apiPunchOut, "Could not punch out.");
      else if (action === "hub-punch-self-close") void handleSelfClose();
      else if (action === "hub-punch-retry" && refreshCallback) void refreshCallback();
    });
  }
}
