// View: the SMR27 audit page (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).
//
// Layer: views. One tile per SMR order with its before / after delta, four
// filters, the Owner-only workbook export, and a click-through to the normal
// Work Orders editor. Reads `GET /work-orders/smr`; owns no state beyond the
// last payload and the active filter.

import { apiExportSmrXlsx, apiListSmrTiles, friendlyError } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, formatMoney } from "../format.js";
import { getCurrentUser } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { focusWorkOrderNumber } from "./workOrders.js";
import { showPage } from "./nav.js";

const bar = document.getElementById("smr-bar");
const grid = document.getElementById("smr-tiles");
const message = document.getElementById("smr-message");
const exportBtn = document.getElementById("smr-export-btn");
const filterButtons = Array.from(document.querySelectorAll(".smr-btn[data-filter]"));

export const EMPTY_COPY = "NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS.";

let activeFilter = "all";
let lastPayload = null;

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

function matches(tile, filter) {
  if (filter === "all") return true;
  if (filter === "archived") return Boolean(tile.archived_at);
  return (filter === "edited") === Boolean(tile.edited);
}

function barHtml(payload) {
  const c = payload.counts || {};
  const d = payload.delta || {};
  const cells = [
    `${c.orders || 0} ORDERS`,
    `${c.edited || 0} EDITED`,
    `${c.untouched || 0} UNTOUCHED`,
    `${c.archived || 0} ARCHIVED`,
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
  return `<button type="button" class="smr-tile smr-tile--${state}" data-number="${escapeHtml(tile.number)}" data-id="${escapeHtml(tile.id)}">
    <span class="smr-tile-number">${escapeHtml(tile.number)}</span>
    <span class="smr-tile-where">${escapeHtml(`${where}${who}`.toUpperCase())}</span>
    <span class="smr-tile-delta">${escapeHtml(signedMoney(tile.delta?.total))}</span>
    <span class="smr-tile-meta">${escapeHtml(`${minutes} MIN · ${tile.after_line_count || 0} LINES · ${state.toUpperCase()}`)}</span>
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
  const tiles = payload.tiles || [];
  grid.innerHTML = tiles.length
    ? tiles.map(tileHtml).join("")
    : `<p class="smr-empty">${escapeHtml(EMPTY_COPY)}</p>`;
  applyFilter();
}

export async function loadSmr() {
  const user = getCurrentUser();
  if (exportBtn) exportBtn.hidden = !(user && roleAtLeast(user.role, "owner"));
  setMessage(message, "", "");
  try {
    render(await apiListSmrTiles());
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

if (grid) {
  grid.addEventListener("click", (event) => {
    const tile = event.target.closest(".smr-tile");
    if (!tile) return;
    // By id: the Work Orders list never shows an SMR order (spec D1), so a
    // number search would come back empty. The card page fetches the detail
    // directly, and the editor route accepts SMR orders.
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
