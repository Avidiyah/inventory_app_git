// View: the "Flagged time" step-through pop-up, and the queue builders that
// feed it.
//
// Layer: views (no fetch). Payload and callbacks in; the caller owns every
// request and the refetch, as `hubTimesheetsTab.js` does for the punch editor.
// One flagged item per step; the punch step embeds `mountPunchEditor`.
//
// Built like `workOrderSignature.js`'s flow: a `.modal-overlay` on the body, a
// `.modal-box` dialog, focus on the step heading, back to the opener on close.
// The time picker is the shell's own `#prompt-time-overlay`, which the flow's
// CSS block stacks above this pop-up -- no second picker.

import { escapeHtml, friendlyError } from "../format.js";
import { mountPunchEditor } from "./hubAttendancePunchEditor.js";
import { mountClockStep } from "./flaggedClockStep.js";

const CENTRAL = "America/Chicago";

const REASON = {
  auto: "Auto-closed at midnight. No clock-out was recorded.",
  crosses: "This punch ends on the next day. Set the real end.",
  other: "Marked for review.",
};
const sessionReason = (number) =>
  `The clock on WO ${number} was stopped automatically after 12 hours.`;

function personName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim();
}

function punchReason(p) {
  if (p.end_source === "auto_clock_out") return REASON.auto;
  if (p.crosses_midnight) return REASON.crosses;
  return REASON.other;
}

function centralDate(instant) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: CENTRAL }).format(new Date(instant));
}

function byDateThenName(a, b) {
  return a.date.localeCompare(b.date)
    || a.name.localeCompare(b.name)
    || String(a.started_at).localeCompare(String(b.started_at));
}

// Every flagged punch (a carried copy is skipped: the punch is listed once, on
// the day it started) and work-order clock in the week payload. Order is
// `Array.sort`'s stable one, so ties keep payload order.
export function flaggedItems(weekPayload) {
  const items = [];
  const names = new Map();
  for (const row of weekPayload?.rows || []) {
    const name = personName(row.user) || "Unknown";
    names.set(row.user?.id, name);
    for (const day of row.days || []) {
      for (const p of day.punches || []) {
        if (p.carried || !(p.needs_review || p.crosses_midnight)) continue;
        items.push({
          key: `punch:${p.id}`, kind: "punch", id: p.id, userId: row.user?.id, name,
          date: day.date, reason: punchReason(p),
          started_at: p.started_at, ended_at: p.ended_at, number: null,
        });
      }
    }
  }
  for (const s of weekPayload?.flagged_sessions || []) {
    items.push({
      key: `session:${s.session_id}`, kind: "session", id: s.session_id, userId: s.user_id,
      workOrderId: s.work_order_id,
      name: names.get(s.user_id) || "Unknown", date: s.date, reason: sessionReason(s.number),
      started_at: s.started_at, ended_at: s.ended_at, number: s.number,
    });
  }
  return items.sort(byDateThenName);
}

// The caller's own flagged punches (Home's `week_punches`); never a clock.
export function ownFlaggedItems(attendance, user) {
  const name = personName(user) || "You";
  return (attendance?.week_punches || [])
    .filter((p) => p.needs_review)
    .map((p) => ({
      key: `punch:${p.id}`, kind: "punch", id: p.id, userId: user?.id, name,
      date: centralDate(p.started_at), reason: punchReason(p),
      started_at: p.started_at, ended_at: p.ended_at, number: null,
    }))
    .sort(byDateThenName);
}

function dayLabel(date) {
  return new Date(`${date}T12:00:00`).toLocaleDateString([], {
    weekday: "short", month: "short", day: "numeric",
  });
}

// `items` is the queue built once at open. After every action the caller's
// `refresh()` returns the items still flagged; the queue drops the rest and
// keeps its position.
export function openFlaggedTimeFlow({ items, canAccept, actions, refresh, onClose }) {
  if (document.querySelector(".flagged-flow")) return { close() {} };
  const opener = document.activeElement;
  // Workers never see work-order clocks: they cannot accept them.
  let queue = items.filter((i) => canAccept || i.kind === "punch");
  let pos = 0;
  let fixed = 0;
  let skipped = 0;
  let busy = false;
  let closed = false;

  const flow = document.createElement("div");
  flow.className = "modal-overlay flagged-flow";
  flow.innerHTML = `<div class="modal-box flagged-flow-box" role="dialog" aria-modal="true"
      aria-labelledby="flagged-flow-heading">
    <div class="flagged-flow-head">
      <h2 class="modal-title flagged-flow-heading" id="flagged-flow-heading" tabindex="-1"></h2>
      <button type="button" class="secondary-btn flagged-flow-close" aria-label="Close">✕</button>
    </div>
    <div class="flagged-flow-step"></div>
  </div>`;
  document.body.appendChild(flow);
  const heading = flow.querySelector(".flagged-flow-heading");
  const stepEl = flow.querySelector(".flagged-flow-step");

  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("tutorial:end", close);
    flow.remove();
    opener?.focus?.();
    onClose?.({ fixed, skipped });
  }

  // One write at a time: a second tap while one is in flight does nothing.
  async function act(work) {
    if (busy) return;
    busy = true;
    flow.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    const current = queue[pos];
    let ok = false;
    let message = "";
    try {
      await work(current);
      ok = true;
      fixed += 1;
    } catch (err) {
      message = friendlyError(err, "Could not save that change.");
    }
    // Either way the item may have changed under us (a rejection can mean
    // someone else already accepted it), so ask what is still flagged.
    try {
      const fresh = await refresh?.();
      if (Array.isArray(fresh)) {
        const byKey = new Map(fresh.map((i) => [i.key, i]));
        const before = queue.slice(0, pos).filter((i) => byKey.has(i.key)).length;
        const currentKept = byKey.has(current.key);
        queue = queue.filter((i) => byKey.has(i.key)).map((i) => byKey.get(i.key));
        pos = before + (ok && currentKept ? 1 : 0);
        if (ok || !currentKept) message = "";
      } else if (ok) {
        pos += 1;
      }
    } catch (_err) {
      if (ok) pos += 1;
    }
    busy = false;
    render(message);
  }

  function skip() {
    if (busy) return;
    skipped += 1;
    pos += 1;
    render();
  }

  function punchStep(item) {
    const host = stepEl.querySelector(".flagged-flow-editor");
    mountPunchEditor(host, {
      punch: { started_at: item.started_at, ended_at: item.ended_at },
      date: item.date,
      onSave: (values) => act(() => actions.savePunch(item.id, values)),
      onDelete: (reason) => act(() => actions.deletePunch(item.id, reason)),
      onCancel: skip,
    });
    const cancel = host.querySelector(".punch-editor-cancel");
    if (cancel) cancel.textContent = "Skip";
    stepEl.querySelector('[data-flow="looks-right"]')
      ?.addEventListener("click", () => void act(() => actions.looksRight(item.id)));
  }

  function sessionStep(item) {
    mountClockStep(stepEl.querySelector(".flagged-flow-clock"), {
      item,
      loadWorkOrder: actions.loadWorkOrder,
      onSave: (endedAt) => void act(() => actions.saveSession(item.id, endedAt)),
      onAccept: () => void act(() => actions.acceptSession(item.id)),
      onOpen: () => { close(); actions.openWorkOrder(item.number); },
      onSkip: skip,
    });
  }

  function stepHtml(item) {
    const head = `<p class="flagged-flow-who">${escapeHtml(item.name)} · ${escapeHtml(dayLabel(item.date))}</p>
      <p class="flagged-flow-reason">${escapeHtml(item.reason)}</p>`;
    const error = `<p class="flagged-flow-error" role="alert" aria-live="polite"></p>`;
    if (item.kind === "session") return `${head}<div class="flagged-flow-clock"></div>${error}`;
    return `${head}
      <div class="flagged-flow-editor"></div>
      ${canAccept ? `<div class="flagged-flow-actions">
        <button type="button" class="secondary-btn" data-flow="looks-right">Looks right</button>
      </div>
      <p class="hub-hours-punch-note">Looks right keeps the times as they are. Skip leaves it flagged.</p>` : ""}
      ${error}`;
  }

  function render(message = "") {
    if (closed) return;
    if (pos >= queue.length) {
      heading.textContent = "Flagged time";
      stepEl.innerHTML = `<p class="flagged-flow-summary">Fixed ${fixed} · Skipped ${skipped}</p>
        <div class="flagged-flow-actions"><button type="button" data-flow="done">Done</button></div>`;
      stepEl.querySelector('[data-flow="done"]').addEventListener("click", close);
    } else {
      const item = queue[pos];
      const done = fixed + skipped;
      heading.textContent = `Flagged time · ${done + 1} of ${done + queue.length - pos}`;
      stepEl.innerHTML = stepHtml(item);
      if (item.kind === "session") sessionStep(item); else punchStep(item);
      stepEl.querySelector(".flagged-flow-error").textContent = message;
    }
    heading.focus();
  }

  // The shell's time picker handles its own Escape and Tab; stand down while
  // it is open so one key does not close both.
  function pickerOpen() {
    const picker = document.getElementById("prompt-time-overlay");
    return Boolean(picker && !picker.hidden);
  }
  function onKey(event) {
    if (pickerOpen()) return;
    if (event.key === "Escape") { close(); return; }
    if (event.key !== "Tab") return;
    const stops = [...flow.querySelectorAll("button:not([disabled]), input")];
    if (!stops.length) return;
    const at = stops.indexOf(document.activeElement);
    if (event.shiftKey ? at <= 0 : at === stops.length - 1) {
      event.preventDefault();
      stops[event.shiftKey ? stops.length - 1 : 0].focus();
    }
  }

  flow.querySelector(".flagged-flow-close").addEventListener("click", close);
  document.addEventListener("keydown", onKey);
  // A tour opens the pop-up on sample data; it must not outlive the tour.
  document.addEventListener("tutorial:end", close);
  render();
  return { close };
}
