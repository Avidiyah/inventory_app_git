// View: Work Orders page.
//
// Layer: views. Owns the Work Orders page: a server-scoped list of standalone
// work orders (identity = number). Work orders are IMPORT-ONLY -- the Admin+ CSV
// import is the only way one appears; there is no create form. Admin+ can export
// the current filtered list as the operational CSV; the separate client export
// retains its scope dropdown. Admin+ Edit details includes imported metadata;
// Supervisor sees only routing, technicians, and status, and also manages labor,
// entry mode, and material corrections. Assigned Technicians/Supervisors get a
// narrow Set In-Progress -> Mark Completed walkthrough plus an In-Progress-only
// Place On-Hold action and On-Hold-only Resume In-Progress action outside the
// unchanged editor; Technicians can also save notes and add new materials.
// Admin+ can archive any live work order directly from its expanded card.
// Reached via the nav button or a Unit click in the Mass Stage tree (which calls
// `focusWorkOrder` before switching pages).

import {
  apiListWorkOrders,
  apiGetWorkOrderFilterOptions,
  apiGetWorkOrder,
  apiUpdateWorkOrder,
  apiStartWorkOrder,
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
  apiGetLegacyWorkOrderArchivePreview,
  apiArchiveLegacyWorkOrders,
  apiImportWorkOrders,
  apiExportWorkOrders,
  apiListItems,
  apiListUsers,
} from "../api.js";
import {
  escapeHtml,
  friendlyError,
  formatMoney,
  formatUserName,
  safeHttpUrl,
} from "../format.js";
import { setMessage, confirmDialog, messageDialog } from "../dom.js";
import { getCurrentUser, getRole } from "../state.js";
import {
  canBeWorkOrderSupervisor,
  canBeWorkOrderTechnician,
  roleAtLeast,
} from "../roles.js";
import { openBillingEditor } from "./billingEditor.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const statusFilter = document.getElementById("work-orders-status-filter");
const serviceTypeFilter = document.getElementById("work-orders-service-filter");
const supervisorFilter = document.getElementById("work-orders-supervisor-filter");
const communityFilter = document.getElementById("work-orders-community-filter");
const scheduledDateFilter = document.getElementById("work-orders-date-filter");
const searchInput = document.getElementById("work-orders-search");
const searchBtn = document.getElementById("work-orders-search-btn");
const clearFiltersBtn = document.getElementById("work-orders-clear-filters");
const exportMessage = document.getElementById("work-orders-export-message");
const moreEl = document.getElementById("work-orders-more");

const importSection = document.getElementById("work-orders-import-section");
const importFile = document.getElementById("wo-import-file");
const importBtn = document.getElementById("wo-import-btn");
const importMessage = document.getElementById("wo-import-message");
const exportScope = document.getElementById("wo-export-scope");
const exportBtn = document.getElementById("wo-export-btn");
const exportClientBtn = document.getElementById("wo-export-client-btn");
const archiveLegacyBtn = document.getElementById("wo-archive-legacy-btn");

// Reference lists are reused during interactions within one visit (for example,
// debounced Work Order searches), then refreshed when nav.js activates the page
// again so item and user changes made elsewhere cannot remain stale.
let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let allSupers = [];
let usersLoaded = false;
let filterOptionsLoaded = false;
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

export function focusWorkOrder(workOrderId) {
  pendingFocusId = workOrderId;
}

function isSupervisorPlus() {
  return roleAtLeast(getRole(), "supervisor");
}

function isAdminPlus() {
  return roleAtLeast(getRole(), "admin");
}

function isOwner() {
  return getRole() === "owner";
}

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
    scheduledDate: scheduledDateFilter ? scheduledDateFilter.value : "",
    q: searchInput ? searchInput.value.trim() : "",
  };
}

function hasActiveFilters() {
  return Object.values(currentFilters()).some(Boolean);
}

function resetFilterControls() {
  [statusFilter, serviceTypeFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
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
  return `<div class="wo-labor-entry" data-labor-id="${escapeHtml(entry.id)}" data-technician-id="${escapeHtml(entry.technician_id)}">
            <div><strong>${escapeHtml(entry.technician_name)}</strong><span class="hint">${escapeHtml(formatMinutes(entry.minutes))} actual</span></div>
            ${actions}
          </div>`;
}

function laborTechnicianControl(detail) {
  const ids = assignedIds(detail);
  const names = assignedNames(detail);
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
  const hasAssignments = assignedIds(detail).length > 0;
  const rateText = detail.labor_rate === null || detail.labor_rate === undefined
    ? "The combined actual time is rounded up to the next 30 minutes for billing."
    : `Labor is billed at ${formatMoney(detail.labor_rate)}/hour. The combined actual time is rounded up to the next 30 minutes.`;
  return `<details class="wo-section-card wo-labor-section">
            <summary class="wo-section-summary">Labor</summary>
            <div class="wo-section-content">
              <p class="hint">${escapeHtml(rateText)}</p>
              <div class="wo-labor-list">${entries}</div>
              ${laborSummaryHtml(detail)}
              <div class="wo-add-labor">
                ${laborTechnicianControl(detail)}
                ${hasAssignments ? `<label><span>Actual hours</span><input type="number" class="wo-new-labor-hours" min="0.01" step="0.01" placeholder="e.g. 1.25"></label><button type="button" data-action="add-labor">Add labor</button>` : ""}
              </div>
            </div>
          </details>`;
}

function statusLabel(status) {
  return {
    created: "Created",
    assigned: "Assigned",
    in_progress: "In-Progress",
    on_hold: "On-Hold",
    completed: "Completed",
    review: "Review",
  }[status] || status;
}

function statusBadge(status) {
  return `<span class="wo-status wo-status-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
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
            <div class="wo-tech-search-wrap">
              <label class="wo-tech-search-label">
                <span>Search Technicians or Supervisors</span>
                <input type="search" class="wo-tech-search" placeholder="Search by name" autocomplete="off" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="${escapeHtml(resultsId)}" aria-expanded="false">
              </label>
              <div class="wo-tech-results" id="${escapeHtml(resultsId)}" role="listbox" aria-label="Technician search results" hidden></div>
            </div>
            <div class="wo-tech-selected">
              <span class="wo-tech-selected-label">Assigned to this work order</span>
              <div class="wo-tech-selected-list" aria-live="polite">
                ${selections || emptyTechnicianSelectionHtml()}
              </div>
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
  const matches = allTechs
    .map((technician) => ({ technician, name: formatUserName(technician) }))
    .filter(
      ({ technician, name }) =>
        !selectedIds.has(technician.id) && name.toLowerCase().includes(query)
    )
    .sort((left, right) => left.name.localeCompare(right.name))
    .slice(0, 8);

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
function editableStatusOptions(detail) {
  const prework = assignedIds(detail).length ? "assigned" : "created";
  let statuses;
  if (detail.status === "on_hold") {
    // A hold does not remember which step it paused. Let the supervisor resume
    // at the appropriate non-Review step or leave it held.
    statuses = [prework, "in_progress", "on_hold", "completed"];
  } else {
    const rank = { created: 0, assigned: 1, in_progress: 2, completed: 3 }[detail.status];
    statuses = [prework, "in_progress"];
    statuses.push("on_hold");
    if (rank >= 3) statuses.push("completed");
  }
  return [...new Set(statuses)]
    .map(
      (status) =>
        `<option value="${escapeHtml(status)}"${status === detail.status ? " selected" : ""}>${escapeHtml(statusLabel(status))}</option>`
    )
    .join("");
}

function statusEditorHtml(detail) {
  if (detail.status === "review") {
    return `<label class="wo-edit-field">
              <span>Status</span>
              <input type="text" value="Review" disabled>
            </label>`;
  }
  return `<label class="wo-edit-field wo-edit-status-field">
            <span>Status</span>
            <select class="wo-edit-status">${editableStatusOptions(detail)}</select>
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
                  <select class="wo-edit-supervisor">${supervisorOptions(detail.supervisor_id || "")}</select>
                </label>
                <fieldset class="wo-edit-field wo-edit-technicians">
                  <legend>Assigned technicians</legend>
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

export async function loadWorkOrders({ refreshReferenceData = false } = {}) {
  if (refreshReferenceData || !itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = [];
    }
  }
  if ((refreshReferenceData || !usersLoaded) && isSupervisorPlus()) {
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
  if (importSection) importSection.hidden = !isAdminPlus();
  if (exportBtn) exportBtn.hidden = !isAdminPlus();
  if (archiveLegacyBtn) archiveLegacyBtn.hidden = !isOwner();

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
      const card = listEl.querySelector(`details.wo-card[data-id="${pendingFocusId}"]`);
      if (card) {
        card.open = true;
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      pendingFocusId = null;
    }
  } catch (err) {
    listEl.innerHTML = "";
    if (moreEl) {
      moreEl.hidden = true;
      moreEl.innerHTML = "";
    }
    setMessage(listMessage, friendlyError(err, "Could not load work orders."), "error");
  }
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

function buildCard(card) {
  const el = document.createElement("details");
  el.className = `wo-card wo-card-status-${card.status}`;
  el.dataset.id = card.id;

  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  const place = placeMeta(card);
  const technicianNames = assignedNames(card);
  const assignee = technicianNames.length
    ? ` · ${escapeHtml(technicianNames.join(", "))}`
    : "";
  const legacyTag = card.legacy ? `<span class="wo-legacy-tag">Legacy</span>` : "";
  summary.innerHTML =
    `<span class="wo-title">WO ${escapeHtml(card.number)}</span>` +
    statusBadge(card.status) +
    legacyTag +
    `<span class="wo-meta">${place ? escapeHtml(place) + " · " : ""}${card.item_count} items${assignee}</span>`;

  const body = document.createElement("div");
  body.className = "wo-body";
  body.innerHTML = `<p class="hint">Loading…</p>`;

  el.appendChild(summary);
  el.appendChild(body);
  el.addEventListener("toggle", () => {
    if (el.open && !el.dataset.loaded) openDetail(card.id, body, el);
  });
  return el;
}

async function openDetail(workOrderId, bodyEl, cardEl) {
  try {
    const detail = await apiGetWorkOrder(workOrderId);
    renderBody(detail, bodyEl);
    if (cardEl) {
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
    }
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this work order."))}</p>`;
  }
}

// --- detail rendering ----------------------------------------------------

function renderBody(detail, bodyEl) {
  const sup = isSupervisorPlus();
  const assignedToCurrentUser = isAssignedToCurrentUser(detail);
  const canSendToReview = canCurrentUserSendToReview(detail);
  const items =
    detail.items.map((it) => renderLineHtml(it)).join("") ||
    `<p class="hint">No materials logged yet.</p>`;

  let statusActions = "";
  if (assignedToCurrentUser && detail.status === "assigned") {
    statusActions = `<button type="button" data-action="start-wo">Set In-Progress</button>`;
  } else if (assignedToCurrentUser && detail.status === "in_progress") {
    statusActions =
      `<button type="button" data-action="complete-assigned-wo">Mark Completed</button>` +
      `<button type="button" class="secondary-btn" data-action="hold-assigned-wo">Place On-Hold</button>`;
  } else if (assignedToCurrentUser && detail.status === "on_hold") {
    statusActions = `<button type="button" data-action="resume-assigned-wo">Resume In-Progress</button>`;
  } else if (sup && detail.status === "in_progress") {
    statusActions = `<button type="button" data-action="complete-wo">Mark Completed</button>`;
  } else if (sup && detail.status === "on_hold") {
    statusActions = `<span class="hint wo-status-note">On-Hold — a supervisor can resume or roll back this work order in the Edit details card.</span>`;
  } else if (detail.status === "completed") {
    if (canSendToReview) {
      statusActions += `<button type="button" data-action="review-wo">Send to Review</button>`;
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
    statusActions += `<button type="button" class="btn-danger" data-action="archive-wo">Archive</button>`;
  }

  const modeControl = sup
    ? `<div class="wo-mode-row">
       <label>New entries:</label>
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
    (sup ? laborSectionHtml(detail) : "") +
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
  const matches = allItems
    .filter(
      (it) =>
        it.name.toLowerCase().includes(q) ||
        (it.barcode && it.barcode.toLowerCase().includes(q))
    )
    .slice(0, 8);
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-action="pick-item" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>`;
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

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "start-wo") {
      await apiStartWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "complete-assigned-wo") {
      await apiCompleteWorkOrder(workOrderId);
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
  if (event.key !== "Escape" || !event.target.classList.contains("wo-tech-search")) return;
  closeTechnicianResults(event.target.closest(".wo-tech-picker"));
});

listEl.addEventListener("focusout", (event) => {
  const picker = event.target.closest(".wo-tech-picker");
  if (!picker) return;
  setTimeout(() => {
    if (!picker.contains(document.activeElement)) closeTechnicianResults(picker);
  }, 0);
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

// --- CSV import (Admin+) --------------------------------------------------

async function handleImport() {
  const file = importFile.files && importFile.files[0];
  if (!file) return;
  setMessage(importMessage, "Importing…", "");
  importBtn.disabled = true;
  try {
    const r = await apiImportWorkOrders(file);
    const parts = [
      `Processed ${r.total} CSV row${r.total === 1 ? "" : "s"}`,
      `${r.created} new, ${r.opened} updated`,
      `${r.closed} closed work order${r.closed === 1 ? "" : "s"} ignored`,
    ];
    if (r.supervisors_matched || r.supervisors_unmatched) {
      parts.push(`${r.supervisors_matched} supervisor name matches, ${r.supervisors_unmatched} unmatched`);
    }
    if (r.skipped) parts.push(`${r.skipped} skipped (no number)`);
    setMessage(importMessage, parts.join(" · ") + ".", "success");
    // Reset caches so a re-import reflects fresh data, then reload the list.
    usersLoaded = false;
    filterOptionsLoaded = false;
    await loadWorkOrders();
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import that file."), "error");
  } finally {
    importBtn.disabled = false;
    importFile.value = "";  // allow re-selecting the same file
  }
}

if (importBtn) importBtn.addEventListener("click", () => importFile && importFile.click());
if (importFile) importFile.addEventListener("change", handleImport);

// --- Legacy work-order re-archive (Owner only) ---------------------------

async function handleArchiveLegacyWorkOrders() {
  setMessage(importMessage, "Checking legacy work orders...", "");
  archiveLegacyBtn.disabled = true;
  try {
    const preview = await apiGetLegacyWorkOrderArchivePreview();
    const count = preview.count || 0;
    setMessage(importMessage, "", "");

    if (count === 0) {
      await messageDialog("There are 0 live legacy work orders to archive.");
      return;
    }

    const noun = count === 1 ? "work order" : "work orders";
    const approved = await confirmDialog(
      `There ${count === 1 ? "is" : "are"} ${count} live legacy ${noun}. ` +
      `Re-archive ${count === 1 ? "it" : "all of them"}? ` +
      "They will leave the active list and can still be restored from History."
    );
    if (!approved) return;

    setMessage(importMessage, "Archiving legacy work orders...", "");
    const result = await apiArchiveLegacyWorkOrders();
    const archived = result.archived || 0;
    setMessage(
      importMessage,
      `Archived ${archived} legacy work order${archived === 1 ? "" : "s"}.`,
      "success"
    );
    filterOptionsLoaded = false;
    await loadWorkOrders();
  } catch (err) {
    setMessage(
      importMessage,
      friendlyError(err, "Could not archive legacy work orders."),
      "error"
    );
  } finally {
    archiveLegacyBtn.disabled = false;
  }
}

if (archiveLegacyBtn) {
  archiveLegacyBtn.addEventListener("click", handleArchiveLegacyWorkOrders);
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
if (searchBtn) searchBtn.addEventListener("click", loadWorkOrders);
if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(woSearchDebounce);
    woSearchDebounce = setTimeout(loadWorkOrders, 250);
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(woSearchDebounce);
      loadWorkOrders();
    }
  });
}
[statusFilter, serviceTypeFilter, supervisorFilter, communityFilter, scheduledDateFilter].forEach((control) => {
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
