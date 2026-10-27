// View: the SMR27 audit page (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).
//
// Layer: views. One tile per SMR order with its before / after delta, four
// filters, the Owner-only workbook export, and a click-through to the normal
// Work Orders editor. Reads `GET /work-orders/smr`; owns no state beyond the
// last payload and the active filter.

import { apiExportSmrXlsx, apiListSmrTiles } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, formatMoney, friendlyError } from "../format.js";
import { getCurrentUser } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { focusWorkOrderNumber } from "./workOrders.js";
import { showPage } from "./nav.js";
import { setProfileOrigin } from "./profileOrigin.js";
import { applyFilterOptions, currentParams, installFilterControls } from "./smrFilters.js";

const bar = document.getElementById("smr-bar");
const grid = document.getElementById("smr-tiles");
const message = document.getElementById("smr-message");
const resultCount = document.getElementById("smr-result-count");
const exportBtn = document.getElementById("smr-export-btn");
const filterButtons = Array.from(document.querySelectorAll(".smr-btn[data-filter]"));

export const EMPTY_COPY = "NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS.";

// Untouched is the working view: the orders still to be re-charged.
let activeFilter = "untouched";
let lastPayload = null;
// Where the page stood when a tile opened a card; consumed by the next render.
let pendingScrollY = null;

// "+$58.40" / "-$3.00" / "$0.00": the sign is the whole point of a delta.
export function signedMoney(value) {
  const amount = Number(value) || 0;
  const text = formatMoney(Math.abs(amount));
  if (amount > 0) return `+${text}`;
  if (amount < 0) return `-${text}`;
  return text;
}

function stamp(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], {
    month: "2-digit", day: "2-digit", year: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function tileState(tile) {
  if (tile.archived_at) return "archived";
  return tile.edited ? "edited" : "untouched";
}

// Short = has a client target and is not yet matched; Matched = has one and is
// (spec 2026-10-23-smr-target-match). Orders without a Breakdown row are neither.
function matches(tile, filter) {
  if (filter === "all") return true;
  if (filter === "archived") return Boolean(tile.archived_at);
  if (filter === "short") return Boolean(tile.target) && !tile.target.matched;
  if (filter === "matched") return tile.target?.matched === true;
  // Paper check (spec 2026-10-27-smr-paper-check): Short keeps its meaning.
  if (filter === "checked") return Boolean(tile.paper_check);
  if (filter === "short_checked") return Boolean(tile.paper_check) && Boolean(tile.target) && !tile.target.matched;
  return (filter === "edited") === Boolean(tile.edited);
}

const hoursText = (value) => `${(Number(value) || 0).toFixed(1)} H`;

// "2.0 H · $67.16 TO GO" / "MATCHED" / "NO TARGET": what is left to reach the
// client's number, both sides, so the Admin sees which one still needs work.
export function targetLine(tile) {
  const t = tile.target;
  if (!t) return "NO TARGET";
  if (t.matched) return "MATCHED";
  return `${hoursText(t.remaining_hours)} · ${formatMoney(t.remaining_materials_total || 0)} TO GO`;
}

function barHtml(payload) {
  const c = payload.counts || {};
  const d = payload.delta || {};
  const r = payload.remaining || {};
  const cells = [
    `${c.orders || 0} ORDERS`,
    `${c.edited || 0} EDITED`,
    `${c.untouched || 0} UNTOUCHED`,
    `${c.archived || 0} ARCHIVED`,
    `${c.matched || 0} MATCHED`,
    `${c.short || 0} SHORT`,
    `${c.no_target || 0} NO TARGET`,
    `${c.paper_checked || 0} PAPER CHECKED`,
    `${c.short_checked || 0} CHECKED, STILL SHORT`,
    `REMAINING ${hoursText(r.hours)}`,
    `REMAINING ${formatMoney(r.materials_total || 0)}`,
    `Δ LABOR ${signedMoney(d.labor_total)}`,
    `Δ MATERIAL ${signedMoney(d.materials_total)}`,
    `Δ TOTAL ${signedMoney(d.total)}`,
    payload.imported_at ? `IMPORTED ${stamp(payload.imported_at)}` : "NOT IMPORTED",
  ];
  return cells.map((text) => `<div class="smr-bar-cell">${escapeHtml(text)}</div>`).join("");
}

function tileHtml(tile) {
  const state = tileState(tile);
  const where = [tile.building_number, tile.unit_number].filter(Boolean).join(" ") || tile.location || "";
  const who = tile.vendor_assignee ? ` · ${tile.vendor_assignee}` : "";
  const minutes = (tile.after?.real_minutes || 0) + (tile.after?.skilled_minutes || 0);
  const matched = tile.target?.matched ? " smr-tile--matched" : "";
  const checked = tile.paper_check ? " smr-tile--checked" : "";
  return `<button type="button" class="smr-tile smr-tile--${state}${matched}${checked}" data-number="${escapeHtml(tile.number)}" data-id="${escapeHtml(tile.id)}">
    <span class="smr-tile-number">${escapeHtml(tile.number)}</span>
    <span class="smr-tile-where">${escapeHtml(`${where}${who}`.toUpperCase())}</span>
    <span class="smr-tile-delta">${escapeHtml(signedMoney(tile.delta?.total))}</span>
    <span class="smr-tile-target">${escapeHtml(targetLine(tile))}</span>
    <span class="smr-tile-meta">${escapeHtml(`${minutes} MIN · ${tile.after_line_count || 0} LINES · ${state.toUpperCase()}`)}</span>
    ${tile.paper_check ? `<span class="smr-tile-paper">PAPER ✓</span>` : ""}
  </button>`;
}

function applyFilter() {
  filterButtons.forEach((btn) => btn.classList.toggle("smr-btn--on", btn.dataset.filter === activeFilter));
  const byNumber = new Map((lastPayload?.tiles || []).map((tile) => [tile.number, tile]));
  grid.querySelectorAll(".smr-tile").forEach((el) => {
    const tile = byNumber.get(el.dataset.number);
    el.hidden = !(tile && matches(tile, activeFilter));
  });
}

function render(payload) {
  lastPayload = payload;
  bar.innerHTML = barHtml(payload);
  applyFilterOptions(payload.filter_options);
  if (resultCount) {
    const matched = payload.matched ?? (payload.tiles || []).length;
    resultCount.textContent = `${matched} OF ${payload.counts?.orders || 0} ORDERS`;
  }
  const tiles = payload.tiles || [];
  grid.innerHTML = tiles.length
    ? tiles.map(tileHtml).join("")
    : `<p class="smr-empty">${escapeHtml(EMPTY_COPY)}</p>`;
  applyFilter();
  if (pendingScrollY !== null) {
    const y = pendingScrollY;
    pendingScrollY = null;
    window.requestAnimationFrame(() => window.scrollTo(0, y));
  }
}

// The card page's way back (button or browser Back). The filter controls and
// state chips are page DOM / module state, so they are still set; only the
// scroll needs carrying across the refetch.
export function returnToSmr(scrollY) {
  pendingScrollY = typeof scrollY === "number" ? scrollY : null;
  showPage("smr");
}

export async function loadSmr() {
  const user = getCurrentUser();
  if (exportBtn) exportBtn.hidden = !(user && roleAtLeast(user.role, "owner"));
  setMessage(message, "", "");
  try {
    render(await apiListSmrTiles(currentParams()));
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not load SMR orders."), "error");
  }
}

filterButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeFilter = btn.dataset.filter;
    applyFilter();
  });
});

// Search, dropdowns, Clear filters and the sort toggle all refetch with the
// current controls; the state buttons above (Untouched, Short, Paper checked
// and the rest) stay local.
installFilterControls(() => { void loadSmr(); });

if (grid) {
  grid.addEventListener("click", (event) => {
    const tile = event.target.closest(".smr-tile");
    if (!tile) return;
    // By id: the Work Orders list never shows an SMR order (spec D1), so a
    // number search would come back empty. The card page fetches the detail
    // directly, and the editor route accepts SMR orders.
    setProfileOrigin({ page: "smr", scrollY: window.scrollY });
    focusWorkOrderNumber(tile.dataset.number, { id: tile.dataset.id });
    showPage("work-orders");
  });
}

if (exportBtn) {
  exportBtn.addEventListener("click", async () => {
    exportBtn.disabled = true;
    setMessage(message, "PREPARING WORKBOOK…", "");
    try {
      const { blob, filename } = await apiExportSmrXlsx();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setMessage(message, `DOWNLOADED ${filename}`, "success");
    } catch (err) {
      setMessage(message, friendlyError(err, "Could not export the SMR workbook."), "error");
    } finally {
      exportBtn.disabled = false;
    }
  });
}
