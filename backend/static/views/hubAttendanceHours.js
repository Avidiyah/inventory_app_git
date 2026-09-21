// View: the Admin Timesheets tab's **Hours** sub-feature.
//
// Layer: views (no fetch, no state beyond which cell is open). The payload
// owns both the grid and every cell's drill-down, so opening detail never
// starts another request -- the rule hubTimesheets.js established.
//
// **Clocked time only** (spec §8): what this prints is time on shift, the pay
// number, never rounded to 30 minutes the way a billed number is. The
// comparison against tracked and billed is a different sub-tab, in P4.
//
// P3 added editing: `[Edit]` / `[Looks right]` per punch row and
// `[+ Add punch]` per day, all inside the drill-down and all withheld unless
// the caller passes the matching callback -- which `hubTimesheetsTab.js` does
// only for an Admin. A `carried` punch never gets one: spec §9 gives a
// cross-midnight punch to the day it started, and it is editable only there.
// The editor itself is `hubAttendancePunchEditor.js`; this module stays a
// pure view and hands values back through callbacks.

import { escapeHtml } from "../format.js";
import { mountPunchEditor } from "./hubAttendancePunchEditor.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

// `8:00`, not format.js's `8 h 0 m`: a seven-column grid of hours reads as a
// column of clock times. hubTimesheets.js makes the same local choice.
function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function shortDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC",
  });
}

function longDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "long", month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });
}

function weekLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

// Punch instants are rendered in Central, not the viewer's zone: the week
// boundaries are Central by construction, so a Chicago 11 PM punch must not
// print as a different day for an Admin reading from another timezone.
function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

function dayLabel(instant) {
  return new Date(instant).toLocaleDateString([], {
    weekday: "short", timeZone: CENTRAL_TIME_ZONE,
  });
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function cellFlagsHtml(day) {
  let html = "";
  if (day.has_open) {
    html += `<span class="hub-hours-flag hub-hours-flag-open"><span aria-hidden="true">●</span><span class="sr-only"> still on shift</span></span>`;
  }
  if (day.needs_review) {
    html += `<span class="hub-hours-flag hub-hours-flag-review"><span aria-hidden="true">&#9888;</span><span class="sr-only"> needs review</span></span>`;
  }
  return html;
}

function cellFlagLabels(day) {
  const labels = [];
  if (day.has_open) labels.push("still on shift");
  if (day.needs_review) labels.push("needs review");
  return labels.join(", ");
}

function punchRowHtml(punch, { canEdit } = {}) {
  const ended = punch.open ? "running" : timeLabel(punch.ended_at);
  const notes = [];
  // Why the row is here rather than on its own day -- without this a two-hour
  // Tuesday cell with a punch stamped 10 PM Monday reads as a data error.
  if (punch.carried) notes.push(`carried from ${escapeHtml(dayLabel(punch.started_at))}`);
  if (punch.start_source === "auto_work_order") notes.push("auto, from a work-order clock");
  if (punch.needs_review) notes.push("needs review");
  const suffix = notes.length
    ? ` <span class="hub-hours-punch-note">${notes.join(" · ")}</span>`
    : "";
  // Spec §9: a carried punch is owned by the day it started, so it is
  // editable there and nowhere else.
  const controls = !canEdit || punch.carried ? "" : `<span class="hub-hours-row-actions">
      <button type="button" class="link-btn hub-hours-edit" data-punch="${escapeHtml(punch.id)}">Edit</button>
      ${punch.needs_review ? `<button type="button" class="link-btn hub-hours-clear-review" data-punch="${escapeHtml(punch.id)}">Looks right</button>` : ""}
    </span>`;
  return `<div class="hub-hours-drilldown-row">
    <span>${escapeHtml(timeLabel(punch.started_at))} – ${escapeHtml(ended)}${suffix}</span>
    <span>${formatHm(punch.minutes)}${controls}</span>
  </div>`;
}

function drilldownHtml(day, name, { canEdit } = {}) {
  const rows = day.punches.map((punch) => punchRowHtml(punch, { canEdit })).join("");
  const empty = day.punches.length
    ? ""
    : `<p class="hint hub-hours-no-detail">No punches recorded.</p>`;
  const add = canEdit
    ? `<button type="button" class="secondary-btn hub-hours-add" data-date="${escapeHtml(day.date)}">+ Add punch</button>`
    : "";
  return `<div class="hub-hours-drilldown">
    <div class="hub-hours-drilldown-heading">
      <strong>${escapeHtml(name)} · ${escapeHtml(longDateLabel(day.date))}</strong>
      <strong>${formatHm(day.clocked_minutes)} clocked</strong>
    </div>
    ${rows}${empty}${add}
    <div class="hub-hours-editor" data-date="${escapeHtml(day.date)}"></div>
  </div>`;
}

function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}

export function mountHubAttendanceHours(container, payload, {
  onWeekChange, onSavePunch, onAddPunch, onDeletePunch, onClearReview,
} = {}) {
  let expanded = null;
  // A punch id, `add:<date>`, or null. Cleared whenever the open cell moves:
  // an editor left mounted under a different day would save to the wrong one.
  let editing = null;
  const canEdit = Boolean(onSavePunch);

  function openCell(picked) {
    const same = expanded?.rowIndex === picked.rowIndex && expanded?.date === picked.date;
    expanded = same ? null : picked;
    editing = null;
  }

  function expandedDay() {
    if (!expanded) return null;
    return payload.rows[expanded.rowIndex]?.days
      .find((day) => day.date === expanded.date) || null;
  }

  function findPunch(punchId) {
    return expandedDay()?.punches.find((punch) => punch.id === punchId) || null;
  }

  function expandedUserId() {
    return payload.rows[expanded?.rowIndex]?.user?.id;
  }

  function render() {
    const headers = payload.days
      .map((day) => `<th scope="col">${escapeHtml(shortDateLabel(day))}</th>`)
      .join("");
    const rows = payload.rows
      .map((row, rowIndex) => {
        const name = userName(row.user);
        const byDate = new Map(row.days.map((day) => [day.date, day]));
        const cells = payload.days
          .map((dateValue) => {
            const day = byDate.get(dateValue) || {
              date: dateValue, clocked_minutes: 0, needs_review: false,
              has_open: false, punches: [],
            };
            const isExpanded = expanded?.rowIndex === rowIndex && expanded?.date === dateValue;
            const flags = cellFlagLabels(day);
            const label = `${name}, ${longDateLabel(dateValue)}, ${formatHm(day.clocked_minutes)} clocked${flags ? `, ${flags}` : ""}`;
            return `<td><button type="button" class="hub-hours-cell" data-row="${rowIndex}" data-date="${escapeHtml(dateValue)}" aria-label="${escapeHtml(label)}" aria-expanded="${isExpanded}" aria-controls="hub-hours-detail-${rowIndex}">${formatHm(day.clocked_minutes)}${cellFlagsHtml(day)}</button></td>`;
          })
          .join("");
        const mainRow = `<tr><th scope="row">${escapeHtml(name)}</th>${cells}<td class="hub-hours-row-total">${formatHm(row.total_minutes)}</td></tr>`;
        if (expanded?.rowIndex !== rowIndex) return mainRow;
        const day = byDate.get(expanded.date);
        if (!day) return mainRow;
        return `${mainRow}<tr class="hub-hours-detail-row"><td colspan="${payload.days.length + 2}" id="hub-hours-detail-${rowIndex}">${drilldownHtml(day, name, { canEdit })}</td></tr>`;
      })
      .join("");
    const totals = payload.totals_by_day
      .map((entry) => `<td>${formatHm(entry.minutes)}</td>`)
      .join("");
    // 167 or 169. Said out loud so a short week does not read as lost hours.
    const dst = payload.week_hours === 168
      ? ""
      : `<p class="hint hub-hours-dst">Daylight saving: this week is ${escapeHtml(String(payload.week_hours))} hours long, not 168.</p>`;
    const table = payload.rows.length
      ? `<div class="hub-hours-table-wrap">
          <table class="hub-hours-table">
            <caption class="sr-only">Clocked hours for ${escapeHtml(payload.week_start)} through ${escapeHtml(payload.week_end)}</caption>
            <thead><tr><th scope="col">Person</th>${headers}<th scope="col">Week</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><th scope="row">Company total</th>${totals}<td>${formatHm(payload.total_minutes)}</td></tr></tfoot>
          </table>
        </div>`
      : `<p class="hint hub-hours-empty">Nobody clocked in this week.</p>`;

    container.innerHTML = `<section class="hub-hours" aria-labelledby="hub-hours-heading">
      <h3 id="hub-hours-heading" class="sr-only">Clocked hours</h3>
      <div class="hub-hours-toolbar">
        <div class="hub-hours-week-nav">
          <button type="button" class="secondary-btn hub-hours-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
          <button type="button" class="secondary-btn hub-hours-next" aria-label="Next week">▶</button>
        </div>
      </div>
      <p class="hub-hours-message" aria-live="polite"></p>
      ${table}
      ${dst}
    </section>`;

    container.querySelectorAll(".hub-hours-cell").forEach((button) => {
      button.addEventListener("click", () => {
        openCell({ rowIndex: Number(button.dataset.row), date: button.dataset.date });
        render();
      });
    });
    container.querySelectorAll(".hub-hours-edit").forEach((button) => {
      button.addEventListener("click", () => {
        editing = button.dataset.punch;
        render();
      });
    });
    container.querySelector(".hub-hours-add")?.addEventListener("click", (event) => {
      editing = `add:${event.currentTarget.dataset.date}`;
      render();
    });
    container.querySelectorAll(".hub-hours-clear-review").forEach((button) => {
      button.addEventListener("click", () => onClearReview?.(button.dataset.punch));
    });

    const editorHost = container.querySelector(".hub-hours-editor");
    if (editorHost && editing) {
      const adding = editing.startsWith("add:");
      const punch = adding ? null : findPunch(editing);
      mountPunchEditor(editorHost, {
        punch,
        date: expanded.date,
        onSave: (values) => (adding
          ? onAddPunch?.(expandedUserId(), values)
          : onSavePunch?.(editing, values)),
        onDelete: (reason) => onDeletePunch?.(editing, reason),
        onCancel: () => { editing = null; render(); },
      });
    }

    container.querySelector(".hub-hours-prev")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, -7));
    });
    container.querySelector(".hub-hours-next")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, 7));
    });
  }

  render();
}
