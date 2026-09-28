// Work Orders: applied-filter chips and the result count.
//
// Layer: beside workOrderFilters.js, whose control state it reads. One chip per
// non-default filter under the controls block, each a real button that clears
// just that filter, plus a Clear all chip once two or more are active; and a
// count line under them so a filtered-empty list never looks like an empty
// one. Sort is a view preference, not a filter, so it never gets a chip.
// workOrderList.js calls the two renders after each load and supplies the
// reload path, so no filter logic lives here.

import { escapeHtml } from "../format.js";
import { RECENT_LIMIT, currentFilters, filterControl, filterKeys } from "./workOrderFilters.js";
import { statusGlyph } from "./workOrderGlyphs.js";

const chipsEl = document.getElementById("work-orders-filter-chips");
const countEl = document.getElementById("work-orders-result-count");

const CHIP_PREFIX = {
  status: "Status",
  serviceType: "Service type",
  priority: "Priority",
  supervisorId: "Supervisor",
  assignedToId: "Technician",
  community: "Community",
  scheduledDate: "Scheduled",
  q: "WO #",
  locationQ: "Location",
  taskQ: "Task",
};

// Free-text searches are quoted so a trailing space or a one-letter search is
// visible for what it is. Selects show their option text (a supervisor's name,
// not their id).
const QUOTED = new Set(["locationQ", "taskQ"]);

function chipValueText(key, value) {
  const control = filterControl(key);
  if (control?.tagName === "SELECT") {
    const option = Array.from(control.options).find((o) => o.value === value);
    return option ? option.textContent : value;
  }
  return QUOTED.has(key) ? `"${value}"` : value;
}

export function activeFilterChips() {
  const filters = currentFilters();
  return filterKeys()
    .filter((key) => filters[key])
    .map((key) => ({
      key,
      value: filters[key],
      label: `${CHIP_PREFIX[key]}: ${chipValueText(key, filters[key])}`,
    }));
}

function chipHtml({ key, value, label }) {
  // The status chip carries the status pill's hue and glyph, so it doubles as
  // a legend for the one filter that is color-coded on the cards.
  const swatch = key === "status"
    ? `<span class="wo-filter-chip-swatch wo-status-${escapeHtml(value)}">${statusGlyph(value)}</span>`
    : "";
  return `<button type="button" class="wo-filter-chip" data-filter-key="${escapeHtml(key)}" aria-label="Remove filter ${escapeHtml(label)}">` +
    `${swatch}<span>${escapeHtml(label)}</span><span class="wo-filter-chip-x" aria-hidden="true">×</span></button>`;
}

export function renderFilterChips() {
  if (!chipsEl) return;
  const chips = activeFilterChips();
  const clearAll = chips.length >= 2
    ? `<button type="button" class="wo-filter-chip wo-filter-chip-clear" data-filter-clear-all>Clear all</button>`
    : "";
  chipsEl.innerHTML = chips.map(chipHtml).join("") + clearAll;
  chipsEl.hidden = chips.length === 0;
}

// `capped` is the unfiltered RECENT_LIMIT browse; `count` is the rows loaded.
export function renderResultCount({ count, capped }) {
  if (!countEl) return;
  let text;
  if (!count && activeFilterChips().length) {
    text = "No work orders match these filters — clear a filter to widen the list";
  } else if (capped && count >= RECENT_LIMIT) {
    text = `Showing the ${RECENT_LIMIT} most recent`;
  } else {
    text = `Showing ${count} work order${count === 1 ? "" : "s"}`;
  }
  countEl.textContent = text;
  countEl.hidden = false;
}

export function hideResultCount() {
  if (countEl) countEl.hidden = true;
}

// `onRemove` runs after one control has been reset (the list's own filter-
// change reload); `onClearAll` is the Clear filters handler.
export function installFilterChips({ onRemove, onClearAll }) {
  if (!chipsEl) return;
  chipsEl.addEventListener("click", (event) => {
    const chip = event.target.closest(".wo-filter-chip");
    if (!chip) return;
    if (chip.hasAttribute("data-filter-clear-all")) {
      onClearAll();
      return;
    }
    const control = filterControl(chip.dataset.filterKey);
    if (!control) return;
    control.value = "";
    onRemove(chip.dataset.filterKey);
  });
}
