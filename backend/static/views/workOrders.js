// View: Work Orders page.
//
// Layer: views. Owns the Work Orders page: a server-scoped list of standalone
// work orders (identity = number). Work orders are IMPORT-ONLY -- the Admin+ CSV
// import is the only way one appears; there is no create form. The CSV import,
// NetFacilities/Langston University card, and "For Client" export render on
// the separate Integrations page (loadIntegrationsPage, pages/integrations.html)
// but are still owned by this module, since they share state with the list
// below. Admin+ can export the current filtered list as the operational CSV
// from this page. Admin+ Edit details includes imported metadata;
// Supervisor sees only routing, technicians, and status, and also manages labor,
// entry mode, and material corrections. Assigned Technicians/Supervisors get a
// narrow Set In-Progress -> Mark Completed walkthrough plus an In-Progress-only
// Place On-Hold action and On-Hold-only Resume In-Progress action outside the
// unchanged editor; Technicians can also save notes and add new materials.
// Admin+ can archive any live work order directly from its expanded card. An
// exact-number search for a closed row offers the explicit restore workflow.
// Reached via the nav button or a Unit click in the Mass Stage tree (which calls
// `focusWorkOrder` before switching pages).

import {
  apiListWorkOrders,
  apiGetWorkOrderFilterOptions,
  apiGetWorkOrder,
  apiUpdateWorkOrder,
  apiStartWorkOrderTracking,
  apiStopWorkOrderTracking,
  apiCompleteWorkOrder,
  apiHoldWorkOrder,
  apiResumeWorkOrder,
  apiAddWorkOrderItem,
  apiUpdateWorkOrderItem,
  apiSetWorkOrderItemBilling,
  apiDeleteWorkOrderItem,
  apiAddWorkOrderLabor,
  apiUpdateWorkOrderLabor,
  apiDeleteWorkOrderLabor,
  apiArchiveWorkOrder,
  apiLookupWorkOrder,
  apiRestoreWorkOrder,
  apiImportWorkOrders,
  apiGetNetFacilitiesSession,
  apiStartNetFacilitiesAuthentication,
  apiConfirmNetFacilitiesAuthentication,
  apiCancelNetFacilitiesAuthentication,
  apiStartNetFacilitiesEnrichment,
  apiGetNetFacilitiesEnrichment,
  apiImportNetFacilitiesDownload,
  apiGetNetFacilitiesCloudSession,
  apiStartNetFacilitiesCloudAuthentication,
  apiCancelNetFacilitiesCloudAuthentication,
  apiImportNetFacilitiesCloudDownload,
  apiExportWorkOrders,
  apiListItems,
  apiListUsers,
} from "../api.js";
import {
  escapeHtml,
  friendlyError,
  formatMoney,
  formatUserName,
  filterRanked,
  safeHttpUrl,
} from "../format.js";
import { setMessage, confirmDialog, messageDialog } from "../dom.js";
import { tipHtml } from "../tooltip.js";
import { itemRequestPromptHtml } from "./itemRequest.js";
import { getCurrentUser, getRole } from "../state.js";
import {
  canBeWorkOrderSupervisor,
  canBeWorkOrderTechnician,
  roleAtLeast,
} from "../roles.js";
import { openBillingEditor } from "./billingEditor.js";
import { subscribe } from "../realtime.js";
import { skeletonCard } from "../skeleton.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const statusFilter = document.getElementById("work-orders-status-filter");
const serviceTypeFilter = document.getElementById("work-orders-service-filter");
const priorityFilter = document.getElementById("work-orders-priority-filter");
const priorityLevelFilter = document.getElementById("work-orders-priority-level-filter");
const supervisorFilter = document.getElementById("work-orders-supervisor-filter");
const communityFilter = document.getElementById("work-orders-community-filter");
const scheduledDateFilter = document.getElementById("work-orders-date-filter");
const searchInput = document.getElementById("work-orders-search");
const searchBtn = document.getElementById("work-orders-search-btn");
const clearFiltersBtn = document.getElementById("work-orders-clear-filters");
const exportMessage = document.getElementById("work-orders-export-message");
const moreEl = document.getElementById("work-orders-more");
// The filters/search block. Hidden in solo mode ("card page"), where the list
// holds one work order and there is nothing to filter.
const controlsSection = document.getElementById("work-orders-controls-section");

const importSection = document.getElementById("integrations-import-section");
const importFile = document.getElementById("wo-import-file");
const importBtn = document.getElementById("wo-import-btn");
const importMessage = document.getElementById("wo-import-message");
const netFacilitiesStatus = document.getElementById("wo-netfacilities-status");
const netFacilitiesSignInBtn = document.getElementById("wo-netfacilities-sign-in-btn");
const netFacilitiesConfirmBtn = document.getElementById("wo-netfacilities-confirm-btn");
const netFacilitiesCancelBtn = document.getElementById("wo-netfacilities-cancel-btn");
const netFacilitiesEnrichBtn = document.getElementById("wo-netfacilities-enrich-btn");
const netFacilitiesImportDownloadBtn = document.getElementById("wo-netfacilities-import-download-btn");
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
const exportScope = document.getElementById("wo-export-scope");
const exportBtn = document.getElementById("wo-export-btn");
const exportClientBtn = document.getElementById("wo-export-client-btn");

// Reference lists are reused during interactions within one visit (for example,
// debounced Work Order searches), then refreshed when nav.js activates the page
// again so item and user changes made elsewhere cannot remain stale.
let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let allSupers = [];
let usersLoaded = false;
let filterOptionsLoaded = false;
let netFacilitiesCapability = null;
let netFacilitiesPollingJobId = null;
let netFacilitiesSessionPolling = false;
document.addEventListener("user-names-updated", () => {
  allTechs = [];
  allSupers = [];
  usersLoaded = false;
  filterOptionsLoaded = false;
});
// Work order id to expand once the list renders (set by a Mass Stage tree click).
let pendingFocusId = null;

// The default browse shows only the RECENT_LIMIT highest scheduled dates to keep
// the page fast as the archive grows; `showAll` drops the cap. Any active filter
// queries the full set. See loadWorkOrders / renderMoreControl.
const RECENT_LIMIT = 10;
let showAll = false;

// --- card page ("solo") mode ----------------------------------------------
//
// A work-order card opened from the list is shown as a page: the same
// `details.wo-card`, expanded, alone in `#work-orders-list`, with the filter
// and import sections hidden and a Back control above it.
//
// The card is NOT relocated, and must never be. Every interaction on it --
// status actions, notes, materials, labor, the billing editor, the technician
// picker -- is delegated off `listEl`, and the realtime subscriber finds cards
// by querying `listEl`. Rendering the detail into a different container leaves
// a card that looks correct and whose every button is dead, with no error.
//
// `soloActive` drives the chrome; `soloNumber` is the number in the URL and
// stays null when a deep link could not be resolved (renderSoloError).
let soloActive = false;
let soloNumber = null;

// Must match the FastAPI route in backend/app/main.py and the rate-limit
// exemption in backend/app/domain/rate_limit.py. These three strings are the
// whole contract.
const SOLO_PATH_PREFIX = "/workorder_card/";

// A number pending a card-page open, set before nav.js activates the page (see
// focusWorkOrderNumber / focusWorkOrder). loadWorkOrders consumes it instead of
// rendering the list, which is what keeps the two renders from racing.
let pendingSoloNumber = null;

// The work-order number in `pathname`, or null if it is not a card-page URL.
export function soloNumberFromPath(pathname = window.location.pathname) {
  if (!pathname.startsWith(SOLO_PATH_PREFIX)) return null;
  const raw = pathname.slice(SOLO_PATH_PREFIX.length);
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    // A malformed %-escape is not a work order number. Treat it as no link
    // rather than throwing out of a boot path.
    return null;
  }
}

// Show/hide everything around the card. The Import/Export section now lives
// on its own Integrations page (see loadIntegrationsPage), so solo mode no
// longer needs to touch it -- it is already hidden whenever Work Orders
// isn't the active page.
function setSoloChrome(on) {
  if (controlsSection) controlsSection.hidden = on;
  if (moreEl) {
    if (on) moreEl.innerHTML = "";
    moreEl.hidden = true;
  }
}

// Leave card-page mode and put the address bar back. Called from the top of
// every path that renders the full list, so the browser can never show a
// /workorder_card/ URL for a page that is no longer showing that card. The URL
// is normalized even when solo mode was already off -- that covers navigating
// to another page and back while a stale card URL is in the bar.
function exitSolo() {
  if (soloActive) setSoloChrome(false);
  soloActive = false;
  soloNumber = null;
  if (window.location.pathname.startsWith(SOLO_PATH_PREFIX)) {
    window.history.replaceState({}, "", "/");
  }
}

// The card page's own way back. It lives inside `listEl` (so it is cleared with
// the card) but outside any `.wo-card`, which the click delegation has to
// account for -- see the `back-to-work-orders` branch.
function soloBackControl() {
  const wrap = document.createElement("div");
  wrap.className = "wo-solo-back";
  wrap.innerHTML =
    `<button type="button" class="secondary-btn" data-action="back-to-work-orders">` +
    `&larr; Back to work orders</button>`;
  return wrap;
}

const STATUS_CHANGED_EVENT = "work_order.status.changed";
const WORK_ORDERS_PAGE = "work-orders";

export function focusWorkOrder(workOrderId) {
  pendingFocusId = workOrderId;
}

function isSupervisorPlus() {
  return roleAtLeast(getRole(), "supervisor");
}

// The admin *toolkit* floor, which is TechFM OA and above. Distinct from
// `canCurrentUserSendToReview` below, which is the one control still gated on
// Admin proper.
function isAdminPlus() {
  return roleAtLeast(getRole(), "techfm_oa");
}

// Matches `domain.work_orders.PRIORITY_FILTER_NONE`: the work orders whose
// priority never came back from NetFacilities, which the detail card shows as
// "Not imported". A sentinel rather than "" because "" already means no filter.
const PRIORITY_NOT_IMPORTED = "__none__";

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

async function loadFilterOptions() {
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

function currentFilters() {
  return {
    status: statusFilter ? statusFilter.value : "",
    serviceType: serviceTypeFilter ? serviceTypeFilter.value : "",
    supervisorId: supervisorFilter ? supervisorFilter.value : "",
    community: communityFilter ? communityFilter.value : "",
    priority: priorityFilter ? priorityFilter.value : "",
    priorityBucket: priorityLevelFilter ? priorityLevelFilter.value : "",
    scheduledDate: scheduledDateFilter ? scheduledDateFilter.value : "",
    q: searchInput ? searchInput.value.trim() : "",
  };
}

function hasActiveFilters() {
  return Object.values(currentFilters()).some(Boolean);
}

function resetFilterControls() {
  [statusFilter, serviceTypeFilter, priorityFilter, priorityLevelFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
    if (control) control.value = "";
  });
  if (searchInput) searchInput.value = "";
}

// Fixed company mark-up on the line total (mirrors history.js MARKUP_RATE).
// A work-order material line is the billing unit: charge = effective billable
// units * price, where effective billable is the override when set else the
// full quantity.
const MARKUP_RATE = 1.15;

function effectiveBillable(it) {
  const b = it.billable_quantity;
  return (b === null || b === undefined) ? Number(it.quantity) : Number(b);
}

// The Admin/Owner-only charge cell for a material line, or "" when no price is
// visible (backend redacts `unit_price` to null below Admin, so this renders
// only for those who may see cost). Carries `data-*` so the inline editor can
// read the line quantity / current override without re-fetching.
function lineChargeHtml(it) {
  if (it.unit_price === null || it.unit_price === undefined) return "";
  const quantity = Number(it.quantity);
  const billable = effectiveBillable(it);
  const base = billable * Number(it.unit_price);
  const marked = base * MARKUP_RATE;
  let flag = "";
  if (billable !== quantity) {
    flag = billable === 0
      ? `<span class="charge-flag not-charged">Not charged</span>`
      : `<span class="charge-flag">Billing ${escapeHtml(String(billable))} of ${escapeHtml(String(quantity))}</span>`;
  }
  return `<span class="wo-line-charge" data-quantity="${escapeHtml(String(quantity))}" data-billable="${escapeHtml(String(billable))}">` +
    `<span class="charge-base">${escapeHtml(formatMoney(base))}</span>` +
    `<span class="charge-marked">+15%: ${escapeHtml(formatMoney(marked))}</span>` +
    flag +
    `<button type="button" class="wo-edit-charge-btn">Edit charge</button>` +
    `</span>`;
}

// The Admin/Owner-only work-order materials total (base + mark-up), or "" when
// the backend redacted the figure (below Admin).
function materialsTotalHtml(detail) {
  if (detail.materials_total === null || detail.materials_total === undefined) return "";
  const base = Number(detail.materials_total);
  const marked = base * MARKUP_RATE;
  return `<div class="wo-materials-total">Materials total: ` +
    `<strong>${escapeHtml(formatMoney(base))}</strong> ` +
    `<span class="charge-marked">+15%: ${escapeHtml(formatMoney(marked))}</span></div>`;
}

function notesLogContentsHtml(notes) {
  const log = String(notes || "").trim();
  return log
    ? `<div class="wo-notes-log-text">${escapeHtml(log)}</div>`
    : `<p class="hint wo-notes-empty">No notes recorded yet.</p>`;
}

function formatMinutes(minutes) {
  const total = Number(minutes) || 0;
  const hours = Math.floor(total / 60);
  const remainder = total % 60;
  if (!hours) return `${remainder} min`;
  if (!remainder) return `${hours} hr${hours === 1 ? "" : "s"}`;
  return `${hours} hr ${remainder} min`;
}

function hoursInputValue(minutes) {
  return String(Math.round((Number(minutes) / 60) * 100) / 100);
}

function hoursToMinutes(value) {
  const hours = Number(value);
  if (!Number.isFinite(hours) || hours <= 0) return null;
  return Math.max(1, Math.round(hours * 60));
}

function laborSummaryHtml(detail) {
  const actual = formatMinutes(detail.labor_minutes || 0);
  const billed = formatMinutes(detail.labor_billed_minutes || 0);
  const charge = detail.labor_total === null || detail.labor_total === undefined
    ? ""
    : `<span class="wo-labor-charge">${escapeHtml(formatMoney(detail.labor_total))} at ${escapeHtml(formatMoney(detail.labor_rate))}/hr</span>`;
  return `<div class="wo-labor-summary"><span>Actual: <strong>${escapeHtml(actual)}</strong></span><span>Billed: <strong>${escapeHtml(billed)}</strong></span>${charge}</div>`;
}

function canEditLabor() {
  return isSupervisorPlus();
}

function renderLaborEntryHtml(entry) {
  const actions = canEditLabor()
    ? `<div class="wo-labor-actions">
         <input type="number" class="wo-labor-hours" value="${escapeHtml(hoursInputValue(entry.minutes))}" min="0.01" step="0.01" aria-label="Actual labor hours">
         <button type="button" class="secondary-btn" data-action="edit-labor">Update</button>
         <button type="button" class="btn-danger" data-action="remove-labor">Remove</button>
       </div>`
    : "";
  // A tracked entry shows the window it came from; a hand-entered correction
  // and every row predating tracked time have no session and show the duration
  // alone. The server pre-formats the window, so there is nothing to parse.
  const window = entry.session_window
    ? `<span class="hint wo-labor-window">${escapeHtml(entry.session_window)}</span>`
    : "";
  // The 12-hour cap invented this figure. Flagged so a supervisor scanning the
  // card can see which numbers are estimates; nothing blocks it from billing.
  const autoStopped = entry.auto_closed
    ? `<span class="wo-labor-auto-stopped">auto-stopped</span>${tipHtml("wo.auto-stopped")}`
    : "";
  return `<div class="wo-labor-entry" data-labor-id="${escapeHtml(entry.id)}" data-technician-id="${escapeHtml(entry.technician_id)}">
            <div><strong>${escapeHtml(entry.technician_name)}</strong><span class="hint">${escapeHtml(formatMinutes(entry.minutes))} actual</span>${window}${autoStopped}</div>
            ${actions}
          </div>`;
}

// Hand-entered labor is Supervisor+ only, so this picker is Supervisor+ only.
// A supervisor may also credit themselves without being on the crew (the
// server allows "assigned, or the Supervisor recording themselves"), so they
// are appended to the list when they are not already in it.
function laborTechnicianControl(detail) {
  if (!isSupervisorPlus()) return "";
  const ids = assignedIds(detail).slice();
  const names = assignedNames(detail).slice();
  const user = getCurrentUser();
  if (user?.id && !ids.includes(user.id)) {
    ids.push(user.id);
    names.push(`${user.full_name || "You"} (not assigned)`);
  }
  if (!ids.length) {
    return `<p class="hint">Assign at least one technician before recording labor.</p>`;
  }
  const options = ids
    .map((id, index) => `<option value="${escapeHtml(id)}">${escapeHtml(names[index] || "Assigned technician")}</option>`)
    .join("");
  return `<label><span>Technician</span><select class="wo-labor-technician">${options}</select></label>`;
}

function laborSectionHtml(detail) {
  const entries = (detail.labor || []).map(renderLaborEntryHtml).join("") ||
    `<p class="hint">No labor recorded yet.</p>`;
  // Charged time is authoritative: a technician's labor card is a read-only
  // list of the sessions they clocked, and only a Supervisor can key a figure
  // by hand to correct a forgotten Begin Charging.
  const technicianControl = laborTechnicianControl(detail);
  const canAdd = isSupervisorPlus() && Boolean(technicianControl) &&
    !technicianControl.startsWith("<p");
  const rateText = detail.labor_rate === null || detail.labor_rate === undefined
    ? "The combined actual time is rounded up to the next 30 minutes for billing."
    : `Labor is billed at ${formatMoney(detail.labor_rate)}/hour. The combined actual time is rounded up to the next 30 minutes.`;
  const trackedHint = isSupervisorPlus()
    ? "Entries come from charged sessions. Add one by hand only to correct a missed clock-in."
    : "Your hours come from Begin Charging. Ask a supervisor to correct anything that looks wrong.";
  return `<details class="wo-section-card wo-labor-section">
            <summary class="wo-section-summary">Labor</summary>
            <div class="wo-section-content">
              <p class="hint">${escapeHtml(rateText)}</p>
              <p class="hint">${escapeHtml(trackedHint)}</p>
              <div class="wo-labor-list">${entries}</div>
              ${laborSummaryHtml(detail)}
              ${isSupervisorPlus() ? `<div class="wo-add-labor">
                ${technicianControl}
                ${canAdd ? `<label><span>Actual hours</span><input type="number" class="wo-new-labor-hours" min="0.01" step="0.01" placeholder="e.g. 1.25"></label><button type="button" data-action="add-labor">Add labor</button>` : ""}
              </div>` : ""}
            </div>
          </details>`;
}

function statusLabel(status) {
  return {
    created: "Created",
    assigned: "Assigned",
    in_progress: "In-Progress",
    on_hold: "On-Hold",
    ready_to_complete: "Ready to Complete",
    completed: "Completed",
    review: "Review",
  }[status] || status;
}

function statusBadge(status) {
  return `<span class="wo-status wo-status-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

// Priority is raw NetFacilities vendor text with no fixed vocabulary (see
// normalize_priority_filter), so it's bucketed into a severity color by
// keyword rather than an exact match. Unrecognized text still displays
// as-is -- only the color falls back to neutral.
function priorityBucket(priority) {
  if (!priority) return "none";
  const p = priority.toLowerCase();
  if (p.includes("emergency")) return "emergency";
  if (p.includes("urgent")) return "urgent";
  if (p.includes("high")) return "high";
  if (p.includes("low")) return "low";
  if (p.includes("normal") || p.includes("routine") || p.includes("standard")) return "normal";
  return "unknown";
}

function priorityBadge(priority) {
  const bucket = priorityBucket(priority);
  const label = priority || "No priority";
  return `<span class="wo-priority wo-priority-${bucket}">${escapeHtml(label)}</span>`;
}

function modeLabel(mode) {
  return mode === "retroactive" ? "Retroactive" : "Dispense";
}

// Location meta string from a card/detail (any of the parts may be blank).
// Imported work orders carry a single free-text `location` instead of the older
// community/building/unit trio, so fall back to it -- otherwise an imported
// card's summary would show nothing but the item count.
function placeMeta(c) {
  const parts = [];
  if (c.community) parts.push(c.community);
  if (c.building_number) parts.push(`Bldg ${c.building_number}`);
  if (c.unit_number) parts.push(`Unit ${c.unit_number}`);
  if (parts.length) return parts.join(" · ");
  return c.location || "";
}

function assignedIds(detail) {
  if (Array.isArray(detail.assigned_to_ids)) return detail.assigned_to_ids;
  return detail.assigned_to_id ? [detail.assigned_to_id] : [];
}

function assignedNames(detail) {
  if (Array.isArray(detail.assigned_to_names) && detail.assigned_to_names.length) {
    return detail.assigned_to_names;
  }
  return detail.assigned_to_name ? [detail.assigned_to_name] : [];
}

function isAssignedToCurrentUser(detail) {
  const userId = getCurrentUser()?.id;
  return Boolean(userId && assignedIds(detail).includes(userId));
}

// Review is a deliberate second-person handoff. Admin+ may review any work
// order they are not working, while a Supervisor must be the routed supervisor
// and must not also be one of the assigned workers.
function canCurrentUserSendToReview(detail) {
  const user = getCurrentUser();
  if (!user || isAssignedToCurrentUser(detail)) return false;
  return roleAtLeast(user.role, "admin") ||
    (user.role === "supervisor" && detail.supervisor_id === user.id);
}

function technicianSelectionHtml(id, name) {
  return `<div class="wo-tech-selected-row" data-technician-id="${escapeHtml(id)}">
            <span class="wo-tech-selected-name">${escapeHtml(name)}</span>
            <button type="button" class="secondary-btn wo-tech-remove" data-action="remove-technician" aria-label="Remove ${escapeHtml(name)}">Remove</button>
          </div>`;
}

function emptyTechnicianSelectionHtml() {
  return `<p class="hint wo-tech-empty">No technicians assigned.</p>`;
}

function technicianPickerHtml(detail) {
  const ids = assignedIds(detail);
  const names = assignedNames(detail);
  const resultsId = `wo-tech-results-${detail.id}`;
  const selections = ids
    .map((id, index) => {
      const activeTechnician = allTechs.find((technician) => technician.id === id);
      const name = names[index] || (activeTechnician ? formatUserName(activeTechnician) : "Assigned technician");
      return technicianSelectionHtml(id, name);
    })
    .join("");

  return `<div class="wo-tech-picker">
            <div class="wo-tech-selected">
              <span class="wo-tech-selected-label">Assigned to this work order</span>
              <div class="wo-tech-selected-list" aria-live="polite">
                ${selections || emptyTechnicianSelectionHtml()}
              </div>
            </div>
            <div class="wo-tech-search-wrap">
              <label class="wo-tech-search-label">
                <span>Search Technicians or Supervisors</span>
                <input type="search" class="wo-tech-search" placeholder="Search by name" autocomplete="off" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="${escapeHtml(resultsId)}" aria-expanded="false">
              </label>
              <div class="wo-tech-results" id="${escapeHtml(resultsId)}" role="listbox" aria-label="Technician search results" hidden></div>
            </div>
          </div>`;
}

function closeTechnicianResults(picker) {
  const results = picker?.querySelector(".wo-tech-results");
  const input = picker?.querySelector(".wo-tech-search");
  if (results) {
    results.hidden = true;
    results.innerHTML = "";
  }
  if (input) input.setAttribute("aria-expanded", "false");
}

function renderTechnicianSearch(input) {
  const picker = input.closest(".wo-tech-picker");
  const results = picker.querySelector(".wo-tech-results");
  const query = input.value.trim().toLowerCase();
  if (!query) {
    closeTechnicianResults(picker);
    return;
  }

  const selectedIds = new Set(
    Array.from(picker.querySelectorAll(".wo-tech-selected-row"), (row) => row.dataset.technicianId)
  );
  // Same normalized rule the item pickers use, so a name punctuated
  // `O'Brien` or `Smith-Jones` is found by typing `obrien` / `smithjones`.
  // Alphabetical remains the tiebreak *within* a relevance tier.
  const selectable = allTechs
    .map((technician) => ({ technician, name: formatUserName(technician) }))
    .filter(({ technician }) => !selectedIds.has(technician.id));
  const matches = filterRanked(
    selectable,
    (entry) => [entry.name],
    query,
    (left, right) => left.name.localeCompare(right.name)
  ).slice(0, 8);

  if (!allTechs.length) {
    results.innerHTML = `<p class="hint">No active Technicians or Supervisors are available.</p>`;
  } else if (!matches.length) {
    results.innerHTML = `<p class="hint">No matching technicians.</p>`;
  } else {
    results.innerHTML = matches
      .map(
        ({ technician, name }) =>
          `<button type="button" class="secondary-btn wo-tech-result" role="option" data-action="pick-technician" data-technician-id="${escapeHtml(technician.id)}" data-technician-name="${escapeHtml(name)}">${escapeHtml(name)}</button>`
      )
      .join("");
  }
  results.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function supervisorOptions(selectedId) {
  return (
    `<option value="">Unassigned</option>` +
    allSupers
      .map(
        (s) =>
          `<option value="${escapeHtml(s.id)}"${s.id === selectedId ? " selected" : ""}>${escapeHtml(formatUserName(s))}</option>`
      )
      .join("")
  );
}

function supervisorChoices() {
  return [{ value: "", label: "Unassigned" }].concat(
    allSupers.map((s) => ({ value: s.id, label: formatUserName(s) }))
  );
}

// A custom-styled stand-in for a native <select>, used where the OS-rendered
// popup of a real select can't be reached by our CSS (see docs/design-system.md).
// `nativeSelectHtml` is a real, hidden <select> that still holds the value --
// save/read logic (and the class name callers already query for) is
// unchanged; this only replaces what the user sees and clicks.
function comboListHtml(id, options, selectedValue, ariaLabel) {
  return `<div class="wo-combo-list" id="${escapeHtml(id)}" role="listbox" aria-label="${escapeHtml(ariaLabel)}" hidden>
            ${options
              .map(
                ({ value, label }) =>
                  `<button type="button" class="secondary-btn wo-combo-option" role="option" data-action="pick-combo-option" data-value="${escapeHtml(value)}" aria-selected="${value === selectedValue}">${escapeHtml(label)}</button>`
              )
              .join("")}
          </div>`;
}

export function comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) {
  const selected = options.find((opt) => opt.value === selectedValue);
  const triggerLabel = selected ? selected.label : options[0]?.label || "";
  // The trigger button renders before the hidden native select: both are
  // "labelable" and this whole thing sits inside a <label>, which forwards a
  // caption click to the first labelable descendant in tree order. Button
  // first means the click opens the combo instead of landing on a select
  // that's hidden and can't respond.
  return `<div class="wo-combo${extraClass ? ` ${extraClass}` : ""}" data-combo>
            <button type="button" class="wo-combo-trigger" data-action="toggle-combo" aria-haspopup="listbox" aria-expanded="false" aria-controls="${escapeHtml(id)}">
              <span class="wo-combo-trigger-label">${escapeHtml(triggerLabel)}</span>
              <svg class="wo-combo-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
            ${comboListHtml(id, options, selectedValue, ariaLabel)}
            ${nativeSelectHtml}
          </div>`;
}

function closeCombo(combo) {
  const list = combo?.querySelector(".wo-combo-list");
  const trigger = combo?.querySelector(".wo-combo-trigger");
  if (list) list.hidden = true;
  if (trigger) trigger.setAttribute("aria-expanded", "false");
}

// True when a work order still carries the pre-import community/building/unit
// attributes. Those fields are dead weight on an imported work order (which
// describes its place in the free-text `location`), so they are shown and
// offered for editing only where they actually hold something.
function hasLegacyPlace(detail) {
  return Boolean(
    detail.legacy || detail.community || detail.building_number || detail.unit_number
  );
}

// A generated task is stored as its full NetFacilities URL. Reuse the shared
// http(s)-only guard before placing any description in href; ordinary task text
// remains escaped text, and the URL stays visible so users can verify where it
// leads before opening it.
function importedDetailValueHtml(label, value) {
  if (label === "Symptom / task") {
    const safe = safeHttpUrl(value);
    if (safe) {
      return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safe)}</a>`;
    }
  }
  return escapeHtml(value);
}

// The read-only field block shown in a card body: the imported CSV fields plus
// routing, and only the ones that are actually filled in. This stays visible as
// the work-order overview; the matching inputs live in a separate, collapsed
// Edit details card below it.
function detailsViewHtml(detail) {
  const rows = [
    ["Location", detail.location],
    ["Service type", detail.service_type],
    ["Scheduled", detail.schedule_date],
    ["Output to", detail.output_to],
    ["Vendor contact", detail.vendor_assignee],
    ["Symptom / task", detail.description],
    ["Priority", detail.priority || "Not imported"],
    ["Supervisor", detail.supervisor_name],
    ["Technicians", assignedNames(detail).join(", ")],
  ];
  if (hasLegacyPlace(detail)) {
    rows.push(
      ["Community", detail.community],
      ["Building", detail.building_number],
      ["Unit", detail.unit_number]
    );
  }
  const filled = rows.filter(([, v]) => v);
  if (!filled.length) return `<p class="hint wo-details-empty">No details on this work order yet.</p>`;
  return (
    `<dl class="wo-import-meta">` +
    filled
      .map(
        ([label, value]) =>
          `<dt>${escapeHtml(label)}</dt><dd>${importedDetailValueHtml(label, value)}</dd>`
      )
      .join("") +
    `</dl>`
  );
}

// One labelled text input in the editor. `field` is the API field name, which
// doubles as the class the save handler reads back.
function editField(field, label, value) {
  return `<label class="wo-edit-field">
            <span>${escapeHtml(label)}</span>
            <input type="text" class="wo-edit-${escapeHtml(field)}" value="${escapeHtml(value || "")}">
          </label>`;
}

// Manual status changes live inside the Supervisor+ editor. Created/Assigned
// can advance explicitly to In-Progress here (the same transition formerly
// exposed as a standalone button), and On-Hold is always available as a pause.
// Created/Assigned remains one assignment-derived pre-work choice so the status
// cannot contradict the technician field.
function editableStatusValues(detail) {
  const prework = assignedIds(detail).length ? "assigned" : "created";
  let statuses;
  if (detail.status === "on_hold" || detail.status === "ready_to_complete") {
    // A hold does not remember which step it paused. Let the supervisor resume
    // at the appropriate non-Review step or leave it held. Ready to Complete
    // gets the same set: it is an ordinary supervisory decision point, so the
    // full rollback path stays open. `ready_to_complete` itself is deliberately
    // absent -- like Review it is reached by an action, and a supervisor
    // selecting it from a menu would be asserting on a technician's behalf that
    // the work is done.
    statuses = [prework, "in_progress", "on_hold", "completed"];
  } else {
    const rank = { created: 0, assigned: 1, in_progress: 2, completed: 3 }[detail.status];
    statuses = [prework, "in_progress"];
    statuses.push("on_hold");
    if (rank >= 3) statuses.push("completed");
  }
  return [...new Set(statuses)];
}

function editableStatusOptions(detail) {
  return editableStatusValues(detail)
    .map(
      (status) =>
        `<option value="${escapeHtml(status)}"${status === detail.status ? " selected" : ""}>${escapeHtml(statusLabel(status))}</option>`
    )
    .join("");
}

function statusEditorHtml(detail) {
  const label = `Status${tipHtml("wo.status")}`;
  if (detail.status === "review") {
    return `<label class="wo-edit-field">
              <span>${label}</span>
              <input type="text" value="Review" disabled>
            </label>`;
  }
  const options = editableStatusValues(detail).map((status) => ({ value: status, label: statusLabel(status) }));
  const nativeSelect = `<select class="wo-edit-status wo-combo-native" hidden>${editableStatusOptions(detail)}</select>`;
  return `<label class="wo-edit-field wo-edit-status-field">
            <span>${label}</span>
            ${comboHtml({
              id: `wo-status-list-${detail.id}`,
              extraClass: "wo-status-combo",
              nativeSelectHtml: nativeSelect,
              options,
              selectedValue: detail.status,
              ariaLabel: "Status",
            })}
            <small class="hint">Start work, roll back to an earlier step, or place this work order On-Hold. Created/Assigned follows technician assignment.</small>
          </label>`;
}

// Role-specific editor: Admin+ gets imported metadata plus operational fields;
// Supervisor gets only routing, technicians, and status. The number and legacy
// place fields stay read-only.
function detailsEditorHtml(detail) {
  const adminMetadata = isAdminPlus()
    ? editField("location", "Location", detail.location) +
      editField("service-type", "Service type", detail.service_type) +
      editField("schedule-date", "Schedule date", detail.schedule_date) +
      editField("output-to", "Output to", detail.output_to) +
      editField("vendor", "Vendor contact", detail.vendor_assignee) +
      editField("priority", "Priority", detail.priority) +
      `<label class="wo-edit-field wo-edit-wide">
         <span>Symptom / task</span>
         <textarea class="wo-edit-description" rows="2">${escapeHtml(detail.description || "")}</textarea>
       </label>`
    : "";
  const hint = isAdminPlus()
    ? `Edit imported metadata and operations for WO ${escapeHtml(detail.number)}.`
    : `Edit assignment and status for WO ${escapeHtml(detail.number)}.`;
  return `<details class="wo-edit-card">
            <summary class="wo-edit-summary">Edit details</summary>
            <div class="wo-edit" data-original-supervisor-id="${escapeHtml(detail.supervisor_id || "")}">
              <p class="hint">${hint}</p>
              <div class="wo-edit-grid">
                ${adminMetadata}
                <label class="wo-edit-field">
                  <span>Supervisor</span>
                  ${comboHtml({
                    id: `wo-supervisor-list-${detail.id}`,
                    extraClass: "wo-supervisor-combo",
                    nativeSelectHtml: `<select class="wo-edit-supervisor wo-combo-native" hidden>${supervisorOptions(detail.supervisor_id || "")}</select>`,
                    options: supervisorChoices(),
                    selectedValue: detail.supervisor_id || "",
                    ariaLabel: "Supervisor",
                  })}
                </label>
                <fieldset class="wo-edit-field wo-edit-technicians">
                  <legend>Assigned technicians${tipHtml("wo.routing")}</legend>
                  ${technicianPickerHtml(detail)}
                </fieldset>
                ${statusEditorHtml(detail)}
              </div>
              <div class="wo-edit-actions">
                <button type="button" data-action="save-details">Save details</button>
                <button type="button" class="secondary-btn" data-action="cancel-edit">Cancel</button>
              </div>
            </div>
          </details>`;
}

// --- list ----------------------------------------------------------------

// Incremented as each list load begins so a slower lookup from an older search
// cannot open a prompt after the operator has already typed something else.
let archivedSearchToken = 0;
let archivedSearchPromptOpen = false;

async function offerRestoreForExactArchivedSearch(number, token) {
  if (!isAdminPlus() || !number) return;

  let info;
  try {
    // Lookup uses the work-order identity rule (trimmed + case-insensitive), not
    // the list endpoint's substring match. An archived result is therefore an
    // exact match for the number currently in the search box.
    info = await apiLookupWorkOrder(number);
  } catch {
    return; // Courtesy lookup: a failure must not disturb the live list search.
  }

  const currentNumber = searchInput ? searchInput.value.trim() : "";
  if (
    token !== archivedSearchToken ||
    currentNumber.toLowerCase() !== number.toLowerCase() ||
    !info?.found ||
    !info.archived ||
    archivedSearchPromptOpen
  ) {
    return;
  }

  archivedSearchPromptOpen = true;
  try {
    const restore = await confirmDialog("Work Order has been closed.", {
      confirmText: "Restore",
      cancelText: "Close",
    });
    if (!restore) return;
    await apiRestoreWorkOrder(info.id);
    await loadWorkOrders();
  } catch (err) {
    setMessage(
      listMessage,
      friendlyError(err, "Could not restore that work order."),
      "error"
    );
  } finally {
    archivedSearchPromptOpen = false;
  }
}

// Item and user reference lists that the card *body* needs: the add-material
// search reads `allItems`, the technician picker reads `allTechs`/`allSupers`.
//
// Shared by the list load and the card-page load. A cold deep link paints a
// card body without ever rendering the list, and empty lists there are a
// picker that silently matches nothing rather than an error the user can act
// on. Failures stay swallowed, as before: the card is still worth showing.
async function ensureReferenceData({ refresh = false } = {}) {
  if (refresh || !itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = [];
    }
  }
  if ((refresh || !usersLoaded) && isSupervisorPlus()) {
    try {
      const users = await apiListUsers();
      allTechs = users.filter((u) => canBeWorkOrderTechnician(u.role));
      allSupers = users.filter((u) => canBeWorkOrderSupervisor(u.role));
      usersLoaded = true;
    } catch {
      allTechs = [];
      allSupers = [];
    }
  }
}

export async function loadWorkOrders({
  refreshReferenceData = false,
  checkArchivedSearch = false,
  background = false,
} = {}) {
  // Any completed full load -- nav entry, filter change, Show all, Clear
  // filters, or this call itself -- genuinely satisfies a pending deferred
  // refresh, so this states a truth rather than defends against a bug.
  deferredListRefresh = false;

  // A pending card-page open wins: rendering the list first and the card
  // second is the same two renders racing, and whichever settled last would
  // win. nav.js calls this on page entry, so consuming the request here is the
  // one place both orderings can be serialized.
  if (pendingSoloNumber !== null) {
    const number = pendingSoloNumber;
    pendingSoloNumber = null;
    await ensureReferenceData({ refresh: refreshReferenceData });
    await openWorkOrderPageByNumber(number);
    return;
  }

  // Rendering the list is the definition of leaving the card page. Placed
  // here rather than at each call site so a path added later cannot forget it
  // and strand a /workorder_card/ URL over a list.
  exitSolo();

  const archivedLookupToken = ++archivedSearchToken;
  await ensureReferenceData({ refresh: refreshReferenceData });
  if (refreshReferenceData) filterOptionsLoaded = false;
  if (!filterOptionsLoaded) {
    try {
      await loadFilterOptions();
    } catch {
      // The card list is still useful if the small options request fails. Keep
      // the existing selections/placeholders and retry on the next page entry.
      filterOptionsLoaded = false;
    }
  }
  if (exportBtn) exportBtn.hidden = !isAdminPlus();

  const filters = currentFilters();
  // The cap applies only to a completely unfiltered browse. Any advanced filter
  // is a search and must return the complete matching set.
  const capped = !hasActiveFilters() && !showAll && !pendingFocusId;
  const limit = capped ? RECENT_LIMIT : null;
  try {
    let cards = await apiListWorkOrders({ ...filters, limit });
    if (pendingFocusId && !cards.some((c) => c.id === pendingFocusId)) {
      resetFilterControls();
      showAll = false;
      cards = await apiListWorkOrders({ limit: null });
    }
    renderCards(cards);
    renderMoreControl(capped, cards.length);
    setMessage(listMessage, "", "");
    if (pendingFocusId) {
      const focused = cards.find((c) => c.id === pendingFocusId);
      pendingFocusId = null;
      if (focused) {
        // Cards are pages now. Expanding a row here would drop the user
        // mid-list at a card they then have to scroll to -- the thing this
        // change exists to remove. The list was fetched (and filters reset if
        // needed) above, so this is the id/number resolution as well.
        //
        // Returns before the archived-number prompt below: `checkArchivedSearch`
        // is only ever set by the number-search path, and a Mass Stage focus
        // never sets it.
        await openWorkOrderPage({ id: focused.id, number: focused.number });
        return;
      }
    }
    if (checkArchivedSearch) {
      await offerRestoreForExactArchivedSearch(filters.q, archivedLookupToken);
    }
  } catch (err) {
    // A socket-driven refresh must stay silent on failure (spec section 6):
    // leave the existing list exactly as it was rather than wipe it out from
    // under a user who never asked for this reload. The user-initiated path
    // (background=false) keeps today's error behavior unchanged.
    if (background) return;
    listEl.innerHTML = "";
    if (moreEl) {
      moreEl.hidden = true;
      moreEl.innerHTML = "";
    }
    setMessage(listMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

// Called by nav.js on entry to the Integrations page. Owns the role gate on
// the NetFacilities/Langston University card and refreshes its session state
// -- the counterpart of the importSection/netFacilities handling loadWorkOrders
// used to do when the card lived on the Work Orders page.
export async function loadIntegrationsPage() {
  if (importSection) importSection.hidden = !isAdminPlus();
  if (!isAdminPlus()) return;
  void refreshNetFacilitiesSession();
  void refreshNetFacilitiesCloudSession();
}

function renderCards(cards) {
  listEl.innerHTML = "";
  if (!cards.length) {
    listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    return;
  }
  cards.forEach((c) => listEl.appendChild(buildCard(c)));
}

// The "Show all" / "Show recent only" control beneath the list. Only meaningful on
// a plain (not search-driven) browse:
//  - a capped browse that filled the page (>= RECENT_LIMIT rows) may have more
//    beyond the cap, so offer "Show all". (An exact-RECENT_LIMIT total just reloads
//    the same rows on click -- harmless.)
//  - when showing all, offer "Show recent only" to return to the fast view.
//  - during a search, or a short capped page, show nothing.
function renderMoreControl(capped, shownCount) {
  if (!moreEl) return;
  if (showAll && !hasActiveFilters()) {
    moreEl.innerHTML =
      `<button type="button" class="secondary-btn" id="wo-show-recent">Show recent only</button>`;
    moreEl.hidden = false;
  } else if (capped && shownCount >= RECENT_LIMIT) {
    moreEl.innerHTML = `<button type="button" id="wo-show-all">Show all work orders</button>`;
    moreEl.hidden = false;
  } else {
    moreEl.innerHTML = "";
    moreEl.hidden = true;
  }
}

if (moreEl) {
  moreEl.addEventListener("click", (event) => {
    if (event.target.id === "wo-show-all") {
      showAll = true;
      loadWorkOrders();
    } else if (event.target.id === "wo-show-recent") {
      showAll = false;
      loadWorkOrders();
    }
  });
}

// The summary line of a work-order card. Shared by the initial render and the
// real-time single-card update, so the two projections cannot drift. Accepts a
// WorkOrderDetail as well: the schema subclasses WorkOrderCard, so a detail
// response carries every field this reads.
function summaryHtml(card) {
  const place = placeMeta(card);
  const technicianNames = assignedNames(card);
  const assignee = technicianNames.length
    ? ` · ${escapeHtml(technicianNames.join(", "))}`
    : "";
  const legacyTag = card.legacy ? `<span class="wo-legacy-tag">Legacy</span>` : "";
  return (
    `<span class="wo-title">WO ${escapeHtml(card.number)}</span>` +
    statusBadge(card.status) +
    priorityBadge(card.priority) +
    legacyTag +
    `<span class="wo-meta">${place ? escapeHtml(place) + " · " : ""}${card.item_count} items${assignee}</span>`
  );
}

// One work order changed. Rewrite that card's summary and status class, and,
// if the card is expanded and not held, its body too, so the badge and the
// body's status actions never disagree. A held card's editor is never
// touched -- the caller filters those out before calling this.
//
// A 404 means the work order left this user's view: archived, or unassigned
// from them. Either way the row goes. Only 404 removes a card; a network blip
// rejects without a `status` field and must leave the list alone.
async function refreshCardSummary(cardEl) {
  let detail;
  try {
    detail = await apiGetWorkOrder(cardEl.dataset.id);
  } catch (err) {
    if (err?.status !== 404) return;
    if (soloActive) {
      // The card page's only card just left this user's view -- archived, or
      // unassigned from them. Wiping to the list's "No work orders match."
      // would leave a page with no card and no way back.
      renderSoloError("This work order is no longer available.");
      return;
    }
    cardEl.remove();
    if (!listEl.querySelector("details.wo-card")) {
      listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    }
    return;
  }
  const summary = cardEl.querySelector("summary.wo-summary");
  if (summary) summary.innerHTML = summaryHtml(detail);
  cardEl.className = `wo-card wo-card-status-${detail.status}`;

  // A badge alone is not enough: an expanded, non-held card still shows its
  // body, and the body's status actions (renderBody picks them off
  // detail.status) must not fall out of sync with the badge just repainted
  // above -- that is exactly the "Completed" badge over a live "Mark
  // Completed" button spec section 5 exists to prevent.
  //
  // `paintDetail` reuses the detail already fetched above rather than going
  // back to the server, so this stays one request and inherits no second
  // failure path. Held cards are never reached here -- both callers guard for
  // it -- and the re-check below closes the window where an editor opened
  // while the fetch was in flight.
  const bodyEl =
    cardEl.open && !isHeld(cardEl) ? cardEl.querySelector(".wo-body") : null;
  if (bodyEl) {
    paintDetail(detail, bodyEl, cardEl);
  } else {
    // Collapsed, held, or bodyless: drop the loaded flag so the next expansion
    // re-fetches instead of showing a body that is now stale.
    delete cardEl.dataset.loaded;
  }
}

// The four editor sections inside a card body. A card holding any of them open
// is "held": nothing refreshes it, because rewriting it would discard an unsaved
// note, a material quantity, labor hours, or a technician selection in progress.
// The technician combobox needs no entry -- it renders inside `.wo-edit-card`.
const EDITOR_SECTIONS =
  ".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section";

function isHeld(cardEl) {
  return Array.from(cardEl.querySelectorAll(EDITOR_SECTIONS)).some((s) => s.open);
}

function anyCardHeld() {
  if (!listEl) return false;
  return Array.from(listEl.querySelectorAll("details.wo-card")).some(isHeld);
}

// A full list refetch rebuilds every card (renderCards clears the list), so it
// must never run while an editor is open. Restore and reconnect are both rare,
// so deferring until the last hold clears costs nothing.
let deferredListRefresh = false;

function runOrDeferListRefresh() {
  if (soloActive) {
    // A list refetch would replace the card page with the list -- silently,
    // with the card's URL still in the address bar. On a card page the only
    // row that can matter is the one on screen, so refresh that instead. A
    // held card defers exactly as it does in the list.
    const cardEl = listEl.querySelector("details.wo-card");
    if (!cardEl) return;
    if (isHeld(cardEl)) {
      cardEl.dataset.missedUpdate = "1";
      return;
    }
    void refreshCardSummary(cardEl);
    return;
  }
  if (anyCardHeld()) {
    deferredListRefresh = true;
    return;
  }
  deferredListRefresh = false;
  void loadWorkOrders({ background: true });
}

function buildCard(card, { onOpen, solo = false } = {}) {
  const el = document.createElement("details");
  el.className = `wo-card wo-card-status-${card.status}`;
  el.dataset.id = card.id;

  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  summary.innerHTML = summaryHtml(card);

  const body = document.createElement("div");
  body.className = "wo-body";
  body.innerHTML = skeletonCard({ lines: 3, hasHeader: false });

  el.appendChild(summary);
  el.appendChild(body);
  el.addEventListener("toggle", () => {
    if (el.open && !el.dataset.loaded) openDetail(card.id, body, el);
  });
  summary.addEventListener("click", (event) => {
    // Cards navigate rather than expand in place. `preventDefault` suppresses
    // the native toggle, and covers the keyboard path with it: Enter and Space
    // on a focused summary both dispatch a click, so there is no second path
    // to intercept. It also makes the card page's own card non-collapsible,
    // which is right -- there is nothing to collapse to.
    event.preventDefault();
    // Being *the* solo card is a property of this card, passed in by
    // `showSoloCard`. It used to read the module-global `soloActive`, which
    // silently broke every other list: `exitSolo` runs only inside
    // `loadWorkOrders`, so leaving the card page for the User Hub left the
    // flag set, and the hub's own cards (built by `mountWorkOrderList`, a
    // different container on a different page) went dead on click until the
    // Work Orders page was visited again.
    if (solo) return;
    if (onOpen) {
      onOpen(card);
      return;
    }
    void openWorkOrderPage({ id: card.id, number: card.number });
  });
  return el;
}

async function openDetail(workOrderId, bodyEl, cardEl) {
  try {
    paintDetail(await apiGetWorkOrder(workOrderId), bodyEl, cardEl);
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this work order."))}</p>`;
  }
}

// --- card page render ------------------------------------------------------

// Open one work order as a page. `number` is optional: a click from the list
// already has it, a Mass Stage hand-off has only an id, and either way the
// detail fetched here carries the authoritative number for the URL.
//
// One request, not two: the detail fetched here is painted directly rather
// than being re-fetched by `openDetail`, so opening a card page costs exactly
// what expanding a card used to.
async function openWorkOrderPage({ id, number = null }) {
  await ensureReferenceData();
  soloActive = true;
  soloNumber = number;
  setSoloChrome(true);
  if (listMessage) setMessage(listMessage, "", "");
  listEl.innerHTML = skeletonCard({ lines: 6 });

  let detail;
  try {
    detail = await apiGetWorkOrder(id);
  } catch (err) {
    renderSoloError(friendlyError(err, "Could not open this work order."));
    return;
  }
  showSoloCard(detail);
}

// Open a card page from a work-order NUMBER -- a refreshed page, a bookmark,
// or a pasted link, where the id is not known.
//
// Resolved through the ordinary list search rather than `/work-orders/lookup`:
// lookup is Supervisor+, so a technician following a link to their own
// assigned work order would get a 403 -- the exact person the link is usually
// for. The list route is open to any session and already server-scoped, so it
// answers "may this caller see it" as a side effect of answering "does it
// exist". It partial-matches, so the exact number is chosen here.
async function openWorkOrderPageByNumber(number) {
  await ensureReferenceData();
  soloActive = true;
  soloNumber = number;
  setSoloChrome(true);
  if (listMessage) setMessage(listMessage, "", "");
  listEl.innerHTML = skeletonCard({ lines: 6 });

  let matches;
  try {
    matches = await apiListWorkOrders({ q: number });
  } catch (err) {
    renderSoloError(friendlyError(err, "Could not open this work order."));
    return;
  }

  const match =
    matches.find((c) => c.number === number) ||
    matches.find((c) => c.number.toLowerCase() === number.toLowerCase());
  if (!match) {
    // Archived, or outside this caller's scope. `/work-orders/lookup` could
    // tell those apart but is Supervisor+, so say the one thing that is true
    // for every role rather than guess.
    renderSoloError(`Work order ${number} is not available.`);
    return;
  }
  await openWorkOrderPage({ id: match.id, number: match.number });
}

// Queue a card page to open the next time the Work Orders page loads. Used by
// the post-login boot: nav.js's `showPage` triggers `loadWorkOrders`, which
// consumes this instead of rendering the list, so the two cannot race.
export function focusWorkOrderNumber(number) {
  pendingSoloNumber = number;
}

// Called from the Admin Dashboard's pipeline tiles (hubAdmin.js). Sets the
// status filter and clears every other one, so the tile always lands on
// exactly that status's full company-wide list -- never a stale filter left
// over from the last time someone visited this page. Does not itself fetch:
// `showPage("work-orders")` (nav.js) already calls `loadWorkOrders` on every
// page entry, and that reads these dropdowns' live values.
export function openWorkOrdersFilteredByStatus(status) {
  resetFilterControls();
  if (statusFilter) statusFilter.value = status;
  showAll = false;
}

// Called from the User Hub's Graphs tab (hubGraphs.js via userHub.js), one
// donut click each. Same shape as `openWorkOrdersFilteredByStatus` -- reset
// every other filter first, so a graph always lands on exactly that slice's
// full company-wide list. `community` and `serviceType` set the same
// dropdowns the page's own controls do; `priorityBucket` sets the
// high/medium "Priority level" control, which is a distinct, coarser filter
// from the exact-vendor-text "Priority" dropdown above it.
export function openWorkOrdersFilteredByDistribution({
  community = null,
  serviceType = null,
  priorityBucket = null,
} = {}) {
  resetFilterControls();
  if (community && communityFilter) communityFilter.value = community;
  if (serviceType && serviceTypeFilter) serviceTypeFilter.value = serviceType;
  if (priorityBucket && priorityLevelFilter) priorityLevelFilter.value = priorityBucket;
  showAll = false;
}

// A second, independent card-list renderer for a container other than
// `#work-orders-list` -- the User Hub's "My Work Orders" tab (spec §4.4).
// Deliberately does NOT reuse listEl, the six delegated listeners, solo
// mode, held-card tracking, or the realtime subscriber: none of that
// machinery is reachable from a *collapsed* card (see this plan's Global
// Constraints for why), and a collapsed card is all this ever renders --
// a click hands off to `onOpen` instead of expanding in place, exactly like
// the standalone page's own collapsed cards already do via `openWorkOrderPage`.
//
// `lockedFilter` is forwarded to `apiListWorkOrders` as-is (the same
// {status, serviceType, supervisorId, assignedToId, community, priority,
// scheduledDate, q, mine, limit} shape that function already accepts). The
// technician's own scope needs no filter at all -- `apiListWorkOrders` is
// already scoped server-side per role (`_scoped_to_user`), so an unfiltered
// call already returns exactly "my work orders" for a Technician. The
// Supervisor caller passes `{ mine: true }` -- routed to me or assigned to
// me -- and the Admin caller passes nothing.
export function mountWorkOrderList({ container, lockedFilter = null, onOpen } = {}) {
  async function refresh() {
    container.innerHTML = skeletonCard({ lines: 1 }).repeat(3);
    let cards;
    try {
      cards = await apiListWorkOrders(lockedFilter || {});
    } catch (err) {
      container.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load work orders."))}</p>`;
      return;
    }
    container.innerHTML = "";
    if (!cards.length) {
      container.innerHTML = `<p class="hint">No work orders match.</p>`;
      return;
    }
    cards.forEach((card) => container.appendChild(buildCard(card, { onOpen })));
  }
  return { refresh };
}

// Render `detail` as the only card in the list, expanded, with a Back control
// above it. The element is exactly what `buildCard` produces -- same tag, same
// classes, same `data-id`, same parent -- plus a `.wo-solo` presentation
// modifier, so delegation, the realtime subscriber, and every repaint path
// keep working untouched.
function showSoloCard(detail) {
  soloActive = true;
  soloNumber = detail.number;
  setSoloChrome(true);

  const path = SOLO_PATH_PREFIX + encodeURIComponent(detail.number);
  if (window.location.pathname !== path) {
    // `{ solo: ... }` marks entries this module pushed, which is how the Back
    // control knows whether `history.back()` would leave the app entirely (a
    // cold deep link has a null state).
    window.history.pushState({ solo: detail.number }, "", path);
  }

  listEl.innerHTML = "";
  listEl.appendChild(soloBackControl());
  const cardEl = buildCard(detail, { solo: true });
  cardEl.classList.add("wo-solo");
  listEl.appendChild(cardEl);
  // Paint before opening. `paintDetail` sets `dataset.loaded`, so `buildCard`'s
  // own toggle listener sees a loaded card and does not fetch it a second time
  // -- this does not rely on when the async `toggle` event happens to fire.
  paintDetail(detail, cardEl.querySelector(".wo-body"), cardEl);
  cardEl.open = true;
}

// A card page that has no card: the work order could not be fetched, could not
// be resolved from a link, or has just left this user's view. It still needs
// its own Back control -- the filters are hidden, and a cold deep link has no
// history entry to go back to.
function renderSoloError(message) {
  soloActive = true;
  soloNumber = null;
  setSoloChrome(true);
  listEl.innerHTML = "";
  listEl.appendChild(soloBackControl());
  const p = document.createElement("p");
  p.className = "error";
  p.textContent = message;
  listEl.appendChild(p);
}

// Paint one already-fetched work order into its card.
//
// Split out of `openDetail` so a caller holding a fresh detail can repaint
// without a second round-trip. That matters for more than bandwidth: a second
// fetch carries a second failure path, and `openDetail`'s is deliberately loud
// (it writes an error into the body). Loud is right when a user clicked to
// expand a card; it is wrong for a socket-driven refresh the user never asked
// for, and it would stick -- `dataset.loaded` only advances on success, so
// collapsing and re-expanding would not retry.
function paintDetail(detail, bodyEl, cardEl) {
  renderBody(detail, bodyEl);
  if (!cardEl) return;

  cardEl.dataset.loaded = "1";
  cardEl.className = `wo-card wo-card-status-${detail.status}`;
  const badge = cardEl.querySelector(".wo-status");
  if (badge) {
    badge.className = `wo-status wo-status-${detail.status}`;
    badge.textContent = statusLabel(detail.status);
  }
  const meta = cardEl.querySelector(".wo-meta");
  if (meta) {
    const place = placeMeta(detail);
    const technicianNames = assignedNames(detail);
    const assignee = technicianNames.length ? ` · ${technicianNames.join(", ")}` : "";
    meta.textContent = `${place ? place + " · " : ""}${detail.items.length} items${assignee}`;
  }
  // This repaint already reflects the latest data, so any missed socket
  // update while the card was held is now satisfied -- every repaint path
  // (Cancel, Save details, materials/labor actions, initial expansion)
  // routes through here.
  delete cardEl.dataset.missedUpdate;
}

// --- detail rendering ----------------------------------------------------

function renderBody(detail, bodyEl) {
  const sup = isSupervisorPlus();
  const assignedToCurrentUser = isAssignedToCurrentUser(detail);
  const canSendToReview = canCurrentUserSendToReview(detail);
  const items =
    detail.items.map((it) => renderLineHtml(it)).join("") ||
    `<p class="hint">No materials logged yet.</p>`;

  // Whoever may hold a clock on this row: assigned workers, plus a Supervisor+
  // on any work order they can see (they need not be on the crew to do the
  // work and record it).
  const canTrack = assignedToCurrentUser || sup;
  const tracking = Boolean(detail.active_labor_session);
  const startTracking = `<button type="button" data-action="start-tracking-wo">W.O. Received, Begin Charging</button>`;

  let statusActions = "";
  if (canTrack && (detail.status === "created" || detail.status === "assigned")) {
    // "Set In-Progress" is gone: that transition is now a side effect of
    // starting work, which is what the button always meant.
    statusActions = startTracking;
  } else if (canTrack && detail.status === "in_progress") {
    statusActions = tracking
      ? `<button type="button" data-action="stop-tracking-wo">Stop Charging</button>`
      : startTracking;
    // Notify Supervisor is the "I'm done" button and belongs to someone with a
    // clock running; Stop Charging is the "I'm pausing" one. Both /complete and
    // /hold require assignment server-side, so an unassigned supervisor who is
    // only charging gets neither -- they close the row out with Mark Completed.
    // A Supervisor+ who is *also* assigned skips this button entirely: they
    // already have Mark Completed below, which is the real completion action
    // for them, and complete_work_order's target status for a Supervisor+ is
    // Completed anyway -- Notify Supervisor's "ask someone else" framing
    // doesn't apply to the person who'd be notifying themself.
    if (assignedToCurrentUser && tracking && !sup) {
      statusActions += `<button type="button" data-action="notify-supervisor-wo">Notify Supervisor</button>`;
    }
    if (assignedToCurrentUser) {
      statusActions += `<button type="button" class="secondary-btn" data-action="hold-assigned-wo">Place On-Hold</button>`;
    }
    if (sup) {
      statusActions += `<button type="button" data-action="complete-wo">Mark Completed</button>`;
    }
  } else if (detail.status === "on_hold" && canTrack) {
    // Begin Charging sits beside Resume and is the one a returning technician
    // taps: it does the same transition *and* starts the clock. Resume stays
    // for the case where work resumes without the tapper being the one doing
    // it. Not an either/or with the supervisor half either -- a Supervisor who
    // is also an assigned worker needs both.
    statusActions += startTracking;
    if (assignedToCurrentUser) {
      statusActions += `<button type="button" class="secondary-btn" data-action="resume-assigned-wo">Resume In-Progress</button>`;
    }
    if (sup) {
      statusActions += `<button type="button" data-action="complete-wo">Mark Completed</button>`;
      statusActions += `<span class="hint wo-status-note">On-Hold — nobody is charging time. A supervisor can also resume or roll back this work order in the Edit details card.</span>`;
    }
  } else if (detail.status === "ready_to_complete") {
    // The first review gate: one supervisor confirming the work happened.
    // Distinct from Send to Review, which is the later Admin handoff.
    if (sup) {
      statusActions =
        `<button type="button" data-action="complete-wo">Approve — Mark Completed</button>` +
        `<button type="button" class="secondary-btn" data-action="send-back-wo">Send Back</button>`;
    } else {
      statusActions = `<span class="hint wo-status-note">Sent to your supervisor for review.</span>`;
    }
  } else if (detail.status === "completed") {
    if (canSendToReview) {
      statusActions += `<button type="button" data-action="review-wo">Send to Review</button>`;
    } else if (getRole() === "techfm_oa") {
      // A TechFM OA holds the rest of the Admin toolkit, so a missing button
      // reads as a bug to them rather than as a rule. Show it, disabled, with
      // the reason. Every other role keeps the hidden treatment -- for them
      // Review was never on the menu. The server refuses the transition either
      // way (services/work_orders._require_review_handoff_permission), and a
      // disabled button fires no click, so the delegate below is unreachable.
      statusActions += `<button type="button" data-action="review-wo" disabled title="An Admin, Owner, or the routed Supervisor must send this to Review.">Send to Review</button>`;
    }
    if (sup) {
      statusActions += `<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>`;
    }
  } else if (sup && detail.status === "review") {
    statusActions =
      `<span class="wo-review-ready">Ready for Admin Review</span>` +
      `<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>`;
  }
  if (isAdminPlus()) {
    statusActions += `<button type="button" class="btn-netfacilities" data-action="open-netfacilities-wo" data-number="${escapeHtml(detail.number)}">Open Netfacilities</button>`;
    statusActions += `<button type="button" class="btn-danger" data-action="archive-wo">Archive</button>`;
  }

  const modeControl = sup
    ? `<div class="wo-mode-row">
       <label>New entries:${tipHtml("wo.entry-mode")}</label>
       <select class="wo-mode-select">
         <option value="dispense"${detail.entry_mode === "dispense" ? " selected" : ""}>Dispense (moves stock)</option>
         <option value="retroactive"${detail.entry_mode === "retroactive" ? " selected" : ""}>Retroactive (paper sheet, no stock)</option>
       </select>
     </div>`
    : "";

  bodyEl.innerHTML =
    ((modeControl || statusActions) ? `<div class="wo-controls">${modeControl}${statusActions}</div>` : "") +
    `<div class="wo-details">${detailsViewHtml(detail)}</div>` +
    (sup ? detailsEditorHtml(detail) : "") +
    `<details class="wo-section-card wo-notes-section">
       <summary class="wo-section-summary">Notes</summary>
       <div class="wo-section-content">
         <div class="wo-notes-log" aria-label="Work order note log">${notesLogContentsHtml(detail.notes)}</div>
         <textarea class="wo-notes-input" rows="4" aria-label="Add a work order note" placeholder="Add a note…"></textarea>
         <div class="wo-notes-actions">
           <button type="button" data-action="save-notes">Save note</button>
         </div>
         <p class="wo-notes-message" aria-live="polite"></p>
       </div>
     </details>` +
    `<details class="wo-section-card wo-materials-section">
       <summary class="wo-section-summary">Materials</summary>
       <div class="wo-section-content">
         <div class="wo-items">${items}</div>
         ${materialsTotalHtml(detail)}
         <div class="wo-add-item">
           <div class="wo-add-item-row">
             <input type="text" class="ms-item-search" placeholder="Search item by name or barcode">
             <input type="number" class="wo-item-qty" placeholder="Qty" min="0" step="any">
             <button type="button" data-action="add-item">Add</button>
           </div>
           <div class="ms-item-results scan-chooser" hidden></div>
         </div>
       </div>
     </details>` +
    (sup || assignedToCurrentUser ? laborSectionHtml(detail) : "") +
    `<p class="wo-message"></p>`;
}

function renderLineHtml(it) {
  const modeTag = `<span class="wo-line-mode wo-line-mode-${escapeHtml(it.mode)}">${escapeHtml(modeLabel(it.mode))}</span>`;
  const actions = isSupervisorPlus()
    ? `<div class="wo-item-actions">
         <input type="number" class="wo-line-qty" value="${escapeHtml(it.quantity)}" min="0" step="any" aria-label="Quantity">
         <button type="button" class="secondary-btn" data-action="edit-item">Update</button>
         <button type="button" class="btn-danger" data-action="remove-item">Remove</button>
       </div>`
    : `<span class="hint">Quantity: ${escapeHtml(it.quantity)}</span>`;
  return `<div class="wo-item" data-wo-item-id="${escapeHtml(it.id)}">
            <div class="wo-item-head">
              <span class="ms-item-name">${escapeHtml(it.item_name)}</span>
              <span class="ms-item-barcode">${escapeHtml(it.item_barcode)}</span>
              ${modeTag}
              <span class="wo-onhand">On hand: ${escapeHtml(it.item_quantity)}</span>
              ${lineChargeHtml(it)}
            </div>
            ${actions}
          </div>`;
}

async function refreshCard(cardEl, reopenSelector = null) {
  const body = cardEl.querySelector(".wo-body");
  await openDetail(cardEl.dataset.id, body, cardEl);
  if (reopenSelector) {
    const section = cardEl.querySelector(reopenSelector);
    if (section) section.open = true;
  }
}

// --- add-material search (input delegation) ------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
  if (input.classList.contains("wo-tech-search")) {
    renderTechnicianSearch(input);
    return;
  }
  if (!input.classList.contains("ms-item-search")) return;
  const container = input.closest(".wo-add-item");
  const results = container.querySelector(".ms-item-results");
  delete container.dataset.itemId;
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = filterRanked(
    allItems,
    (it) => [it.name, it.barcode],
    q
  ).slice(0, 8);
  // No match means the catalogue has no row for what they typed, so offer to
  // report it. The work order travels with the request: fulfilling it later
  // logs the material back onto this job retroactively.
  const cardEl = input.closest(".wo-card");
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-action="pick-item" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>` +
      itemRequestPromptHtml({
        searchedText: input.value.trim(),
        workOrderId: cardEl ? cardEl.dataset.id : null,
        source: "work_orders",
      });
  results.hidden = false;
});

// --- actions (click delegation) ------------------------------------------

listEl.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;

  if (action === "pick-item") {
    const container = btn.closest(".wo-add-item");
    container.dataset.itemId = btn.dataset.itemId;
    container.querySelector(".ms-item-search").value = btn.dataset.itemName;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    container.querySelector(".wo-item-qty").focus();
    return;
  }

  if (action === "pick-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    const technicianId = btn.dataset.technicianId;
    if (!list.querySelector(`[data-technician-id="${technicianId}"]`)) {
      list.querySelector(".wo-tech-empty")?.remove();
      list.insertAdjacentHTML(
        "beforeend",
        technicianSelectionHtml(technicianId, btn.dataset.technicianName)
      );
    }
    const input = picker.querySelector(".wo-tech-search");
    input.value = "";
    closeTechnicianResults(picker);
    input.focus();
    return;
  }

  if (action === "remove-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    btn.closest(".wo-tech-selected-row")?.remove();
    if (!list.querySelector(".wo-tech-selected-row")) {
      list.innerHTML = emptyTechnicianSelectionHtml();
    }
    picker.querySelector(".wo-tech-search")?.focus();
    return;
  }

  if (action === "toggle-combo") {
    const combo = btn.closest(".wo-combo");
    const list = combo.querySelector(".wo-combo-list");
    const opening = list.hidden;
    // Only one open at a time -- picking in one shouldn't leave another
    // combo's listbox stranded open behind it.
    listEl.querySelectorAll(".wo-combo").forEach((other) => {
      if (other !== combo) closeCombo(other);
    });
    list.hidden = !opening;
    btn.setAttribute("aria-expanded", String(opening));
    return;
  }

  if (action === "pick-combo-option") {
    const combo = btn.closest(".wo-combo");
    const nativeSelect = combo.querySelector(".wo-combo-native");
    const label = combo.querySelector(".wo-combo-trigger-label");
    nativeSelect.value = btn.dataset.value;
    label.textContent = btn.textContent;
    combo.querySelectorAll(".wo-combo-option").forEach((opt) => {
      opt.setAttribute("aria-selected", String(opt === btn));
    });
    closeCombo(combo);
    combo.querySelector(".wo-combo-trigger")?.focus();
    return;
  }

  if (action === "back-to-work-orders") {
    // Above the `.wo-card` lookup below: this control lives in the list but
    // outside any card, so the `if (!cardEl) return` guard would swallow it.
    if (window.history.state?.solo) {
      // We pushed this entry. Unwinding it keeps Back and Forward agreeing
      // with the button; `popstate` does the actual restore.
      window.history.back();
    } else {
      // A cold deep link: there is no entry of ours to pop, and calling
      // back() would leave the app. loadWorkOrders normalizes the URL itself
      // (exitSolo).
      void loadWorkOrders();
    }
    return;
  }

  if (action === "open-netfacilities-wo") {
    // Placeholder pending real NetFacilities integration on this button --
    // same destination the domain layer's work_order_task_fallback generates
    // (app/domain/work_orders.py) for an imported task with no real one yet.
    const url = `https://system.netfacilities.com/tools/viewworkorders/${encodeURIComponent(btn.dataset.number)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "start-tracking-wo") {
      await apiStartWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "stop-tracking-wo") {
      const stopped = await apiStopWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
      // Stopping the last clock on a job moves it On-Hold by itself. Without
      // saying so, the badge changing on its own reads as something going
      // wrong. Chosen from the refreshed row, so the message and the server
      // cannot disagree. Re-queried after the refresh: renderBody replaced the
      // old element.
      if (stopped?.status === "on_hold") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Work stopped. Nobody is charging, so this is now On-Hold.",
          "success"
        );
      }
    } else if (action === "notify-supervisor-wo") {
      let finished;
      try {
        finished = await apiCompleteWorkOrder(workOrderId);
      } catch (err) {
        // A co-worker's clock is still running: this is not a failure to
        // report inline, it's a rule the tapper needs to act on -- go find
        // that person -- so it gets the same pop-up treatment as the other
        // hard stop above rather than the quiet inline .wo-message text.
        if (
          err?.status === 400 &&
          err.detail === "All Users must Stop Charging before a Supervisor can be notified."
        ) {
          await messageDialog(err.detail);
          return;
        }
        throw err;
      }
      await refreshCard(cardEl);
      // A Technician's finish lands Ready to Complete, so the badge that
      // appears a moment later would otherwise read as a failed save. Chosen
      // from the row the server returned rather than from the role.
      if (finished?.status === "ready_to_complete") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Sent to your supervisor for review.",
          "success"
        );
      }
    } else if (action === "send-back-wo") {
      // Rejection means "go finish the job", so the crew is live again rather
      // than paused -- which keeps On-Hold meaning purely "nobody is on it".
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "hold-assigned-wo") {
      await apiHoldWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "resume-assigned-wo") {
      await apiResumeWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "complete-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "completed" });
      await refreshCard(cardEl);
    } else if (action === "review-wo") {
      if (!(await confirmDialog("Are you sure this work order is ready for Review?"))) return;
      await apiUpdateWorkOrder(workOrderId, { status: "review" });
      await refreshCard(cardEl);
    } else if (action === "reopen-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "archive-wo") {
      if (!(await confirmDialog(
        "Archive this work order? It will leave the active list and can be restored from History."
      ))) return;
      await apiArchiveWorkOrder(workOrderId);
      await loadWorkOrders();
    } else if (action === "cancel-edit") {
      // Re-fetch to throw away drafts and return the Edit details card to its
      // default collapsed state with the saved values restored.
      await refreshCard(cardEl);
    } else if (action === "save-details") {
      const body = cardEl.querySelector(".wo-body");
      // Only the fields the editor actually rendered: the legacy
      // community/building/unit inputs are absent on an imported work order,
      // and sending them as null would wipe values the editor never showed.
      const value = (selector) => {
        const el = body.querySelector(selector);
        return el ? el.value.trim() || null : undefined;
      };
      const patch = {
        status: value(".wo-edit-status"),
        location: value(".wo-edit-location"),
        service_type: value(".wo-edit-service-type"),
        schedule_date: value(".wo-edit-schedule-date"),
        output_to: value(".wo-edit-output-to"),
        vendor_assignee: value(".wo-edit-vendor"),
        description: value(".wo-edit-description"),
        priority: value(".wo-edit-priority"),
        supervisor_id: body.querySelector(".wo-edit-supervisor")?.value || null,
        expected_supervisor_id:
          body.querySelector(".wo-edit")?.dataset.originalSupervisorId || null,
        assigned_to_ids: Array.from(body.querySelectorAll(".wo-tech-selected-row")).map(
          (row) => row.dataset.technicianId
        ),
      };
      Object.keys(patch).forEach((k) => patch[k] === undefined && delete patch[k]);
      await apiUpdateWorkOrder(workOrderId, patch);
      await refreshCard(cardEl);
    } else if (action === "save-notes") {
      const notesInput = cardEl.querySelector(".wo-notes-input");
      const notesMessage = cardEl.querySelector(".wo-notes-message");
      const notes = notesInput.value.trim() || null;
      setMessage(notesMessage, "", "");
      if (!notes) {
        setMessage(notesMessage, "Enter a note before saving.", "error");
        return;
      }
      const updated = await apiUpdateWorkOrder(workOrderId, { notes });
      notesInput.value = "";
      const notesLog = cardEl.querySelector(".wo-notes-log");
      if (notesLog) notesLog.innerHTML = notesLogContentsHtml(updated.notes);
      setMessage(notesMessage, "Note saved.", "success");
      const notesSection = cardEl.querySelector(".wo-notes-section");
      if (notesSection) notesSection.open = false;
    } else if (action === "add-labor") {
      const section = btn.closest(".wo-labor-section");
      const technicianId = section.querySelector(".wo-labor-technician")?.value;
      const minutes = hoursToMinutes(section.querySelector(".wo-new-labor-hours")?.value);
      if (!technicianId) {
        setMessage(msg, "Assign and select a technician first.", "error");
        return;
      }
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiAddWorkOrderLabor(workOrderId, { technicianId, minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "edit-labor") {
      const row = btn.closest(".wo-labor-entry");
      const minutes = hoursToMinutes(row.querySelector(".wo-labor-hours")?.value);
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderLabor(workOrderId, row.dataset.laborId, { minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "remove-labor") {
      const row = btn.closest(".wo-labor-entry");
      if (!(await confirmDialog("Remove this labor entry from the work order?"))) return;
      await apiDeleteWorkOrderLabor(workOrderId, row.dataset.laborId);
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "add-item") {
      const container = btn.closest(".wo-add-item");
      const itemId = container.dataset.itemId;
      const qty = parseFloat(container.querySelector(".wo-item-qty").value);
      if (!itemId) {
        setMessage(msg, "Search and pick an item first.", "error");
        return;
      }
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      const addedLine = await apiAddWorkOrderItem(workOrderId, { itemId, quantity: qty });
      await refreshCard(cardEl, ".wo-materials-section");
      const refreshedMessage = cardEl.querySelector(".wo-message");
      if (Number(addedLine.item_quantity) < 0) {
        setMessage(refreshedMessage, "Item added. Please re-count stock.", "error");
      } else {
        setMessage(refreshedMessage, "Item added.", "success");
      }
    } else if (action === "edit-item") {
      const row = btn.closest(".wo-item");
      const qty = parseFloat(row.querySelector(".wo-line-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderItem(workOrderId, row.dataset.woItemId, { quantity: qty });
      await refreshCard(cardEl, ".wo-materials-section");
    } else if (action === "remove-item") {
      const row = btn.closest(".wo-item");
      if (!(await confirmDialog("Remove this material from the work order?"))) return;
      await apiDeleteWorkOrderItem(workOrderId, row.dataset.woItemId);
      await refreshCard(cardEl, ".wo-materials-section");
    }
  } catch (err) {
    if (
      err?.status === 409 &&
      typeof err.detail === "string" &&
      err.detail.startsWith("This Work Order was already assigned to ")
    ) {
      await messageDialog(err.detail);
      window.location.reload();
      return;
    }
    if (msg) setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
});

listEl.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (event.target.classList.contains("wo-tech-search")) {
    closeTechnicianResults(event.target.closest(".wo-tech-picker"));
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) closeCombo(combo);
});

listEl.addEventListener("focusout", (event) => {
  const picker = event.target.closest(".wo-tech-picker");
  if (picker) {
    setTimeout(() => {
      if (!picker.contains(document.activeElement)) closeTechnicianResults(picker);
    }, 0);
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) {
    setTimeout(() => {
      if (!combo.contains(document.activeElement)) closeCombo(combo);
    }, 0);
  }
});

// --- Inline line-billing editor (Admin/Owner) ----------------------------
//
// The editor UI is shared with History (`views/billingEditor.js`); here we
// just supply the line's numbers and how to persist the change, then refresh
// the card. The "Edit charge" button only renders for those who may see cost,
// so no extra role check is needed.
listEl.addEventListener("click", (event) => {
  const editBtn = event.target.closest(".wo-edit-charge-btn");
  if (!editBtn) return;

  const cell = editBtn.closest(".wo-line-charge");
  const row = editBtn.closest(".wo-item");
  const cardEl = editBtn.closest(".wo-card");
  if (!cell || !row || !cardEl) return;

  const workOrderId = cardEl.dataset.id;
  const woItemId = row.dataset.woItemId;
  openBillingEditor(cell, {
    quantity: Number(cell.dataset.quantity),
    billable: Number(cell.dataset.billable),
    onSave: async (value) => {
      await apiSetWorkOrderItemBilling(workOrderId, woItemId, value);
      await refreshCard(cardEl, ".wo-materials-section");  // repaint the card (line charge + total)
    },
  });
});

// Mode select change.
listEl.addEventListener("change", async (event) => {
  const sel = event.target;
  if (!sel.classList.contains("wo-mode-select")) return;
  const cardEl = sel.closest(".wo-card");
  if (!cardEl) return;
  const msg = cardEl.querySelector(".wo-message");
  try {
    await apiUpdateWorkOrder(cardEl.dataset.id, { entry_mode: sel.value });
    if (msg) setMessage(msg, `New entries will be ${modeLabel(sel.value).toLowerCase()}.`, "success");
  } catch (err) {
    if (msg) setMessage(msg, friendlyError(err, "Could not switch mode."), "error");
  }
});

// --- In-app manual NetFacilities authentication and enrichment (Admin+) ---

const NETFACILITIES_ACTIVE_AUTH_STATES = new Set([
  "starting",
  "awaiting_confirmation",
  "confirming",
]);
// Capability states in which the card keeps refreshing on its own, so that
// auto-confirm, a saved CSV, and a closed window show up without a click.
const NETFACILITIES_LIVE_STATES = new Set(["authenticating", "signed_in"]);
const NETFACILITIES_SESSION_POLL_MS = 3000;

function updateNetFacilitiesControls(capability) {
  const authentication = capability && capability.latest_authentication;
  const authActive = Boolean(
    authentication && NETFACILITIES_ACTIVE_AUTH_STATES.has(authentication.state),
  );
  // "Window open" is read from the attempt, not the capability, so that an
  // `expired` capability with the window still open (a live job lost auth)
  // offers Close instead of a second Log in.
  const windowSignedIn = Boolean(authentication && authentication.state === "signed_in");
  const windowOpen = authActive || windowSignedIn;
  const signedIn = Boolean(capability && capability.state === "signed_in");
  const available = Boolean(capability && capability.available);
  const interactiveAuthentication = Boolean(
    capability && capability.interactive_authentication_available,
  );
  const enrichmentRunning = Boolean(capability && capability.state === "running");
  const hasCsv = Boolean(authentication && authentication.last_download_filename);

  if (netFacilitiesSignInBtn) {
    const hide = !available || !interactiveAuthentication || windowOpen || enrichmentRunning;
    netFacilitiesSignInBtn.hidden = hide;
    netFacilitiesSignInBtn.disabled = hide;
    netFacilitiesSignInBtn.textContent = capability && capability.state === "ready"
      ? "Log in again"
      : "Log in to NetFacilities";
  }
  if (netFacilitiesConfirmBtn) {
    netFacilitiesConfirmBtn.hidden = !authActive;
    netFacilitiesConfirmBtn.disabled = !authentication
      || authentication.state !== "awaiting_confirmation";
  }
  if (netFacilitiesCancelBtn) {
    netFacilitiesCancelBtn.hidden = !windowOpen;
    netFacilitiesCancelBtn.disabled = !authentication
      || authentication.state === "confirming"
      || enrichmentRunning;
  }
  if (netFacilitiesImportDownloadBtn) {
    netFacilitiesImportDownloadBtn.hidden = !(signedIn && hasCsv);
    netFacilitiesImportDownloadBtn.disabled = enrichmentRunning
      || Boolean(netFacilitiesPollingJobId);
  }
  if (netFacilitiesEnrichBtn) {
    netFacilitiesEnrichBtn.hidden = !available;
    netFacilitiesEnrichBtn.disabled = !capability
      || !(capability.state === "ready" || signedIn)
      || Boolean(netFacilitiesPollingJobId);
  }
}

function netFacilitiesReauthenticationAction() {
  return netFacilitiesCapability
    && netFacilitiesCapability.interactive_authentication_available
    ? "Log in again"
    : "Refresh the saved authentication secret and redeploy";
}

function netFacilitiesCountsMessage(job) {
  const counts = job && job.counts;
  if (!counts) return "NetFacilities enrichment did not return result counts.";
  return [
    `checked ${counts.fetched} of ${counts.candidates} candidate${counts.candidates === 1 ? "" : "s"}`,
    `${counts.descriptions_updated} Task/Symptom updated`,
    `${counts.priorities_updated} Priority updated`,
    `${counts.unchanged} unchanged`,
    `${counts.not_found} not found`,
    `${counts.permission_denied} permission denied`,
    `${counts.other_failures} other failure${counts.other_failures === 1 ? "" : "s"}`,
  ].join(" · ");
}

// Pure: one job snapshot -> the line the card shows and its message kind.
// Split from the renderer so the signed-in view can prefix a job result to
// its own guidance in a single status line.
function describeNetFacilitiesJob(job) {
  if (job.state === "queued" || job.state === "running") {
    const currentRequest = job.current_work_order_number
      ? ` Currently requesting work order ${job.current_work_order_number}.`
      : "";
    return { text: `Seeking Task/Symptom and Priority in NetFacilities…${currentRequest}`, kind: "" };
  }
  if (job.state === "completed") {
    return { text: `NetFacilities enrichment completed: ${netFacilitiesCountsMessage(job)}.`, kind: "success" };
  }
  if (job.state === "authentication_required") {
    return {
      text: `NetFacilities authentication is missing or expired. ${netFacilitiesReauthenticationAction()}, then click Import Tasks and Priority.`,
      kind: "error",
    };
  }
  if (job.state === "timed_out") {
    return { text: `NetFacilities enrichment timed out with partial results: ${netFacilitiesCountsMessage(job)}.`, kind: "error" };
  }
  if (job.state === "cancelled") {
    return { text: "NetFacilities enrichment stopped when the local app shut down.", kind: "error" };
  }
  return {
    text: "NetFacilities enrichment failed without changing unapproved work-order fields. Try again or log in again.",
    kind: "error",
  };
}

function renderNetFacilitiesJob(job) {
  if (!job || !netFacilitiesStatus) return;
  const described = describeNetFacilitiesJob(job);
  setMessage(netFacilitiesStatus, described.text, described.kind);
}

// The signed-in status line: the latest job's result, if it ran in this
// session, followed by what to do next in the open window.
function renderNetFacilitiesSignedIn(capability) {
  const job = capability.latest_job;
  const authentication = capability.latest_authentication;
  const parts = [];
  let kind = "success";
  const jobFinished = job && job.state !== "queued" && job.state !== "running";
  const jobIsFromThisSession = jobFinished
    && job.finished_at && authentication && authentication.signed_in_at
    && new Date(job.finished_at) >= new Date(authentication.signed_in_at);
  if (jobIsFromThisSession) {
    const described = describeNetFacilitiesJob(job);
    parts.push(described.text);
    kind = described.kind || kind;
  }
  if (authentication && authentication.last_download_filename) {
    parts.push(`Saved ${authentication.last_download_filename} to your Downloads folder. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.`);
  } else {
    parts.push("NetFacilities is open and logged in. Export the work-order CSV in that window; it is saved to your Downloads folder and can be imported from here.");
  }
  setMessage(netFacilitiesStatus, parts.join(" "), kind);
}

async function pollNetFacilitiesJob(jobId) {
  if (!jobId || netFacilitiesPollingJobId === jobId) return;
  netFacilitiesPollingJobId = jobId;
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    while (netFacilitiesPollingJobId === jobId) {
      const job = await apiGetNetFacilitiesEnrichment(jobId);
      renderNetFacilitiesJob(job);
      if (job.state !== "queued" && job.state !== "running") {
        if (job.state === "completed" || job.state === "timed_out") {
          usersLoaded = false;
          filterOptionsLoaded = false;
          await loadWorkOrders();
        }
        await refreshNetFacilitiesSession({ preserveJobResult: true });
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not check NetFacilities enrichment progress."), "error");
    }
  } finally {
    if (netFacilitiesPollingJobId === jobId) netFacilitiesPollingJobId = null;
    updateNetFacilitiesControls(netFacilitiesCapability);
  }
}

async function refreshNetFacilitiesSession({ preserveJobResult = false } = {}) {
  if (!isAdminPlus() || !netFacilitiesStatus) return null;
  try {
    const capability = await apiGetNetFacilitiesSession();
    netFacilitiesCapability = capability;
    updateNetFacilitiesControls(capability);
    const job = capability.latest_job;
    const jobActive = job && (job.state === "queued" || job.state === "running");
    if (jobActive) {
      renderNetFacilitiesJob(job);
      void pollNetFacilitiesJob(job.job_id);
    } else if (capability.state === "signed_in") {
      renderNetFacilitiesSignedIn(capability);
    } else if (preserveJobResult && job) {
      renderNetFacilitiesJob(job);
    } else if (capability.state === "authenticating") {
      setMessage(netFacilitiesStatus, "Log in to NetFacilities in the window that opened. This page will notice when you're in.", "");
    } else if (capability.state === "ready") {
      setMessage(netFacilitiesStatus, "Saved NetFacilities login is ready. Choose a downloaded CSV to import it and seek Task/Symptom and Priority, or log in to export a fresh one.", "success");
    } else if (capability.state === "not_authenticated" || capability.state === "expired") {
      setMessage(netFacilitiesStatus, `${capability.message} Then export and import the CSV, or use Import Tasks and Priority to retry existing rows.`, "error");
    } else {
      setMessage(netFacilitiesStatus, `${capability.message} CSV import still works normally.`, "");
    }
    if (NETFACILITIES_LIVE_STATES.has(capability.state)) ensureNetFacilitiesSessionPolling();
    return capability;
  } catch (err) {
    netFacilitiesCapability = null;
    updateNetFacilitiesControls(null);
    setMessage(netFacilitiesStatus, friendlyError(err, "NetFacilities status is unavailable. CSV import still works normally."), "error");
    return null;
  }
}

// Keep the card current while the window is open. One loop at a time; it
// ends on its own when the session leaves the live states. Skips a tick
// while the tab is hidden or the 1-second job poll is already refreshing.
function ensureNetFacilitiesSessionPolling() {
  if (netFacilitiesSessionPolling) return;
  netFacilitiesSessionPolling = true;
  void (async () => {
    try {
      while (netFacilitiesCapability && NETFACILITIES_LIVE_STATES.has(netFacilitiesCapability.state)) {
        await new Promise((resolve) => setTimeout(resolve, NETFACILITIES_SESSION_POLL_MS));
        if (document.hidden || netFacilitiesPollingJobId) continue;
        await refreshNetFacilitiesSession();
      }
    } finally {
      netFacilitiesSessionPolling = false;
    }
  })();
}

async function runNetFacilitiesEnrichment() {
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    const job = await apiStartNetFacilitiesEnrichment();
    renderNetFacilitiesJob(job);
    await pollNetFacilitiesJob(job.job_id);
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, `Could not start NetFacilities enrichment. ${netFacilitiesReauthenticationAction()}, then try again.`), "error");
    }
    await refreshNetFacilitiesSession({ preserveJobResult: true });
  } finally {
    updateNetFacilitiesControls(netFacilitiesCapability);
  }
}

async function startNetFacilitiesAuthentication() {
  if (netFacilitiesSignInBtn) netFacilitiesSignInBtn.disabled = true;
  try {
    await apiStartNetFacilitiesAuthentication();
    await refreshNetFacilitiesSession();
  } catch (err) {
    await refreshNetFacilitiesSession({ preserveJobResult: true });
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not open NetFacilities sign-in."), "error");
  }
}

async function confirmNetFacilitiesAuthentication() {
  if (netFacilitiesConfirmBtn) netFacilitiesConfirmBtn.disabled = true;
  try {
    await apiConfirmNetFacilitiesAuthentication();
    await refreshNetFacilitiesSession();
  } catch (err) {
    await refreshNetFacilitiesSession({ preserveJobResult: true });
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not confirm NetFacilities sign-in."), "error");
  }
}

async function cancelNetFacilitiesAuthentication() {
  if (netFacilitiesCancelBtn) netFacilitiesCancelBtn.disabled = true;
  try {
    await apiCancelNetFacilitiesAuthentication();
    await refreshNetFacilitiesSession();
  } catch (err) {
    await refreshNetFacilitiesSession({ preserveJobResult: true });
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not cancel NetFacilities sign-in."), "error");
  }
}

if (netFacilitiesSignInBtn) {
  netFacilitiesSignInBtn.addEventListener("click", startNetFacilitiesAuthentication);
}
if (netFacilitiesConfirmBtn) {
  netFacilitiesConfirmBtn.addEventListener("click", confirmNetFacilitiesAuthentication);
}
if (netFacilitiesCancelBtn) {
  netFacilitiesCancelBtn.addEventListener("click", cancelNetFacilitiesAuthentication);
}

if (netFacilitiesEnrichBtn) {
  netFacilitiesEnrichBtn.addEventListener("click", runNetFacilitiesEnrichment);
}

// --- Per-user NetFacilities cloud sign-in (Admin+, spec D2, D3, D7) -------
//
// Independent of the local flow above: any authorized user, on any device,
// signs into NetFacilities through a Steel cloud browser instead of the
// owner's Windows machine. Only rendered when the backend reports the
// capability as available (NETFACILITIES_CLOUD_AUTH_ENABLED and its
// prerequisites -- see cloud_config.py).

let netFacilitiesCloudPollTimer = null;

async function refreshNetFacilitiesCloudSession() {
  let capability;
  try {
    capability = await apiGetNetFacilitiesCloudSession();
  } catch {
    capability = null;
  }
  updateNetFacilitiesCloudControls(capability);
  return capability;
}

function updateNetFacilitiesCloudControls(capability) {
  const available = Boolean(capability && capability.available);
  const cloudStatus = capability && capability.status;
  const awaitingSignIn = Boolean(cloudStatus && cloudStatus.state === "awaiting_sign_in");
  const signedIn = Boolean(cloudStatus && cloudStatus.state === "signed_in");
  const hasCsv = signedIn && Boolean(cloudStatus.last_download_filename);

  if (netFacilitiesCloudSignInBtn) {
    netFacilitiesCloudSignInBtn.hidden = !available || awaitingSignIn || signedIn;
  }
  if (netFacilitiesCloudCancelBtn) {
    netFacilitiesCloudCancelBtn.hidden = !(awaitingSignIn || signedIn);
  }
  if (netFacilitiesCloudImportDownloadBtn) {
    netFacilitiesCloudImportDownloadBtn.hidden = !hasCsv;
  }

  const shouldPoll = available && (awaitingSignIn || signedIn);
  if (shouldPoll && !netFacilitiesCloudPollTimer) {
    netFacilitiesCloudPollTimer = setInterval(
      refreshNetFacilitiesCloudSession,
      NETFACILITIES_SESSION_POLL_MS,
    );
  } else if (!shouldPoll && netFacilitiesCloudPollTimer) {
    clearInterval(netFacilitiesCloudPollTimer);
    netFacilitiesCloudPollTimer = null;
  }
}

async function startNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = true;
  try {
    const status = await apiStartNetFacilitiesCloudAuthentication();
    if (status && status.live_view_url) {
      window.open(status.live_view_url, "_blank", "noopener");
    }
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not open a NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function cancelNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = true;
  try {
    await apiCancelNetFacilitiesCloudAuthentication();
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not close the NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function importNetFacilitiesCloudDownload() {
  if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    const r = await apiImportNetFacilitiesCloudDownload();
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
  } finally {
    await refreshNetFacilitiesCloudSession();
  }
}

if (netFacilitiesCloudSignInBtn) {
  netFacilitiesCloudSignInBtn.addEventListener("click", startNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudCancelBtn) {
  netFacilitiesCloudCancelBtn.addEventListener("click", cancelNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudImportDownloadBtn) {
  netFacilitiesCloudImportDownloadBtn.addEventListener("click", importNetFacilitiesCloudDownload);
}

// --- CSV import (Admin+) --------------------------------------------------

// How many work orders the import added, and how many of those the CSV's
// `ASSIGNED TO` name routed to a supervisor on its own. `supervisors_matched`
// counts new work orders only, so the match count never exceeds `created`.
function importSummary(r) {
  if (!r.created) return "No new work orders.";
  const noun = r.created === 1 ? "new work order" : "new work orders";
  return `${r.created} ${noun} · ${r.supervisors_matched} with a supervisor name match.`;
}

// Everything that follows a successful import, whether the CSV was uploaded
// or captured from the live window: summary, list reload, then enrichment
// through whichever session is available (the open window or saved state).
async function afterWorkOrderImport(r) {
  // Only the new work orders are worth reporting: re-imported numbers keep
  // their own routing, and rows the import passed over changed nothing.
  setMessage(importMessage, importSummary(r), "success");
  // Reset caches so a re-import reflects fresh data, then reload the list.
  usersLoaded = false;
  filterOptionsLoaded = false;
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesSession();
  if (capability && (capability.state === "ready" || capability.state === "signed_in")) {
    await runNetFacilitiesEnrichment();
  }
}

async function handleImport() {
  const file = importFile.files && importFile.files[0];
  if (!file) return;
  setMessage(importMessage, "Importing…", "");
  importBtn.disabled = true;
  try {
    const r = await apiImportWorkOrders(file);
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import that file."), "error");
  } finally {
    importBtn.disabled = false;
    importFile.value = "";  // allow re-selecting the same file
  }
}

async function importNetFacilitiesDownload() {
  if (netFacilitiesImportDownloadBtn) netFacilitiesImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    const r = await apiImportNetFacilitiesDownload();
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
    updateNetFacilitiesControls(netFacilitiesCapability);
  }
}

if (importBtn) importBtn.addEventListener("click", () => importFile && importFile.click());
if (importFile) importFile.addEventListener("change", handleImport);
if (netFacilitiesImportDownloadBtn) {
  netFacilitiesImportDownloadBtn.addEventListener("click", importNetFacilitiesDownload);
}

// --- CSV export (Admin+) --------------------------------------------------

// Label for the status the export dropdown is set to, for the result message.
function exportScopeLabel(scope) {
  const option = exportScope && [...exportScope.options].find(o => o.value === scope);
  return option ? option.textContent : scope;
}

async function downloadExport({ scope, variant, filters = {}, button, messageEl, label }) {
  setMessage(messageEl, "Preparing export…", "");
  if (button) button.disabled = true;
  try {
    const { blob, filename } = await apiExportWorkOrders(scope, { variant, filters });
    // An empty scope still returns a header-only file; say so rather than
    // handing over a CSV that looks broken.
    const headerOnly = blob.size > 0 && (await blob.text()).trim().split("\n").length <= 1;
    // Anchor + object URL is the only way to name a downloaded blob; revoke on
    // the next tick so the click has already consumed the URL.
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setMessage(
      messageEl,
      headerOnly
        ? `No work orders matched ${label} — downloaded an empty file.`
        : `Exported ${label} to ${filename}.`,
      headerOnly ? "" : "success",
    );
  } catch (err) {
    setMessage(messageEl, friendlyError(err, "Could not export work orders."), "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function handleFilteredExport() {
  const filters = currentFilters();
  await downloadExport({
    scope: filters.status || "all",
    variant: "full",
    filters,
    button: exportBtn,
    messageEl: exportMessage,
    label: "the current Work Orders filters",
  });
}

async function handleClientExport() {
  const scope = exportScope ? exportScope.value : "all";
  await downloadExport({
    scope,
    variant: "client",
    button: exportClientBtn,
    messageEl: importMessage,
    label: `${exportScopeLabel(scope)} client receipts`,
  });
}

if (exportBtn) exportBtn.addEventListener("click", handleFilteredExport);
if (exportClientBtn) exportClientBtn.addEventListener("click", handleClientExport);

// --- filter / search controls --------------------------------------------

// #16: search live-updates as you type (250 ms debounce), matching the
// History work-order filter so the two sibling pages behave the same way.
// The Search button and Enter stay as redundant explicit triggers -- nothing
// is removed, so no one loses the click-to-search workflow.
let woSearchDebounce = null;
function runWorkOrderNumberSearch() {
  loadWorkOrders({ checkArchivedSearch: true });
}

if (searchBtn) searchBtn.addEventListener("click", runWorkOrderNumberSearch);
if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(woSearchDebounce);
    woSearchDebounce = setTimeout(runWorkOrderNumberSearch, 250);
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(woSearchDebounce);
      runWorkOrderNumberSearch();
    }
  });
}
[statusFilter, serviceTypeFilter, priorityFilter, priorityLevelFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
  if (!control) return;
  control.addEventListener("change", () => {
    showAll = false;
    loadWorkOrders();
  });
});

if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener("click", () => {
    clearTimeout(woSearchDebounce);
    resetFilterControls();
    showAll = false;
    loadWorkOrders();
  });
}

// Status invalidations for the card list. Like Admin Review, this refreshes only
// while its own page is active -- an inactive page needs no dirty flag because
// nav.js already performs a fresh REST load on entry (static/views/nav.js:154).
//
// An event for a work order that is not on screen is ignored. Chasing it with a
// list refetch would mean every technician's client reloading the whole list
// every time anyone changed a status anywhere. A work order newly *appearing*
// for someone is a membership change, which arrives as a null id instead.
subscribe(STATUS_CHANGED_EVENT, ({ activePage, envelope, reason }) => {
  if (activePage !== WORK_ORDERS_PAGE) return;
  if (!listEl) return;

  // A null id is a membership command (restore) and a reconnect means events
  // were missed while the socket was down. Both mean "the list itself may be
  // wrong", which only a refetch can settle -- deciding locally would duplicate
  // the server's ordering, row cap and filter semantics.
  if (reason === "reconnect" || !envelope?.id) {
    runOrDeferListRefresh();
    return;
  }

  const cardEl = listEl.querySelector(`details.wo-card[data-id="${envelope.id}"]`);
  if (!cardEl) return;
  if (isHeld(cardEl)) {
    // Catch up when the editor closes rather than yanking input away mid-edit.
    cardEl.dataset.missedUpdate = "1";
    return;
  }
  return refreshCardSummary(cardEl);
});

// `toggle` does not bubble, so this listens in the capture phase -- a delegated
// bubble-phase listener here would silently never fire.
if (listEl) {
  listEl.addEventListener(
    "toggle",
    () => {
      if (deferredListRefresh && !anyCardHeld()) {
        // Route through the single function that knows a socket-driven
        // refresh must be silent -- do not duplicate its background flag here.
        runOrDeferListRefresh();
        return;
      }

      const cards = Array.from(listEl.querySelectorAll("details.wo-card"));
      for (const cardEl of cards) {
        if (cardEl.dataset.missedUpdate !== "1" || isHeld(cardEl)) continue;
        delete cardEl.dataset.missedUpdate;
        void refreshCardSummary(cardEl);
      }
    },
    true
  );
}

// Browser Back/Forward between the list and a card page. The card page is the
// SPA's only routed URL, so this handles both directions itself.
//
// The active-page check reads the DOM rather than importing `getActivePage`
// from nav.js: nav.js already imports this module, and the cycle is not worth
// one boolean. Popstate while some other page is showing is ignored -- the
// stale URL is harmless and `exitSolo` normalizes it on the next list render.
window.addEventListener("popstate", () => {
  if (!listEl) return;
  const workOrdersPage = document.getElementById("work-orders-page");
  if (!workOrdersPage?.classList.contains("active")) return;

  const number = soloNumberFromPath();
  if (number === null) {
    if (!soloActive) return;
    void loadWorkOrders();  // exits solo mode itself
    return;
  }
  if (soloActive && number === soloNumber) return;
  void openWorkOrderPageByNumber(number);
});
