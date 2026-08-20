// View: the User Hub's Dashboard tab (technician-shaped, every role for now
// -- see this plan's Global Constraints) and My Work Orders tab.
//
// Layer: views. Consumes exactly the GET /hub payload userHub.js already
// fetched; makes no requests of its own except the embedded work-order list.

import { escapeHtml } from "../format.js";
import { mountWorkOrderList, focusWorkOrderNumber } from "./workOrders.js";
import { showPage } from "./nav.js";

// Mirrors `domain.labor_day.DISPLAY_ANCHOR_HOUR` -- the timeline strip's
// axis starts here unless work began earlier. A *display* anchor only,
// never a day boundary (see P1's labor_day.py).
const DISPLAY_ANCHOR_HOUR = 8;

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value, sub) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(String(value))}</p>
      ${sub ? `<p class="hub-tile-sub">${escapeHtml(sub)}</p>` : ""}
    </section>`;
}

function countsHtml(counts) {
  return `
    <div class="hub-tile-grid">
      ${tileHtml("Assigned to me", counts.assigned, "work orders")}
      ${tileHtml("In progress", counts.in_progress, "")}
      ${tileHtml("Ready to complete", counts.ready_to_complete, counts.ready_to_complete ? "waiting on supervisor" : "")}
    </div>`;
}

// The axis range: `min(8am, earliest session start)` to `max(now, 5pm)`, so
// an early start extends it left instead of falling off (spec §5.2). All in
// minutes-since-midnight for the local day the payload's `day` describes.
function timelineRangeMinutes(timeline, nowMinutes) {
  const anchor = DISPLAY_ANCHOR_HOUR * 60;
  const fivePm = 17 * 60;
  let start = anchor;
  let end = Math.max(fivePm, nowMinutes);
  timeline.forEach((entry) => {
    const startedMinutes = minutesSinceMidnight(entry.started_at);
    if (startedMinutes < start) start = startedMinutes;
  });
  return { start, end: Math.max(end, start + 60) };
}

function minutesSinceMidnight(isoString) {
  const d = new Date(isoString);
  return d.getHours() * 60 + d.getMinutes();
}

function hourLabelsHtml(rangeStart, rangeEnd) {
  const labels = [];
  const firstHour = Math.floor(rangeStart / 60);
  const lastHour = Math.ceil(rangeEnd / 60);
  for (let h = firstHour; h <= lastHour; h++) {
    const hour12 = ((h + 11) % 12) + 1;
    const suffix = h < 12 || h === 24 ? "a" : "p";
    labels.push(`<span class="hub-timeline-hour">${hour12}${suffix}</span>`);
  }
  return `<div class="hub-timeline-axis">${labels.join("")}</div>`;
}

function timelineBlocksHtml(timeline, rangeStart, rangeEnd) {
  const span = rangeEnd - rangeStart;
  return timeline
    .map((entry) => {
      const startedMinutes = minutesSinceMidnight(entry.started_at);
      const leftPct = ((startedMinutes - rangeStart) / span) * 100;
      const widthPct = Math.max((entry.minutes / span) * 100, 0.5);
      const running = !entry.ended_at;
      const label = running ? `${entry.number} (running)` : entry.number;
      // Position rides on data-* and is applied via CSSOM in
      // `mountHubDashboard`, not an inline `style=`: the app's CSP has no
      // `style-src`, so it falls back to `default-src 'self'` and the
      // browser drops style attributes parsed out of markup. CSSOM sets
      // are outside CSP's scope, so they still apply.
      return `<div class="hub-timeline-block${running ? " hub-timeline-block-running" : ""}" data-left="${leftPct}" data-width="${widthPct}" title="WO ${escapeHtml(entry.number)} — ${escapeHtml(formatHm(entry.minutes))}${entry.auto_closed ? " (auto-closed estimate)" : ""}">${escapeHtml(label)}</div>`;
    })
    .join("");
}

function timelineHtml(payload) {
  const { timeline, clock } = payload;
  const nowMinutes = minutesSinceMidnight(payload.server_now);
  if (!timeline.length && !clock.running_session) {
    return `<p class="hint">No time tracked yet today. Start a clock from a work order or use Start on… above.</p>`;
  }
  const { start, end } = timelineRangeMinutes(timeline, nowMinutes);
  return `
    <div class="hub-timeline">
      ${hourLabelsHtml(start, end)}
      <div class="hub-timeline-track">
        ${timelineBlocksHtml(timeline, start, end)}
      </div>
    </div>`;
}

function adjustmentsHtml(adjustments) {
  if (!adjustments.length) return "";
  return adjustments
    .map(
      (a) =>
        `<p class="hub-adjustment-line">Adjustments &nbsp;<strong>${escapeHtml(formatHm(a.minutes))}</strong> &nbsp;recorded by ${escapeHtml(a.recorded_by_name)} · WO ${escapeHtml(a.work_order_number)}</p>`
    )
    .join("");
}

function timeTodayHtml(payload) {
  const { clock } = payload;
  return `
    <section class="hub-time-today">
      <p class="hub-tile-label">Time today</p>
      <div class="hub-time-today-row">
        <p class="hub-clock-hero">${escapeHtml(formatHm(clock.total_minutes_today))}</p>
        ${clock.running_session ? `<span class="hub-running-badge">● running</span>` : ""}
      </div>
      <p class="hub-time-today-line">Tracked &nbsp;<strong>${escapeHtml(formatHm(clock.closed_minutes_today + clock.running_minutes_today))}</strong></p>
      ${adjustmentsHtml(clock.adjustments)}
      ${timelineHtml(payload)}
    </section>`;
}

function toolsOutHtml(toolsOut) {
  if (!toolsOut.length) {
    return `<section class="hub-tools-out"><p class="hub-tile-label">Tools out</p><p class="hint">No tools currently checked out.</p></section>`;
  }
  const rows = toolsOut
    .map((t) => {
      const since = t.since
        ? new Date(t.since).toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" })
        : "";
      return `<li><span>${escapeHtml(t.name)}</span><span class="hub-tool-since">since ${escapeHtml(since)}</span></li>`;
    })
    .join("");
  return `
    <section class="hub-tools-out">
      <p class="hub-tile-label">Tools out <span class="hub-tile-count">${toolsOut.length}</span></p>
      <ul class="hub-tools-list">${rows}</ul>
    </section>`;
}

export function mountHubDashboard(container, payload) {
  container.innerHTML =
    countsHtml(payload.counts) +
    timeTodayHtml(payload) +
    toolsOutHtml(payload.tools_out) +
    // Empty for a Technician; userHub.js mounts the crew board here for
    // supervisor+ viewers (spec §5.3: the crew board lives inside this same
    // Dashboard tab, not a new one). Present unconditionally so userHub.js
    // never has to special-case whether this element exists.
    `<div id="hub-crew-mount"></div>`;
  container.querySelectorAll(".hub-timeline-block").forEach((block) => {
    block.style.left = `${block.dataset.left}%`;
    block.style.width = `${block.dataset.width}%`;
  });
}

// Capped so an Admin/Owner's (currently company-wide, until P4 scopes it)
// call does not render hundreds of cards in a hub tab -- the escape hatch
// is the "View all" link, not client-side pagination duplicating the real
// page's "Show all" control.
const HUB_WORK_ORDERS_LIMIT = 10;

let mountedList = null;

export function mountHubWorkOrders(container, payload) {
  container.innerHTML = `
    <div class="hub-wo-list"></div>
    <p class="hub-wo-view-all"><button type="button" class="secondary-btn" data-action="hub-view-all-work-orders">View all in Work Orders →</button></p>
  `;
  const listContainer = container.querySelector(".hub-wo-list");
  mountedList = mountWorkOrderList({
    container: listContainer,
    lockedFilter: { limit: HUB_WORK_ORDERS_LIMIT },
    onOpen: (card) => {
      focusWorkOrderNumber(card.number);
      showPage("work-orders");
    },
  });
  void mountedList.refresh();

  container.querySelector('[data-action="hub-view-all-work-orders"]').addEventListener("click", () => {
    showPage("work-orders");
  });
}
