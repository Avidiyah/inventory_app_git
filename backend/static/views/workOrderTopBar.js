// Work Orders: the pinned location + task header and the top icon bar.
//
// Layer: HTML builders and one sync helper for the card page's header. The
// pin stays on screen while the card scrolls; the bar picks the open section
// (materials, labor, notes, photos), and More holds Details, the extra
// sections and the admin tools. Builders only: the click handling lives in
// workOrderActions.js and the tab/section state in workOrderCardHtml.js.

import { escapeHtml } from "../format.js";
import {
  attentionPriorityBadge,
  overdueTag,
  placeParts,
  statusBadge,
} from "./workOrderPresenters.js";

// Inline SVG only (CSP, no icon fonts). Paths are the owner-approved preview's.
const ICON = {
  details: '<path d="M5 4h14v16H5z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  notes: '<path d="M4 5h16v11H9l-5 4z"/>',
  materials: '<path d="M3 8l9-5 9 5-9 5z"/><path d="M3 8v8l9 5 9-5V8"/>',
  labor: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  photos: '<rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/>',
  takeoff: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  more: '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
  invoice: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/>',
};
const svg = (key) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[key] || ICON.details}</svg>`;

const WORDS = { materials: "Materials", labor: "Labor", notes: "Notes", photos: "Photos" };

function counts(detail) {
  const minutes = Number(detail.labor_minutes) || 0;
  const noteLines = String(detail.notes || "").split("\n").filter((l) => l.trim()).length;
  return {
    materials: detail.items.length ? String(detail.items.length) : "",
    labor: minutes ? `${Math.round((minutes / 60) * 100) / 100} h` : "",
    notes: noteLines ? String(noteLines) : "",
    photos: detail.photo_count ? String(detail.photo_count) : "",
  };
}

const tabButton = (key, word, count) =>
  `<button type="button" class="wo-tab" role="tab" data-wo-tab="${key}" aria-selected="false">` +
  `${svg(key)}<span class="wo-tab-word">${escapeHtml(word)}</span><small>${escapeHtml(count)}</small></button>`;

// `moreSections`: [key, label] pairs listed under More after Details.
export function topBarHtml(detail, { showLabor, moreSections = [], toolsHtml = "", canEdit = false }) {
  const count = counts(detail);
  const keys = ["materials", ...(showLabor ? ["labor"] : []), "notes", "photos"];
  const entries = [["details", "Details"], ...moreSections];
  const menu = entries
    .map(([key, label]) => `<button type="button" class="wo-tab wo-more-item" role="tab" data-wo-tab="${key}" aria-selected="false">${svg(key)}<span>${escapeHtml(label)}</span></button>`)
    .join("");
  const tools = toolsHtml || canEdit
    ? `<hr>${toolsHtml}${canEdit ? `<button type="button" class="secondary-btn" data-wo-open-edit>Edit details</button>` : ""}`
    : "";
  return `<nav class="wo-topbar" id="wo-sec-tabs" role="tablist" aria-label="Work order sections">` +
    keys.map((key) => tabButton(key, WORDS[key], count[key])).join("") +
    `<details class="wo-more" id="wo-more"><summary class="wo-more-btn" aria-label="More">${svg("more")}` +
    `<span class="wo-tab-word">More</span><small class="wo-more-current"></small></summary>` +
    `<div class="wo-more-menu">${menu}${tools}</div></details></nav>`;
}

export function pinHtml(detail, barHtml) {
  const { heading, detail: room } = placeParts(detail);
  const chips = statusBadge(detail.status) + attentionPriorityBadge(detail) + overdueTag(detail);
  const task = detail.description || "No task on this work order";
  return `<div class="wo-pin" id="wo-sec-pin">` +
    `<p class="wo-pin-place">${escapeHtml(heading)}${room ? ` · ${escapeHtml(room)}` : ""}</p>` +
    `<p class="wo-pin-task">${escapeHtml(task)}</p>` +
    `<div class="wo-pin-chips">${chips}<span class="wo-pin-number">WO ${escapeHtml(detail.number)}</span></div>` +
    `${barHtml}</div>`;
}

// Marks the active tab. A More section (Details, Invoice) selects its menu
// row, marks More current and names the section under the More word.
export function syncTopBar(bodyEl, active) {
  const bar = bodyEl.querySelector(":scope > .wo-pin > .wo-topbar");
  if (!bar) return;
  bar.querySelectorAll(".wo-tab").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.woTab === active));
  });
  const row = bar.querySelector(`.wo-more-item[data-wo-tab="${active}"]`);
  const more = bar.querySelector(".wo-more");
  more.classList.toggle("wo-more-active", Boolean(row));
  more.querySelector(".wo-more-current").textContent = row ? row.textContent : "";
}
