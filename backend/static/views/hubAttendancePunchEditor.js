// View: the inline editor that opens inside an Hours drill-down row.
//
// Layer: views (no fetch). Payload in, callbacks out -- `hubTimesheetsTab.js`
// owns the request and the refetch, exactly as it owns the week load.
//
// Two time *buttons* rather than a second modal: promptTime() (dom.js, P1) is
// already the picker, and nesting it under another overlay buys nothing. The
// buttons are siblings, never inside another button -- HTML hoists a nested
// one out and silently shifts the row.
//
// An omitted field means unchanged on the wire, so an untouched end time is
// still sent here as its original value and the tab decides what changed.

import { escapeHtml } from "../format.js";
import { promptTime } from "../dom.js";

const CENTRAL_TIME_ZONE = "America/Chicago";

function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

// The day the punch belongs to, so a picked time lands on the right date --
// promptTime resolves on its `initial`'s own calendar day and never rolls
// past midnight (its module comment says why).
function anchor(date, existing) {
  if (existing) return new Date(existing);
  const noon = new Date(`${date}T12:00:00`);
  return Number.isNaN(noon.getTime()) ? new Date() : noon;
}

export function mountPunchEditor(hostEl, { punch, date, onSave, onDelete, onCancel } = {}) {
  let startedAt = punch?.started_at || null;
  let endedAt = punch?.ended_at || null;
  let busy = false;

  function render() {
    hostEl.innerHTML = `<div class="punch-editor">
      <div class="punch-editor-times">
        <button type="button" class="secondary-btn punch-editor-start">
          Start: ${escapeHtml(startedAt ? timeLabel(startedAt) : "pick")}
        </button>
        <span aria-hidden="true">–</span>
        <button type="button" class="secondary-btn punch-editor-end">
          End: ${escapeHtml(endedAt ? timeLabel(endedAt) : "pick")}
        </button>
      </div>
      <label class="punch-editor-reason-label">
        <span class="sr-only">Reason (optional)</span>
        <input type="text" class="punch-editor-reason" placeholder="Reason (optional)" maxlength="200">
      </label>
      <div class="punch-editor-actions">
        <button type="button" class="punch-editor-save">Save</button>
        ${punch ? `<button type="button" class="danger-btn punch-editor-delete">Delete</button>` : ""}
        <button type="button" class="secondary-btn punch-editor-cancel">Cancel</button>
      </div>
      <p class="punch-editor-message" aria-live="polite"></p>
    </div>`;
    wire();
  }

  function say(text) {
    const target = hostEl.querySelector(".punch-editor-message");
    if (target) target.textContent = text;
  }

  function reason() {
    return hostEl.querySelector(".punch-editor-reason")?.value.trim() || "";
  }

  async function run(work) {
    if (busy) return;
    busy = true;
    hostEl.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      await work();
    } finally {
      busy = false;
    }
  }

  async function pick(which) {
    const current = which === "start" ? startedAt : endedAt;
    const chosen = await promptTime({
      title: which === "start" ? "Punch in at" : "Punch out at",
      help: "Central time, on this day.",
      initial: anchor(date, current),
    });
    if (!chosen) return;
    const value = chosen.toISOString();
    if (which === "start") startedAt = value; else endedAt = value;
    const label = hostEl.querySelector(`.punch-editor-${which}`);
    if (label) {
      label.textContent = `${which === "start" ? "Start" : "End"}: ${timeLabel(value)}`;
    }
    say("");
  }

  function wire() {
    hostEl.querySelector(".punch-editor-start")
      ?.addEventListener("click", () => void pick("start"));
    hostEl.querySelector(".punch-editor-end")
      ?.addEventListener("click", () => void pick("end"));
    hostEl.querySelector(".punch-editor-save")?.addEventListener("click", () => {
      if (!startedAt || !endedAt) {
        say("Pick both a start and an end before saving.");
        return;
      }
      void run(() => onSave?.({ startedAt, endedAt, reason: reason() }));
    });
    hostEl.querySelector(".punch-editor-delete")?.addEventListener("click", () => {
      void run(() => onDelete?.(reason()));
    });
    hostEl.querySelector(".punch-editor-cancel")
      ?.addEventListener("click", () => onCancel?.());
  }

  render();
}
