// View helper: the SMR page's weekly hours chart (spec
// 2026-11-06-smr-weekly-hours-chart, bars redefined 2026-11-06). One bar per
// vendor (Green Choice, XXL, BT) per Mon-Sun week: the hours the vendor
// invoiced, colour-coded into Original (the Breakdown's NetFacilities charge),
// Found (charged paper hours) and Missing (the rest). A trailing Undated
// column holds the paper hours with no date. Dependency-free SVG; the table
// under it repeats every number. CSP: colours are classes.
//
// Layer: views (leaf under smr.js). Admin+; smr.js shows the panel, this
// module fills it.

import { apiSmrWeeklyHours } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";

const panel = document.getElementById("smr-weekly-body");
const message = document.getElementById("smr-message");

export const SEGMENTS = [["original", "Original charge"], ["found", "Found hours"], ["undated", "Undated hours"], ["missing", "Missing hours"]];
const SHORT = { "Green Choice": "GC", "XXL Construction": "XXL", "BT Restoration": "BT" };

const hours = (value) => (Number(value) || 0).toFixed(1);
const sum = (cells, key) => cells.reduce((acc, c) => acc + (Number(c[key]) || 0), 0);

function niceStep(max) {
  const raw = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * magnitude).find((step) => step >= raw);
}

const GROUP = 96, BAR = 24, GAP = 4, LEFT = 48, TOP = 12, PLOT = 200, BOTTOM = 44;

// One <g> per week; inside it one bar per vendor, the segments stacked in
// SEGMENTS order so the stack reads like the legend.
function chartSvg({ weeks, vendors, cells }) {
  const weekCells = (week) => cells.filter((c) => c.week === week);
  const barTotal = (c) => SEGMENTS.reduce((acc, [key]) => acc + (Number(c?.[key]) || 0), 0);
  const max = Math.max(1, ...cells.map(barTotal));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const y = (value) => TOP + PLOT - (value / top) * PLOT;
  const width = LEFT + weeks.length * GROUP;
  const height = TOP + PLOT + BOTTOM;
  const span = BAR * vendors.length + GAP * (vendors.length - 1);
  const grid = [];
  for (let v = 0; v <= top; v += step) {
    grid.push(`<line class="smr-weekly-grid" x1="${LEFT}" x2="${width}" y1="${y(v)}" y2="${y(v)}"></line>`
      + `<text class="smr-weekly-axis" x="${LEFT - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`);
  }
  const groups = weeks.map((week, index) => {
    const mine = weekCells(week);
    const label = mine[0]?.week_label || "Undated";
    const x0 = LEFT + index * GROUP + (GROUP - span) / 2;
    const bars = vendors.map((vendor, b) => {
      const x = x0 + b * (BAR + GAP);
      const c = mine.find((cell) => cell.vendor === vendor);
      let stack = 0;
      const rects = SEGMENTS.flatMap(([key, name]) => {
        const value = Number(c?.[key]) || 0;
        if (!value) return [];
        const y1 = y(stack + value);
        const rect = `<rect class="smr-seg--${key}" x="${x}" y="${y1.toFixed(1)}" width="${BAR}" height="${(y(stack) - y1).toFixed(1)}">`
          + `<title>${escapeHtml(`${label} · ${vendor} · ${hours(value)} h ${name.toLowerCase()} (invoiced ${hours(c?.invoiced)} h)`)}</title></rect>`;
        stack += value;
        return [rect];
      });
      return rects.join("") + `<text class="smr-weekly-bar-label" x="${x + BAR / 2}" y="${TOP + PLOT + 14}" text-anchor="middle">${SHORT[vendor] || escapeHtml(vendor)}</text>`;
    });
    return `<g data-week="${week === null ? "" : week}">${bars.join("")}`
      + `<text class="smr-weekly-week" x="${x0 + span / 2}" y="${TOP + PLOT + 32}" text-anchor="middle">${escapeHtml(label)}</text></g>`;
  });
  return `<svg class="smr-weekly-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Invoiced hours per vendor per week, split into original charge, found, undated and missing">`
    + grid.join("") + groups.join("") + `</svg>`;
}

function legendHtml(vendors) {
  const swatches = SEGMENTS.map(([key, name]) => `<li><span class="smr-weekly-swatch smr-seg--${key}"></span>${escapeHtml(name)}</li>`);
  const names = vendors.map((v) => `${SHORT[v] || v} = ${v}`).join(", ");
  return `<ul class="smr-weekly-legend">${swatches.join("")}</ul>`
    + `<p class="smr-hours-note">${escapeHtml(`One bar per vendor (${names}) per Mon–Sun week: the hours the vendor invoiced, split into the original NetFacilities charge, the hours the paper review has found and dated, and what is still missing. The Undated column is paper hours with no date yet, with the original charge of their orders.`)}</p>`;
}

function tableHtml({ weeks, vendors, cells }) {
  const tr = (row, tag = "td") => `<tr>${row.map((c) => `<${tag}>${escapeHtml(String(c))}</${tag}>`).join("")}</tr>`;
  const keys = ["invoiced", ...SEGMENTS.map(([key]) => key)];
  const rows = weeks.flatMap((week) => vendors.map((vendor) => {
    const c = cells.find((cell) => cell.week === week && cell.vendor === vendor);
    return c ? [c.week_label || "Undated", SHORT[vendor] || vendor, ...keys.map((key) => hours(c[key]))] : null;
  }).filter(Boolean));
  const foot = ["Total", "", ...keys.map((key) => hours(sum(cells, key)))];
  return `<table class="smr-hours-table smr-weekly-table"><thead>${tr(["Week", "Vendor", "Invoiced", ...SEGMENTS.map(([, name]) => name)], "th")}</thead>`
    + `<tbody>${rows.map((r) => tr(r)).join("")}</tbody><tfoot>${tr(foot)}</tfoot></table>`;
}

export function weeklyHtml(data) {
  const weeks = data.weeks || [];
  const cells = data.cells || [];
  const vendors = data.vendors || [];
  if (!cells.length) return `<p class="smr-empty">No hours yet. The chart fills from the Breakdown targets, paper lines and vendor invoices.</p>`;
  return chartSvg({ weeks, vendors, cells }) + legendHtml(vendors) + tableHtml({ weeks, vendors, cells });
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
