// View: the live roster strip above Charged vs clocked.
//
// Layer: views. No fetch and no state but the tick: the payload arrives from
// hubTimesheetsTab.js, and everything on screen is derived from it.
//
// **Colour is never the only signal** (design-system.md). Every card prints
// what its rail means in words -- "idle 12m", "charging WO-1042" -- so the
// strip is readable with the hues removed.
//
// Ticking is the hubClock.js pattern: elapsed recomputed each second from an
// instant plus the server skew, never a counter incremented in place, so a
// backgrounded tab that misses a hundred ticks still snaps to the truth on
// its first tick back. A card that crosses `idle_red_minutes` is recoloured
// **in place**; the list order is the server's and changes only on a fetch,
// because a strip that reshuffles under a reading eye is worse than one row
// sitting out of position for a minute.
//
// The absent footer is `<details>`, not a button that toggles a panel: a
// button inside the strip's header row would be a button inside a button.

import { escapeHtml } from "../format.js";

const DEFAULT_IDLE_RED_MINUTES = 10;

let container = null;
let payload = null;
let skewMs = 0;
let tickHandle = null;

function serverNow() {
  return Date.now() + skewMs;
}

function minutesSince(iso) {
  if (!iso) return 0;
  return Math.max(0, Math.floor((serverNow() - new Date(iso).getTime()) / 60000));
}

// `45m`, `2h 05m`: the figure sits inside a sentence, so it reads as a
// duration rather than as the clock times the grids below print.
function formatElapsed(minutes) {
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

function timeLabel(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

// The card's own colour, recomputed from the anchor so it can cross the
// threshold between polls. A charging card never changes: only a fetch can
// tell us a clock stopped.
function stateOf(entry) {
  if (entry.charging_since) return "green";
  if (!entry.idle_since) return entry.state;
  const threshold = payload?.idle_red_minutes ?? DEFAULT_IDLE_RED_MINUTES;
  return minutesSince(entry.idle_since) >= threshold ? "red" : "yellow";
}

// Plain text, set with textContent on every tick -- which is also why it is
// not built as HTML.
function detailText(entry, state) {
  if (state === "green") {
    const job = entry.work_order_number || "a job";
    return `charging ${job} · ${formatElapsed(minutesSince(entry.charging_since))}`;
  }
  return `idle ${formatElapsed(minutesSince(entry.idle_since))}`;
}

function cardHtml(entry) {
  const state = stateOf(entry);
  const name = userName(entry.user);
  const since = entry.punch_started_at
    ? `on shift since ${timeLabel(entry.punch_started_at)}`
    : "";
  return `<li class="hub-roster-card hub-roster-${escapeHtml(state)}"
    data-user="${escapeHtml(String(entry.user?.id ?? ""))}" data-state="${escapeHtml(state)}">
    <span class="hub-roster-name">${escapeHtml(name)}</span>
    <span class="hub-roster-detail">${escapeHtml(detailText(entry, state))}</span>
    <span class="hub-roster-since">${escapeHtml(since)}</span>
  </li>`;
}

function absentHtml(entries) {
  if (!entries.length) return "";
  const names = entries
    .map((entry) => `<li class="hub-roster-absent-name">${escapeHtml(userName(entry.user))}</li>`)
    .join("");
  return `<details class="hub-roster-absent">
    <summary>${entries.length} not clocked in</summary>
    <ul class="hub-roster-absent-list">${names}</ul>
  </details>`;
}

function render() {
  if (!container || !payload) return;
  const onShift = payload.on_shift || [];
  const counts = `${payload.on_shift_count} on shift · ${payload.charging_count} charging · ${payload.idle_count} idle`;
  const strip = onShift.length
    ? `<ul class="hub-roster-strip">${onShift.map(cardHtml).join("")}</ul>`
    : `<p class="hint hub-roster-empty">Nobody is clocked in right now.</p>`;
  container.innerHTML = `<section class="hub-roster" aria-labelledby="hub-roster-heading">
    <h4 id="hub-roster-heading" class="sr-only">On shift now</h4>
    <p class="hub-roster-counts" aria-live="polite">${escapeHtml(counts)}</p>
    ${strip}
    ${absentHtml(payload.absent || [])}
  </section>`;
}

// One pass per second. Each card's figure is rewritten as text; a card whose
// colour has changed forces a single re-render and the pass stops there,
// because the nodes it was walking are about to be replaced.
function tick() {
  if (!container || !payload) return;
  for (const entry of payload.on_shift || []) {
    const node = container.querySelector(
      `.hub-roster-card[data-user="${CSS.escape(String(entry.user?.id ?? ""))}"]`,
    );
    if (!node) continue;
    const state = stateOf(entry);
    if (node.dataset.state !== state) {
      render();
      return;
    }
    const detail = node.querySelector(".hub-roster-detail");
    if (detail) detail.textContent = detailText(entry, state);
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

// Payload in, strip out. Re-mounting with a fresh payload is how a poll or an
// `attendance.changed` envelope lands -- and is also what re-sorts the list.
export function mountHubAttendanceRoster(mountEl, newPayload) {
  container = mountEl;
  payload = newPayload;
  skewMs = new Date(newPayload.server_now).getTime() - Date.now();
  render();
  startTicking();
}

// The tab-hide half of the safety net, called from userHub.js's existing
// `visibilitychange` listener beside `stopHubClockTicking` -- this view owns
// no timer of its own beyond the one that listener governs.
export function stopHubRosterTicking() {
  stopTicking();
}

export function startHubRosterTicking() {
  if (container) startTicking();
}

// A different person signed in, or the tab went away. Everything goes,
// including the interval -- the frontend suite asserts no timer survives.
export function destroyHubAttendanceRoster() {
  stopTicking();
  container = null;
  payload = null;
  skewMs = 0;
}
