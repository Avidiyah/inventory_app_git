// View helper: the SMR page's search and filter controls.
//
// Layer: views (leaf under smr.js). The Work Orders page's filter row minus
// service type, bound to the `smr-*` controls in pages/smr.html. Builds the
// same query the list sends, so the server applies the same predicates;
// fills the dropdowns from the payload's `filter_options`; owns the sort
// direction and its localStorage memory under its own key, and the filters'
// sessionStorage memory (they survive a reload, not a new tab).

export const SMR_SORT_STORAGE_KEY = "smr.sort";
const SORT_VALUES = new Set(["scheduled_desc", "scheduled_asc"]);

const statusFilter = document.getElementById("smr-status-filter");
const priorityFilter = document.getElementById("smr-priority-filter");
const supervisorFilter = document.getElementById("smr-supervisor-filter");
const technicianFilter = document.getElementById("smr-technician-filter");
const communityFilter = document.getElementById("smr-community-filter");
const dateFilter = document.getElementById("smr-date-filter");
const searchInput = document.getElementById("smr-search");
const locationSearch = document.getElementById("smr-location-search");
const taskSearch = document.getElementById("smr-task-search");
const sortControl = document.getElementById("smr-sort");

const SELECTS = [statusFilter, priorityFilter, supervisorFilter, technicianFilter, communityFilter];
const TEXTS = [searchInput, locationSearch, taskSearch];

// Keys are `currentParams` names; the state chip rides along as `chip`.
export const SMR_FILTERS_STORAGE_KEY = "smr.filters";
const CONTROLS = {
  status: statusFilter, priority: priorityFilter, supervisorId: supervisorFilter,
  assignedToId: technicianFilter, community: communityFilter, scheduledDate: dateFilter,
  q: searchInput, locationQ: locationSearch, taskQ: taskSearch,
};

let saved = {};
try { saved = JSON.parse(sessionStorage.getItem(SMR_FILTERS_STORAGE_KEY)) || {}; } catch { /* none */ }

// Saved dropdown values whose options only arrive with the first payload;
// `fill` consumes them, and `currentParams` sends them in the meantime.
const pendingSelect = new Map();
for (const [key, control] of Object.entries(CONTROLS)) {
  const value = saved[key];
  if (!control || typeof value !== "string" || !value) continue;
  control.value = value;
  if (control.value !== value) pendingSelect.set(control, value);
}

export function savedChip() { return typeof saved.chip === "string" ? saved.chip : null; }

export function saveFilters(chip = saved.chip) {
  const { sort, ...filters } = currentParams();
  saved = { ...filters, chip };
  try { sessionStorage.setItem(SMR_FILTERS_STORAGE_KEY, JSON.stringify(saved)); } catch { /* ignore */ }
}

const valueOf = (control) => control?.value.trim() || pendingSelect.get(control) || "";

let sortDir = "scheduled_desc";
try {
  const saved = localStorage.getItem(SMR_SORT_STORAGE_KEY);
  if (SORT_VALUES.has(saved)) sortDir = saved;
} catch { /* storage unavailable: default stands */ }

export function getSortDir() { return sortDir; }

export function setSortDir(value) {
  if (!SORT_VALUES.has(value)) return;
  sortDir = value;
  try { localStorage.setItem(SMR_SORT_STORAGE_KEY, value); } catch { /* ignore */ }
  renderSortControl();
}

export function renderSortControl() {
  if (!sortControl) return;
  sortControl.querySelectorAll("[data-sort]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.sort === sortDir));
  });
}

// The same keys `apiListWorkOrders` takes, minus serviceType/mine/limit.
export function currentParams() {
  const params = { sort: sortDir };
  for (const [key, control] of Object.entries(CONTROLS)) params[key] = valueOf(control);
  return params;
}

export function resetControls() {
  pendingSelect.clear();
  SELECTS.forEach((control) => { if (control) control.value = ""; });
  TEXTS.forEach((control) => { if (control) control.value = ""; });
  if (dateFilter) dateFilter.value = "";
}

function fill(select, allLabel, choices) {
  if (!select) return;
  const current = select.value || pendingSelect.get(select) || "";
  pendingSelect.delete(select);
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.appendChild(all);
  for (const { value, label } of choices) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  // Keep a selection the new list still offers; otherwise fall back to All.
  select.value = choices.some((c) => c.value === current) ? current : "";
}

export function applyFilterOptions(options = {}) {
  fill(priorityFilter, "All priorities", (options.priorities || []).map((value) => ({ value, label: value })));
  fill(supervisorFilter, "All Team Leads", (options.supervisors || []).map((p) => ({ value: p.id, label: p.name })));
  fill(technicianFilter, "All technicians", (options.technicians || []).map((p) => ({ value: p.id, label: p.name })));
  fill(communityFilter, "All communities", options.communities || []);
}

// Wire the controls: `reload` runs on Search, Enter in a text box, any
// dropdown or date change, Clear filters, and a sort click.
export function installFilterControls(refetch) {
  const reload = () => { saveFilters(); refetch(); };
  document.getElementById("smr-search-btn")?.addEventListener("click", reload);
  document.getElementById("smr-clear-filters")?.addEventListener("click", () => {
    resetControls();
    reload();
  });
  TEXTS.forEach((input) => input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); reload(); }
  }));
  [...SELECTS, dateFilter].forEach((control) => control?.addEventListener("change", reload));
  sortControl?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-sort]");
    if (!btn || btn.dataset.sort === sortDir) return;
    setSortDir(btn.dataset.sort);
    reload();
  });
  renderSortControl();
}
