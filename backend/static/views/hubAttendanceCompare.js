// View: the Admin Timesheets tab's **Charged vs clocked** sub-feature.
//
// Layer: views. No fetch but the export blob, no state: everything on screen
// comes from the payload `hubTimesheetsTab.js` hands in -- the same payload
// the Hours grid reads, so the two sub-tabs cannot disagree about a week.
//
// **Three numbers, never blurred** (spec §8). Clocked is time on shift, the
// pay number. Charged is real wall-clock on jobs. Off job is `clocked -
// charged`, floored at zero, and means exactly that. There is no billed
// column: billing rounds a whole work order's labor up to 30 minutes, so no
// honest per-person-per-day billed number exists.
//
// Two flags, in opposite directions and both possible on one day: `⚠ charged
// outside shift` is time on a job that no punch covers (§9 allows it and
// flags it), and `+0:30 adjusted` is hand-entered labor, which has no start
// or stop and is therefore never inside either wall-clock number.
//
// Every flag prints its glyph *and* its words: design-system.md keeps status
// hues to badges, and nothing here may be readable by colour alone.

import { apiExportHubAttendance } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { tipHtml } from "../tooltip.js";

// `8:00`, not format.js's `8 h 0 m`: a seven-column grid of hours reads as a
// column of clock times. hubAttendanceHours.js makes the same local choice.
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

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}

function blankDay(date) {
  return {
    date, clocked_minutes: 0, tracked_minutes: 0, delta_minutes: 0,
    outside_shift_minutes: 0, adjustment_minutes: 0,
  };
}

// The whole cell in words. A stack of three bare figures is unreadable to a
// screen reader, and neither flag below may depend on its glyph alone.
function cellLabel(day, name) {
  const parts = [
    name,
    longDateLabel(day.date),
    `${formatHm(day.clocked_minutes)} clocked`,
    `${formatHm(day.tracked_minutes)} charged`,
    `${formatHm(day.delta_minutes)} off job`,
  ];
  if (day.outside_shift_minutes > 0) {
    parts.push(`${formatHm(day.outside_shift_minutes)} charged outside shift`);
  }
  if (day.adjustment_minutes > 0) {
    parts.push(`${formatHm(day.adjustment_minutes)} adjusted`);
  }
  return parts.join(", ");
}

// A `<div>`, not a `<button>`: there is no drill-down here, and the detail
// this grid could expand already has a home in Hours.
function cellHtml(day, name) {
  const outside = day.outside_shift_minutes > 0
    ? `<span class="hub-compare-flag hub-compare-flag-outside"><span aria-hidden="true">⚠</span> ${escapeHtml(formatHm(day.outside_shift_minutes))} charged outside shift</span>`
    : "";
  const adjusted = day.adjustment_minutes > 0
    ? `<span class="hub-compare-adjustment">+${escapeHtml(formatHm(day.adjustment_minutes))} adjusted</span>`
    : "";
  return `<div class="hub-compare-cell" aria-label="${escapeHtml(cellLabel(day, name))}">
    <span class="hub-compare-clocked">${formatHm(day.clocked_minutes)}</span>
    <span class="hub-compare-tracked">${formatHm(day.tracked_minutes)}</span>
    <span class="hub-compare-delta">Δ ${formatHm(day.delta_minutes)}</span>
    ${outside}${adjusted}
  </div>`;
}

// The Week column and the Company total foot stack the same three figures as
// a cell, without the flags: a week's worth of warnings is a number nobody
// can act on.
function totalsStackHtml(clocked, tracked, delta) {
  return `<div class="hub-compare-cell">
    <span class="hub-compare-clocked">${formatHm(clocked)}</span>
    <span class="hub-compare-tracked">${formatHm(tracked)}</span>
    <span class="hub-compare-delta">Δ ${formatHm(delta)}</span>
  </div>`;
}

function setStatus(container, message, type = "") {
  const status = container.querySelector(".hub-compare-message");
  if (!status) return;
  status.textContent = message;
  status.className = `hub-compare-message${type ? ` ${type}` : ""}`;
}

export function mountHubAttendanceCompare(container, payload, { onWeekChange } = {}) {
  async function downloadCsv(button) {
    button.disabled = true;
    setStatus(container, "Preparing export…");
    try {
      const { blob, filename } = await apiExportHubAttendance({ week: payload.week_start });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setStatus(container, `Exported ${filename}.`, "success");
    } catch (err) {
      setStatus(container, friendlyError(err, "Could not export attendance."), "error");
    } finally {
      button.disabled = false;
    }
  }

  function render() {
    const headers = payload.days
      .map((day) => `<th scope="col">${escapeHtml(shortDateLabel(day))}</th>`)
      .join("");
    const rows = payload.rows
      .map((row) => {
        const name = userName(row.user);
        const byDate = new Map(row.days.map((day) => [day.date, day]));
        const cells = payload.days
          .map((dateValue) => `<td>${cellHtml(byDate.get(dateValue) || blankDay(dateValue), name)}</td>`)
          .join("");
        const total = totalsStackHtml(row.total_minutes, row.tracked_minutes, row.delta_minutes);
        return `<tr><th scope="row">${escapeHtml(name)}</th>${cells}<td class="hub-compare-row-total">${total}</td></tr>`;
      })
      .join("");

    // The foot's charged and off-job columns are summed here rather than
    // carried on the payload: `totals_by_day` is the clocked tally the Hours
    // grid already shares, and growing it would give two sub-tabs one object
    // with a column only one of them reads.
    const trackedByDate = new Map();
    const deltaByDate = new Map();
    for (const row of payload.rows) {
      for (const day of row.days) {
        trackedByDate.set(day.date, (trackedByDate.get(day.date) || 0) + day.tracked_minutes);
        deltaByDate.set(day.date, (deltaByDate.get(day.date) || 0) + day.delta_minutes);
      }
    }
    const totals = payload.totals_by_day
      .map((entry) => `<td>${totalsStackHtml(
        entry.minutes,
        trackedByDate.get(entry.date) || 0,
        deltaByDate.get(entry.date) || 0,
      )}</td>`)
      .join("");

    // 167 or 169. Said out loud so a short week does not read as lost hours.
    const dst = payload.week_hours === 168
      ? ""
      : `<p class="hint hub-compare-dst">Daylight saving: this week is ${escapeHtml(String(payload.week_hours))} hours long, not 168.</p>`;

    const foot = totalsStackHtml(
      payload.total_minutes, payload.tracked_minutes, payload.delta_minutes,
    );
    const table = payload.rows.length
      ? `<div class="hub-hours-table-wrap hub-compare-table-wrap">
          <table class="hub-hours-table hub-compare-table">
            <caption class="sr-only">Clocked against charged for ${escapeHtml(payload.week_start)} through ${escapeHtml(payload.week_end)}</caption>
            <thead><tr><th scope="col">Person</th>${headers}<th scope="col">Week</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><th scope="row">Company total</th>${totals}<td>${foot}</td></tr></tfoot>
          </table>
        </div>`
      : `<p class="hint hub-compare-empty">Nobody clocked in this week.</p>`;

    container.innerHTML = `<section class="hub-compare" aria-labelledby="hub-compare-heading">
      <h3 id="hub-compare-heading" class="sr-only">Charged against clocked</h3>
      <div class="hub-compare-toolbar">
        <div class="hub-compare-week-nav">
          <button type="button" class="secondary-btn hub-compare-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
          <button type="button" class="secondary-btn hub-compare-next" aria-label="Next week">▶</button>
        </div>
        <div class="hub-compare-actions">
          ${tipHtml("hub.charged-vs-clocked")}
          <button type="button" class="secondary-btn hub-compare-export">Export CSV</button>
        </div>
      </div>
      <p class="hub-compare-message" aria-live="polite"></p>
      ${table}
      ${dst}
      <p class="hint hub-compare-legend">Clocked = time on shift, the pay number. Charged = time on a work-order clock. Δ = on shift, not on a job. ⚠ = charged with no punch covering it. Adjusted = hand-entered labor, which has no start or stop and is counted in neither column.</p>
    </section>`;

    container.querySelector(".hub-compare-prev")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, -7));
    });
    container.querySelector(".hub-compare-next")?.addEventListener("click", () => {
      onWeekChange?.(shiftMonday(payload.week_start, 7));
    });
    container.querySelector(".hub-compare-export")?.addEventListener("click", (event) => {
      void downloadCsv(event.currentTarget);
    });
  }

  render();
}
