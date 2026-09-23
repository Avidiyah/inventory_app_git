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

// Each duration series plots a weekly median with a band shaded up to its
// p90; the on-time series is a plain percentage line. A week with fewer than
// LOW_SAMPLE rows is faded rather than hidden -- the number is real, just not
// one to steer by.
const LOW_SAMPLE = 5;
// Mirrors `services.hub.ON_TIME_DAYS`.
const ON_TIME_DAYS = 4;
const durationTitle = (label) => (bucket, series) =>
  `${label}, week of ${weekLabel(bucket)}: median ${bucket[series.value].toFixed(1)}d · p90 ${bucket[series.p90].toFixed(1)}d · n=${bucket[series.count]}`;
const DURATION_SERIES = [
  { key: "age", label: "Circulating age", value: "circulating_median_age_days", p90: "circulating_p90_age_days", count: "circulating_count", title: durationTitle("Circulating age") },
  { key: "close", label: "Time to close", value: "closed_median_days", p90: "closed_p90_days", count: "closed_count", title: durationTitle("Time to close") },
];
const ON_TIME_SERIES = {
  key: "ontime", value: "on_time_pct", count: "scheduled_closed_count",
  title: (bucket) => `Week of ${weekLabel(bucket)}: ${onTimeSummary(bucket, 0)}`,
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2026-09-14" -> "Sep 14", read off the string so no timezone can shift it.
function shortDate(iso) {
  return `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}`;
}

function weekLabel(bucket) {
  const sameMonth = bucket.start.slice(5, 7) === bucket.end.slice(5, 7);
  return `${shortDate(bucket.start)}–${sameMonth ? Number(bucket.end.slice(8, 10)) : shortDate(bucket.end)}`;
}

// A 1/2/5 x 10^n step giving about four gridlines, so the axis reads in round days.
function niceStep(max) {
  const raw = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * magnitude).find((step) => step >= raw);
}

// Runs of consecutive non-null weeks; a null week breaks the line and band.
function runs(buckets, field) {
  const result = [];
  let current = [];
  buckets.forEach((bucket, index) => {
    if (bucket[field] === null) {
      if (current.length) result.push(current);
      current = [];
    } else current.push(index);
  });
  if (current.length) result.push(current);
  return result;
}

// "82% on time (41 of 50 scheduled · 6 unscheduled)"; the unscheduled count
// is always shown so a week that mostly lacks schedule dates cannot pass as
// a clean percentage.
function onTimeSummary(bucket, digits) {
  const unscheduled = `${bucket.unscheduled_closed_count} unscheduled`;
  if (bucket.on_time_pct === null) return `No scheduled closes (${unscheduled})`;
  return `${bucket.on_time_pct.toFixed(digits)}% on time (${bucket.on_time_count} of ${bucket.scheduled_closed_count} scheduled · ${unscheduled})`;
}

function seriesSvg(buckets, series, x, y) {
  const last = buckets.length - 1;
  const partialIndex = buckets[last]?.partial ? last : -1;
  const point = (index) => `${x(index)},${y(buckets[index][series.value])}`;
  const bands = !series.p90 ? "" : runs(buckets, series.value).filter((run) => run.length > 1).map((run) => {
    const upper = run.map((index) => `${x(index)},${y(buckets[index][series.p90])}`);
    const lower = run.slice().reverse().map(point);
    return `<polygon class="hub-duration-band hub-duration-band-${series.key}" points="${[...upper, ...lower].join(" ")}"/>`;
  }).join("");
  // The week in progress hangs off the solid line by a dashed segment: its
  // figures will still move before the week closes.
  let partialSegment = "";
  const lines = runs(buckets, series.value).map((run) => {
    let solid = run;
    if (run.at(-1) === partialIndex) {
      solid = run.slice(0, -1);
      if (solid.length) {
        const from = solid.at(-1);
        partialSegment = `<line class="hub-duration-line hub-duration-partial hub-duration-${series.key}" x1="${x(from)}" y1="${y(buckets[from][series.value])}" x2="${x(partialIndex)}" y2="${y(buckets[partialIndex][series.value])}"/>`;
      }
    }
    return solid.length ? `<polyline class="hub-duration-line hub-duration-${series.key}" points="${solid.map(point).join(" ")}"/>` : "";
  }).join("");
  const points = buckets.map((bucket, index) => {
    if (bucket[series.value] === null) return "";
    const low = bucket[series.count] < LOW_SAMPLE;
    const title = `${series.title(bucket, series)}${low ? " · low sample" : ""}${bucket.partial ? " (in progress)" : ""}`;
    const classes = `hub-duration-point hub-duration-point-${series.key}${low ? " hub-duration-point-low" : ""}${bucket.partial ? " hub-duration-point-partial" : ""}`;
    return `<circle class="${classes}" cx="${x(index)}" cy="${y(bucket[series.value])}" r="4"><title>${escapeHtml(title)}</title></circle>`;
  }).join("");
  return { bands, lines: lines + partialSegment, points };
}

// The shared frame: gridlines from 0 to `max` every `step`, ~5 date labels,
// then each series' bands under every line under every dot.
function lineChart(buckets, seriesList, { max, step, unit, className, ariaLabel, height = 230 }) {
  const width = 620;
  const pad = { left: 42, right: 12, top: 16, bottom: 32 };
  const x = (index) => pad.left + ((width - pad.left - pad.right) * index) / Math.max(1, buckets.length - 1);
  const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  const grid = [];
  for (let value = 0; value <= max; value += step) {
    grid.push(`<line class="${value ? "hub-duration-grid" : "hub-duration-axis"}" x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}"/><text class="hub-duration-tick" x="${pad.left - 6}" y="${y(value) + 4}" text-anchor="end">${value}${unit}</text>`);
  }
  // About five date labels, always including the last week; a regular label
  // too close to the last is dropped so the two never overlap.
  const every = Math.ceil(buckets.length / 5);
  const lastIndex = buckets.length - 1;
  const labelled = buckets.map((_, index) => index).filter((index) => index === lastIndex || (index % every === 0 && lastIndex - index >= every / 2));
  const dates = labelled.map((index) => `<text x="${x(index)}" y="${height - 10}" text-anchor="middle">${escapeHtml(shortDate(buckets[index].start))}</text>`).join("");
  const drawn = seriesList.map((series) => seriesSvg(buckets, series, x, y));
  const layer = (name) => drawn.map((parts) => parts[name]).join("");
  return `<svg class="hub-duration-chart ${className}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(ariaLabel)}">${grid.join("")}${layer("bands")}${layer("lines")}${layer("points")}${dates}</svg>`;
}

function durationSvg(buckets) {
  const values = buckets.flatMap((bucket) => DURATION_SERIES.map((series) => bucket[series.p90])).filter((value) => value !== null);
  if (!values.length) return `<div class="hub-graph-empty">No duration samples in this range.</div>`;
  const step = niceStep(Math.max(...values, 1));
  const max = Math.ceil(Math.max(...values, 1) / step) * step;
  return lineChart(buckets, DURATION_SERIES, {
    max, step, unit: "d", className: "hub-duration-days",
    ariaLabel: "Median circulating work-order age and median time to close by week, in days, each shaded up to its 90th percentile",
  });
}

function onTimeSvg(buckets) {
  if (!buckets.some((bucket) => bucket.on_time_pct !== null)) {
    return `<div class="hub-graph-empty">No scheduled work orders closed in this range.</div>`;
  }
  return lineChart(buckets, [ON_TIME_SERIES], {
    max: 100, step: 25, unit: "%", className: "hub-ontime-chart", height: 170,
    ariaLabel: `Percent of scheduled work orders closed within ${ON_TIME_DAYS} days of their schedule date, by week`,
  });
}

function durationLegend() {
  const item = (swatch, text) => `<li><span class="hub-duration-key ${swatch}"></span>${text}</li>`;
  return `<ul class="hub-duration-legend">${[
    item("hub-duration-key-age", "Circulating age (median)"),
    item("hub-duration-key-close", "Time to close (median)"),
    item("hub-duration-key-band", "Shaded up to p90"),
    item("hub-duration-key-partial", "Hollow: week in progress"),
    item("hub-duration-key-low", `Faded: fewer than ${LOW_SAMPLE} work orders`),
  ].join("")}</ul>`;
}

function durationCell(bucket, series) {
  if (bucket[series.value] === null) return "No sample";
  return `${bucket[series.value].toFixed(2)} / ${bucket[series.p90].toFixed(2)} days (n=${bucket[series.count]})`;
}

function durationTable(buckets) {
  const rows = buckets.map((bucket) => `<tr><th scope="row">${escapeHtml(bucket.start)} – ${escapeHtml(bucket.end)}${bucket.partial ? " (partial)" : ""}</th>${DURATION_SERIES.map((series) => `<td>${durationCell(bucket, series)}</td>`).join("")}<td>${escapeHtml(onTimeSummary(bucket, 1))}</td></tr>`).join("");
  return `<details class="hub-duration-details"><summary>View exact weekly values</summary><div class="hub-timesheet-table-wrap"><table class="hub-timesheet-table"><thead><tr><th>Week</th>${DURATION_SERIES.map((series) => `<th>${series.label} (median / p90)</th>`).join("")}<th>Closed within ${ON_TIME_DAYS} days of schedule</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
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
  container.innerHTML = `<section class="hub-graphs"><header class="hub-graphs-header"><div><h2>Graphs${tipHtml("hub.graphs")}</h2><p class="hint">Live circulating work orders. Updated ${escapeHtml(updated)}.</p></div><label class="hub-graphs-range">Range <select class="hub-graphs-weeks" aria-label="Duration graph range"><option value="12" ${payload.weeks === 12 ? "selected" : ""}>12 weeks</option><option value="26" ${payload.weeks === 26 ? "selected" : ""}>26 weeks</option><option value="52" ${payload.weeks === 52 ? "selected" : ""}>52 weeks</option></select></label></header><section>${tabStrip(communityTabs, activeCommunity.key, { attribute: "data-graph-tab", label: "Community" })}<p class="hint">A work order that names multiple communities appears in each matching community chart; do not add community totals together.</p><div class="hub-graph-community">${distributionCard(activeCommunity, payload.statuses, communityDimension(activeCommunity))}</div>${tabStrip(INNER_TABS, activeInner, { attribute: "data-graph-inner", label: `Split ${activeCommunity.label} by` })}${innerGrid(activeCommunity, payload.statuses, activeInner)}</section><section class="hub-duration-section"><h2>Work-order age and close-out time</h2><p class="hint">Circulating age is how old the still-open work orders were at each week end; time to close is creation to Closed for work orders closed that week. Hover a dot for its figures.</p>${durationLegend()}${durationSvg(payload.duration.buckets)}<h3 class="hub-ontime-heading">Closed within ${ON_TIME_DAYS} days of schedule</h3><p class="hint">Share of each week's closed work orders that closed no more than ${ON_TIME_DAYS} days after their schedule date; early counts as on time. Work orders without a schedule date are left out and counted separately.</p>${onTimeSvg(payload.duration.buckets)}${durationTable(payload.duration.buckets)}</section></section>`;
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
