// View: Work Orders page.
//
// Layer: views. Owns the Work Orders page: a server-scoped list of standalone
// work orders (identity = number). Work orders are IMPORT-ONLY -- the Admin+ CSV
// import is the only way one appears; there is no create form. The same Admin+
// card exports work orders back out as CSV, filtered by status (plus "all" and
// the archived/closed ones the list hides). Supervisor+ can
// edit an imported work order's fields / assignee, but only after
// clicking "Edit details" on the card (the editor stays collapsed so the card
// reads as a clean summary); any in-scope user (incl. an assigned technician) can
// switch entry mode, set pre-work jobs In-Progress, mark work completed, and
// log/edit/remove materials and save free-form Work Order notes. Only Supervisor+ can manually
// roll status back, place it On-Hold, send Completed work to Review, or reopen it.
// Closing is intentionally absent: it belongs only on the Admin Review page.
// Reached via the nav button or a Unit click in the Mass Stage tree (which calls
// `focusWorkOrder` before switching pages).

import {
  apiListWorkOrders,
  apiGetWorkOrder,
  apiUpdateWorkOrder,
  apiAddWorkOrderItem,
  apiUpdateWorkOrderItem,
  apiSetWorkOrderItemBilling,
  apiDeleteWorkOrderItem,
  apiAddWorkOrderLabor,
  apiUpdateWorkOrderLabor,
  apiDeleteWorkOrderLabor,
  apiImportWorkOrders,
  apiExportWorkOrders,
  apiListItems,
  apiListUsers,
} from "../api.js";
import { escapeHtml, friendlyError, formatMoney, formatUserName } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { getCurrentUser, getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { openBillingEditor } from "./billingEditor.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const statusFilter = document.getElementById("work-orders-status-filter");
const searchInput = document.getElementById("work-orders-search");
const searchBtn = document.getElementById("work-orders-search-btn");
const moreEl = document.getElementById("work-orders-more");

const importSection = document.getElementById("work-orders-import-section");
const importFile = document.getElementById("wo-import-file");
const importBtn = document.getElementById("wo-import-btn");
const importMessage = document.getElementById("wo-import-message");
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
document.addEventListener("user-names-updated", () => {
  allTechs = [];
  allSupers = [];
  usersLoaded = false;
});
// Work order id to expand once the list renders (set by a Mass Stage tree click).
let pendingFocusId = null;

// The default browse shows only the RECENT_LIMIT newest work orders to keep the
// page fast as the archive grows; `showAll` (flipped by the "Show all" control)
// drops the cap. A search always queries the full set, and a status-filter change
// resets back to the capped browse. See loadWorkOrders / renderMoreControl.
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

function canEditLabor(entry) {
  const user = getCurrentUser();
  return isSupervisorPlus() || Boolean(user && user.id === entry.technician_id);
}

function renderLaborEntryHtml(entry) {
  const actions = canEditLabor(entry)
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
  if (!isSupervisorPlus()) {
    return `<input type="hidden" class="wo-labor-technician" value="${escapeHtml(getCurrentUser()?.id || ids[0])}">`;
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
  return `<section class="wo-labor-section">
            <h4>Labor</h4>
            <p class="hint">${escapeHtml(rateText)}</p>
            <div class="wo-labor-list">${entries}</div>
            ${laborSummaryHtml(detail)}
            <div class="wo-add-labor">
              ${laborTechnicianControl(detail)}
              ${hasAssignments ? `<label><span>Actual hours</span><input type="number" class="wo-new-labor-hours" min="0.01" step="0.01" placeholder="e.g. 1.25"></label><button type="button" data-action="add-labor">Add labor</button>` : ""}
            </div>
          </section>`;
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

function techCheckboxes(selectedIds) {
  const selected = new Set(selectedIds || []);
  if (!allTechs.length) return `<p class="hint">No active technicians are available.</p>`;
  return allTechs
    .map(
      (t) =>
        `<label class="wo-tech-choice"><input type="checkbox" class="wo-edit-assignee" value="${escapeHtml(t.id)}"${selected.has(t.id) ? " checked" : ""}> <span>${escapeHtml(formatUserName(t))}</span></label>`
    )
    .join("");
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

// The read-only field block shown in a card body: the imported CSV fields plus
// routing, and only the ones that are actually filled in. This is the default,
// uncluttered face of a card -- the matching inputs live in the editor below,
// which stays collapsed until "Edit details" is clicked.
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
          `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`
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

// Manual status changes live inside the Supervisor+ editor. The choices never
// advance a normal lifecycle beyond its current state; On-Hold is always
// available as a pause. Created/Assigned remains one assignment-derived
// pre-work choice so the status cannot contradict the technician field.
function editableStatusOptions(detail) {
  const prework = assignedIds(detail).length ? "assigned" : "created";
  let statuses;
  if (detail.status === "on_hold") {
    // A hold does not remember which step it paused. Let the supervisor resume
    // at the appropriate non-Review step or leave it held.
    statuses = [prework, "in_progress", "on_hold", "completed"];
  } else {
    const rank = { created: 0, assigned: 1, in_progress: 2, completed: 3 }[detail.status];
    statuses = [prework];
    if (rank >= 2) statuses.push("in_progress");
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
            <small class="hint">Roll back to an earlier step or place this work order On-Hold. Created/Assigned follows technician assignment.</small>
          </label>`;
}

// The Supervisor+ editor for an imported work order's fields, rendered hidden.
// "Edit details" reveals it (see the toggle-edit action) so the card stays a
// clean read-only summary until someone deliberately asks to change something.
// The number is deliberately absent: it is the identity the CSV import matches
// on, so renaming it here would split the work order in two on the next import.
function detailsEditorHtml(detail) {
  const legacy = hasLegacyPlace(detail)
    ? editField("community", "Community", detail.community) +
      editField("building", "Building number", detail.building_number) +
      editField("unit", "Unit number", detail.unit_number)
    : "";
  return `<div class="wo-edit" hidden>
            <p class="hint">Editing the imported details for WO ${escapeHtml(detail.number)}. A re-import will not overwrite what you save here.</p>
            <div class="wo-edit-grid">
              ${editField("location", "Location", detail.location)}
              ${editField("service-type", "Service type", detail.service_type)}
              ${editField("schedule-date", "Schedule date", detail.schedule_date)}
              ${editField("output-to", "Output to", detail.output_to)}
              ${editField("vendor", "Vendor contact", detail.vendor_assignee)}
              ${legacy}
              <label class="wo-edit-field wo-edit-wide">
                <span>Symptom / task</span>
                <textarea class="wo-edit-description" rows="2">${escapeHtml(detail.description || "")}</textarea>
              </label>
              <label class="wo-edit-field">
                <span>Supervisor</span>
                <select class="wo-edit-supervisor">${supervisorOptions(detail.supervisor_id || "")}</select>
              </label>
              <fieldset class="wo-edit-field wo-edit-technicians">
                <legend>Assigned technicians</legend>
                <div class="wo-tech-choices">${techCheckboxes(assignedIds(detail))}</div>
              </fieldset>
              ${statusEditorHtml(detail)}
            </div>
            <div class="wo-edit-actions">
              <button type="button" data-action="save-details">Save details</button>
              <button type="button" class="secondary-btn" data-action="cancel-edit">Cancel</button>
            </div>
          </div>`;
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
      allTechs = users.filter((u) => u.role === "technician");
      allSupers = users.filter((u) => u.role === "supervisor");
      usersLoaded = true;
    } catch {
      allTechs = [];
      allSupers = [];
    }
  }
  if (importSection) importSection.hidden = !isAdminPlus();

  const status = statusFilter.value;
  const q = searchInput.value.trim();
  // The cap applies only to a plain browse. A search must reach the full set (so an
  // old work order stays findable); "Show all" and a pending focus-jump also need
  // the full set. Otherwise cap at the RECENT_LIMIT newest.
  const capped = !q && !showAll && !pendingFocusId;
  const limit = capped ? RECENT_LIMIT : null;
  try {
    let cards = await apiListWorkOrders({ status, q, limit });
    if (pendingFocusId && !cards.some((c) => c.id === pendingFocusId)) {
      statusFilter.value = "";
      cards = await apiListWorkOrders({ status: "", q, limit: null });
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
  if (showAll && !searchInput.value.trim()) {
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
  const items =
    detail.items.map((it) => renderLineHtml(it)).join("") ||
    `<p class="hint">No materials logged yet.</p>`;

  let statusActions = "";
  if (detail.status === "created" || detail.status === "assigned") {
    statusActions =
      `<button type="button" data-action="progress-wo">Set In-Progress</button>` +
      `<span class="hint wo-status-note">Material or labor activity also starts work automatically.</span>`;
  } else if (detail.status === "in_progress") {
    statusActions = `<button type="button" data-action="complete-wo">Mark completed</button>`;
  } else if (detail.status === "on_hold") {
    statusActions = `<span class="hint wo-status-note">On-Hold — a supervisor can resume or roll back this work order in Edit details.</span>`;
  } else if (detail.status === "completed") {
    statusActions = sup
      ? `<button type="button" data-action="review-wo">Send to Review</button>` +
        `<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>`
      : `<span class="hint wo-status-note">Completed — waiting for a supervisor to send it to Review.</span>`;
  } else if (detail.status === "review") {
    statusActions =
      `<span class="wo-review-ready">Ready for Admin Review</span>` +
      (sup ? `<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>` : "");
  }

  const modeControl =
    `<div class="wo-mode-row">
       <label>New entries:</label>
       <select class="wo-mode-select">
         <option value="dispense"${detail.entry_mode === "dispense" ? " selected" : ""}>Dispense (moves stock)</option>
         <option value="retroactive"${detail.entry_mode === "retroactive" ? " selected" : ""}>Retroactive (paper sheet, no stock)</option>
       </select>
     </div>`;

  // The imported fields are read-only by default and the editor is collapsed;
  // Supervisor+ gets an "Edit details" button that swaps one for the other, so
  // nothing but a summary is on screen until an edit is actually intended.
  const editToggle = sup
    ? `<button type="button" class="secondary-btn" data-action="toggle-edit">Edit details</button>`
    : "";

  bodyEl.innerHTML =
    `<div class="wo-controls">${modeControl}${statusActions}${editToggle}</div>` +
    `<div class="wo-details">${detailsViewHtml(detail)}</div>` +
    (sup ? detailsEditorHtml(detail) : "") +
    `<section class="wo-notes-section">
       <h4>Notes</h4>
       <textarea class="wo-notes-input" rows="4" aria-label="Work order notes" placeholder="Add notes for this work order…">${escapeHtml(detail.notes || "")}</textarea>
       <div class="wo-notes-actions">
         <button type="button" data-action="save-notes">Save notes</button>
       </div>
       <p class="wo-notes-message" aria-live="polite"></p>
     </section>` +
    `<div class="wo-items">${items}</div>` +
    materialsTotalHtml(detail) +
    `<div class="wo-add-item">
       <div class="wo-add-item-row">
         <input type="text" class="ms-item-search" placeholder="Search item by name or barcode">
         <input type="number" class="wo-item-qty" placeholder="Qty" min="0" step="any">
         <button type="button" data-action="add-item">Add</button>
       </div>
       <div class="ms-item-results scan-chooser" hidden></div>
     </div>` +
    laborSectionHtml(detail) +
    `<p class="wo-message"></p>`;
}

function renderLineHtml(it) {
  const modeTag = `<span class="wo-line-mode wo-line-mode-${escapeHtml(it.mode)}">${escapeHtml(modeLabel(it.mode))}</span>`;
  return `<div class="wo-item" data-wo-item-id="${escapeHtml(it.id)}">
            <div class="wo-item-head">
              <span class="ms-item-name">${escapeHtml(it.item_name)}</span>
              <span class="ms-item-barcode">${escapeHtml(it.item_barcode)}</span>
              ${modeTag}
              <span class="wo-onhand">On hand: ${escapeHtml(it.item_quantity)}</span>
              ${lineChargeHtml(it)}
            </div>
            <div class="wo-item-actions">
              <input type="number" class="wo-line-qty" value="${escapeHtml(it.quantity)}" min="0" step="any" aria-label="Quantity">
              <button type="button" class="secondary-btn" data-action="edit-item">Update</button>
              <button type="button" class="btn-danger" data-action="remove-item">Remove</button>
            </div>
          </div>`;
}

async function refreshCard(cardEl) {
  const body = cardEl.querySelector(".wo-body");
  await openDetail(cardEl.dataset.id, body, cardEl);
}

// Swap a card between its read-only summary and the details editor. Only one is
// on screen at a time, so opening the editor does not double the card's height.
function setEditing(cardEl, editing) {
  const editor = cardEl.querySelector(".wo-edit");
  const view = cardEl.querySelector(".wo-details");
  const toggle = cardEl.querySelector('[data-action="toggle-edit"]');
  if (!editor || !view) return;
  editor.hidden = !editing;
  view.hidden = editing;
  // "Close editor", not "Done" -- this button only hides the panel; Save is the
  // one that writes.
  if (toggle) toggle.textContent = editing ? "Close editor" : "Edit details";
  if (editing) editor.querySelector("input, textarea, select")?.focus();
}

// --- add-material search (input delegation) ------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
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

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "complete-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "completed" });
      await refreshCard(cardEl);
    } else if (action === "progress-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "review-wo") {
      if (!(await confirmDialog("Are you sure this work order is ready for Review?"))) return;
      await apiUpdateWorkOrder(workOrderId, { status: "review" });
      await refreshCard(cardEl);
    } else if (action === "reopen-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "toggle-edit") {
      setEditing(cardEl, cardEl.querySelector(".wo-edit")?.hidden !== false);
    } else if (action === "cancel-edit") {
      // Re-fetch rather than just re-hiding: the simplest way to throw away
      // whatever was typed and put the inputs back on the saved values.
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
        community: value(".wo-edit-community"),
        building_number: value(".wo-edit-building"),
        unit_number: value(".wo-edit-unit"),
        supervisor_id: body.querySelector(".wo-edit-supervisor").value || null,
        assigned_to_ids: Array.from(body.querySelectorAll(".wo-edit-assignee:checked")).map((input) => input.value),
      };
      Object.keys(patch).forEach((k) => patch[k] === undefined && delete patch[k]);
      await apiUpdateWorkOrder(workOrderId, patch);
      await refreshCard(cardEl);
    } else if (action === "save-notes") {
      const notesInput = cardEl.querySelector(".wo-notes-input");
      const notesMessage = cardEl.querySelector(".wo-notes-message");
      const notes = notesInput.value.trim() || null;
      await apiUpdateWorkOrder(workOrderId, { notes });
      notesInput.value = notes || "";
      setMessage(notesMessage, "Notes saved.", "success");
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
      await refreshCard(cardEl);
    } else if (action === "edit-labor") {
      const row = btn.closest(".wo-labor-entry");
      const minutes = hoursToMinutes(row.querySelector(".wo-labor-hours")?.value);
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderLabor(workOrderId, row.dataset.laborId, { minutes });
      await refreshCard(cardEl);
    } else if (action === "remove-labor") {
      const row = btn.closest(".wo-labor-entry");
      if (!(await confirmDialog("Remove this labor entry from the work order?"))) return;
      await apiDeleteWorkOrderLabor(workOrderId, row.dataset.laborId);
      await refreshCard(cardEl);
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
      await apiAddWorkOrderItem(workOrderId, { itemId, quantity: qty });
      await refreshCard(cardEl);
    } else if (action === "edit-item") {
      const row = btn.closest(".wo-item");
      const qty = parseFloat(row.querySelector(".wo-line-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderItem(workOrderId, row.dataset.woItemId, { quantity: qty });
      await refreshCard(cardEl);
    } else if (action === "remove-item") {
      const row = btn.closest(".wo-item");
      if (!(await confirmDialog("Remove this material from the work order?"))) return;
      await apiDeleteWorkOrderItem(workOrderId, row.dataset.woItemId);
      await refreshCard(cardEl);
    }
  } catch (err) {
    if (msg) setMessage(msg, friendlyError(err, "That action did not work."), "error");
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
      await refreshCard(cardEl);  // repaint the card (line charge + total)
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
      `Imported ${r.total} work order${r.total === 1 ? "" : "s"}`,
      `${r.created} new, ${r.opened} updated`,
    ];
    if (r.supervisors_matched || r.supervisors_unmatched) {
      parts.push(`${r.supervisors_matched} routed to a supervisor, ${r.supervisors_unmatched} unmatched`);
    }
    if (r.skipped) parts.push(`${r.skipped} skipped (no number)`);
    setMessage(importMessage, parts.join(" · ") + ".", "success");
    // Reset caches so a re-import reflects fresh data, then reload the list.
    usersLoaded = false;
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

// --- CSV export (Admin+) --------------------------------------------------

// Label for the status the export dropdown is set to, for the result message.
function exportScopeLabel(scope) {
  const option = exportScope && [...exportScope.options].find(o => o.value === scope);
  return option ? option.textContent : scope;
}

// Both export buttons share the status dropdown and this handler; `variant`
// is the only difference -- "full" is the operational, re-importable sheet and
// "client" is the billing one (number, billed totals, full receipt).
async function handleExport(variant) {
  const scope = exportScope ? exportScope.value : "all";
  const buttons = [exportBtn, exportClientBtn].filter(Boolean);
  setMessage(importMessage, "Preparing export…", "");
  buttons.forEach(button => { button.disabled = true; });
  try {
    const { blob, filename } = await apiExportWorkOrders(scope, { variant });
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
    const what = variant === "client" ? "client receipts" : "work orders";
    setMessage(
      importMessage,
      headerOnly
        ? `No work orders matched "${exportScopeLabel(scope)}" — downloaded an empty file.`
        : `Exported ${exportScopeLabel(scope)} ${what} to ${filename}.`,
      headerOnly ? "" : "success",
    );
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not export work orders."), "error");
  } finally {
    buttons.forEach(button => { button.disabled = false; });
  }
}

if (exportBtn) exportBtn.addEventListener("click", () => handleExport("full"));
if (exportClientBtn) exportClientBtn.addEventListener("click", () => handleExport("client"));

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
if (statusFilter) {
  statusFilter.addEventListener("change", () => {
    showAll = false;  // each filter view starts at the fast, capped browse
    loadWorkOrders();
  });
}
