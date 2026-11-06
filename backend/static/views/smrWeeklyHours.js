// View helper: the SMR page's weekly hours chart (spec
// 2026-11-06-smr-weekly-hours-chart). Per Mon-Sun week three stacked bars --
// Original (NetFacilities charge before any audit), Added (charged paper
// hours), Missing (invoiced but on no order yet) -- each split by vendor.
// Dependency-free SVG; the figures table under it repeats every number so
// the picture is never the only way to read one. CSP: colours are classes.
//
// Layer: views (leaf under smr.js). Admin+; smr.js shows the panel, this
// module fills it.

import { apiSmrWeeklyHours } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";

const panel = document.getElementById("smr-weekly-body");
const message = document.getElementById("smr-message");

export const BARS = [["original", "Original"], ["added", "Added"], ["missing", "Missing"]];

const hours = (value) => (Number(value) || 0).toFixed(1);
const slug = (vendor) => vendor.toLowerCase().replace(/[^a-z0-9]+/g, "-");
const sum = (cells, key) => cells.reduce((acc, c) => acc + (Number(c[key]) || 0), 0);

function niceStep(max) {
  const raw = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * magnitude).find((step) => step >= raw);
}

const GROUP = 96, BAR = 24, GAP = 4, LEFT = 48, TOP = 12, PLOT = 200, BOTTOM = 44;

// One <g> per week; inside it three bars of stacked vendor rects, tallest
// value first so the stack order matches the legend.
function chartSvg({ weeks, vendors, cells }) {
  const weekCells = (week) => cells.filter((c) => c.week === week);
  const max = Math.max(1, ...weeks.flatMap((w) => BARS.map(([key]) => sum(weekCells(w), key))));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const y = (value) => TOP + PLOT - (value / top) * PLOT;
  const width = LEFT + weeks.length * GROUP;
  const height = TOP + PLOT + BOTTOM;
  const grid = [];
  for (let v = 0; v <= top; v += step) {
    grid.push(`<line class="smr-weekly-grid" x1="${LEFT}" x2="${width}" y1="${y(v)}" y2="${y(v)}"></line>`
      + `<text class="smr-weekly-axis" x="${LEFT - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`);
  }
  const groups = weeks.map((week, index) => {
    const mine = weekCells(week);
    const label = mine[0]?.week_label || "Undated";
    const x0 = LEFT + index * GROUP + (GROUP - (BAR * 3 + GAP * 2)) / 2;
    const bars = BARS.map(([key, name], b) => {
      const x = x0 + b * (BAR + GAP);
      let stack = 0;
      const rects = vendors.flatMap((vendor) => {
        const value = Number(mine.find((c) => c.vendor === vendor)?.[key]) || 0;
        if (!value) return [];
        const y1 = y(stack + value);
        const rect = `<rect class="smr-vendor--${slug(vendor)}" x="${x}" y="${y1.toFixed(1)}" width="${BAR}" height="${(y(stack) - y1).toFixed(1)}">`
          + `<title>${escapeHtml(`${label} · ${vendor} · ${hours(value)} h ${name.toLowerCase()}`)}</title></rect>`;
        stack += value;
        return [rect];
      });
      return rects.join("") + `<text class="smr-weekly-bar-label" x="${x + BAR / 2}" y="${TOP + PLOT + 14}" text-anchor="middle">${name[0]}</text>`;
    });
    return `<g data-week="${week === null ? "" : week}">${bars.join("")}`
      + `<text class="smr-weekly-week" x="${x0 + (BAR * 3 + GAP * 2) / 2}" y="${TOP + PLOT + 32}" text-anchor="middle">${escapeHtml(label)}</text></g>`;
  });
  return `<svg class="smr-weekly-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Original, added and missing hours per week by vendor">`
    + grid.join("") + groups.join("") + `</svg>`;
}

function legendHtml(vendors) {
  const swatches = vendors.map((v) => `<li><span class="smr-weekly-swatch smr-vendor--${slug(v)}"></span>${escapeHtml(v)}</li>`);
  return `<ul class="smr-weekly-legend">${swatches.join("")}</ul>`
    + `<p class="smr-hours-note">O = Original hours NetFacilities charged before the audit (by close week) · A = Added paper hours charged in the app (by work week) · M = Missing: hours the vendor invoiced that no order carries yet.</p>`;
}

function tableHtml({ weeks, cells }) {
  const tr = (row, tag = "td") => `<tr>${row.map((c) => `<${tag}>${escapeHtml(String(c))}</${tag}>`).join("")}</tr>`;
  const rows = weeks.map((week) => {
    const mine = cells.filter((c) => c.week === week);
    return [mine[0]?.week_label || "Undated", ...BARS.map(([key]) => hours(sum(mine, key))), hours(sum(mine, "invoiced"))];
  });
  const foot = ["Total", ...BARS.map(([key]) => hours(sum(cells, key))), hours(sum(cells, "invoiced"))];
  return `<table class="smr-hours-table smr-weekly-table"><thead>${tr(["Week", "Original", "Added", "Missing", "Invoiced"], "th")}</thead>`
    + `<tbody>${rows.map((r) => tr(r)).join("")}</tbody><tfoot>${tr(foot)}</tfoot></table>`;
}

export function weeklyHtml(data) {
  const weeks = data.weeks || [];
  const cells = data.cells || [];
  if (!cells.length) return `<p class="smr-empty">No hours yet. The chart fills from the SMR import, paper lines and vendor invoices.</p>`;
  return chartSvg({ weeks, vendors: data.vendors || [], cells }) + legendHtml(data.vendors || []) + tableHtml({ weeks, cells });
}

export async function loadWeeklyHours() {
  if (!panel) return;
  panel.innerHTML = `<p class="smr-empty">Loading…</p>`;
  try {
    panel.innerHTML = weeklyHtml(await apiSmrWeeklyHours());
  } catch (err) {
    panel.innerHTML = "";
    setMessage(message, friendlyError(err, "Could not load the weekly hours chart."), "error");
  }
}
