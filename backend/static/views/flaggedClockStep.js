// View: the auto-stopped work-order clock step inside Fix flagged time.
//
// Layer: views (no fetch). The flow mounts it the way the punch step mounts
// `mountPunchEditor`; `loadWorkOrder` and the callbacks belong to the caller.
// Layout A (spec 2026-11-27): the edit and the buttons first, the order's
// crew, labor and notes folded below so a phone shows the decision at once.

import { escapeHtml } from "../format.js";
import { promptTime } from "../dom.js";
import { formatMinutes, statusLabel } from "./workOrderPresenters.js";

const CENTRAL = "America/Chicago";
const DAY_MS = 24 * 60 * 60 * 1000;
// LABOR_SESSION_MAX_MINUTES: where the server stops a clock nobody stopped.
const CAP_MS = 12 * 60 * 60 * 1000;
const OUT_OF_RANGE = "Pick a time after the start and no later than the automatic stop.";

function clockLabel(instant) {
  return new Date(instant).toLocaleString([], {
    weekday: "short", hour: "numeric", minute: "2-digit", timeZone: CENTRAL,
  });
}

function hoursText(startIso, endIso) {
  return `${((new Date(endIso) - new Date(startIso)) / 3600000).toFixed(1)} h`;
}

// The picker answers on the automatic stop's calendar day. A clock crossing
// midnight can only mean the start day for a time later than that stop.
// ponytail: fixed 24 h step, an hour off across a DST change; use a Central
// calendar shift if that ever bites.
export function resolveStop(chosen, startedAt, endedAt) {
  const start = new Date(startedAt).getTime();
  const end = new Date(endedAt).getTime();
  let t = chosen.getTime();
  if (t > end) t -= DAY_MS;
  return t > start && t <= end ? new Date(t).toISOString() : null;
}

// Note-log entries are separated by a blank line (`append_note_log`).
export function recentNotes(notes, n = 5) {
  return String(notes || "").split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean)
    .slice(-n).reverse();
}

function orderLine(item, detail) {
  const parts = [`WO ${item.number}`];
  if (detail) {
    for (const v of [detail.location, detail.description, statusLabel(detail.status)]) {
      if (v) parts.push(v);
    }
  }
  return parts.map(escapeHtml).join(" · ");
}

function laborHtml(item, detail) {
  const crew = (detail.assigned_to_names || []).join(", ") || "Nobody assigned";
  const rows = (detail.labor || []).map((l) => `<li>${escapeHtml(l.technician_name)} · ${
    escapeHtml(formatMinutes(l.minutes))} · ${l.recorded_by_self ? "Self" : "Admin"}${
    l.session_id === item.id ? " · this clock" : ""}</li>`).join("");
  return `<details class="flagged-clock-labor">
      <summary>Crew and labor (${(detail.labor || []).length})</summary>
      <p class="hub-hours-punch-note">Crew: ${escapeHtml(crew)}</p>
      <ul class="flagged-clock-list">${rows}</ul>
    </details>`;
}

function notesHtml(detail) {
  const notes = recentNotes(detail.notes);
  const body = notes.length
    ? `<ul class="flagged-clock-list">${notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>`
    : `<p class="hub-hours-punch-note">No notes</p>`;
  return `<details class="flagged-clock-notes">
      <summary>Recent notes (${notes.length})</summary>${body}
    </details>`;
}

export function mountClockStep(hostEl, { item, loadWorkOrder, onSave, onAccept, onOpen, onSkip }) {
  let stop = null;
  // A clock past the cap but not yet swept arrives still running; saving
  // sweeps it to start + 12 h first, so that is its automatic stop.
  const autoStop = item.ended_at
    ? new Date(item.ended_at).toISOString()
    : new Date(new Date(item.started_at).getTime() + CAP_MS).toISOString();
  hostEl.innerHTML = `<div class="flagged-clock">
    <p class="flagged-clock-order">${orderLine(item, null)}</p>
    <div class="flagged-clock-times">
      <span>Started ${escapeHtml(clockLabel(item.started_at))}</span>
      <button type="button" class="secondary-btn flagged-clock-stop">Stopped: ${
        escapeHtml(clockLabel(autoStop))}</button>
      <span class="flagged-clock-hours">${escapeHtml(hoursText(item.started_at, autoStop))}</span>
    </div>
    <p class="flagged-clock-message" aria-live="polite"></p>
    <div class="flagged-flow-actions">
      <button type="button" data-flow="save-accept" disabled>Save &amp; accept</button>
      <button type="button" class="secondary-btn" data-flow="accept">Accept as is</button>
      <button type="button" class="secondary-btn" data-flow="open-wo">Open work order</button>
      <button type="button" class="secondary-btn" data-flow="skip">Skip</button>
    </div>
    <p class="hub-hours-punch-note">Save &amp; accept sets the clock and the billed hours to the new
      stop time. Accept as is keeps 12 hours.</p>
    <div class="flagged-clock-details"><p class="hub-hours-punch-note">Loading work order…</p></div>
  </div>`;
  const $ = (sel) => hostEl.querySelector(sel);
  const save = $('[data-flow="save-accept"]');

  $(".flagged-clock-stop").addEventListener("click", async () => {
    const chosen = await promptTime({
      title: "Stopped at", help: "Central time.", initial: new Date(stop || autoStop),
    });
    if (!chosen) return;
    const resolved = resolveStop(chosen, item.started_at, autoStop);
    $(".flagged-clock-message").textContent = resolved ? "" : OUT_OF_RANGE;
    if (!resolved) return;
    stop = resolved;
    $(".flagged-clock-stop").textContent = `Stopped: ${clockLabel(stop)}`;
    $(".flagged-clock-hours").textContent = hoursText(item.started_at, stop);
    save.disabled = stop === autoStop;
  });
  save.addEventListener("click", () => { if (stop) onSave(stop); });
  $('[data-flow="accept"]').addEventListener("click", () => onAccept());
  $('[data-flow="open-wo"]').addEventListener("click", () => onOpen());
  $('[data-flow="skip"]').addEventListener("click", () => onSkip());

  Promise.resolve()
    .then(() => loadWorkOrder(item.workOrderId))
    .then((detail) => {
      if (!hostEl.contains(save)) return; // the step moved on
      $(".flagged-clock-order").innerHTML = orderLine(item, detail);
      $(".flagged-clock-details").innerHTML = laborHtml(item, detail) + notesHtml(detail);
    })
    .catch(() => {
      if (!hostEl.contains(save)) return;
      $(".flagged-clock-details").innerHTML =
        `<p class="hub-hours-punch-note">Could not load the work order.</p>`;
    });
}
