// Work Orders: status actions.
//
// Layer: HTML builders for the expanded card's controls row, above
// workOrderCardHtml.js (which calls them) and below nothing that fetches. The
// status-action ladder is split into three tiers so each state shows exactly
// one filled red button -- the lifecycle's next step -- with the other
// workflow buttons as secondary and the Admin+ tools in a trailing group.
// Labels, `data-action`s and who sees what are unchanged; only class and order
// are decided here. The click handlers live in workOrderActions.js.

import { escapeHtml } from "../format.js";
import { getRole } from "../state.js";
import { DOT_GLYPH } from "./workOrderGlyphs.js";
import {
  canCurrentUserSendToReview,
  isAdminPlus,
  isAssignedToCurrentUser,
  isSupervisorPlus,
} from "./workOrderPresenters.js";

// Written out literally, one per tier used: the action-coverage audit greps
// `data-action="..."` out of the source, so the names must appear verbatim.
const BTN = {
  begin: '<button type="button" data-action="start-tracking-wo">W.O. Received, Begin Charging</button>',
  completePrimary: '<button type="button" data-action="complete-wo">Mark Completed</button>',
  completeSecondary: '<button type="button" class="secondary-btn" data-action="complete-wo">Mark Completed</button>',
  notify: '<button type="button" data-action="notify-supervisor-wo">Notify Supervisor</button>',
  stop: '<button type="button" class="secondary-btn" data-action="stop-tracking-wo">Stop Charging</button>',
  hold: '<button type="button" class="secondary-btn" data-action="hold-assigned-wo">Place On-Hold</button>',
  resume: '<button type="button" class="secondary-btn" data-action="resume-assigned-wo">Resume In-Progress</button>',
  approve: '<button type="button" data-action="complete-wo">Approve — Mark Completed</button>',
  sendBack: '<button type="button" class="secondary-btn" data-action="send-back-wo">Send Back</button>',
  review: '<button type="button" data-action="review-wo">Send to Review</button>',
  reopen: '<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>',
};

// Returns `{ primary, secondary, tools }` HTML strings, any of which may be
// empty. `primary` holds at most one filled button.
export function statusActionsHtml(detail) {
  const sup = isSupervisorPlus();
  const assigned = isAssignedToCurrentUser(detail);
  // Whoever may hold a clock on this row: assigned workers, plus a Supervisor+
  // on any work order they can see (they need not be on the crew to do the
  // work and record it).
  const canTrack = assigned || sup;
  const tracking = Boolean(detail.active_labor_session);
  let primary = "";
  let secondary = "";

  if (canTrack && (detail.status === "created" || detail.status === "assigned")) {
    // "Set In-Progress" is gone: that transition is a side effect of starting
    // work, which is what the button always meant.
    primary = BTN.begin;
  } else if (canTrack && detail.status === "in_progress") {
    // Notify Supervisor is the "I'm done" button and belongs to a Technician
    // with a clock running; Stop Charging is the "I'm pausing" one. /complete
    // and /hold both require assignment server-side, so an unassigned
    // supervisor who is only charging gets neither -- they close the row out
    // with Mark Completed. A Supervisor+ never gets Notify Supervisor: Mark
    // Completed is the real completion action for them.
    if (!tracking) {
      primary = BTN.begin;
    } else if (sup) {
      primary = BTN.completePrimary;
    } else if (assigned) {
      primary = BTN.notify;
    }
    if (tracking) secondary += BTN.stop;
    if (assigned) secondary += BTN.hold;
    if (sup && !tracking) secondary += BTN.completeSecondary;
  } else if (detail.status === "on_hold" && canTrack) {
    // Begin Charging is the one a returning technician taps: it does the same
    // transition as Resume *and* starts the clock. Resume stays for work that
    // resumes without the tapper being the one doing it.
    primary = BTN.begin;
    if (assigned) secondary += BTN.resume;
    if (sup) {
      secondary += BTN.completeSecondary;
      secondary += `<span class="hint wo-status-note">On-Hold — nobody is charging time. A supervisor can also resume or roll back this work order in the Edit details card.</span>`;
    }
  } else if (detail.status === "ready_to_complete") {
    // The first review gate: one supervisor confirming the work happened.
    // Distinct from Send to Review, which is the later Admin handoff.
    if (sup) {
      primary = BTN.approve;
      secondary = BTN.sendBack;
    } else {
      secondary = `<span class="hint wo-status-note">Sent to your supervisor for review.</span>`;
    }
  } else if (detail.status === "completed") {
    if (canCurrentUserSendToReview(detail)) {
      primary = BTN.review;
    } else if (getRole() === "techfm_oa") {
      // A TechFM OA holds the rest of the Admin toolkit, so a missing button
      // reads as a bug to them rather than as a rule. Show it, disabled, with
      // the reason. The server refuses the transition either way
      // (services/work_orders._require_review_handoff_permission), and a
      // disabled button fires no click.
      primary = `<button type="button" data-action="review-wo" disabled title="An Admin or the Owner must send this to Review.">Send to Review</button>`;
    }
    if (sup) secondary += BTN.reopen;
  } else if (sup && detail.status === "review") {
    primary = `<span class="wo-review-ready">Ready for Admin Review</span>`;
    secondary = BTN.reopen;
  }

  const tools = isAdminPlus()
    ? `<button type="button" class="secondary-btn wo-netfacilities-btn" data-action="open-netfacilities-wo" data-number="${escapeHtml(detail.number)}">Open Netfacilities</button>` +
      `<button type="button" class="btn-danger" data-action="archive-wo">Archive</button>`
    : "";
  return { primary, secondary, tools };
}

// "Charging since 9:14 AM" above the controls whenever this caller's own clock
// is running on the row. Static: it repaints with the card, no timer.
export function chargingStripHtml(detail) {
  const session = detail.active_labor_session;
  if (!session) return "";
  const started = new Date(session.started_at);
  const time = Number.isNaN(started.getTime())
    ? ""
    : ` since ${started.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  return `<div class="wo-charging-strip" role="status">${DOT_GLYPH}<span>Charging${escapeHtml(time)}</span></div>`;
}
