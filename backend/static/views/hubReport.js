// View: the Admin hub's weekly closed report tab.
//
// Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §7
//
// Mirrors the Excel export (W11): one section per service type, rows grouped
// under it with their primary community, the six workbook columns plus the
// close instant. The week picker moves one Monday at a time; the payload's
// own `week_start` is the source of truth for where the arrows go, and the
// server decides whether a week is frozen -- this view only labels it.

import { escapeHtml, friendlyError } from "../format.js";
import { openWorkOrdersByNumberSearch } from "./workOrders.js";
import { showPage } from "./nav.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

// Mirrors `domain.work_orders.COMMUNITY_LABELS`; the payload carries keys.
const COMMUNITY_LABELS = {
  scholars: "Scholars",
  centennial: "Centennial",
  commons: "Commons",
  young_hall: "Young Hall",
  academics: "Academics",
};

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function shortDateLabel(iso, { year = false } = {}) {
  return isoDate(iso).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(year ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
}

// Monday arithmetic in UTC on the ISO date, so a DST-shifted local clock can
// never land the arrow on a Sunday or a Tuesday.
function shiftMonday(iso, days) {
  const day = isoDate(iso);
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}

// The server sends UTC instants; the Admin reads them in Central, which is the
// zone the report's own week is cut in.
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

function cellText(value) {
  return escapeHtml(value || "—");
}

function statusLine(payload) {
  if (payload.status === "completed" && payload.frozen_at) {
    return `Completed · frozen ${centralStamp(payload.frozen_at)}`;
  }
  const label = payload.status === "completed" ? "Completed" : "In progress";
  return `${label} · generated ${centralStamp(payload.generated_at)}`;
}

function countLine(closedCount, newWorkOrderCount) {
  const closed = `${closedCount} closed work order${closedCount === 1 ? "" : "s"}`;
  const added = `${newWorkOrderCount} new work order${newWorkOrderCount === 1 ? "" : "s"}`;
  return `${closed} · ${added}`;
}

function rowHtml(row) {
  // A real <button>, so the row is keyboard-reachable -- and the cell's only
  // button, because a button inside a button is hoisted out into a sibling.
  // Every row here is closed, so every one routes to the exact-number search.
  return `<tr>
      <td>${escapeHtml(COMMUNITY_LABELS[row.community] || row.community)}</td>
      <td><button type="button" class="hub-report-row-btn" data-number="${escapeHtml(
        row.number
      )}" data-archived="1">${escapeHtml(row.number)}</button></td>
      <td>${cellText(row.assigned_to)}</td>
      <td>${cellText(row.location)}</td>
      <td>${cellText(row.schedule_date)}</td>
      <td>${cellText(row.priority)}</td>
      <td>${escapeHtml(centralStamp(row.archived_at))}</td>
    </tr>`;
}

// Rows arrive in workbook order (service type, community, number); group by
// service type preserving that order.
function groupByServiceType(rows) {
  const groups = new Map();
  for (const row of rows) {
    const label = row.service_type_label;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(row);
  }
  return groups;
}

function sectionHtml(label, rows) {
  // The wrap is what scrolls on a narrow screen, so the page itself does not.
  return `<section class="hub-report-section">
      <h3>${escapeHtml(label)} (${rows.length})</h3>
      <div class="hub-timesheet-table-wrap">
        <table class="hub-report-table">
          <thead>
            <tr>
              <th>Community</th><th>Number</th><th>Assigned to</th><th>Location</th>
              <th>Schedule date</th><th>Priority</th><th>Closed</th>
            </tr>
          </thead>
          <tbody>${rows.map(rowHtml).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

function bodyHtml(payload) {
  if (!payload.rows.length) {
    return `<p class="hub-report-empty">No work orders closed this week.</p>`;
  }
  return Array.from(groupByServiceType(payload.rows), ([label, rows]) =>
    sectionHtml(label, rows)
  ).join("");
}

function headerHtml(payload) {
  const inProgress = payload.status === "in_progress";
  // A plain link, as the timesheet export is -- the browser downloads it and
  // the server names the file for the Monday it covers.
  return `<header class="hub-report-header">
      <div class="hub-report-title">
        <h2>Weekly Report</h2>
        <div class="hub-report-weeknav">
          <button type="button" class="secondary-btn hub-report-prev" aria-label="Previous week">◀</button>
          <p class="hub-report-week">Week of ${escapeHtml(
            shortDateLabel(payload.week_start)
          )} – ${escapeHtml(shortDateLabel(payload.week_end, { year: true }))}</p>
          <button type="button" class="secondary-btn hub-report-next" aria-label="Next week"${
            inProgress ? " disabled" : ""
          }>▶</button>
          <button type="button" class="secondary-btn hub-report-this-week"${
            inProgress ? " disabled" : ""
          }>This week</button>
        </div>
        <p class="hub-report-status">${escapeHtml(statusLine(payload))}</p>
      </div>
      <div class="hub-report-actions">
        <p class="hub-report-count">${escapeHtml(
          countLine(payload.count, payload.new_work_order_count)
        )}</p>
        <a class="secondary-btn hub-report-download" href="/hub/report/export?week=${escapeHtml(
          payload.week_start
        )}">Download Excel</a>
      </div>
    </header>`;
}

// A closed row has no card page -- the Work Orders list hides archived rows --
// so it routes to the exact-number search, which fires the shipped "Work Order
// has been closed. Restore?" prompt.
function wireRowButtons(panel) {
  panel.querySelectorAll(".hub-report-row-btn").forEach((button) => {
    button.addEventListener("click", () => {
      openWorkOrdersByNumberSearch(button.dataset.number);
      showPage("work-orders");
    });
  });
}

function wireWeekNav(panel, payload, onSelectWeek) {
  panel.querySelector(".hub-report-prev")?.addEventListener("click", () => {
    onSelectWeek?.(shiftMonday(payload.week_start, -7));
  });
  panel.querySelector(".hub-report-next")?.addEventListener("click", () => {
    onSelectWeek?.(shiftMonday(payload.week_start, 7));
  });
  panel.querySelector(".hub-report-this-week")?.addEventListener("click", () => {
    onSelectWeek?.(null);
  });
}

export function mountHubReport(panel, payload, { onSelectWeek } = {}) {
  panel.innerHTML = `${headerHtml(payload)}${bodyHtml(payload)}`;
  wireRowButtons(panel);
  wireWeekNav(panel, payload, onSelectWeek);
}

export function renderReportSkeleton(panel) {
  panel.innerHTML = `<p class="hub-report-loading">Loading the report…</p>`;
}

export function renderReportError(panel, err, onRetry) {
  const message = escapeHtml(friendlyError(err, "Could not load the report."));
  panel.innerHTML = `<div class="hub-report-load-error"><p class="error">${message}</p>
      <button type="button" class="secondary-btn hub-report-retry">Retry</button></div>`;
  panel.querySelector(".hub-report-retry")?.addEventListener("click", () => onRetry?.());
}
