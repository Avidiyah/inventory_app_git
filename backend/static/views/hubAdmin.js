// View: the Admin+ hub's company-wide time summary and work order pipeline.
//
// Layer: views. Renders inside the Dashboard tab body, above the crew
// board mount point `hubTechnician.js` already draws. Consumes exactly the
// `GET /hub/admin` payload `userHub.js` fetches for techfm_oa+ viewers;
// makes no requests of its own.

import { escapeHtml, formatMoney } from "../format.js";
import { tipHtml } from "../tooltip.js";
import { showPage } from "./nav.js";
import { openWorkOrdersFilteredByStatus } from "./workOrders.js";

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(value)}</p>
    </section>`;
}

// `domain/hub.py`'s flag vocabulary -- same map `hubSupervisor.js` uses for
// the crew board's flag badges (spec §8: icon plus word, never color alone).
const FLAG_LABELS = {
  long_session: "long session",
  approaching_cap: "approaching cap",
};

function onClockRowHtml(entry) {
  const subject = [`WO ${entry.work_order_number}`, entry.community]
    .filter(Boolean)
    .join(" · ");
  const flag = entry.flag
    ? ` <span class="hub-attention-icon" aria-hidden="true">⚠ ${escapeHtml(FLAG_LABELS[entry.flag] || entry.flag.replace(/_/g, " "))}</span>`
    : "";
  return `
    <li class="hub-onclock-row">
      <span class="hub-onclock-name">${escapeHtml(entry.technician_name)}</span>
      <span class="hub-onclock-subject">${escapeHtml(subject)}</span>
      <span class="hub-onclock-elapsed">${escapeHtml(formatHm(entry.elapsed_minutes))}${flag}</span>
    </li>`;
}

function onClockHtml(onTheClock) {
  const body = onTheClock.length
    ? `<ul class="hub-onclock-list">${onTheClock.map(onClockRowHtml).join("")}</ul>`
    : `<p class="hint">Nobody is on the clock right now.</p>`;
  return `
    <section class="hub-onclock-section">
      <p class="hub-tile-label">On the clock now${tipHtml("hub.clock-attention")} <span class="hub-tile-count">${onTheClock.length}</span></p>
      ${body}
    </section>`;
}

// Order and labels match `backend/static/pages/work-orders.html`'s own
// status filter `<option>`s verbatim (Global Constraints) -- the tile's
// label and the page it opens must always agree.
const PIPELINE_STAGES = [
  ["created", "Created"],
  ["assigned", "Assigned"],
  ["in_progress", "In-Progress"],
  ["ready_to_complete", "Ready to Complete"],
  ["completed", "Completed"],
  ["review", "Review"],
];

function pipelineTileHtml(status, label, count) {
  // Ready to complete carries the attention flag (spec §5.4): it is the one
  // status where the work is done and the supervisor is the bottleneck.
  const flag =
    status === "ready_to_complete" && count > 0
      ? ` <span class="hub-attention-icon" aria-hidden="true">⚠</span>`
      : "";
  return `
    <button type="button" class="hub-tile hub-tile-pipeline-item" data-status="${escapeHtml(status)}">
      <p class="hub-tile-label">${escapeHtml(label)}${flag}</p>
      <p class="hub-tile-value">${escapeHtml(String(count))}</p>
    </button>`;
}

function pipelineHtml(pipeline) {
  const tiles = PIPELINE_STAGES.map(([status, label]) =>
    pipelineTileHtml(status, label, pipeline[status])
  ).join("");
  return `<div class="hub-tile-grid">${tiles}</div>`;
}

// `open`-suffixed rows read as "N open"; the last two (review queue, stale)
// are already a count of open work on their own and don't repeat the word.
const EXCEPTION_ROWS = [
  ["inventory_recounts", "Inventory recounts", true],
  ["missing_item_price", "Missing price / link", true],
  ["item_requests", "Item requests", true],
  ["admin_review_queue", "Admin review queue", false],
  ["stale_work_orders", "Stale > 3 days", false],
];

function exceptionsHtml(exceptions) {
  const rows = EXCEPTION_ROWS.map(([key, label, showOpenSuffix]) => {
    const count = exceptions[key];
    const value = showOpenSuffix ? `${count} open` : String(count);
    return `<li class="hub-exceptions-row"><span>${escapeHtml(label)}</span><span>${escapeHtml(value)}</span></li>`;
  }).join("");
  return `
    <section class="hub-exceptions">
      <p class="hub-tile-label">Exceptions${tipHtml("hub.exceptions")}</p>
      <ul class="hub-exceptions-list">${rows}</ul>
    </section>`;
}

// Unicode block levels, low to high -- a single-series sparkline needs no
// legend (the section title carries it, spec §5.4).
const SPARK_LEVELS = "▁▂▃▄▅▆▇█";

function sparkline(values) {
  if (!values.length) return "";
  const max = Math.max(1, ...values);
  return values
    .map((v) => SPARK_LEVELS[Math.min(SPARK_LEVELS.length - 1, Math.floor((v / max) * (SPARK_LEVELS.length - 1)))])
    .join("");
}

function billingHtml(billing) {
  const legacyRow =
    billing.legacy_live_count === null || billing.legacy_live_count === undefined
      ? ""
      : `<li class="hub-exceptions-row"><span>Legacy work orders live</span><span>${escapeHtml(String(billing.legacy_live_count))}</span></li>`;
  const avg =
    billing.avg_days_to_complete === null || billing.avg_days_to_complete === undefined
      ? "—"
      : `${billing.avg_days_to_complete.toFixed(1)} d`;
  return `
    <section class="hub-billing">
      <p class="hub-tile-label">Billing · this week${tipHtml("hub.billing-week")}</p>
      <ul class="hub-exceptions-list">
        <li class="hub-exceptions-row"><span>Materials</span><span>${escapeHtml(formatMoney(billing.materials_total))}</span></li>
        <li class="hub-exceptions-row"><span>Labor</span><span>${escapeHtml(formatMoney(billing.labor_total))}</span></li>
        <li class="hub-exceptions-row hub-billing-total"><span>Total</span><span>${escapeHtml(formatMoney(billing.total))}</span></li>
        <li class="hub-exceptions-row"><span>Avg time to complete</span><span>${escapeHtml(avg)}</span></li>
        <li class="hub-exceptions-row"><span>Completed / day</span><span class="hub-billing-sparkline">${escapeHtml(sparkline(billing.completed_per_day))}</span></li>
        ${legacyRow}
      </ul>
    </section>`;
}

export function mountHubAdminSummary(container, payload) {
  container.innerHTML = `
    ${onClockHtml(payload.on_the_clock)}
    <div class="hub-tile-grid">
      ${tileHtml("Supervisor Time", formatHm(payload.supervisor_minutes_today))}
      ${tileHtml("Technician Time", formatHm(payload.technician_minutes_today))}
    </div>
    ${pipelineHtml(payload.pipeline)}
    <div class="hub-exceptions-billing-grid">
      ${exceptionsHtml(payload.exceptions)}
      ${billingHtml(payload.billing)}
    </div>`;

  // Bound once per container element, guarded by a dataset flag -- this
  // function re-runs on every live refresh (initial load, the
  // `labor.session.changed` socket event, the 60s safety timer) against the
  // *same* container node whenever the Dashboard tab hasn't been rebuilt in
  // between, so binding unconditionally here would stack up duplicate
  // listeners over a session. The container is only ever replaced wholesale
  // by `hubTechnician.js`'s `mountHubDashboard`, which drops the flag along
  // with the old node.
  if (!container.dataset.pipelineBound) {
    container.dataset.pipelineBound = "true";
    container.addEventListener("click", (event) => {
      const tile = event.target.closest("[data-status]");
      if (!tile) return;
      openWorkOrdersFilteredByStatus(tile.dataset.status);
      showPage("work-orders");
    });
  }
}
