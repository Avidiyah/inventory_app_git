// View: the Admin hub's daily Report tab.
//
// Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md
//
// Three visual sections from the payload's five: Closed and New each render
// their *week* rows with today's marked, rather than repeating rows in a second
// table. The two counts sit above as a total and its subset -- the same "total
// plus subsets, not disjoint buckets" idiom HubCounts already establishes. The
// CSV still writes all five sections, because a spreadsheet filters on a column
// where a page uses a badge.
//
// Every number on screen comes from the payload's own counts, never from
// counting rows: `closing` can be capped, and a tally over the rendered rows
// would then quietly under-report.

import { escapeHtml, friendlyError } from "../format.js";
import { focusWorkOrderNumber, openWorkOrdersByNumberSearch } from "./workOrders.js";
import { showPage } from "./nav.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

// Lifecycle order, mirroring the service's CLOSING_STATUSES.
const CLOSING_STATUS_LABELS = [
  ["ready_to_complete", "ready to complete"],
  ["completed", "completed"],
  ["review", "review"],
];

const STATUS_LABELS = {
  created: "Created",
  assigned: "Assigned",
  in_progress: "In progress",
  on_hold: "On hold",
  ready_to_complete: "Ready to complete",
  completed: "Completed",
  review: "Review",
};

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function longDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function shortDateLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// The server sends UTC instants; the Admin reads them in Central, which is the
// zone the report's own windows are cut in.
function centralStamp(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: CENTRAL_TIME_ZONE,
  });
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status;
}

// Composed the way the Work Orders card does: community first, then the
// building/unit pair, then the raw vendor LOCATION string.
function placeLabel(row) {
  const unit = [row.building_number, row.unit_number].filter(Boolean).join("-");
  return [row.community, unit, row.location].filter(Boolean).join(" · ") || "—";
}

function techniciansLabel(row) {
  return row.technician_names?.length ? row.technician_names.join(", ") : "—";
}

function badgeHtml(text, extraClass) {
  return `<span class="hub-report-badge ${extraClass}">${escapeHtml(text)}</span>`;
}

// The parenthetical appears only when the sweep actually closed something --
// with the reconcile migration not yet landed this is always absent, which is
// correct rather than a bug.
function autoClosedSuffix(section) {
  const n = section.auto_closed_count;
  return n ? ` <span class="hub-report-subcount">(${n} in NetFacilities)</span>` : "";
}

function countHtml(label, value, suffix = "") {
  return `<span class="hub-report-count"><span class="hub-report-count-label">${escapeHtml(
    label
  )}</span> <span class="hub-report-count-value">${value}</span>${suffix}</span>`;
}

function rowHtml(row, { timestampField, todayNumbers }) {
  const badges = [];
  if (todayNumbers?.has(row.number)) badges.push(badgeHtml("Today", "is-today"));
  if (row.auto_closed) badges.push(badgeHtml("Closed in NetFacilities", "is-auto"));
  if (row.legacy) badges.push(badgeHtml("Legacy", "is-legacy"));

  // A real <button>, so the row is keyboard-reachable -- and the cell's only
  // button, because a button inside a button is hoisted out into a sibling.
  return `<tr>
      <td>
        <div class="hub-report-number-cell">
          <button type="button" class="hub-report-row-btn" data-number="${escapeHtml(
            row.number
          )}" data-archived="${row.archived_at ? "1" : ""}">${escapeHtml(row.number)}</button>
          ${badges.join("")}
        </div>
      </td>
      <td>${escapeHtml(statusLabel(row.status))}</td>
      <td>${escapeHtml(placeLabel(row))}</td>
      <td>${escapeHtml(row.service_type || "—")}</td>
      <td>${escapeHtml(row.supervisor_name || "—")}</td>
      <td>${escapeHtml(techniciansLabel(row))}</td>
      <td>${escapeHtml(centralStamp(row[timestampField]))}</td>
    </tr>`;
}

function tableHtml(rows, { timestampField, timestampHeader, todayNumbers, emptyText }) {
  if (!rows.length) {
    return `<p class="hub-report-empty">${escapeHtml(emptyText)}</p>`;
  }
  const body = rows
    .map((row) => rowHtml(row, { timestampField, todayNumbers }))
    .join("");
  // The wrap is what scrolls on a narrow screen, so the page itself does not.
  return `<div class="hub-timesheet-table-wrap">
      <table class="hub-report-table">
        <thead>
          <tr>
            <th>Number</th><th>Status</th><th>Community / Location</th>
            <th>Service type</th><th>Supervisor</th><th>Technicians</th>
            <th>${escapeHtml(timestampHeader)}</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function closedSectionHtml(payload) {
  const today = payload.sections.closed_today;
  const week = payload.sections.closed_week;
  const todayNumbers = new Set(today.rows.map((row) => row.number));
  return `<section class="hub-report-section">
      <h3>Closed</h3>
      <div class="hub-report-counts">
        ${countHtml("Today", today.count, autoClosedSuffix(today))}
        ${countHtml("This week", week.count, autoClosedSuffix(week))}
      </div>
      ${tableHtml(week.rows, {
        timestampField: "archived_at",
        timestampHeader: "Closed",
        todayNumbers,
        emptyText: "Nothing closed yet today.",
      })}
      <p class="hub-report-footnote">A live view, not an archival record:
        restoring a closed work order -- by hand, by the auto-close undo, or by
        a NetFacilities reappearance -- removes it from these numbers.</p>
    </section>`;
}

function closingSectionHtml(payload) {
  const closing = payload.sections.closing;
  // From `by_status`, never from counting rows: these stay true when capped.
  const breakdown = CLOSING_STATUS_LABELS.filter(([key]) => closing.by_status?.[key])
    .map(([key, label]) => `${escapeHtml(label)} ${closing.by_status[key]}`)
    .join(" · ");
  const truncated = closing.truncated
    ? `<p class="hub-report-truncated">Showing the first rows only -- more are in
        the pipeline than this list displays. The counts above are complete.</p>`
    : "";
  return `<section class="hub-report-section">
      <h3>Closing</h3>
      <div class="hub-report-counts">
        ${countHtml("In the pipeline", closing.count)}
        ${breakdown ? `<span class="hub-report-breakdown">${breakdown}</span>` : ""}
      </div>
      ${truncated}
      ${tableHtml(closing.rows, {
        timestampField: "created_at",
        timestampHeader: "Created",
        todayNumbers: null,
        emptyText: "Nothing is sitting in a closing status.",
      })}
    </section>`;
}

function newSectionHtml(payload) {
  const today = payload.sections.new_today;
  const week = payload.sections.new_week;
  const todayNumbers = new Set(today.rows.map((row) => row.number));
  return `<section class="hub-report-section">
      <h3>New</h3>
      <div class="hub-report-counts">
        ${countHtml("Today", today.count)}
        ${countHtml("This week", week.count)}
      </div>
      ${tableHtml(week.rows, {
        timestampField: "created_at",
        timestampHeader: "Created",
        todayNumbers,
        emptyText: "Nothing new has arrived today.",
      })}
    </section>`;
}

function headerHtml(payload) {
  // A plain link, as the timesheet export is -- the browser downloads it and
  // the server names the file for the day it covers.
  return `<header class="hub-report-header">
      <div class="hub-report-title">
        <h2>Daily Report</h2>
        <p class="hub-report-week">Week of ${escapeHtml(
          shortDateLabel(payload.week.start)
        )} – ${escapeHtml(shortDateLabel(payload.week.end))} · week to date</p>
      </div>
      <div class="hub-report-actions">
        <p class="hub-report-day">${escapeHtml(longDateLabel(payload.day))}</p>
        <p class="hub-report-generated">Generated ${escapeHtml(
          centralStamp(payload.generated_at)
        )}</p>
        <a class="secondary-btn hub-report-download" href="/hub/report/export">Download CSV</a>
      </div>
    </header>`;
}

// R11: a live row opens its card page; a closed row has none -- the Work Orders
// list hides archived rows -- so it routes to the exact-number search, which
// fires the shipped "Work Order has been closed. Restore?" prompt.
function wireRowButtons(panel) {
  panel.querySelectorAll(".hub-report-row-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const number = button.dataset.number;
      if (button.dataset.archived) openWorkOrdersByNumberSearch(number);
      else focusWorkOrderNumber(number);
      showPage("work-orders");
    });
  });
}

export function mountHubReport(panel, payload) {
  panel.innerHTML = `${headerHtml(payload)}
    ${closedSectionHtml(payload)}
    ${closingSectionHtml(payload)}
    ${newSectionHtml(payload)}`;
  wireRowButtons(panel);
}

export function renderReportSkeleton(panel) {
  panel.innerHTML = `<p class="hub-report-loading">Loading the daily report…</p>`;
}

export function renderReportError(panel, err, onRetry) {
  const message = escapeHtml(friendlyError(err, "Could not load the daily report."));
  panel.innerHTML = `<div class="hub-report-load-error"><p class="error">${message}</p>
      <button type="button" class="secondary-btn hub-report-retry">Retry</button></div>`;
  panel.querySelector(".hub-report-retry")?.addEventListener("click", () => onRetry?.());
}
