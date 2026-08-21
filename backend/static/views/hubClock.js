// View: the persistent clock widget above the User Hub's tabs.
//
// Layer: views. Every role's one clock, in one place (D8). Mounted once per
// `loadUserHub()` call; owns its own 1-second tick interval, started on
// mount and cleared on the next mount (page re-entry) or explicitly via
// `unmountHubClock` (tab-hide safety net, spec §6.1).
//
// Two different elapsed numbers, both derived from the same payload and
// never confused: the widget's own hero figure ticks *session* elapsed from
// `running_session.started_at` ("started 8:12 AM" directly below it, spec
// §5.1's mockup). The Dashboard tab's "Time today" hero (hubTechnician.js)
// ticks from `running_session.day_counting_from` instead -- see this plan's
// Global Constraints for why they must stay separate.

import { apiStartWorkOrderTracking, apiStopWorkOrderTracking } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

// D18: the technician's own long-clock warnings, keyed off *session*
// elapsed minutes -- mirrors the constants the design spec assigns to
// `domain/hub.py` (deferred to P3; duplicated here as plain numbers since
// nothing server-side reads them yet). 720 is `LABOR_SESSION_MAX_MINUTES`.
const LONG_SESSION_WARN_MINUTES = 480;
const SESSION_CAP_WARN_MINUTES = 660;

let container = null;
let payload = null;
let skewMs = 0; // server_now - Date.now() at fetch time
let tickHandle = null;
let refreshCallback = null; // set by mountHubClock's `onChanged` option

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function nowWithSkew() {
  return Date.now() + skewMs;
}

function sessionElapsedMinutes() {
  if (!payload?.clock?.running_session) return 0;
  const startedAt = new Date(payload.clock.running_session.started_at).getTime();
  return (nowWithSkew() - startedAt) / 60000;
}

function warningHtml() {
  const elapsed = sessionElapsedMinutes();
  if (elapsed >= SESSION_CAP_WARN_MINUTES) {
    return `<p class="hub-clock-warning" role="alert">⚠ At 12 h this session is capped and your time stops counting.</p>`;
  }
  if (elapsed >= LONG_SESSION_WARN_MINUTES) {
    return `<p class="hub-clock-warning" role="alert">⚠ Still on the clock after 8 h — did you forget to stop?</p>`;
  }
  return "";
}

function onClockHtml() {
  const session = payload.clock.running_session;
  const place = [session.number ? `WO ${session.number}` : null]
    .filter(Boolean)
    .join(" · ");
  return `
    <div class="hub-clock hub-clock-on">
      <p class="hub-clock-status"><span class="hub-clock-dot"></span> ON THE CLOCK</p>
      <p class="hub-clock-subject">${escapeHtml(place)}</p>
      <div class="hub-clock-row">
        <div>
          <p class="hub-clock-hero">${escapeHtml(formatHm(sessionElapsedMinutes()))}</p>
          <p class="hub-clock-started">started ${escapeHtml(
            new Date(session.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
          )}</p>
        </div>
        <button type="button" class="hub-clock-stop-btn" data-action="hub-clock-stop">Stop</button>
      </div>
      ${warningHtml()}
      <p class="hub-clock-message" id="hub-clock-message"></p>
    </div>`;
}

// The top of `payload.startable` is already priority-ordered (In-Progress >
// On-Hold > Assigned > Created, see `hub.py::_STARTABLE_ORDER`) -- that's the
// work order someone would reach for first, so it's the one-click default.
// No picker: this widget only ever offers that top pick.
function topStartable() {
  const wo = (payload.startable || [])[0];
  if (!wo) return null;
  const place = [wo.community, wo.building_number ? `Bldg ${wo.building_number}` : null, wo.unit_number ? `Unit ${wo.unit_number}` : null]
    .filter(Boolean)
    .join(" · ") || wo.location || "";
  const label = place ? `WO ${wo.number} — ${place}` : `WO ${wo.number}`;
  return { value: wo.work_order_id, label };
}

function offClockHtml() {
  const top = topStartable();
  const startBtn = top
    ? `<button type="button" class="hub-clock-start-btn" data-action="hub-clock-start" data-value="${escapeHtml(
        top.value
      )}">Track ${escapeHtml(top.label)}</button>`
    : `<p class="hint">Nothing assigned to start a clock on yet.</p>`;
  return `
    <div class="hub-clock hub-clock-off">
      <p class="hub-clock-status">○ Not clocked in</p>
      <div class="hub-clock-row">
        <p class="hub-clock-today">Today <strong>${escapeHtml(formatHm(payload.clock.total_minutes_today))}</strong></p>
        <div class="hub-clock-start-wrap">
          ${startBtn}
        </div>
      </div>
      <p class="hub-clock-message" id="hub-clock-message"></p>
    </div>`;
}

function render() {
  container.innerHTML = payload.clock.running_session ? onClockHtml() : offClockHtml();
}

function tick() {
  if (!payload?.clock?.running_session) return;
  const hero = container.querySelector(".hub-clock-hero");
  if (hero) hero.textContent = formatHm(sessionElapsedMinutes());
  const warning = container.querySelector(".hub-clock-warning");
  const freshWarning = warningHtml();
  if (!warning && freshWarning) {
    render(); // a threshold was just crossed -- rebuild once to insert it
  } else if (warning && !freshWarning) {
    render();
  }
}

function stopTicking() {
  if (tickHandle !== null) {
    clearInterval(tickHandle);
    tickHandle = null;
  }
}

function startTicking() {
  stopTicking();
  tickHandle = setInterval(tick, 1000);
}

async function handleStart(workOrderId) {
  const message = document.getElementById("hub-clock-message");
  try {
    await apiStartWorkOrderTracking(workOrderId);
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not start charging."), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

async function handleStop() {
  const session = payload?.clock?.running_session;
  if (!session) return;
  const message = document.getElementById("hub-clock-message");
  try {
    await apiStopWorkOrderTracking(session.work_order_id);
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not stop charging."), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

// `onChanged` is called after a successful Start/Stop, and is expected to
// re-fetch GET /hub and remount -- userHub.js supplies its own
// `refreshUserHub`, so a Start/Stop here also refreshes the Dashboard tab's
// counts and timeline in the same round trip, not just this widget.
export function mountHubClock(mountEl, newPayload, { onChanged } = {}) {
  container = mountEl;
  payload = newPayload;
  skewMs = new Date(newPayload.server_now).getTime() - Date.now();
  refreshCallback = onChanged || null;
  render();
  startTicking();

  if (!container.dataset.wired) {
    container.dataset.wired = "1";
    container.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-action]");
      if (btn?.dataset.action === "hub-clock-stop") {
        void handleStop();
        return;
      }
      if (btn?.dataset.action === "hub-clock-start") {
        if (btn.dataset.value) void handleStart(btn.dataset.value);
        return;
      }
    });
  }
}

// Tab-hide / page-leave safety net (spec §6.1): nothing ticks in a
// background tab. userHub.js's page is a `.page` toggled by nav.js, not a
// browser tab, so this is called from the same visibilitychange listener
// pattern nav.js already uses for camera scanners -- see Task 4 Step 3.
export function stopHubClockTicking() {
  stopTicking();
}

// The resume side of the same safety net: called when the tab returns to
// foreground while the hub is still the active page. `tick()` recomputes
// elapsed from `started_at` + skew on its own, so restarting the interval is
// enough to snap the figure back to correct -- no fetch needed.
export function startHubClockTicking() {
  if (container) startTicking();
}
