// Work Orders: the live card body.
//
// Layer: above workOrderCardHtml.js. A socket-driven update patches an open
// card body in place and leaves alone whatever the user has typed, picked or
// opened. The patcher pairs elements by id; the builders give every element
// it may keep an id (bodyLiveCensus.test.js holds them to that).
//
// Not for a repaint after the user's own save: that one rebuilds the body, so
// the saved field comes back empty.

import { setMessage } from "../dom.js";
import { morphInto } from "../morph.js";
import { renderBody, showWorkOrderTab, syncWorkOrderTabs } from "./workOrderCardHtml.js";

// Entry rows whose fields act together: kept or updated as one unit.
export const LIVE_FORMS = ".wo-add-item, .wo-add-labor";
// Server rows (a material line, a labor entry or an SMR line).
export const LIVE_ROWS = ".wo-item, .wo-labor-entry";
// A field that saves the moment it changes, so it always follows the server.
export const SAVES_ON_CHANGE = ".wo-mode-select";

const FIELDS = "input, select, textarea";
const ACTION_TEXT = "#wo-sec-actions, .wo-smr-ready";
const SETTLE_MS = 500;
const DROPPED = "This work order changed while you were typing. Something you entered no longer applies.";
const CONFLICT = "Someone else changed a value you are editing. Saving yours will replace theirs.";
const settledAt = new WeakMap();

// The value a field had when it was drawn. A select with no `selected`
// option shows its first, so that one is its default (not a typed value).
function defaultOf(field) {
  if (field.localName === "select") {
    const options = [...field.options];
    return (options.find((o) => o.defaultSelected) || options[0])?.value ?? "";
  }
  if (field.type === "checkbox" || field.type === "radio") return String(field.defaultChecked);
  return field.defaultValue;
}

export function isDirty(field) {
  if (field.type === "checkbox" || field.type === "radio") return field.checked !== field.defaultChecked;
  return field.value !== defaultOf(field);
}

// An entry form the user has started: focused, typed in, or holding a pick
// (an item, a material request, or the SMR line being edited).
export function isTouched(form, active = document.activeElement) {
  const { itemId, materialRequestId, lineId } = form.dataset;
  return form.contains(active) || [...form.querySelectorAll(FIELDS)].some(isDirty) ||
    Boolean(itemId || materialRequestId || lineId);
}

export function actionsSettling(cardEl) {
  const at = settledAt.get(cardEl);
  return at !== undefined && Date.now() - at < SETTLE_MS;
}

const actionText = (bodyEl) => [...bodyEl.querySelectorAll(ACTION_TEXT)].map((el) => el.textContent).join("\n");
const notesText = (bodyEl) => bodyEl.querySelector(".wo-notes-log")?.textContent ?? "";

function selectionOf(el) {
  try {
    return el.selectionStart === null || el.selectionStart === undefined ? null : [el.selectionStart, el.selectionEnd];
  } catch {
    return null;
  }
}

// Patch `bodyEl` to `detail` around whatever the user is in the middle of.
// `deferred` is true when something was left stale only because the user is
// on it (an open Edit details, a focused field): the caller catches it up later.
export function patchBodyLive(detail, bodyEl, cardEl) {
  const active = document.activeElement;
  const tab = bodyEl.dataset.woTab;
  const notesBefore = notesText(bodyEl);
  const actionsBefore = actionText(bodyEl);
  const caret = bodyEl.contains(active) ? selectionOf(active) : null;
  let anchor = bodyEl.contains(active) && active !== bodyEl ? active : null;
  let anchorTop = anchor?.getBoundingClientRect().top;
  for (const el of anchor ? [] : bodyEl.children) {
    const rect = el.getBoundingClientRect();
    if (rect.bottom > 0) {
      [anchor, anchorTop] = [el, rect.top];
      break;
    }
  }
  const held = [
    ...[...bodyEl.querySelectorAll(LIVE_FORMS)].filter((form) => isTouched(form, active)),
    ...[...bodyEl.querySelectorAll(FIELDS)].filter(isDirty),
  ];

  let deferred = false;
  const conflicts = [];
  const skip = (el, newEl) => {
    if (el.hasAttribute("data-live-keep")) return true;
    if (el.id === "wo-edit-card" && el.open) {
      deferred = true;
      return true;
    }
    if (el.matches(LIVE_FORMS) && isTouched(el, active)) return true;
    if (el.matches(".wo-item") && el.querySelector(".charge-cancel")) return true;
    if (!el.matches(FIELDS)) return false;
    if (el === active) {
      if (!isDirty(el)) deferred = true;
      return true;
    }
    if (!isDirty(el) || el.matches(SAVES_ON_CHANGE)) return false;
    if (newEl?.matches?.(FIELDS) && defaultOf(newEl) !== defaultOf(el)) conflicts.push(el);
    return true;
  };

  const tree = document.createElement("div");
  renderBody(detail, tree);
  morphInto(bodyEl, tree.childNodes, { skip, flashSelector: "#wo-sec-actions", flashKey: (el) => el.textContent });

  // A section the patch added open (an SMR Labor or Invoice) must not take
  // over the tab the user is reading.
  if (tab && bodyEl.querySelector(`:scope > .wo-tabs > [data-wo-tab="${tab}"]`)) showWorkOrderTab(bodyEl, tab);
  else syncWorkOrderTabs(bodyEl, { settle: true });

  // The notes gate: an acknowledgement covers only the notes it was given for.
  if (cardEl.dataset.notesAck === "1") {
    if (notesText(bodyEl) === notesBefore) {
      bodyEl.querySelectorAll('[data-action="ack-notes-wo"]').forEach((b) => { b.hidden = true; });
      bodyEl.querySelectorAll('[data-action="start-tracking-wo"]').forEach((b) => {
        b.disabled = false;
        b.removeAttribute("title");
      });
    } else {
      delete cardEl.dataset.notesAck;
    }
  }

  const msg = bodyEl.querySelector("#wo-sec-msg");
  if (held.some((el) => !el.isConnected)) {
    if (msg) setMessage(msg, DROPPED, "error");
  } else if (conflicts.length) {
    if (msg) setMessage(msg, CONFLICT, "error");
    conflicts.forEach((el) => el.classList.add("wo-field-conflict"));
  }

  // iOS Safari has no moveBefore: a moved element loses focus there.
  if (active?.isConnected && bodyEl.contains(active) && document.activeElement !== active) {
    active.focus({ preventScroll: true });
    if (caret) {
      try { active.setSelectionRange(...caret); } catch { /* not a text field */ }
    }
  }

  // Chrome and Firefox anchor scrolling themselves; a second correction jumps.
  if (!globalThis.CSS?.supports?.("overflow-anchor", "auto") && anchor?.isConnected) {
    const moved = anchor.getBoundingClientRect().top - anchorTop;
    if (moved) window.scrollBy(0, moved);
  }

  if (actionText(bodyEl) !== actionsBefore) settledAt.set(cardEl, Date.now());
  return { deferred };
}
