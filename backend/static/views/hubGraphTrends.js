// The two weekly trend charts on the User Hub Graphs tab: work-order age and
// close-out time, and the share closed on schedule. Each shows as a tile (the
// last full week's figures over a sparkline) and opens in the Graphs pop-up
// as the full dependency-free SVG chart. Exact values are always repeated in
// the table; the SVG is an at-a-glance aid, never the only way to read a number.

import { escapeHtml } from "../format.js";

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
  { key: "age", label: "Circulating age", short: "open age", value: "circulating_median_age_days", p90: "circulating_p90_age_days", count: "circulating_count", title: durationTitle("Circulating age") },
  { key: "close", label: "Time to close", short: "time to close", value: "closed_median_days", p90: "closed_p90_days", count: "closed_count", title: durationTitle("Time to close") },
];
const ON_TIME_SERIES = {
  key: "ontime", value: "on_time_pct", count: "scheduled_closed_count",
  title: (bucket) => `Week of ${weekLabel(bucket)}: ${onTimeSummary(bucket, 0)}`,
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const isPhone = () => typeof matchMedia === "function" && matchMedia("(max-width: 600px)").matches;

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
// then each series' bands under every line under every dot. Drawn narrower on
// a phone so the axis text keeps its size instead of shrinking with the chart.
function lineChart(buckets, seriesList, { max, step, unit, className, ariaLabel, height = 230 }) {
  const width = isPhone() ? 340 : 620;
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
  // The last label hangs left of its tick: centred, it runs off the chart's edge.
  const dates = labelled.map((index) => `<text x="${x(index)}" y="${height - 10}" text-anchor="${index === lastIndex && lastIndex ? "end" : "middle"}">${escapeHtml(shortDate(buckets[index].start))}</text>`).join("");
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
  const rows = buckets.map((bucket) => `<tr><th scope="row">${escapeHtml(bucket.start)} – ${escapeHtml(bucket.end)}${bucket.partial ? " (partial)" : ""}</th>${DURATION_SERIES.map((series) => `<td data-label="${escapeHtml(series.label)}">${durationCell(bucket, series)}</td>`).join("")}<td data-label="Closed within ${ON_TIME_DAYS} days">${escapeHtml(onTimeSummary(bucket, 1))}</td></tr>`).join("");
  return `<details class="hub-duration-details"><summary>View exact weekly values</summary><div class="hub-timesheet-table-wrap"><table class="hub-timesheet-table"><thead><tr><th>Week</th>${DURATION_SERIES.map((series) => `<th>${series.label} (median / p90)</th>`).join("")}<th>Closed within ${ON_TIME_DAYS} days of schedule</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}

// One entry per tile. `stats` is the tile's headline, read off one bucket:
// [series key, figure, caption]. A week with nothing to measure shows a dash
// and says why, rather than printing a zero that was never observed.
const TRENDS = {
  days: {
    tile: "Age and close-out time",
    title: "Work-order age and close-out time",
    hint: "Circulating age is how old the still-open work orders were at each week end; time to close is creation to Closed for work orders closed that week. Hover or tap a dot for its figures.",
    series: DURATION_SERIES,
    chart: (buckets) => durationLegend() + durationSvg(buckets),
    stats: (bucket) => DURATION_SERIES.map((series) => (bucket[series.value] === null
      ? [series.key, "–", `${series.short} · no sample`]
      : [series.key, `${bucket[series.value].toFixed(1)}d`, series.short])),
  },
  ontime: {
    tile: `Closed within ${ON_TIME_DAYS} days`,
    title: `Closed within ${ON_TIME_DAYS} days of schedule`,
    hint: `Share of each week's closed work orders that closed no more than ${ON_TIME_DAYS} days after their schedule date; early counts as on time. Work orders without a schedule date are left out and counted separately.`,
    series: [ON_TIME_SERIES],
    chart: onTimeSvg,
    stats: (bucket) => [bucket.on_time_pct === null
      ? ["ontime", "–", "on time · no scheduled closes"]
      : ["ontime", `${bucket.on_time_pct.toFixed(0)}%`, "on time"]],
  },
};

// The last twelve weeks as bare lines. Nulls are skipped rather than drawn as
// gaps: at this size the tile only has to say which way things are heading.
function sparkSvg(buckets, trend) {
  const recent = buckets.slice(-12);
  const values = recent.flatMap((bucket) => trend.series.map((series) => bucket[series.value])).filter((value) => value !== null);
  const max = trend.series[0].key === "ontime" ? 100 : Math.max(...values, 1) * 1.1;
  const x = (index) => (100 * index) / Math.max(1, recent.length - 1);
  const lines = trend.series.map((series) => {
    const points = recent.flatMap((bucket, index) => (bucket[series.value] === null ? [] : [`${x(index).toFixed(1)},${(28 - (26 * bucket[series.value]) / max).toFixed(1)}`]));
    return points.length > 1 ? `<polyline class="hub-duration-line hub-duration-${series.key}" points="${points.join(" ")}"/>` : "";
  }).join("");
  return `<svg class="hub-trend-spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">${lines}</svg>`;
}

export function trendTilesHtml(buckets) {
  // The week in progress is still moving, so the headline is the last full one.
  const settled = buckets.filter((bucket) => !bucket.partial).at(-1) ?? buckets.at(-1);
  return Object.entries(TRENDS).map(([key, trend]) => {
    const stats = !settled ? "" : trend.stats(settled).map(([seriesKey, value, label]) =>
      `<span class="hub-trend-stat"><span class="hub-duration-key hub-duration-key-${seriesKey}"></span><b>${value}</b>${label}</span>`).join("");
    const foot = settled ? `Week of ${escapeHtml(weekLabel(settled))} · tap to open` : "No weeks in this range · tap to open";
    return `<button type="button" class="hub-graph-tile hub-trend-tile" data-graph-trend="${key}" aria-label="Open ${escapeHtml(trend.title)} chart"><span class="hub-graph-tile-label">${escapeHtml(trend.tile)}</span>${stats}${sparkSvg(buckets, trend)}<span class="hub-trend-tile-foot">${foot}</span></button>`;
  }).join("");
}

// The pop-up's title, subtitle and body for one trend chart. The range pills
// carry `data-graph-weeks`; hubGraphs.js owns the click.
export function trendSheet(key, payload) {
  const trend = TRENDS[key];
  const buckets = payload.duration.buckets;
  const pills = [12, 26, 52].map((weeks) => `<button type="button" class="hub-graph-seg-btn" data-graph-weeks="${weeks}" aria-pressed="${payload.weeks === weeks}">${weeks} weeks</button>`).join("");
  return {
    title: trend.title,
    sub: `Week by week, last ${payload.weeks} weeks`,
    body: `<section class="hub-graph-panel"><p class="hint">${escapeHtml(trend.hint)}</p><div class="hub-graph-seg" role="group" aria-label="Range">${pills}</div>${trend.chart(buckets)}${durationTable(buckets)}</section>`,
  };
}
