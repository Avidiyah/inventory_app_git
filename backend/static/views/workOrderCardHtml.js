// Work Orders: card HTML.
//
// Layer: every HTML string a work-order card is built from -- the summary row,
// the detail view and its editor, the labor section, the technician picker and
// the combo control -- plus the open/close helpers for the two widgets whose
// markup only this module writes. Builders only: nothing here fetches, and the
// listeners that act on these strings live in workOrderActions.js.

import {
  escapeHtml,
  formatMoney,
  formatUserName,
  filterRanked,
  safeHttpUrl,
} from "../format.js";
import { tipHtml } from "../tooltip.js";
import { getCurrentUser, getRole } from "../state.js";
import {
  assignedIds,
  assignedNames,
  canCurrentUserSendToReview,
  canEditLabor,
  formatMinutes,
  hoursInputValue,
  isAdminPlus,
  isAssignedToCurrentUser,
  isSupervisorPlus,
  laborSummaryHtml,
  lineChargeHtml,
  materialsTotalHtml,
  modeLabel,
  notesLogContentsHtml,
  placeMeta,
  priorityBadge,
  statusBadge,
  statusLabel,
} from "./workOrderPresenters.js";
import { getAllSupervisors, getAllTechnicians } from "./workOrderReferenceData.js";
import { livePriorityValues } from "./workOrderFilters.js";

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

export function technicianSelectionHtml(id, name) {
  return `<div class="wo-tech-selected-row" data-technician-id="${escapeHtml(id)}">
            <span class="wo-tech-selected-name">${escapeHtml(name)}</span>
            <button type="button" class="secondary-btn wo-tech-remove" data-action="remove-technician" aria-label="Remove ${escapeHtml(name)}">Remove</button>
          </div>`;
}

export function emptyTechnicianSelectionHtml() {
  return `<p class="hint wo-tech-empty">No technicians assigned.</p>`;
}

function technicianPickerHtml(detail) {
  const ids = assignedIds(detail);
  const names = assignedNames(detail);
  const resultsId = `wo-tech-results-${detail.id}`;
  const selections = ids
    .map((id, index) => {
      const activeTechnician = getAllTechnicians().find((technician) => technician.id === id);
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

export function closeTechnicianResults(picker) {
  const results = picker?.querySelector(".wo-tech-results");
  const input = picker?.querySelector(".wo-tech-search");
  if (results) {
    results.hidden = true;
    results.innerHTML = "";
  }
  if (input) input.setAttribute("aria-expanded", "false");
}

export function renderTechnicianSearch(input) {
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
  const technicians = getAllTechnicians();
  const selectable = technicians
    .map((technician) => ({ technician, name: formatUserName(technician) }))
    .filter(({ technician }) => !selectedIds.has(technician.id));
  const matches = filterRanked(
    selectable,
    (entry) => [entry.name],
    query,
    (left, right) => left.name.localeCompare(right.name)
  ).slice(0, 8);

  if (!technicians.length) {
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
    getAllSupervisors()
      .map(
        (s) =>
          `<option value="${escapeHtml(s.id)}"${s.id === selectedId ? " selected" : ""}>${escapeHtml(formatUserName(s))}</option>`
      )
      .join("")
  );
}

function supervisorChoices() {
  return [{ value: "", label: "Unassigned" }].concat(
    getAllSupervisors().map((s) => ({ value: s.id, label: formatUserName(s) }))
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

export function closeCombo(combo) {
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

// Priority is vendor text everywhere except here: Urgent is the one level a
// person assigns by hand, and it is what makes a card pulse. Suggesting it
// beside the levels already in use makes it a choice rather than a spelling
// somebody has to remember -- a `datalist` rather than a `select`, because
// closing the field would make a level the vendor adds later unsettable.
const MANUAL_PRIORITY = "Urgent";

function priorityEditField(detail) {
  const live = livePriorityValues();
  const suggestions = live.some((value) => value.toLowerCase() === MANUAL_PRIORITY.toLowerCase())
    ? live
    : [MANUAL_PRIORITY, ...live];
  const listId = `wo-priority-options-${detail.id}`;
  return `<label class="wo-edit-field">
            <span>Priority</span>
            <input type="text" class="wo-edit-priority" list="${escapeHtml(listId)}" value="${escapeHtml(detail.priority || "")}">
            <datalist id="${escapeHtml(listId)}">${suggestions
              .map((value) => `<option value="${escapeHtml(value)}"></option>`)
              .join("")}</datalist>
            <small class="hint">Urgent is assigned here by hand -- it makes the card pulse until the level changes.</small>
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
      priorityEditField(detail) +
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

// The summary line of a work-order card. Shared by the initial render and the
// real-time single-card update, so the two projections cannot drift. Accepts a
// WorkOrderDetail as well: the schema subclasses WorkOrderCard, so a detail
// response carries every field this reads.
export function summaryHtml(card) {
  const place = placeMeta(card);
  const technicianNames = assignedNames(card);
  const assignee = technicianNames.length
    ? ` · ${escapeHtml(technicianNames.join(", "))}`
    : "";
  const legacyTag = card.legacy ? `<span class="wo-legacy-tag">Legacy</span>` : "";
  return (
    `<span class="wo-title">WO ${escapeHtml(card.number)}</span>` +
    statusBadge(card.status) +
    priorityBadge(card) +
    legacyTag +
    `<span class="wo-meta">${place ? escapeHtml(place) + " · " : ""}${card.item_count} items${assignee}</span>`
  );
}

export function renderBody(detail, bodyEl) {
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
         <div class="wo-requested-lines"></div>
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
    `<details class="wo-section-card wo-request-section">
       <summary class="wo-section-summary">Request</summary>
       <div class="wo-section-content"></div>
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
