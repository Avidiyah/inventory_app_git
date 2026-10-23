// Work Orders: presenters.
//
// Layer: leaf of the Work Orders module group. Pure formatting and role
// predicates -- status and priority badges, money and minutes, place meta,
// assignment questions. No DOM refs, no fetches, no state of its own: every
// function here answers from its arguments plus the current session.

import { escapeHtml, formatMoney } from "../format.js";
import { getCurrentUser, getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { CLOCK_GLYPH, WARNING_GLYPH, statusGlyph } from "./workOrderGlyphs.js";

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

// Hand-keying, editing and removing anyone's hours is Team Lead and above
// (mirrors the server's `_require_labor_editor`). Everyone else's hours come
// from Begin and Stop Charging.
export function canKeyLabor() {
  return roleAtLeast(getRole(), "supervisor");
}

// 2026-10-16 self-edit, mirroring `_require_labor_editor`: anyone else may
// revise or remove only their own hand-entered row from the open week...
export function canEditLaborEntry(entry) {
  if (canKeyLabor()) return true;
  return Boolean(entry.hand_entered && entry.week_open && entry.technician_id === getCurrentUser()?.id);
}

// ...and add labor only for themselves, while on the crew.
export function canAddLabor(detail) {
  return canKeyLabor() || isAssignedToCurrentUser(detail);
}

// A Technician who is not on a work order's crew can read it but not write to
// it -- notes, materials, requests, the sign-off. Begin Charging adds them.
// Every other role is never locked. Mirrors the server's
// `require_crew_for_technician`.
export function isCrewLocked(detail) {
  return getRole() === "technician" && !isAssignedToCurrentUser(detail);
}

// The one hint a locked card shows in place of its input controls. Begin
// Charging is only on offer while the work is unfinished (the server's start
// statuses), so a finished work order says why it stays read-only instead.
const BEGIN_CHARGING_STATUSES = ["created", "assigned", "in_progress", "on_hold"];
export function crewLockHtml(detail) {
  if (!isCrewLocked(detail)) return "";
  const text = BEGIN_CHARGING_STATUSES.includes(detail.status)
    ? "Begin Charging to add notes, materials, requests, or a signature."
    : "You are not on this work order's crew, so it is read-only for you.";
  return `<p class="hint wo-crew-lock">${escapeHtml(text)}</p>`;
}

// Someone else has already worked this order and the caller has not: the card
// warns, and (with notes to read) Begin Charging waits for "I've read the
// notes". Mirrors the server's `require_prior_work_acknowledged`, which
// enforces it; `detail.prior_work` is null for anyone who has worked here.
export function hasUnreadPriorWork(detail) {
  return Boolean(detail.prior_work) && String(detail.notes || "").trim() !== "";
}

export function priorWorkBannerHtml(detail) {
  const prior = detail.prior_work;
  if (!prior) return "";
  const when = new Date(prior.last_at);
  const stamp = Number.isNaN(when.getTime())
    ? ""
    : ` Last activity ${when.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}.`;
  const action = hasUnreadPriorWork(detail)
    ? "Check the notes before charging."
    : "There are no notes to read.";
  return `<div class="wo-prior-work" role="status"><strong>Someone has been here.</strong> ` +
    `${escapeHtml(action)} <span class="hint">${escapeHtml(prior.by.join(", "))}.${escapeHtml(stamp)}</span></div>`;
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

// One hue per status (the `--wo-status-*` token, shared with the card
// outline) plus a glyph, so a status never rests on color alone. The glyph is
// aria-hidden; the label is what screen readers and textContent read.
export function statusBadge(status) {
  return `<span class="wo-status wo-status-${escapeHtml(status)}">${statusGlyph(status)}${escapeHtml(statusLabel(status))}</span>`;
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

// Only the buckets that ask someone to act get a filled tag and the warning
// glyph; routine priority renders as a quiet outline (styles.css).
const ATTENTION_BUCKETS = new Set(["emergency", "urgent", "high"]);

export function priorityBadge(card) {
  const label = card.priority || "No priority";
  const glyph = ATTENTION_BUCKETS.has(priorityBucket(card.priority)) ? WARNING_GLYPH : "";
  return `<span class="${priorityBadgeClass(card)}">${glyph}${escapeHtml(label)}</span>`;
}

// `schedule_date` is raw import text. Mirrors domain/work_orders.py
// parse_schedule_date: leading M/D/YYYY (vendor, 2-digit years are 20xx) or
// YYYY-M-D (hand edits), optionally followed by a time. Returns a comparable
// YYYYMMDD number, or null for blank / malformed / impossible dates.
export function scheduleDayKey(value) {
  const raw = String(value || "").trim();
  let parts = /^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})(?:\s|$)/.exec(raw);
  let year, month, day;
  if (parts) {
    [month, day, year] = parts.slice(1).map(Number);
    if (year < 100) year += 2000;
  } else {
    parts = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s|$)/.exec(raw);
    if (!parts) return null;
    [year, month, day] = parts.slice(1).map(Number);
  }
  const probe = new Date(year, month - 1, day);
  if (probe.getFullYear() !== year || probe.getMonth() !== month - 1 || probe.getDate() !== day) return null;
  return year * 10000 + month * 100 + day;
}

// Scheduled before today (browser-local) and still open. Shares
// SETTLED_STATUSES with urgentFireActive so a job that stops burning also
// stops being overdue.
export function isOverdue(card, now = new Date()) {
  const key = scheduleDayKey(card.schedule_date);
  if (key === null || SETTLED_STATUSES.has(card.status)) return false;
  return key < now.getFullYear() * 10000 + (now.getMonth() + 1) * 100 + now.getDate();
}

export function overdueTag(card) {
  return isOverdue(card) ? `<span class="wo-tag-overdue">${CLOCK_GLYPH}Overdue</span>` : "";
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

// Review is a deliberate second-person handoff, Admin and Owner only: they may
// review any work order they are not working. Supervisors stop at Completed.
export function canCurrentUserSendToReview(detail) {
  const user = getCurrentUser();
  if (!user || isAssignedToCurrentUser(detail)) return false;
  return roleAtLeast(user.role, "admin");
}
