// Work Orders: a save someone else beat you to (W3).
//
// Layer: beside workOrderActions.js. A protected save that the server refuses
// with 409 `field_conflict` lands here: the card's kept message line
// (`#wo-sec-msg`, `data-live-keep`, so a live patch leaves it alone) names who
// changed what and how long ago, and offers Keep theirs / Save mine. Each save
// path supplies what those two mean for its own fields.

import { formatUserName } from "../format.js";
import { setComboValue } from "../menus.js";
import { emptyTechnicianSelectionHtml, technicianSelectionHtml } from "./workOrderCardHtml.js";
import { isDirty } from "./workOrderLiveBody.js";
import { getAllTechnicians } from "./workOrderReferenceData.js";

const pending = new WeakMap();
const ages = new Intl.RelativeTimeFormat("en", { numeric: "always" });

export function isFieldConflict(err) {
  return err?.status === 409 && err.detail?.code === "field_conflict";
}

// The server sends the age (a phone's clock may be wrong); this only words it.
export function conflictAge(seconds) {
  if (seconds < 60) return ages.format(-seconds, "second");
  if (seconds < 3600) return ages.format(-Math.floor(seconds / 60), "minute");
  if (seconds < 86400) return ages.format(-Math.floor(seconds / 3600), "hour");
  return ages.format(-Math.floor(seconds / 86400), "day");
}

export function conflictSentence({ label, current_label: value, changed_by: who, seconds_ago: seconds }) {
  if (seconds === null || seconds === undefined) return `Someone else changed ${label} to ${value}.`;
  if (!who) return `${label} was changed to ${value} ${conflictAge(seconds)}.`;
  return `${who} changed ${label} to ${value} ${conflictAge(seconds)}.`;
}

// Static markup (no data in it): the action audit reads these data-action
// literals, and a live patch never touches the kept line they sit in.
const ACTIONS_HTML =
  `<button type="button" id="wo-act-keep-theirs" data-action="keep-theirs-wo">Keep theirs</button>` +
  `<button type="button" id="wo-act-save-mine" data-action="save-mine-wo">Save mine</button>`;

// `keep(conflicts)` / `retry(conflicts)` come from the save path. Without them
// (a draft replayed on reconnect) the sentence shows alone.
export function showConflict(cardEl, conflicts, { keep, retry } = {}) {
  const msg = cardEl.querySelector("#wo-sec-msg");
  if (!msg) return;
  const text = document.createElement("span");
  text.className = "wo-conflict-text";
  text.textContent = conflicts.map(conflictSentence).join(" ");
  msg.replaceChildren(text);
  msg.className = "error";
  if (!keep || !retry) {
    pending.delete(cardEl);
    return;
  }
  const actions = document.createElement("div");
  actions.className = "wo-conflict-actions";
  actions.innerHTML = ACTIONS_HTML;
  msg.append(actions);
  pending.set(cardEl, { conflicts, keep, retry });
}

// One choice per conflict message: the entry is taken on the first tap, so a
// double tap cannot send twice.
export async function resolveConflict(cardEl, choice) {
  const entry = pending.get(cardEl);
  if (!entry) return;
  pending.delete(cardEl);
  const msg = cardEl.querySelector("#wo-sec-msg");
  msg?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  if (msg) {
    msg.replaceChildren();
    msg.className = "";
  }
  if (choice === "keep") entry.keep(entry.conflicts);
  else await entry.retry(entry.conflicts);
}

// --- Edit details ----------------------------------------------------------

// Free-text fields: the input's own rendered value is what the person saw.
const TEXT_FIELDS = {
  location: ".wo-edit-location",
  service_type: ".wo-edit-service-type",
  schedule_date: ".wo-edit-schedule-date",
  output_to: ".wo-edit-output-to",
  vendor_assignee: ".wo-edit-vendor",
  description: ".wo-edit-description",
  priority: ".wo-edit-priority",
};
// Combos: dirty against the select's own rendered default, but the expected
// value is the row's real one from `.wo-edit` -- a status with no option of its
// own (Ready to Complete) renders its first option as the default.
const SELECT_FIELDS = {
  status: [".wo-edit-status", "originalStatus"],
  supervisor_id: [".wo-edit-supervisor", "originalSupervisorId"],
};
const CREW = "assigned_to_ids";
// Every editor field the save reads (bodyLiveCensus.test.js holds the editor to it).
export const DETAIL_FIELD_SELECTORS = [
  ...Object.values(TEXT_FIELDS), ...Object.values(SELECT_FIELDS).map(([selector]) => selector),
];

const crewIds = (bodyEl) => [...bodyEl.querySelectorAll(".wo-tech-selected-row")].map((row) => row.dataset.technicianId);
const splitIds = (text) => (text ? text.split(",") : []);
const sameSet = (a, b) => a.length === b.length && a.every((id) => b.includes(id));

// The fields the person changed, each with the value it showed (rules 7-8);
// null when nothing changed.
export function detailsPatch(bodyEl) {
  const edit = bodyEl.querySelector(".wo-edit");
  if (!edit) return null;
  const patch = {};
  const expected = {};
  for (const [field, selector] of Object.entries(TEXT_FIELDS)) {
    const el = bodyEl.querySelector(selector);
    if (!el || !isDirty(el)) continue;
    patch[field] = el.value.trim() || null;
    expected[field] = el.defaultValue.trim() || null;
  }
  for (const [field, [selector, attr]] of Object.entries(SELECT_FIELDS)) {
    const el = bodyEl.querySelector(selector);
    if (!el || !isDirty(el)) continue;
    patch[field] = el.value || null;
    expected[field] = edit.dataset[attr] || null;
  }
  const crew = crewIds(bodyEl);
  const originalCrew = splitIds(edit.dataset.originalCrew);
  if (bodyEl.querySelector(".wo-tech-picker") && !sameSet(crew, originalCrew)) {
    patch[CREW] = crew;
    expected[CREW] = originalCrew;
  }
  return Object.keys(patch).length ? { ...patch, expected } : null;
}

// Keep theirs: each conflicting field takes the current value as both what it
// shows and what it was drawn with, so it is no longer a change of the person's.
export function keepDetails(bodyEl, conflicts) {
  const edit = bodyEl.querySelector(".wo-edit");
  for (const { field, current } of conflicts) {
    if (TEXT_FIELDS[field]) {
      const el = bodyEl.querySelector(TEXT_FIELDS[field]);
      if (!el) continue;
      el.defaultValue = current ?? "";
      el.value = current ?? "";
      el.classList.remove("wo-field-conflict");
    } else if (SELECT_FIELDS[field]) {
      const [selector, attr] = SELECT_FIELDS[field];
      const el = bodyEl.querySelector(selector);
      if (!el) continue;
      const value = current ?? "";
      const match = [...el.options].some((o) => o.value === value);
      // ponytail: a current value the menu cannot offer leaves the select on
      // its rendered default (not dirty); the next save sends nothing for it.
      if (match) [...el.options].forEach((o) => { o.defaultSelected = o.value === value; });
      const target = match ? value : ([...el.options].find((o) => o.defaultSelected) || el.options[0])?.value ?? "";
      setComboValue(el.closest("[data-menu]"), target);
      edit.dataset[attr] = value;
    } else if (field === CREW) {
      const ids = current || [];
      const list = bodyEl.querySelector(".wo-tech-selected-list");
      if (list) {
        list.innerHTML = ids.length
          ? ids.map((id) => {
            const tech = getAllTechnicians().find((t) => t.id === id);
            return technicianSelectionHtml(id, tech ? formatUserName(tech) : "Assigned technician");
          }).join("")
          : emptyTechnicianSelectionHtml();
      }
      edit.dataset.originalCrew = ids.join(",");
    }
  }
}

// The value each conflict says the row holds now, keyed by field: Save mine's
// new expected values.
export const currentValues = (conflicts) => Object.fromEntries(conflicts.map((c) => [c.field, c.current]));
