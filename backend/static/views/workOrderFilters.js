// Work Orders: filters, search and sort.
//
// Layer: owns everything the controls block holds -- the filter reads, the
// filter-option lists fetched from the server, the scheduled-date sort
// direction and its localStorage memory, and the RECENT_LIMIT browse cap.
// The controls are wired in workOrderList.js; the state they read and write
// lives here.

import { escapeHtml } from "../format.js";
import { apiGetWorkOrderFilterOptions } from "../api.js";

const statusFilter = document.getElementById("work-orders-status-filter");
const serviceTypeFilter = document.getElementById("work-orders-service-filter");
const priorityFilter = document.getElementById("work-orders-priority-filter");
const supervisorFilter = document.getElementById("work-orders-supervisor-filter");
const communityFilter = document.getElementById("work-orders-community-filter");
const scheduledDateFilter = document.getElementById("work-orders-date-filter");
const searchInput = document.getElementById("work-orders-search");
const locationSearchInput = document.getElementById("work-orders-location-search");
const taskSearchInput = document.getElementById("work-orders-task-search");
const sortSeg = document.getElementById("work-orders-sort");

let filterOptionsLoaded = false;

// The default browse shows only the RECENT_LIMIT highest scheduled dates to keep
// the page fast as the archive grows; `showAll` drops the cap. Any active filter
// queries the full set. See loadWorkOrders / renderMoreControl.
export const RECENT_LIMIT = 10;
let showAll = false;

// Matches `domain.work_orders.PRIORITY_FILTER_NONE`: the work orders whose
// priority never came back from NetFacilities, which the detail card shows as
// "Not imported". A sentinel rather than "" because "" already means no filter.
export const PRIORITY_NOT_IMPORTED = "__none__";

function populateFilterSelect(select, emptyLabel, options) {
  if (!select) return;
  const selected = select.value;
  select.innerHTML =
    `<option value="">${escapeHtml(emptyLabel)}</option>` +
    options
      .map(({ value, label }) =>
        `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
      .join("");
  if (options.some((option) => option.value === selected)) select.value = selected;
}

export async function loadFilterOptions() {
  if (filterOptionsLoaded) return;
  const options = await apiGetWorkOrderFilterOptions();
  populateFilterSelect(
    serviceTypeFilter,
    "All service types",
    (options.service_types || []).map((value) => ({ value, label: value }))
  );
  // Priority is raw vendor text, so the choices are whatever the live work
  // orders actually carry, plus the rows NetFacilities never reached.
  populateFilterSelect(
    priorityFilter,
    "All priorities",
    (options.priorities || [])
      .map((value) => ({ value, label: value }))
      .concat([{ value: PRIORITY_NOT_IMPORTED, label: "Not imported" }])
  );
  populateFilterSelect(
    supervisorFilter,
    "All supervisors",
    (options.supervisors || []).map((option) => ({
      value: option.id,
      label: option.name,
    }))
  );
  populateFilterSelect(
    communityFilter,
    "All communities",
    options.communities || []
  );
  filterOptionsLoaded = true;
}

// Scheduled-date sort direction. Server-side (`sort` query param) because the
// default browse fetches only the newest RECENT_LIMIT rows -- reversing those
// in the browser would show the wrong ten. Remembered per browser; Clear
// filters leaves it alone since it is a view preference, not a filter.
export const SORT_STORAGE_KEY = "workOrders.sort";
export const SORT_VALUES = new Set(["scheduled_desc", "scheduled_asc"]);
let sortDir = "scheduled_desc";
try {
  const saved = localStorage.getItem(SORT_STORAGE_KEY);
  if (SORT_VALUES.has(saved)) sortDir = saved;
} catch {
  // Storage unavailable (private mode, blocked): keep the default.
}

export function renderSortControl() {
  if (!sortSeg) return;
  sortSeg.querySelectorAll("[data-sort]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.sort === sortDir));
  });
}

export function currentFilters() {
  return {
    status: statusFilter ? statusFilter.value : "",
    serviceType: serviceTypeFilter ? serviceTypeFilter.value : "",
    supervisorId: supervisorFilter ? supervisorFilter.value : "",
    community: communityFilter ? communityFilter.value : "",
    priority: priorityFilter ? priorityFilter.value : "",
    scheduledDate: scheduledDateFilter ? scheduledDateFilter.value : "",
    q: searchInput ? searchInput.value.trim() : "",
    locationQ: locationSearchInput ? locationSearchInput.value.trim() : "",
    taskQ: taskSearchInput ? taskSearchInput.value.trim() : "",
  };
}

export function hasActiveFilters() {
  return Object.values(currentFilters()).some(Boolean);
}

// The list request: every filter plus the sort direction, which is not a
// filter (it never affects the RECENT_LIMIT cap or Clear filters).
export function listParams() {
  return { ...currentFilters(), sort: sortDir };
}

export function resetFilterControls() {
  [statusFilter, serviceTypeFilter, priorityFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
    if (control) control.value = "";
  });
  if (searchInput) searchInput.value = "";
  if (locationSearchInput) locationSearchInput.value = "";
  if (taskSearchInput) taskSearchInput.value = "";
}

export function getShowAll() { return showAll; }
export function setShowAll(value) { showAll = value; }
export function getSortDir() { return sortDir; }
export function setSortDir(value) { sortDir = value; }
export function invalidateFilterOptions() { filterOptionsLoaded = false; }
export function isFilterOptionsLoaded() { return filterOptionsLoaded; }
// The filter-options half of the reset workOrderReferenceData.js also listens
// for. Each module resets only the state it owns.
document.addEventListener("user-names-updated", () => { filterOptionsLoaded = false; });

// The vendor priority levels currently live on the page, for the editor's
// datalist. Excludes the "not imported" sentinel, which is a filter, not a level.
export function livePriorityValues() {
  if (!priorityFilter) return [];
  return Array.from(priorityFilter.options)
    .map((option) => option.value)
    .filter((value) => value && value !== PRIORITY_NOT_IMPORTED);
}
