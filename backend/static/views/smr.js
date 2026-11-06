// View: the SMR27 audit page (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).
//
// Layer: views. One tile per SMR order with its before / after delta and
// paper stage, three chip rows (stage / pile / flags, spec
// 2026-11-06-smr-paper-stage), the Owner-only workbook export, and a
// click-through to the normal Work Orders editor. Reads `GET /work-orders/smr`;
// owns no state beyond the last payload and the active chips.

import { apiExportSmrXlsx, apiListSmrTiles } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, formatMoney, friendlyError } from "../format.js";
import { getCurrentUser } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { focusWorkOrderNumber } from "./workOrders.js";
import { showPage } from "./nav.js";
import { setProfileOrigin } from "./profileOrigin.js";
import { applyFilterOptions, currentParams, installFilterControls, saveFilters, savedChips } from "./smrFilters.js";
import { loadSmrHours } from "./smrHours.js";

const bar = document.getElementById("smr-bar");
const grid = document.getElementById("smr-tiles");
const message = document.getElementById("smr-message");
const resultCount = document.getElementById("smr-result-count");
const exportBtn = document.getElementById("smr-export-btn");
const hoursBtn = document.getElementById("smr-hours-btn");
const hoursCsvBtn = document.getElementById("smr-hours-csv-btn");
const hoursPanel = document.getElementById("smr-hours");
const chipButtons = Array.from(document.querySelectorAll(".smr-btn[data-row][data-filter]"));

export const EMPTY_COPY = "No SMR orders yet. Owner: import from Integrations.";

// Not reviewed is the working view: the next pile to work. A reload of this
// tab keeps the chips the user left on (smrFilters.js); a saved value its row
// does not offer (an older chip name) falls back to the row's default.
const DEFAULT_CHIPS = { stage: "not_reviewed", pile: "all", flags: "all" };
const rowHas = (row, value) => chipButtons.some((btn) => btn.dataset.row === row && btn.dataset.filter === value);
const chips = { ...DEFAULT_CHIPS };
for (const [row, value] of Object.entries(savedChips())) {
  if (rowHas(row, value)) chips[row] = value;
}
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

// Short = has a client target and is not yet matched; Matched = has one and is
// (spec 2026-10-23-smr-target-match). Block pending = lines whose block still
// needs work (none yet, not pasted, or stale since the paste).
function flagMatches(tile, flag) {
  if (flag === "all") return true;
  if (flag === "archived") return Boolean(tile.archived_at);
  if (flag === "short") return Boolean(tile.target) && !tile.target.matched;
  if (flag === "matched") return tile.target?.matched === true;
  if (flag === "block_pending") return Boolean(tile.lines) && blockPending(tile.lines);
  return true;
}

// The three rows AND together: stage is the tile's stage; pile is a week label
// the tile's lines fall in (or Belfor only); flags as above.
function matches(tile, { stage, pile, flags }) {
  if (stage !== "all" && tile.stage !== stage) return false;
  if (pile === "belfor" ? !tile.belfor_only : pile !== "all" && !tileWeeks(tile).includes(pile)) return false;
  return flagMatches(tile, flags);
}

const tileWeeks = (tile) => (tile.weeks?.length ? tile.weeks : ["Undated"]);

const blockPending = (lines) => !lines.block_version || !lines.block_pasted_at || lines.block_stale;

function blockText(lines) {
  if (!lines.block_version) return "no block";
  const v = `v${lines.block_version}`;
  if (lines.block_stale) return `${v} stale`;
  return lines.block_pasted_at ? `${v} pasted` : `${v} not pasted`;
}

const hoursText = (value) => `${(Number(value) || 0).toFixed(1)} h`;

// "2.0 h · $67.16 to go" / "Matched" / "No target": what is left to reach the
// client's number, both sides, so the Admin sees which one still needs work.
export function targetLine(tile) {
  const t = tile.target;
  // With lines the third line is the correction itself: "+82.0 h · v2 pasted"
  // (change against the target when there is one, else the charged hours).
  if (tile.lines) {
    const change = Number(tile.lines.change_hours);
    const figure = t && Number.isFinite(change)
      ? `${change > 0 ? "+" : ""}${change.toFixed(1)} h`
      : `${hoursText(tile.lines.charged_hours)} charged`;
    return `${figure} · ${blockText(tile.lines)}`;
  }
  if (!t) return "No target";
  if (t.matched) return "Matched";
  return `${hoursText(t.remaining_hours)} · ${formatMoney(t.remaining_materials_total || 0)} to go`;
}

function barHtml(payload) {
  const c = payload.counts || {};
  const d = payload.delta || {};
  const r = payload.remaining || {};
  // Stage counts lead (spec 2026-11-06); Short / Matched live on as chips.
  const cells = [
    `${c.not_reviewed || 0} not reviewed`,
    `${c.undated || 0} undated`,
    `${c.dated || 0} dated`,
    `${c.ready || 0} ready`,
    `${c.belfor_only || 0} Belfor only`,
    `${c.orders || 0} orders`,
    `${c.archived || 0} archived`,
    `Charged ${hoursText(c.charged_hours)}`,
    `Excluded ${hoursText(c.excluded_hours)}`,
    `${c.blocks_not_pasted || 0} blocks not pasted`,
    `Remaining ${hoursText(r.hours)}`,
    `Remaining ${formatMoney(r.materials_total || 0)}`,
    `Δ labor ${signedMoney(d.labor_total)}`,
    `Δ material ${signedMoney(d.materials_total)}`,
    `Δ total ${signedMoney(d.total)}`,
    payload.imported_at ? `Imported ${stamp(payload.imported_at)}` : "Not imported",
  ];
  return cells.map((text) => `<div class="smr-bar-cell">${escapeHtml(text)}</div>`).join("");
}

// The stage's words always ride with its color (spec 2026-11-06).
const STAGE_LABEL = {
  not_reviewed: "Not reviewed", undated: "Reviewed · undated", dated: "Reviewed · dated", ready: "Ready for invoice",
};

// Week bubbles across the top: the invoice weeks the paper lines fall in;
// "Undated" carries the NetFacilities close week, the undated pile's own sort key.
function weeksHtml(tile) {
  return tileWeeks(tile).map((w) => {
    if (w !== "Undated") return `<span class="smr-week">${escapeHtml(w)}</span>`;
    const closed = tile.closed_week ? ` · closed ${tile.closed_week}` : "";
    return `<span class="smr-week smr-week--undated">${escapeHtml(`Undated${closed}`)}</span>`;
  }).join("");
}

function tileHtml(tile) {
  const stage = STAGE_LABEL[tile.stage] ? tile.stage : "not_reviewed";
  const where = [tile.building_number, tile.unit_number].filter(Boolean).join(" ") || tile.location || "";
  const who = tile.vendor_assignee ? ` · ${tile.vendor_assignee}` : "";
  const minutes = (tile.after?.real_minutes || 0) + (tile.after?.skilled_minutes || 0);
  const matched = tile.target?.matched ? " smr-tile--matched" : "";
  const archived = tile.archived_at ? " smr-tile--archived" : "";
  return `<button type="button" class="smr-tile smr-tile--${stage}${matched}${archived}" data-number="${escapeHtml(tile.number)}" data-id="${escapeHtml(tile.id)}">
    <span class="smr-tile-top">
      <span class="smr-tile-weeks">${weeksHtml(tile)}</span>
      <span class="smr-tile-stage">${STAGE_LABEL[stage]}</span>
    </span>
    <span class="smr-tile-number">${escapeHtml(tile.number)}</span>
    <span class="smr-tile-where">${escapeHtml(`${where}${who}`)}</span>
    <span class="smr-tile-delta">${escapeHtml(signedMoney(tile.delta?.total))}</span>
    <span class="smr-tile-target">${escapeHtml(targetLine(tile))}</span>
    <span class="smr-tile-bottom">
      <span class="smr-tile-meta">${escapeHtml(`${minutes} min · ${tile.after_line_count || 0} lines`)}</span>
      ${tile.belfor_only ? `<span class="smr-tile-belfor">Belfor</span>` : ""}
    </span>
  </button>`;
}

function applyFilter() {
  chipButtons.forEach((btn) => btn.classList.toggle("smr-btn--on", chips[btn.dataset.row] === btn.dataset.filter));
  const byNumber = new Map((lastPayload?.tiles || []).map((tile) => [tile.number, tile]));
  grid.querySelectorAll(".smr-tile").forEach((el) => {
    const tile = byNumber.get(el.dataset.number);
    el.hidden = !(tile && matches(tile, chips));
  });
}

function render(payload) {
  lastPayload = payload;
  bar.innerHTML = barHtml(payload);
  applyFilterOptions(payload.filter_options);
  if (resultCount) {
    const matched = payload.matched ?? (payload.tiles || []).length;
    resultCount.textContent = `${matched} of ${payload.counts?.orders || 0} orders`;
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

// Hours is a toggle on the same page: the tiles hide, the table shows, and
// the state chips stay where they were for the way back.
let hoursOpen = false;

function showHours(open) {
  hoursOpen = open;
  if (grid) grid.hidden = open;
  if (hoursPanel) hoursPanel.hidden = !open;
  if (hoursBtn) hoursBtn.setAttribute("aria-pressed", String(open));
  if (hoursCsvBtn) hoursCsvBtn.hidden = !open;
  if (open) void loadSmrHours();
}

export async function loadSmr() {
  const user = getCurrentUser();
  if (exportBtn) exportBtn.hidden = !(user && roleAtLeast(user.role, "owner"));
  if (hoursBtn) hoursBtn.hidden = !(user && roleAtLeast(user.role, "admin"));
  if (hoursOpen) void loadSmrHours();
  setMessage(message, "", "");
  try {
    render(await apiListSmrTiles(currentParams()));
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not load SMR orders."), "error");
  }
}

chipButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    chips[btn.dataset.row] = btn.dataset.filter;
    saveFilters(chips);
    applyFilter();
  });
});

// Search, dropdowns, Clear filters and the sort toggle all refetch with the
// current controls; the chip rows above stay local.
installFilterControls(() => { void loadSmr(); });

hoursBtn?.addEventListener("click", () => showHours(!hoursOpen));

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
    setMessage(message, "Preparing workbook…", "");
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
      setMessage(message, `Downloaded ${filename}`, "success");
    } catch (err) {
      setMessage(message, friendlyError(err, "Could not export the SMR workbook."), "error");
    } finally {
      exportBtn.disabled = false;
    }
  });
}
