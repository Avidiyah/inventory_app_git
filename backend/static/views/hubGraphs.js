// The User Hub Graphs tab (TechFM OA+): every chart is a small tile, and
// tapping one opens it in a pop-up over a page that cannot scroll behind it.
//
// The pies are status distributions summed from the payload's `cells` -- one
// per community set x service type x priority x status, see
// `services.hub.GraphCell`. The front switch groups the pies by community,
// service type or priority; inside the pop-up a pie can be broken down by
// whichever of the three is still unused. Any combination ends at a red
// button that opens Work Orders with exactly those filters.
//
// Exact values are always repeated in the legend; the SVG is an at-a-glance
// aid, never the only way to understand a number.

import { escapeHtml } from "../format.js";
import { tipHtml } from "../tooltip.js";
import { trendSheet, trendTilesHtml } from "./hubGraphTrends.js";

const DIMS = [
  { key: "community", label: "Community" },
  { key: "service_type", label: "Service type" },
  { key: "priority", label: "Priority" },
];

// What the viewer has open. Module state, not DOM state: the tab re-mounts on
// every background refresh and has to come back exactly as it was.
//   sheet: null | { trend: "days" | "ontime" } | { path: [step, ...] }
//   step:  { dim, value, label, status, scroll } -- one filter per drill
//          level, each remembering its own status pick and scroll position.
const freshUi = () => ({ frontDim: "community", breakDim: null, sheet: null });
let ui = freshUi();
let live = null; // { container, payload, onWeekChange, onDistributionClick }
let overlay = null;
let openListeners = null;
let openerSelector = null;
// The pies currently drawn, so a tile's click carries an index, not raw text.
let frontGroups = [];
let sheetGroups = [];

const plural = (count) => `${count} work order${count === 1 ? "" : "s"}`;
const percent = (count, total) => (total ? `${((count / total) * 100).toFixed(1)}%` : "0.0%");
const newStep = (group) => ({ dim: group.dim, value: group.value, label: group.label, status: null, scroll: 0 });
const matches = (cell, step) => (step.dim === "community" ? cell.communities.includes(step.value) : cell[step.dim] === step.value);

// Status counts for the work orders matching every step of `path`.
function tally(cells, path) {
  const counts = {};
  let total = 0;
  for (const cell of cells) {
    if (!path.every((step) => matches(cell, step))) continue;
    counts[cell.status] = (counts[cell.status] || 0) + cell.count;
    total += cell.count;
  }
  return { counts, total };
}

// One pie per value of `dim` among the work orders matching `path`.
// Communities keep the payload's fixed order and, on the front screen, their
// place even at zero; service types and priorities run largest first. A blank
// priority (null) gets no pie, so priority pies can sum to less than their parent.
function groups(payload, path, dim) {
  const pie = (value, label) => ({ dim, value, label, ...tally(payload.cells, [...path, { dim, value }]) });
  if (dim === "community") {
    const rows = payload.communities.map((row) => pie(row.key, row.label));
    return path.length ? rows.filter((row) => row.total) : rows;
  }
  const values = new Set(payload.cells
    .filter((cell) => cell[dim] !== null && path.every((step) => matches(cell, step)))
    .map((cell) => cell[dim]));
  return [...values].map((value) => pie(value, value)).sort((a, b) => b.total - a.total || a.label.localeCompare(b.label));
}

function polar(angle) {
  const radians = ((angle - 90) * Math.PI) / 180;
  return [50 + 40 * Math.cos(radians), 50 + 40 * Math.sin(radians)];
}

// `pickable` slices carry `data-status` so a pointer click picks the same
// status its legend row does. The <path> is deliberately pointer-only -- no
// `role`, no tab stop -- because a 40px-radius stroke is a poor keyboard
// target; the legend row is the real, focusable control for the same status.
function donutSvg(distribution, statuses, { pickable = false, selected = null } = {}) {
  const label = escapeHtml(distribution.label);
  if (!distribution.total) {
    return `<svg class="hub-donut" viewBox="0 0 100 100" role="img" aria-label="${label}: no circulating work orders"><circle class="hub-donut-empty" cx="50" cy="50" r="40"/></svg>`;
  }
  let angle = 0;
  const arcs = statuses.map((status) => {
    const count = distribution.counts[status.key] || 0;
    if (!count) return "";
    const next = angle + (count / distribution.total) * 360;
    // A lone status would start and end on the same point, which SVG draws
    // as nothing at all; stop a hair short so the ring still shows.
    const [x1, y1] = polar(Math.min(next, angle + 359.99));
    const [x2, y2] = polar(angle);
    const dim = selected && selected !== status.key ? " hub-graph-slice-dim" : "";
    const path = `<path d="M ${x1} ${y1} A 40 40 0 ${next - angle > 180 ? 1 : 0} 0 ${x2} ${y2}" class="hub-graph-slice hub-graph-slice-${status.key}${dim}"${pickable ? ` data-status="${status.key}"` : ""}/>`;
    angle = next;
    return path;
  }).join("");
  return `<svg class="hub-donut" viewBox="0 0 100 100" role="img" aria-label="${label} status distribution, ${distribution.total} circulating work orders">${arcs}</svg>`;
}

// A whole <button>: the tile holds no controls of its own, so nothing nests.
function tileHtml(distribution, statuses, attribute) {
  const label = escapeHtml(distribution.label);
  return `<button type="button" class="hub-graph-tile" ${attribute}${distribution.total ? "" : " disabled"} aria-label="Open ${label} chart, ${plural(distribution.total)}"><span class="hub-graph-tile-donut">${donutSvg(distribution, statuses)}<span class="hub-graph-tile-total">${distribution.total}</span></span><span class="hub-graph-tile-label">${label}</span></button>`;
}

function segHtml(attribute, options, active, ariaLabel) {
  const buttons = options.map((option) => `<button type="button" class="hub-graph-seg-btn" ${attribute}="${option.key}" aria-pressed="${option.key === active}">${option.label}</button>`).join("");
  return `<div class="hub-graph-seg" role="group" aria-label="${ariaLabel}">${buttons}</div>`;
}

// The pie, its legend and the red button: the same block at every drill
// level. A status row picks (or un-picks) that status; only the red button
// leaves for Work Orders, and it always says which filters it will apply.
function pieBlock(distribution, statuses, selected, names) {
  if (!distribution.total) {
    return `<section class="hub-graph-panel"><div class="hub-graph-empty">No circulating work orders</div></section>`;
  }
  const rows = statuses.filter((status) => distribution.counts[status.key]).map((status) => {
    const count = distribution.counts[status.key];
    return `<li><button type="button" class="hub-graph-legend-row" data-status="${status.key}" aria-pressed="${selected === status.key}"><span class="hub-graph-key"><i class="hub-graph-swatch hub-graph-swatch-${status.key}"></i>${escapeHtml(status.label)}</span><span class="hub-graph-legend-num">${count} · ${percent(count, distribution.total)}</span></button></li>`;
  }).join("");
  const picked = statuses.find((status) => status.key === selected);
  const shown = picked ? distribution.counts[selected] : distribution.total;
  const filters = [...names, picked ? picked.label : "every status"].map(escapeHtml).join(" · ");
  return `<section class="hub-graph-panel"><p class="hint">Tap a status to pick it. The red button opens that list.</p><div class="hub-graph-pie"><div class="hub-donut-wrap">${donutSvg(distribution, statuses, { pickable: true, selected })}<span class="hub-donut-total">${shown}<small>${picked ? escapeHtml(picked.label) : "circulating"}</small></span></div><ul class="hub-graph-legend">${rows}</ul></div><button type="button" class="hub-graph-go" data-graph-go>View ${plural(shown)}<small>${filters}</small></button></section>`;
}

// Whatever has not been picked yet is what this pie can still be broken down by.
function breakdownHtml(payload, path, names) {
  const options = DIMS.filter((dim) => !path.some((step) => step.dim === dim.key));
  if (!options.length) return "";
  const dim = options.find((option) => option.key === ui.breakDim) || options[0];
  const scope = escapeHtml(names.join(" · "));
  sheetGroups = groups(payload, path, dim.key);
  const heading = options.length > 1 ? `Break ${scope} down by` : `${scope} by ${dim.label.toLowerCase()}`;
  const tiles = sheetGroups.length
    ? `<div class="hub-graph-tiles">${sheetGroups.map((group, index) => tileHtml(group, payload.statuses, `data-graph-drill="${index}"`)).join("")}</div>`
    : `<div class="hub-graph-empty">No imported priorities in ${scope}</div>`;
  return `<section class="hub-graph-section"><h3>${heading}</h3><p class="hint">These pies count ${scope} work orders only. Tap one to open it.</p>${options.length > 1 ? segHtml("data-graph-break", options, dim.key, `Break ${scope} down by`) : ""}${tiles}</section>`;
}

function pageHtml(payload) {
  const updated = new Date(payload.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  frontGroups = groups(payload, [], ui.frontDim);
  const key = `<ul class="hub-graph-status-key">${payload.statuses.map((status) => `<li><i class="hub-graph-swatch hub-graph-swatch-${status.key}"></i>${escapeHtml(status.label)}</li>`).join("")}</ul>`;
  const tiles = frontGroups.length
    ? `<div class="hub-graph-tiles">${frontGroups.map((group, index) => tileHtml(group, payload.statuses, `data-graph-pie="${index}"`)).join("")}</div>`
    : `<div class="hub-graph-empty">${ui.frontDim === "priority" ? "No imported priorities" : "No circulating work orders"}</div>`;
  const note = ui.frontDim === "community"
    ? `<p class="hint">A work order that names more than one community is counted in each, so these totals add up to more than the real total.</p>`
    : "";
  return `<section class="hub-graphs"><header class="hub-graphs-header"><h2>Graphs${tipHtml("hub.graphs")}</h2><p class="hint">Live circulating work orders. Updated ${escapeHtml(updated)}.</p></header><section class="hub-graph-section"><h3>Work orders by</h3><p class="hint">Pick how to group the pies, then tap one to open it.</p>${segHtml("data-graph-front", DIMS, ui.frontDim, "Group the pies by")}${key}${tiles}${note}</section><section class="hub-graph-section"><h3>Trends</h3><p class="hint">Tap a tile to open the full chart.</p><div class="hub-graph-tiles hub-trend-tiles">${trendTilesHtml(payload.duration.buckets)}</div></section></section>`;
}

// A re-draw replaces the button that was just pressed. Hand focus to its
// replacement so a keyboard user keeps their place.
const FOCUS_ATTRIBUTES = ["data-status", "data-graph-break", "data-graph-weeks", "data-graph-front"];
function redraw(root, draw) {
  const active = document.activeElement;
  const attribute = active && root.contains(active) && FOCUS_ATTRIBUTES.find((name) => active.hasAttribute(name));
  const selector = attribute && `button[${attribute}="${active.getAttribute(attribute)}"]`;
  draw();
  if (selector) root.querySelector(selector)?.focus({ preventScroll: true });
}

function renderPage() {
  redraw(live.container, () => { live.container.innerHTML = pageHtml(live.payload); });
}

// Head and body are filled separately and the body element is never replaced,
// so picking a status re-draws the pie without moving the pop-up's scroll.
function renderSheet() {
  const { payload } = live;
  let title, sub, body, up = "";
  if (ui.sheet.trend) {
    ({ title, sub, body } = trendSheet(ui.sheet.trend, payload));
  } else {
    const path = ui.sheet.path, step = path.at(-1), names = path.map((entry) => entry.label);
    const distribution = { label: step.label, ...tally(payload.cells, path) };
    // A refresh can empty the picked status; the pick then quietly lapses.
    if (!distribution.counts[step.status]) step.status = null;
    title = step.label;
    sub = path.length > 1 ? `${plural(distribution.total)} in ${names.slice(0, -1).join(" · ")}` : `${plural(distribution.total)} in circulation`;
    if (path.length > 1) up = `<button type="button" class="hub-graph-up" data-graph-up>← Back to ${escapeHtml(names.at(-2))}</button>`;
    body = pieBlock(distribution, payload.statuses, step.status, names) + (distribution.total ? breakdownHtml(payload, path, names) : "");
  }
  redraw(overlay, () => {
    overlay.querySelector(".hub-graph-sheet-head").innerHTML = `<div>${up}<h2 id="hub-graph-sheet-title">${escapeHtml(title)}</h2><p class="hint">${escapeHtml(sub)}</p></div><button type="button" class="hub-graph-close" data-graph-close aria-label="Close ${escapeHtml(title)} chart">✕</button>`;
    overlay.querySelector(".hub-graph-sheet-body").innerHTML = body;
  });
}

function onSheetKey(event) {
  if (event.key === "Escape") { closeSheet(); return; }
  if (event.key !== "Tab") return;
  const stops = [...overlay.querySelectorAll("button:not([disabled]), summary")];
  const at = stops.indexOf(document.activeElement);
  if (event.shiftKey ? at <= 0 : at === -1 || at === stops.length - 1) {
    event.preventDefault();
    stops[event.shiftKey ? stops.length - 1 : 0].focus();
  }
}

function openSheet(sheet, selector) {
  if (!overlay?.isConnected) {
    overlay = document.createElement("div");
    overlay.className = "modal-overlay hub-graph-sheet";
    overlay.hidden = true; // shown below, once the scrollbar has been measured
    overlay.innerHTML = `<div class="hub-graph-sheet-box" role="dialog" aria-modal="true" aria-labelledby="hub-graph-sheet-title"><header class="hub-graph-sheet-head"></header><div class="hub-graph-sheet-body"></div></div>`;
    overlay.addEventListener("click", onSheetClick);
    // On the page, not in the tab panel: the panel's contents are replaced on
    // every refresh, and a frosted ancestor would trap a fixed overlay inside
    // it. styles.css freezes the page behind while this is showing.
    (document.getElementById("user-hub-page") ?? document.body).appendChild(overlay);
  }
  ui.sheet = sheet;
  openerSelector = selector;
  renderSheet();
  // Measured before the page is frozen: the room a desktop scrollbar takes
  // up, which styles.css pads back in so the page does not shift sideways.
  document.documentElement.style.setProperty("--hub-graph-gutter", `${window.innerWidth - document.documentElement.clientWidth}px`);
  overlay.hidden = false;
  overlay.querySelector(".hub-graph-sheet-body").scrollTop = 0;
  overlay.querySelector("[data-graph-close]").focus({ preventScroll: true });
  openListeners = new AbortController();
  document.addEventListener("keydown", onSheetKey, { signal: openListeners.signal });
  // Browser Back swaps the page under the pop-up.
  window.addEventListener("popstate", closeSheet, { signal: openListeners.signal });
}

function closeSheet() {
  if (!ui.sheet) return;
  ui.sheet = null;
  openListeners.abort();
  overlay.hidden = true;
  // `preventScroll`: the page must be exactly where it was left.
  live?.container.querySelector(openerSelector)?.focus({ preventScroll: true });
}

function onSheetClick(event) {
  const hit = (selector) => event.target.closest(selector);
  const body = overlay.querySelector(".hub-graph-sheet-body");
  let el;
  if (hit("[data-graph-close]")) { closeSheet(); return; }
  if ((el = hit("[data-graph-weeks]"))) { live.onWeekChange?.(Number(el.dataset.graphWeeks)); return; }
  const path = ui.sheet?.path;
  if (!path) return;
  const step = path.at(-1);
  if (hit("[data-graph-up]") || (el = hit("[data-graph-drill]"))) {
    if (el) {
      step.scroll = body.scrollTop;
      path.push(newStep(sheetGroups[Number(el.dataset.graphDrill)]));
    } else path.pop();
    renderSheet();
    body.scrollTop = path.at(-1).scroll; // a new level starts at the top; Back returns to where it was left
    overlay.querySelector(".hub-graph-up, [data-graph-close]").focus({ preventScroll: true });
    return;
  }
  if ((el = hit("[data-graph-break]"))) { ui.breakDim = el.dataset.graphBreak; renderSheet(); return; }
  if (hit("[data-graph-go]")) {
    // The raw, case-preserved values the Work Orders <select> options are
    // built from; the community also sends its label, for the page's chip.
    const filters = { community: null, communityLabel: null, serviceType: null, priority: null, status: step.status };
    for (const entry of path) {
      if (entry.dim === "community") Object.assign(filters, { community: entry.value, communityLabel: entry.label });
      else filters[entry.dim === "priority" ? "priority" : "serviceType"] = entry.value;
    }
    const { onDistributionClick } = live;
    closeSheet();
    onDistributionClick?.(filters);
    return;
  }
  if ((el = hit("[data-status]"))) {
    step.status = step.status === el.dataset.status ? null : el.dataset.status;
    renderSheet();
  }
}

function onPageClick(event) {
  const hit = (selector) => event.target.closest(selector);
  let el;
  if ((el = hit("[data-graph-front]"))) { ui.frontDim = el.dataset.graphFront; renderPage(); return; }
  if ((el = hit("[data-graph-trend]"))) { openSheet({ trend: el.dataset.graphTrend }, `[data-graph-trend="${el.dataset.graphTrend}"]`); return; }
  if ((el = hit("[data-graph-pie]"))) openSheet({ path: [newStep(frontGroups[Number(el.dataset.graphPie)])] }, `[data-graph-pie="${el.dataset.graphPie}"]`);
}

export function mountHubGraphs(container, payload, { onWeekChange, onDistributionClick } = {}) {
  live = { container, payload, onWeekChange, onDistributionClick };
  renderPage();
  // Bound once per container element: this re-runs against the same container
  // on every refresh and range change, and replacing its children does not
  // remove a listener bound to the container itself.
  if (!container.dataset.graphClickBound) {
    container.dataset.graphClickBound = "true";
    container.addEventListener("click", onPageClick);
  }
  // A refresh arriving under an open pop-up re-draws it in place.
  if (ui.sheet) renderSheet();
}

// The viewer changed: forget what the last one had open.
export function destroyHubGraphs() {
  closeSheet();
  overlay?.remove();
  overlay = null;
  ui = freshUi();
  live = null;
}
