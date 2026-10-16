// View: one day of a crew member's time as a timeline (spec
// 2026-10-16-edited-time-timeline-and-leaderboards-design.md, U5-U7).
//
// Three lanes share one Central hour axis -- Punched (on shift), Charged (on
// a work-order clock), Uncharged (the punched time no clock covers) -- and a
// fourth, set apart under a dashed rule, holds hand-entered labor. That
// labor has no time of day, so its chips are laid left to right and sized
// by minutes only: placing them on the axis would invent a fact.
//
// Edited time is striped and always carries a text tag; colour never carries
// the meaning alone. Layer: views, pure markup. Positions ride on data-* and
// land through CSSOM in `applyTimelinePositions` -- the CSP drops style=.

import { escapeHtml } from "../format.js";
import { formatHm, timeLabel } from "./hubWeek.js";

const DAY_MINUTES = 24 * 60;
const AXIS_START = 8 * 60;   // the axis opens at 8 AM unless work began earlier
const AXIS_END = 17 * 60;    // and runs to 5 PM unless work ran later
const NARROW_PX = 40;

const centralParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

// Minutes into `date` (Central) for an instant, clamped to the day.
function minuteOfDay(instant, date) {
  const parts = Object.fromEntries(centralParts.formatToParts(new Date(instant))
    .map((p) => [p.type, p.value]));
  const on = `${parts.year}-${parts.month}-${parts.day}`;
  if (on < date) return 0;
  if (on > date) return DAY_MINUTES;
  return Number(parts.hour) * 60 + Number(parts.minute);
}

function span(start, end, date, now) {
  return [minuteOfDay(start, date), minuteOfDay(end ?? now, date)];
}

// Punched spans minus charged spans: the uncharged lane. Both lists are
// [start, end] minute pairs; the result is sorted and gap-free of zero widths.
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

const FIELD_LABEL = { created: "added", started_at: "start", ended_at: "end", lunch_waived: "lunch" };

function stampLabel(value) {
  if (!value) return "none";
  if (!value.includes("T")) return value;
  return value.split("/").map((part) => timeLabel(part)).join("–");
}

function editsLabel(marks) {
  return marks.edits.map((e) => {
    const who = `${e.self ? "self" : "Admin"}-edited by ${e.by_name}`;
    const change = e.field === "created"
      ? `added ${stampLabel(e.new)}`
      : `${FIELD_LABEL[e.field] || e.field} ${stampLabel(e.old)} → ${stampLabel(e.new)}`;
    return `${who}: ${change}`;
  }).join("; ");
}

function tagHtml(kind, word) {
  return `<span class="day-tl-tag day-tl-tag-${kind}">${kind === "self" ? "Self" : "Admin"}-${word}</span>`;
}

function blockAttrs([start, end], range) {
  const width = range[1] - range[0];
  const left = ((start - range[0]) / width) * 100;
  return `data-left="${left.toFixed(3)}" data-width="${Math.max(((end - start) / width) * 100, 0.5).toFixed(3)}"`;
}

export function dayTimelineHtml(day, { now = new Date().toISOString() } = {}) {
  const punches = day.punches || [];
  const charged = (day.charged || []).flatMap((c) => (c.spans || []).map((s) => ({ ...s, entry: c })));
  const adjustments = day.adjustments || [];
  if (!punches.length && !charged.length && !adjustments.length) return "";

  const punchSpans = punches.map((p) => span(p.started_at, p.ended_at, day.date, now));
  const chargeSpans = charged.map((c) => span(c.started_at, c.ended_at, day.date, now));
  const all = [...punchSpans, ...chargeSpans];
  const range = [
    Math.floor(Math.min(AXIS_START, ...all.map((s) => s[0])) / 60) * 60,
    Math.min(DAY_MINUTES, Math.ceil(Math.max(AXIS_END, ...all.map((s) => s[1])) / 60) * 60),
  ];
  const marksById = Object.fromEntries((day.punch_marks || []).map((m) => [m.punch_id, m]));

  const punchBlocks = punches.map((p, i) => {
    const marks = marksById[p.id];
    const times = `${timeLabel(p.started_at)} – ${p.open ? "running" : timeLabel(p.ended_at)}`;
    const fact = `Punch ${times}, ${formatHm(p.minutes)}${marks ? `, ${editsLabel(marks)}` : ""}`;
    const tags = (marks?.tags || []).map((t) => tagHtml(t, "edited")).join("");
    return `<button type="button" class="day-tl-block day-tl-punch${marks ? " day-tl-edited" : ""}" data-punch="${escapeHtml(p.id)}" ${blockAttrs(punchSpans[i], range)} title="${escapeHtml(fact)}" aria-label="${escapeHtml(fact)}"><span class="day-tl-label">${escapeHtml(formatHm(p.minutes))}</span>${tags}</button>`;
  }).join("");

  const chargeBlocks = charged.map((c, i) => {
    const times = `${timeLabel(c.started_at)} – ${c.ended_at ? timeLabel(c.ended_at) : "running"}`;
    const fact = `${c.entry.number}, ${times}${c.entry.auto_closed ? ", auto-stopped" : ""}`;
    return `<button type="button" class="day-tl-block day-tl-charged" data-number="${escapeHtml(c.entry.number)}" ${blockAttrs(chargeSpans[i], range)} title="${escapeHtml(fact)}" aria-label="${escapeHtml(`Charged to ${fact}`)}"><span class="day-tl-label">${escapeHtml(c.entry.number)}</span></button>`;
  }).join("");

  const gaps = subtractSpans(punchSpans, chargeSpans)
    .map((s) => `<span class="day-tl-gap" ${blockAttrs(s, range)} title="Uncharged ${formatHm(s[1] - s[0])}"></span>`)
    .join("");

  const axisWidth = range[1] - range[0];
  const chips = adjustments.map((a) => {
    const kind = a.recorded_by_self ? "self" : "admin";
    const fact = `${a.work_order_number}, ${formatHm(a.minutes)} hand-entered by ${a.recorded_by_name}`;
    return `<button type="button" class="day-tl-chip" data-number="${escapeHtml(a.work_order_number)}" data-width="${((a.minutes / axisWidth) * 100).toFixed(3)}" title="${escapeHtml(fact)}" aria-label="${escapeHtml(fact)}"><span class="day-tl-label">${escapeHtml(a.work_order_number)} · ${formatHm(a.minutes)}</span>${tagHtml(kind, "entered")}</button>`;
  }).join("");

  const pending = day.pending_review
    ? `<p class="day-tl-pending-note"><span aria-hidden="true">&#9888;</span> Not counted — needs review</p>`
    : "";
  return `<div class="day-tl${day.pending_review ? " day-tl-pending" : ""}">
    ${pending}
    ${hourLabelsHtml(range[0], range[1], "hub-timeline-axis day-tl-axis")}
    <div class="day-tl-lane day-tl-lane-punched"><span class="day-tl-lane-name">Punched</span><div class="day-tl-track">${punchBlocks}</div></div>
    <div class="day-tl-lane day-tl-lane-charged"><span class="day-tl-lane-name">Charged</span><div class="day-tl-track">${chargeBlocks}</div></div>
    <div class="day-tl-lane day-tl-lane-uncharged"><span class="day-tl-lane-name">Uncharged</span><div class="day-tl-track">${gaps}</div></div>
    ${chips ? `<hr class="day-tl-divider">
    <div class="day-tl-lane day-tl-lane-hand"><span class="day-tl-lane-name">Hand-entered</span><div class="day-tl-chips">${chips}</div></div>` : ""}
    <p class="day-tl-legend"><span class="day-tl-key day-tl-key-punched">Punched</span><span class="day-tl-key day-tl-key-charged">Charged</span><span class="day-tl-key day-tl-key-uncharged">Uncharged</span><span class="day-tl-key day-tl-key-hand">Hand-entered</span><span class="day-tl-key day-tl-key-edited">Edited</span></p>
  </div>`;
}

export function applyTimelinePositions(root) {
  root.querySelectorAll(".day-tl [data-width]").forEach((el) => {
    if (el.dataset.left !== undefined) el.style.left = `${el.dataset.left}%`;
    if (el.classList.contains("day-tl-chip")) el.style.flexBasis = `${el.dataset.width}%`;
    else el.style.width = `${el.dataset.width}%`;
    const track = el.parentElement?.getBoundingClientRect().width || 0;
    el.classList.toggle("day-tl-narrow", track > 0 && (track * el.dataset.width) / 100 < NARROW_PX);
  });
}
