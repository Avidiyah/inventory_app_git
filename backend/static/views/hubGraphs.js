// Guided, dependency-free SVG charts for the TechFM OA+ User Hub report.
// Exact values are always repeated in HTML legends/tables; the SVG is an
// at-a-glance aid, never the only way to understand a number.

import { escapeHtml } from "../format.js";
import { tipHtml } from "../tooltip.js";

function percent(count, total) {
  return total ? `${((count / total) * 100).toFixed(1)}%` : "0.0%";
}

function polar(cx, cy, radius, angle) {
  const radians = ((angle - 90) * Math.PI) / 180;
  return [cx + radius * Math.cos(radians), cy + radius * Math.sin(radians)];
}

function arcPath(startAngle, endAngle) {
  const [x1, y1] = polar(50, 50, 40, endAngle);
  const [x2, y2] = polar(50, 50, 40, startAngle);
  return `M ${x1} ${y1} A 40 40 0 ${endAngle - startAngle > 180 ? 1 : 0} 0 ${x2} ${y2}`;
}

function donutSvg(distribution, statuses) {
  if (!distribution.total) {
    return `<div class="hub-graph-empty" role="img" aria-label="No circulating work orders">No circulating work orders</div>`;
  }
  let angle = 0;
  const arcs = statuses.flatMap((status) => {
    const count = distribution.counts[status.key] || 0;
    if (!count) return [];
    const next = angle + (count / distribution.total) * 360;
    const path = `<path d="${arcPath(angle, next)}" class="hub-graph-slice hub-graph-slice-${status.key}"/>`;
    angle = next;
    return path;
  }).join("");
  return `<div class="hub-donut-wrap"><svg class="hub-donut" viewBox="0 0 100 100" role="img" aria-label="${escapeHtml(distribution.label)} status distribution, ${distribution.total} circulating work orders">${arcs}</svg><span class="hub-donut-total">${distribution.total}<small>circulating</small></span></div>`;
}

// `kind` identifies which Work Orders filter a click should apply --
// "priority", "community", or "service_type" -- read back by the delegated
// click listener in `mountHubGraphs` below. The filter *value* to send
// differs by kind: priority/community keys line up 1:1 with the Work Orders
// dropdowns' option values, but a service-type key is casefolded for
// grouping (`normalize_service_type` in domain/work_orders.py) while its
// dropdown is populated from raw, case-preserved text -- so service type
// sends `distribution.label` instead, which is always one exact raw value.
// A real <button> gets keyboard activation and focus handling for free,
// matching the Admin Dashboard's existing `hub-tile-pipeline-item` pattern
// (hubAdmin.js).
function distributionCard(distribution, statuses, kind) {
  const rows = statuses.map((status) => {
    const count = distribution.counts[status.key] || 0;
    return `<li><span class="hub-graph-key"><i class="hub-graph-swatch hub-graph-swatch-${status.key}"></i>${escapeHtml(status.label)}</span><span>${count} · ${percent(count, distribution.total)}</span></li>`;
  }).join("");
  const value = kind === "service_type" ? distribution.label : distribution.key;
  return `<button type="button" class="hub-graph-card hub-graph-card-clickable" data-distribution-kind="${kind}" data-distribution-value="${escapeHtml(value)}" aria-label="View ${escapeHtml(distribution.label)} work orders"><h3>${escapeHtml(distribution.label)}</h3>${donutSvg(distribution, statuses)}<ul class="hub-graph-legend">${rows}</ul></button>`;
}

function durationSvg(buckets) {
  const width = 620;
  const height = 230;
  const pad = { left: 42, right: 12, top: 16, bottom: 32 };
  const values = buckets.flatMap((bucket) => [bucket.circulating_avg_age_days, bucket.closed_avg_days]).filter((value) => value !== null);
  if (!values.length) return `<div class="hub-graph-empty">No duration samples in this range.</div>`;
  const max = Math.max(...values, 1);
  const x = (index) => pad.left + ((width - pad.left - pad.right) * index) / Math.max(1, buckets.length - 1);
  const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  const series = (field, className) => {
    let segments = [];
    let current = [];
    buckets.forEach((bucket, index) => {
      const value = bucket[field];
      if (value === null) {
        if (current.length) segments.push(current);
        current = [];
      } else current.push(`${x(index)},${y(value)}`);
    });
    if (current.length) segments.push(current);
    return segments.map((segment) => `<polyline class="hub-duration-line ${className}" points="${segment.join(" ")}"/>`).join("");
  };
  const labels = buckets.filter((_, index) => index === 0 || index === buckets.length - 1 || index % Math.ceil(buckets.length / 4) === 0).map((bucket, index) => {
    const actualIndex = buckets.indexOf(bucket);
    return `<text x="${x(actualIndex)}" y="${height - 10}" text-anchor="middle">${escapeHtml(bucket.start.slice(5))}</text>`;
  }).join("");
  return `<svg class="hub-duration-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Average circulating work-order age and average time to close by week, in days"><line class="hub-duration-axis" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"/><text x="6" y="${pad.top + 6}">${max.toFixed(0)}d</text><text x="13" y="${height - pad.bottom + 4}">0d</text>${series("circulating_avg_age_days", "hub-duration-age")}${series("closed_avg_days", "hub-duration-close")}${labels}</svg>`;
}

function durationTable(buckets) {
  const rows = buckets.map((bucket) => `<tr><th scope="row">${escapeHtml(bucket.start)} – ${escapeHtml(bucket.end)}${bucket.partial ? " (partial)" : ""}</th><td>${bucket.circulating_avg_age_days === null ? "No sample" : `${bucket.circulating_avg_age_days.toFixed(2)} days (n=${bucket.circulating_count})`}</td><td>${bucket.closed_avg_days === null ? "No sample" : `${bucket.closed_avg_days.toFixed(2)} days (n=${bucket.closed_count})`}</td></tr>`).join("");
  return `<details class="hub-duration-details"><summary>View exact weekly values</summary><div class="hub-timesheet-table-wrap"><table class="hub-timesheet-table"><thead><tr><th>Week</th><th>Average circulating age</th><th>Average time to close</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}

export function mountHubGraphs(container, payload, { showAllServiceTypes, onToggleServiceTypes, onWeekChange, onDistributionClick } = {}) {
  const services = showAllServiceTypes ? payload.service_types : payload.service_types.slice(0, 6);
  const serviceToggle = payload.service_types.length > 6
    ? `<button type="button" class="secondary-btn hub-graphs-service-toggle">${showAllServiceTypes ? "Show fewer service types" : `Show all ${payload.service_types.length} service types`}</button>`
    : "";
  const updated = new Date(payload.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  container.innerHTML = `<section class="hub-graphs"><header class="hub-graphs-header"><div><h2>Graphs${tipHtml("hub.graphs")}</h2><p class="hint">Live circulating work orders. Updated ${escapeHtml(updated)}.</p></div><label class="hub-graphs-range">Range <select class="hub-graphs-weeks" aria-label="Duration graph range"><option value="12" ${payload.weeks === 12 ? "selected" : ""}>12 weeks</option><option value="26" ${payload.weeks === 26 ? "selected" : ""}>26 weeks</option><option value="52" ${payload.weeks === 52 ? "selected" : ""}>52 weeks</option></select></label></header><section><h2>Status by priority</h2><div class="hub-graph-grid">${distributionCard(payload.priority_high, payload.statuses, "priority")}${distributionCard(payload.priority_medium, payload.statuses, "priority")}</div></section><section><h2>Status by community</h2><p class="hint">A work order that names multiple communities appears in each matching community chart; do not add community totals together.</p><div class="hub-graph-grid">${payload.communities.map((row) => distributionCard(row, payload.statuses, "community")).join("")}</div></section><section><h2>Status by service type</h2><div class="hub-graph-grid">${services.map((row) => distributionCard(row, payload.statuses, "service_type")).join("")}</div>${serviceToggle}</section><section class="hub-duration-section"><h2>Work-order age and close-out time</h2><p class="hint"><span class="hub-duration-key hub-duration-key-age"></span>Average circulating age at each week end <span class="hub-duration-key hub-duration-key-close"></span>Average time from creation to Closed for work orders closed that week.</p>${durationSvg(payload.duration.buckets)}${durationTable(payload.duration.buckets)}</section></section>`;
  container.querySelector(".hub-graphs-service-toggle")?.addEventListener("click", onToggleServiceTypes);
  // Bound once per container element, guarded like hubAdmin.js's own pipeline
  // tiles: `mountHubGraphs` re-runs against the same container on every
  // service-type toggle and range change, and `container.innerHTML = ...`
  // above only replaces children, not listeners bound to the container
  // itself -- an unguarded bind here would stack up duplicates over a session.
  if (!container.dataset.distributionClickBound) {
    container.dataset.distributionClickBound = "true";
    container.addEventListener("click", (event) => {
      const card = event.target.closest("[data-distribution-kind]");
      if (!card) return;
      onDistributionClick?.(card.dataset.distributionKind, card.dataset.distributionValue);
    });
  }
  container.querySelector(".hub-graphs-weeks")?.addEventListener("change", (event) => onWeekChange?.(Number(event.target.value)));
}

export function destroyHubGraphs() {
  // SVG charts are static DOM only; replacing their mount has no retained
  // canvas instance or listener to dispose. Kept as an explicit lifecycle
  // hook so a future renderer cannot silently skip teardown.
}
