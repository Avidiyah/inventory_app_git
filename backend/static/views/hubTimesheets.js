// View: the Supervisor hub's Timesheets tab.
//
// The JSON payload owns both the grid and each cell's drill-down, so opening
// detail never starts another request. Every displayed total includes manual
// adjustments (D15); the tracked/adjustment split is one click away.

import { apiExportHubTimesheets } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";

const CENTRAL_TIME_ZONE = "America/Chicago";
const FLAG_LABELS = {
  running: { glyph: "●", label: "running" },
  assigned_idle: { glyph: "⚠", label: "assigned but idle" },
};

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  const hours = Math.floor(minutes / 60);
  return `${hours}:${String(minutes % 60).padStart(2, "0")}`;
}

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function shortDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short",
    month: "numeric",
    day: "numeric",
    timeZone: "UTC",
  });
}

function longDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function rangeLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    timeZone: CENTRAL_TIME_ZONE,
  });
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function flagMarkup(flags = []) {
  return flags
    .map((flag) => {
      const meta = FLAG_LABELS[flag] || { glyph: "⚠", label: flag.replace(/_/g, " ") };
      return `<span class="hub-timesheet-flag hub-timesheet-flag-${escapeHtml(flag)}"><span aria-hidden="true">${meta.glyph}</span><span class="sr-only"> ${escapeHtml(meta.label)}</span></span>`;
    })
    .join("");
}

function flagLabels(flags = []) {
  return flags.map((flag) => FLAG_LABELS[flag]?.label || flag.replace(/_/g, " ")).join(", ");
}

function drilldownHtml(day, name) {
  const sessions = day.sessions || [];
  const adjustments = day.adjustments || [];
  const sessionRows = sessions
    .map((session) => {
      const ended = session.ended_at ? timeLabel(session.ended_at) : "running";
      const estimate = session.auto_closed
        ? ` <span class="hub-timesheet-estimate">⚠ estimate</span>`
        : "";
      return `<div class="hub-timesheet-drilldown-row">
        <span>${escapeHtml(timeLabel(session.started_at))} – ${escapeHtml(ended)} · Work order ${escapeHtml(session.number)}${estimate}</span>
        <span>${formatHm(session.minutes)}</span>
      </div>`;
    })
    .join("");
  const adjustmentRows = adjustments
    .map(
      (adjustment) => `<div class="hub-timesheet-drilldown-row">
        <span>Adjustment · Work order ${escapeHtml(adjustment.work_order_number)} by ${escapeHtml(adjustment.recorded_by_name)}</span>
        <span>${formatHm(adjustment.minutes)}</span>
      </div>`,
    )
    .join("");
  const empty = sessions.length || adjustments.length
    ? ""
    : `<p class="hint hub-timesheet-no-detail">No sessions or adjustments recorded.</p>`;
  return `<div class="hub-timesheet-drilldown">
    <div class="hub-timesheet-drilldown-heading">
      <strong>${escapeHtml(name)} · ${escapeHtml(longDateLabel(day.date))}</strong>
      <strong>${formatHm(day.total_minutes)} total</strong>
    </div>
    ${sessionRows}${empty}
    <div class="hub-timesheet-drilldown-row hub-timesheet-subtotal"><span>Tracked</span><span>${formatHm(day.tracked_minutes)}</span></div>
    ${adjustmentRows}
    <div class="hub-timesheet-drilldown-row hub-timesheet-total"><span>Total</span><span>${formatHm(day.total_minutes)}</span></div>
  </div>`;
}

function setStatus(container, message, type = "") {
  const status = container.querySelector(".hub-timesheet-message");
  if (!status) return;
  status.textContent = message;
  status.className = `hub-timesheet-message${type ? ` ${type}` : ""}`;
}

export function mountHubTimesheets(container, payload, { onWeekChange } = {}) {
  const dates = payload.crew_totals_by_day.map((entry) => entry.date);
  let expanded = null;

  function render() {
    const headers = dates
      .map((day) => `<th scope="col">${escapeHtml(shortDateLabel(day))}</th>`)
      .join("");
    const rows = payload.rows
      .map((row, rowIndex) => {
        const name = userName(row.user);
        const daysByDate = new Map(row.days.map((day) => [day.date, day]));
        const cells = dates
          .map((dateValue) => {
            const day = daysByDate.get(dateValue) || {
              date: dateValue,
              tracked_minutes: 0,
              adjustment_minutes: 0,
              total_minutes: 0,
              flags: [],
              sessions: [],
              adjustments: [],
            };
            const isExpanded =
              expanded?.rowIndex === rowIndex && expanded?.date === dateValue;
            const detailId = `hub-timesheet-detail-${rowIndex}`;
            const flags = flagLabels(day.flags);
            const ariaLabel = `${name}, ${longDateLabel(dateValue)}, ${formatHm(day.total_minutes)}${flags ? `, ${flags}` : ""}`;
            return `<td><button type="button" class="hub-timesheet-cell" data-row="${rowIndex}" data-date="${escapeHtml(dateValue)}" aria-label="${escapeHtml(ariaLabel)}" aria-expanded="${isExpanded}" aria-controls="${detailId}">${formatHm(day.total_minutes)}${flagMarkup(day.flags)}</button></td>`;
          })
          .join("");
        const mainRow = `<tr><th scope="row">${escapeHtml(name)}</th>${cells}<td class="hub-timesheet-row-total">${formatHm(row.total_minutes)}</td></tr>`;
        if (expanded?.rowIndex !== rowIndex) return mainRow;
        const day = daysByDate.get(expanded.date);
        if (!day) return mainRow;
        return `${mainRow}<tr class="hub-timesheet-detail-row"><td colspan="${dates.length + 2}" id="hub-timesheet-detail-${rowIndex}">${drilldownHtml(day, name)}</td></tr>`;
      })
      .join("");
    const totals = payload.crew_totals_by_day
      .map((entry) => `<td>${formatHm(entry.minutes)}</td>`)
      .join("");
    const grandTotal = payload.crew_totals_by_day.reduce(
      (sum, entry) => sum + entry.minutes,
      0,
    );
    const table = payload.rows.length
      ? `<div class="hub-timesheet-table-wrap">
          <table class="hub-timesheet-table">
            <caption class="sr-only">Crew timesheets for ${escapeHtml(payload.range.start)} through ${escapeHtml(payload.range.end)}</caption>
            <thead><tr><th scope="col">Technician</th>${headers}<th scope="col">Total</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><th scope="row">Crew total</th>${totals}<td>${formatHm(grandTotal)}</td></tr></tfoot>
          </table>
        </div>`
      : `<p class="hint hub-timesheet-empty">No one is currently routed to you. Crew hours appear here after a work order is routed to you and assigned.</p>`;

    container.innerHTML = `<section class="hub-timesheets" aria-labelledby="hub-timesheets-heading">
      <h2 id="hub-timesheets-heading" class="sr-only">Timesheets</h2>
      <div class="hub-timesheet-toolbar">
        <div class="hub-timesheet-week-nav">
          <button type="button" class="secondary-btn hub-timesheet-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(rangeLabel(payload.range.start, payload.range.end))}</strong>
          <button type="button" class="secondary-btn hub-timesheet-next" aria-label="Next week">▶</button>
        </div>
        <button type="button" class="hub-timesheet-export">Export CSV</button>
      </div>
      <p class="hub-timesheet-message" aria-live="polite"></p>
      ${table}
    </section>`;

    container.querySelectorAll(".hub-timesheet-cell").forEach((button) => {
      button.addEventListener("click", () => {
        const selected = { rowIndex: Number(button.dataset.row), date: button.dataset.date };
        expanded =
          expanded?.rowIndex === selected.rowIndex && expanded?.date === selected.date
            ? null
            : selected;
        render();
      });
    });
    container.querySelector(".hub-timesheet-prev")?.addEventListener("click", () => {
      shiftWeek(-7);
    });
    container.querySelector(".hub-timesheet-next")?.addEventListener("click", () => {
      shiftWeek(7);
    });
    container.querySelector(".hub-timesheet-export")?.addEventListener("click", (event) => {
      void downloadCsv(event.currentTarget);
    });
  }

  function shiftWeek(days) {
    if (!onWeekChange) return;
    const start = isoDate(payload.range.start);
    const end = isoDate(payload.range.end);
    start.setUTCDate(start.getUTCDate() + days);
    end.setUTCDate(end.getUTCDate() + days);
    onWeekChange(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
  }

  async function downloadCsv(button) {
    button.disabled = true;
    setStatus(container, "Preparing export…");
    try {
      const { blob, filename } = await apiExportHubTimesheets({
        start: payload.range.start,
        end: payload.range.end,
      });
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
      setStatus(container, friendlyError(err, "Could not export timesheets."), "error");
    } finally {
      button.disabled = false;
    }
  }

  render();
}
