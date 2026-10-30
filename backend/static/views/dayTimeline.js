// View: one crew member's day as a list in time order (spec
// 2026-10-16-edited-time-timeline-and-leaderboards-design.md, U5-U7,
// reworked 2026-10-16 for self-explanation on phone and desktop).
//
// One line says when they were on the clock; under it every stretch of
// work-order clock time and every punched stretch no clock covers reads top
// to bottom, each with its times, what it was, and its length. The gaps are
// rows of their own ("Not charged"), so no colour key is needed. Hand-entered
// labor has no time of day and is listed by the profile, not here. Layer:
// views, pure markup.

import { escapeHtml } from "../format.js";
import { formatHm, spanList, timeLabel } from "./hubWeek.js";

// Punched spans minus charged spans: the not-charged stretches. Both lists
// are [start, end] pairs in any one unit; the result is sorted and gap-free
// of zero widths.
export function subtractSpans(outer, inner) {
  const cuts = [...inner].sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [start, end] of outer) {
    let cursor = start;
    for (const [cutStart, cutEnd] of cuts) {
      if (cutEnd <= cursor || cutStart >= end) continue;
      if (cutStart > cursor) out.push([cursor, cutStart]);
      cursor = Math.max(cursor, cutEnd);
    }
    if (cursor < end) out.push([cursor, end]);
  }
  return out;
}

export function hourLabelsHtml(rangeStart, rangeEnd, className = "hub-timeline-axis") {
  const labels = [];
  for (let h = Math.floor(rangeStart / 60); h <= Math.ceil(rangeEnd / 60); h++) {
    const hour12 = ((h + 11) % 12) + 1;
    const suffix = h < 12 || h === 24 ? "a" : "p";
    labels.push(`<span class="hub-timeline-hour">${hour12}${suffix}</span>`);
  }
  return `<div class="${className}">${labels.join("")}</div>`;
}

const MINUTE = 60000;

function woButton(number) {
  return `<button type="button" class="hub-link-btn user-profile-wo-btn" data-number="${escapeHtml(number)}">${escapeHtml(number)}</button>`;
}

function rowHtml(row, now) {
  const end = row.end >= now ? "now" : timeLabel(row.end);
  const times = `${timeLabel(row.start)} – ${end}`;
  const minutes = formatHm((row.end - row.start) / MINUTE);
  const what = row.number
    ? `${woButton(row.number)}${row.note ? ` <span class="hub-hours-punch-note">${row.note}</span>` : ""}`
    : "Not charged to a work order";
  return `<li class="day-run day-run-${row.number ? "charged" : "gap"}"><span class="day-run-time">${escapeHtml(times)}</span><span class="day-run-what">${what}</span><span class="day-run-minutes">${minutes}</span></li>`;
}

// Why a day is left out of the week, in words that name the fix. Mirrors
// day_pending_review (domain/attendance.py): a flagged or past-midnight
// punch, or a work-order clock the cap stopped that no Admin has accepted.
export function pendingReasons(day) {
  const reasons = [];
  const own = (day.punches || []).filter((p) => !p.carried);
  if (own.some((p) => p.end_source === "auto_clock_out")) {
    reasons.push("a punch was auto-closed at midnight: set its real end time");
  }
  if (own.some((p) => p.crosses_midnight)) {
    reasons.push("a punch ends on the next day: fix its end time");
  }
  if (own.some((p) => p.needs_review && p.end_source !== "auto_clock_out")) {
    reasons.push("a punch is marked for review: edit it, or Looks right on Timesheets");
  }
  const capped = (day.charged || []).filter((c) => c.auto_closed).map((c) => c.number);
  if (capped.length) {
    reasons.push(`${capped.join(", ")} clock was auto-stopped: accept it with Mark all reviewed on Timesheets`);
  }
  return reasons.length ? reasons.join("; ") : "needs review";
}

export function dayTimelineHtml(day, { now = new Date().toISOString() } = {}) {
  const punches = day.punches || [];
  const charged = day.charged || [];
  if (!punches.length && !charged.length) return "";
  const nowMs = Date.parse(now);
  const at = (instant) => (instant ? Date.parse(instant) : nowMs);

  const runs = charged.flatMap((c) => (c.spans || []).map((s) => ({
    start: at(s.started_at), end: at(s.ended_at), number: c.number,
    note: !s.ended_at ? "running" : c.auto_closed ? "auto-stopped" : "",
  })));
  const gaps = subtractSpans(
    punches.map((p) => [at(p.started_at), at(p.ended_at)]),
    runs.map((r) => [r.start, r.end]),
  ).filter(([start, end]) => end - start >= MINUTE)
    .map(([start, end]) => ({ start, end }));
  const rows = [...runs, ...gaps].sort((a, b) => a.start - b.start).map((r) => rowHtml(r, nowMs));
  // Labor with clock minutes but no recorded clock times still gets a line.
  const untimed = charged.filter((c) => !c.spans?.length).map((c) =>
    `<li class="day-run day-run-charged"><span class="day-run-time">times not recorded</span><span class="day-run-what">${woButton(c.number)}${c.auto_closed ? ` <span class="hub-hours-punch-note">auto-stopped</span>` : ""}</span><span class="day-run-minutes">${formatHm(c.minutes)}</span></li>`);

  const clock = punches.length ? `On the clock ${escapeHtml(spanList(punches))}` : "Not on the clock";
  const lunch = day.lunch_minutes ? ` · lunch −${formatHm(day.lunch_minutes)}` : "";
  const pending = day.pending_review
    ? `<p class="day-tl-pending-note"><span aria-hidden="true">&#9888;</span> Not counted in the week — ${pendingReasons(day)}</p>`
    : "";
  return `<div class="day-tl${day.pending_review ? " day-tl-pending" : ""}">
    ${pending}
    <p class="day-tl-clock">${clock}${lunch}</p>
    ${rows.length + untimed.length ? `<ol class="day-runs">${rows.join("")}${untimed.join("")}</ol>` : ""}
  </div>`;
}
