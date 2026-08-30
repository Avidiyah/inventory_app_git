// Guided, dependency-free SVG charts for the TechFM OA+ User Hub report.
// Exact values are always repeated in HTML legends/tables; the SVG is an
// at-a-glance aid, never the only way to understand a number.
//
// The Graphs panel is a two-level drill: community first, then either
// service type or priority within it. Every donut in the tree -- the
// community's own and every card in either grid -- is a status distribution
// over the same seven statuses; only the row set narrows.

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

// Each arc carries `data-status` so a pointer click on the slice drills the
// same way its legend row does. The <path> is deliberately pointer-only --
// no `role`, no tab stop -- because a 40px-radius stroke is a poor keyboard
// target; the legend row below is the real, focusable control for the same
// status, which is why every status gets a legend row even at zero.
function donutSvg(distribution, statuses) {
  if (!distribution.total) {
    return `<div class="hub-graph-empty" role="img" aria-label="No circulating work orders">No circulating work orders</div>`;
  }
  let angle = 0;
  const arcs = statuses.flatMap((status) => {
    const count = distribution.counts[status.key] || 0;
    if (!count) return [];
    const next = angle + (count / distribution.total) * 360;
    const path = `<path d="${arcPath(angle, next)}" class="hub-graph-slice hub-graph-slice-${status.key}" data-status="${status.key}"/>`;
    angle = next;
    return path;
  }).join("");
  return `<div class="hub-donut-wrap"><svg class="hub-donut" viewBox="0 0 100 100" role="img" aria-label="${escapeHtml(distribution.label)} status distribution, ${distribution.total} circulating work orders">${arcs}</svg><span class="hub-donut-total">${distribution.total}<small>circulating</small></span></div>`;
}

// The card is a <div>, not a <button>: it now holds buttons of its own, and
// HTML forbids nesting them -- the browser hoists an inner button out into a
// sibling, silently breaking the flex layout.
//
// The dimension lives on the card (`data-community` plus at most one of
// `data-service-type` / `data-priority`); the status lives on whichever
// target was clicked. `dataset` values are the raw, case-preserved labels the
// Work Orders <select> options are built from, never the casefolded grouping
// keys -- a <select> silently ignores a value matching no <option>.
function distributionCard(distribution, statuses, dimension) {
  const rows = statuses.map((status) => {
    const count = distribution.counts[status.key] || 0;
    return `<li><button type="button" class="hub-graph-legend-row" data-status="${status.key}" aria-label="View ${escapeHtml(distribution.label)} work orders with status ${escapeHtml(status.label)}"><span class="hub-graph-key"><i class="hub-graph-swatch hub-graph-swatch-${status.key}"></i>${escapeHtml(status.label)}</span><span>${count} · ${percent(count, distribution.total)}</span></button></li>`;
  }).join("");
  return `<div class="hub-graph-card"${dimension}><h3>${escapeHtml(distribution.label)}</h3>${donutSvg(distribution, statuses)}<ul class="hub-graph-legend">${rows}</ul><button type="button" class="hub-graph-card-all" data-status="" aria-label="View all ${escapeHtml(distribution.label)} work orders">View all ${distribution.total}</button></div>`;
}

function communityDimension(community) {
  return ` data-community="${escapeHtml(community.key)}"`;
}

function innerGrid(community, statuses, inner) {
  const rows = inner === "priority" ? community.priorities : community.service_types;
  if (!rows.length) {
    const reason = inner === "priority"
      ? (community.total ? "No imported priorities in this community" : "No circulating work orders")
      : "No circulating work orders";
    return `<div class="hub-graph-empty">${escapeHtml(reason)}</div>`;
  }
  const attribute = inner === "priority" ? "data-priority" : "data-service-type";
  return `<div class="hub-graph-grid">${rows.map((row) => distributionCard(
    row,
    statuses,
    `${communityDimension(community)} ${attribute}="${escapeHtml(row.label)}"`,
  )).join("")}</div>`;
}

function tabStrip(tabs, activeKey, { attribute, label }) {
  const buttons = tabs.map((tab) => {
    const active = tab.key === activeKey;
    return `<button type="button" role="tab" class="hub-tab hub-graphs-tab${active ? " active" : ""}" ${attribute}="${escapeHtml(tab.key)}" aria-selected="${active ? "true" : "false"}">${escapeHtml(tab.label)}</button>`;
  }).join("");
  return `<nav class="hub-tabs hub-graphs-tabs" role="tablist" aria-label="${escapeHtml(label)}">${buttons}</nav>`;
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

// The largest community, ties broken by the payload's own (fixed) community
// order. On an empty database every total is 0, so this lands on the first --
// Scholars.
export function largestCommunityKey(payload) {
  let best = null;
  for (const community of payload.communities || []) {
    if (!best || community.total > best.total) best = community;
  }
  return best ? best.key : null;
}

const INNER_TABS = [
  { key: "service_type", label: "Service Type" },
  { key: "priority", label: "Priority" },
];

export function mountHubGraphs(container, payload, { community, inner, onWeekChange, onTabChange, onDistributionClick } = {}) {
  const activeCommunity = payload.communities.find((row) => row.key === community) || payload.communities[0];
  const activeInner = inner === "priority" ? "priority" : "service_type";
  const updated = new Date(payload.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  // Community sub-tabs carry their totals; the inner two stay plain -- every
  // card beneath them shows its own total, and a Priority count would have to
  // explain why it is lower than the community's (blank priorities get no card).
  const communityTabs = payload.communities.map((row) => ({ key: row.key, label: `${row.label} (${row.total})` }));
  container.innerHTML = `<section class="hub-graphs"><header class="hub-graphs-header"><div><h2>Graphs${tipHtml("hub.graphs")}</h2><p class="hint">Live circulating work orders. Updated ${escapeHtml(updated)}.</p></div><label class="hub-graphs-range">Range <select class="hub-graphs-weeks" aria-label="Duration graph range"><option value="12" ${payload.weeks === 12 ? "selected" : ""}>12 weeks</option><option value="26" ${payload.weeks === 26 ? "selected" : ""}>26 weeks</option><option value="52" ${payload.weeks === 52 ? "selected" : ""}>52 weeks</option></select></label></header><section>${tabStrip(communityTabs, activeCommunity.key, { attribute: "data-graph-tab", label: "Community" })}<p class="hint">A work order that names multiple communities appears in each matching community chart; do not add community totals together.</p><div class="hub-graph-community">${distributionCard(activeCommunity, payload.statuses, communityDimension(activeCommunity))}</div>${tabStrip(INNER_TABS, activeInner, { attribute: "data-graph-inner", label: `Split ${activeCommunity.label} by` })}${innerGrid(activeCommunity, payload.statuses, activeInner)}</section><section class="hub-duration-section"><h2>Work-order age and close-out time</h2><p class="hint"><span class="hub-duration-key hub-duration-key-age"></span>Average circulating age at each week end <span class="hub-duration-key hub-duration-key-close"></span>Average time from creation to Closed for work orders closed that week.</p>${durationSvg(payload.duration.buckets)}${durationTable(payload.duration.buckets)}</section></section>`;
  // Bound once per container element, guarded like hubAdmin.js's own pipeline
  // tiles: `mountHubGraphs` re-runs against the same container on every tab
  // switch and range change, and `container.innerHTML = ...` above only
  // replaces children, not listeners bound to the container itself -- an
  // unguarded bind here would stack up duplicates over a session. The tab
  // strips ride the same listener so there is still exactly one.
  if (!container.dataset.distributionClickBound) {
    container.dataset.distributionClickBound = "true";
    container.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-graph-tab], [data-graph-inner]");
      if (tab) {
        if (tab.dataset.graphTab) onTabChange?.({ community: tab.dataset.graphTab });
        else onTabChange?.({ inner: tab.dataset.graphInner });
        return;
      }
      // The status lives on the clicked target (a slice, a legend row, or the
      // card's "View all"); the dimension lives on the card around it.
      const target = event.target.closest("[data-status]");
      if (!target) return;
      const card = target.closest(".hub-graph-card");
      if (!card) return;
      onDistributionClick?.({
        community: card.dataset.community || null,
        serviceType: card.dataset.serviceType || null,
        priority: card.dataset.priority || null,
        status: target.dataset.status || null,
      });
    });
  }
  container.querySelector(".hub-graphs-weeks")?.addEventListener("change", (event) => onWeekChange?.(Number(event.target.value)));
}

export function destroyHubGraphs() {
  // SVG charts are static DOM only; replacing their mount has no retained
  // canvas instance or listener to dispose. Kept as an explicit lifecycle
  // hook so a future renderer cannot silently skip teardown.
}
