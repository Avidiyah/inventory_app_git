// Work Orders: presenters.
//
// Layer: leaf of the Work Orders module group. Pure formatting and role
// predicates -- status and priority badges, money and minutes, place meta,
// assignment questions. No DOM refs, no fetches, no state of its own: every
// function here answers from its arguments plus the current session.

import { escapeHtml, formatMoney } from "../format.js";
import { getCurrentUser, getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";

export function isSupervisorPlus() {
  return roleAtLeast(getRole(), "supervisor");
}

// The admin *toolkit* floor, which is TechFM OA and above. Distinct from
// `canCurrentUserSendToReview` below, which is the one control still gated on
// Admin proper.
export function isAdminPlus() {
  return roleAtLeast(getRole(), "techfm_oa");
}

// Fixed company mark-up on the line total (mirrors history.js MARKUP_RATE).
// A work-order material line is the billing unit: charge = effective billable
// units * price, where effective billable is the override when set else the
// full quantity.
export const MARKUP_RATE = 1.15;

export function effectiveBillable(it) {
  const b = it.billable_quantity;
  return (b === null || b === undefined) ? Number(it.quantity) : Number(b);
}

// The Admin/Owner-only charge cell for a material line, or "" when no price is
// visible (backend redacts `unit_price` to null below Admin, so this renders
// only for those who may see cost). Carries `data-*` so the inline editor can
// read the line quantity / current override without re-fetching.
export function lineChargeHtml(it) {
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
export function materialsTotalHtml(detail) {
  if (detail.materials_total === null || detail.materials_total === undefined) return "";
  const base = Number(detail.materials_total);
  const marked = base * MARKUP_RATE;
  return `<div class="wo-materials-total">Materials total: ` +
    `<strong>${escapeHtml(formatMoney(base))}</strong> ` +
    `<span class="charge-marked">+15%: ${escapeHtml(formatMoney(marked))}</span></div>`;
}

export function notesLogContentsHtml(notes) {
  const log = String(notes || "").trim();
  return log
    ? `<div class="wo-notes-log-text">${escapeHtml(log)}</div>`
    : `<p class="hint wo-notes-empty">No notes recorded yet.</p>`;
}

export function formatMinutes(minutes) {
  const total = Number(minutes) || 0;
  const hours = Math.floor(total / 60);
  const remainder = total % 60;
  if (!hours) return `${remainder} min`;
  if (!remainder) return `${hours} hr${hours === 1 ? "" : "s"}`;
  return `${hours} hr ${remainder} min`;
}

export function hoursInputValue(minutes) {
  return String(Math.round((Number(minutes) / 60) * 100) / 100);
}

export function hoursToMinutes(value) {
  const hours = Number(value);
  if (!Number.isFinite(hours) || hours <= 0) return null;
  return Math.max(1, Math.round(hours * 60));
}

export function laborSummaryHtml(detail) {
  const actual = formatMinutes(detail.labor_minutes || 0);
  const billed = formatMinutes(detail.labor_billed_minutes || 0);
  const charge = detail.labor_total === null || detail.labor_total === undefined
    ? ""
    : `<span class="wo-labor-charge">${escapeHtml(formatMoney(detail.labor_total))} at ${escapeHtml(formatMoney(detail.labor_rate))}/hr</span>`;
  return `<div class="wo-labor-summary"><span>Actual: <strong>${escapeHtml(actual)}</strong></span><span>Billed: <strong>${escapeHtml(billed)}</strong></span>${charge}</div>`;
}

// Supervisor+ may edit or remove any labor entry; a Technician only one
// attributed to them (their manual add/subtract self-service).
export function canEditLabor(entry) {
  if (isSupervisorPlus()) return true;
  const userId = getCurrentUser()?.id;
  return Boolean(userId && entry && entry.technician_id === userId);
}

// Supervisor+ can always add labor (crediting themselves when unassigned); a
// Technician may add their own hours once they're assigned to the job.
export function canAddLabor(detail) {
  return isSupervisorPlus() || isAssignedToCurrentUser(detail);
}

export function statusLabel(status) {
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

export function statusBadge(status) {
  return `<span class="wo-status wo-status-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

// Priority is raw NetFacilities vendor text with no fixed vocabulary (see
// normalize_priority_filter), so it's bucketed into a severity color by
// keyword rather than an exact match. Unrecognized text still displays
// as-is -- only the color falls back to neutral.
export function priorityBucket(priority) {
  if (!priority) return "none";
  const p = priority.toLowerCase();
  if (p.includes("emergency")) return "emergency";
  if (p.includes("urgent")) return "urgent";
  if (p.includes("high")) return "high";
  if (p.includes("low")) return "low";
  if (p.includes("normal") || p.includes("routine") || p.includes("standard")) return "normal";
  return "unknown";
}

// Fire is a call to act, so it stops where there is nothing left to act on.
// A Completed work order -- and the Review queue behind it -- keeps the Urgent
// pill, because the record stays true, but it no longer burns. Everything
// earlier in the lifecycle burns, `ready_to_complete` included: that status is
// the crew's handoff, not the supervisor's sign-off, and a job waiting on a
// signature is exactly the one urgency is meant to chase.
const SETTLED_STATUSES = new Set(["completed", "review"]);

// Whether this work order is currently on fire. The single predicate behind
// both the burning pill and the burning card outline, so the two can never
// disagree about one work order.
export function urgentFireActive(card) {
  return priorityBucket(card.priority) === "urgent" && !SETTLED_STATUSES.has(card.status);
}

// `wo-priority-*` is the severity color; `wo-priority-fire` is the flame layer
// on top of it. Split because they answer different questions -- the color says
// how bad it is, the fire says whether anyone still has to do something about
// it -- and a Completed urgent work order wants the first without the second.
export function priorityBadgeClass(card) {
  const fire = urgentFireActive(card) ? " wo-priority-fire" : "";
  return `wo-priority wo-priority-${priorityBucket(card.priority)}${fire}`;
}

export function priorityBadge(card) {
  const label = card.priority || "No priority";
  return `<span class="${priorityBadgeClass(card)}">${escapeHtml(label)}</span>`;
}

// The class list for one work-order card. Every place that writes a card's
// className goes through here -- the initial build, a socket-driven repaint,
// and the detail paint -- so a rewritten card cannot silently lose its fire.
export function workOrderCardClass(card) {
  const urgent = urgentFireActive(card) ? " wo-card-urgent" : "";
  return `wo-card wo-card-status-${card.status}${urgent}`;
}

export function modeLabel(mode) {
  return mode === "retroactive" ? "Retroactive" : "Dispense";
}

// Location meta string from a card/detail (any of the parts may be blank).
// Imported work orders carry a single free-text `location` instead of the older
// community/building/unit trio, so fall back to it -- otherwise an imported
// card's summary would show nothing but the item count.
export function placeMeta(c) {
  const parts = [];
  if (c.community) parts.push(c.community);
  if (c.building_number) parts.push(`Bldg ${c.building_number}`);
  if (c.unit_number) parts.push(`Unit ${c.unit_number}`);
  if (parts.length) return parts.join(" · ");
  return c.location || "";
}

export function assignedIds(detail) {
  if (Array.isArray(detail.assigned_to_ids)) return detail.assigned_to_ids;
  return detail.assigned_to_id ? [detail.assigned_to_id] : [];
}

export function assignedNames(detail) {
  if (Array.isArray(detail.assigned_to_names) && detail.assigned_to_names.length) {
    return detail.assigned_to_names;
  }
  return detail.assigned_to_name ? [detail.assigned_to_name] : [];
}

export function isAssignedToCurrentUser(detail) {
  const userId = getCurrentUser()?.id;
  return Boolean(userId && assignedIds(detail).includes(userId));
}

// Review is a deliberate second-person handoff. Admin+ may review any work
// order they are not working, while a Supervisor must be the routed supervisor
// and must not also be one of the assigned workers.
export function canCurrentUserSendToReview(detail) {
  const user = getCurrentUser();
  if (!user || isAssignedToCurrentUser(detail)) return false;
  return roleAtLeast(user.role, "admin") ||
    (user.role === "supervisor" && detail.supervisor_id === user.id);
}
