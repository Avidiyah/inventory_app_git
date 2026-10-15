// View: one crew member's week on the Users page -- per day, work orders
// completed, labor charged, time clocked (spec
// 2026-10-15-user-profile-week-design.md). An Admin+ viewer also edits, adds
// and deletes punches here through the same inline editor and endpoints the
// Timesheets tab uses; everyone else reads.
//
// Layer: views. Owns its fetch (`apiGetPersonWeek`) and two pieces of state,
// the week and which punch is being edited. Each day is a native <details>:
// totals in the summary, the four lists in the body. Wall-clock minutes only;
// no money.
//
// `users.js` dynamic-imports this module on the first profile click, and this
// module dynamic-imports the Work Orders hand-off on the first number click,
// so the Users page's import graph stays as small as it is today.

import {
  apiAddAttendancePunch, apiDeleteAttendancePunch, apiEditAttendancePunch, apiGetPersonWeek,
} from "../api.js";
import { escapeHtml, formatUserName, friendlyError } from "../format.js";
import { roleAtLeast, roleLabel } from "../roles.js";
import { skeletonTableRows } from "../skeleton.js";
import { getRole } from "../state.js";
import { mountPunchEditor } from "./hubAttendancePunchEditor.js";
import { formatHm, isoDate, shiftMonday, spanList, timeLabel, weekLabel } from "./hubWeek.js";
import { statusBadge } from "./workOrderPresenters.js";
import { setProfileOrigin } from "./profileOrigin.js";

function dayLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC",
  });
}

function woButton(number) {
  return `<button type="button" class="hub-link-btn user-profile-wo-btn" data-number="${escapeHtml(number)}">${escapeHtml(number)}</button>`;
}

function dayBand(minutes) {
  if (!minutes) return "none";
  if (minutes < 480) return "short";
  return minutes > 600 ? "over" : "full";
}

// A minimal card: status colour on the edge and the badge, "Archived" as an
// extra tag never a replacement (E6). No element inside may be a button.
function woCard(wo) {
  const location = wo.location ? `<span class="user-profile-wo-location">${escapeHtml(wo.location)}</span>` : "";
  const archived = wo.archived ? `<span class="wo-archived-tag">Archived</span>` : "";
  return `<li><button type="button" class="user-profile-wo-card user-profile-wo-${escapeHtml(wo.status)}" data-id="${escapeHtml(wo.work_order_id)}" data-number="${escapeHtml(wo.number)}" data-archived="${wo.archived ? "1" : ""}">
    <span class="user-profile-wo-number">${escapeHtml(wo.number)}</span>${statusBadge(wo.status)}${location}${archived}
  </button></li>`;
}

function listHtml(title, items) {
  if (!items.length) return "";
  return `<h4 class="user-profile-list-title">${title}</h4><ul class="user-profile-list">${items.join("")}</ul>`;
}

function dayBodyHtml(day, canEdit) {
  const completed = day.completed.map(woCard);
  const charged = day.charged.map((c) => {
    const marks = [];
    if (c.auto_closed) marks.push("auto-stopped");
    if (c.running) marks.push("running");
    const note = marks.length ? ` <span class="hub-hours-punch-note">${marks.join(" · ")}</span>` : "";
    return `<li>${woButton(c.number)} · ${formatHm(c.minutes)}${timesNote(c.spans)}${note}</li>`;
  });
  const adjustments = day.adjustments.map((a) =>
    `<li>${formatHm(a.minutes)} · recorded by ${escapeHtml(a.recorded_by_name)} · ${woButton(a.work_order_number)}</li>`);
  const punches = day.punches.map((p) => {
    const ended = p.open ? "running" : timeLabel(p.ended_at);
    const notes = [];
    if (p.carried) notes.push("carried");
    if (p.start_source === "auto_work_order") notes.push("auto, from a work-order clock");
    if (p.needs_review) notes.push("needs review");
    const note = notes.length ? ` <span class="hub-hours-punch-note">${notes.join(" · ")}</span>` : "";
    const edit = canEdit && !p.carried
      ? ` <button type="button" class="hub-link-btn hub-hours-edit" data-punch="${escapeHtml(p.id)}">Edit</button>`
      : "";
    return `<li>${escapeHtml(timeLabel(p.started_at))} – ${escapeHtml(ended)} · ${formatHm(p.minutes)}${note}${edit}</li>`;
  });
  const html = listHtml("Completed", completed) + listHtml("Charged", charged)
    + listHtml("Adjustments", adjustments) + listHtml("Punches", punches);
  const editor = canEdit
    ? `<button type="button" class="secondary-btn hub-hours-add" data-date="${escapeHtml(day.date)}">+ Add punch</button>
       <div class="hub-hours-editor" data-date="${escapeHtml(day.date)}"></div>`
    : "";
  return (html || `<p class="hint">Nothing recorded.</p>`) + editor;
}

function timesNote(spans) {
  return spans?.length ? ` <span class="hub-hours-punch-note">${escapeHtml(spanList(spans))}</span>` : "";
}

function flagsHtml(day) {
  return day.needs_review
    ? `<span class="hub-hours-flag hub-hours-flag-review"><span aria-hidden="true">&#9888;</span><span class="sr-only"> needs review</span></span>`
    : "";
}

function dayHtml(day, canEdit) {
  const onShift = day.has_open ? ` <span class="hub-hours-punch-note">(on shift)</span>` : "";
  return `<details class="user-profile-day user-profile-day-${dayBand(day.clocked_minutes)}" data-date="${escapeHtml(day.date)}">
    <summary class="user-profile-summary">
      <span class="user-profile-col-day">${escapeHtml(dayLabel(day.date))}${flagsHtml(day)}</span>
      <span class="user-profile-col">${formatHm(day.clocked_minutes)}${timesNote(day.punches)}${onShift}</span>
      <span class="user-profile-col">${formatHm(day.charged_minutes)}${timesNote(day.charged.flatMap((c) => c.spans ?? []))}</span>
      <span class="user-profile-col">${day.completed_count}</span>
    </summary>
    <div class="user-profile-day-body">${dayBodyHtml(day, canEdit)}</div>
  </details>`;
}

function weekHtml(payload, canEdit) {
  return `<div class="user-profile-table-wrap">
      <div class="user-profile-summary user-profile-head" aria-hidden="true">
        <span class="user-profile-col-day">Day</span><span class="user-profile-col">Clocked</span>
        <span class="user-profile-col">Charged</span><span class="user-profile-col">Completed</span>
      </div>
      ${payload.days.map((day) => dayHtml(day, canEdit)).join("")}
      <div class="user-profile-summary user-profile-totals">
        <span class="user-profile-col-day">Week</span>
        <span class="user-profile-col">${formatHm(payload.total_clocked_minutes)}</span>
        <span class="user-profile-col">${formatHm(payload.total_charged_minutes)}</span>
        <span class="user-profile-col">${payload.total_completed}</span>
      </div>
    </div>
    ${payload.total_adjustment_minutes ? `<p class="hint">Adjustments this week: ${formatHm(payload.total_adjustment_minutes)} (shown per day, not counted as charged).</p>` : ""}`;
}

const BACK_LABEL = { users: "‹ Back to users", "user-hub": "‹ Back to timesheets" };

export function mountUserProfile(container, user, { onBack, week: initialWeek = null, page = "users" } = {}) {
  let week = initialWeek;
  let requestId = 0;
  let payload = null;
  let editing = null;          // punch id, or "add:<date>"
  const canEdit = roleAtLeast(getRole(), "admin");

  container.innerHTML = `<section class="user-profile" aria-labelledby="user-profile-heading">
    <div class="user-profile-header">
      <h2 id="user-profile-heading"></h2>
      <p class="hint user-profile-role"></p>
    </div>
    <div class="user-profile-toolbar">
      <button type="button" class="hub-link-btn user-profile-back">${BACK_LABEL[page] || BACK_LABEL.users}</button>
      <div class="user-profile-week-nav"></div>
    </div>
    <div class="user-profile-body"></div>
  </section>`;
  const body = container.querySelector(".user-profile-body");
  const weekNav = container.querySelector(".user-profile-week-nav");
  container.querySelector(".user-profile-back").addEventListener("click", () => onBack?.());

  function paintHeading(payload) {
    const who = payload.user ?? user;
    const archived = payload.archived ? ` <span class="muted">(archived)</span>` : "";
    container.querySelector("#user-profile-heading").innerHTML = `${escapeHtml(formatUserName(who))}${archived}`;
    container.querySelector(".user-profile-role").textContent = roleLabel(who.role);
  }

  async function openByNumber(number) {
    const [{ openWorkOrdersByNumberSearch }, { showPage }] = await Promise.all([
      import("./workOrders.js"), import("./nav.js"),
    ]);
    openWorkOrdersByNumberSearch(number);
    showPage("work-orders");
  }

  // E7: a live card lands on the solo page by id (`focusWorkOrder` is the
  // path Mass Stage uses); an archived one takes the number search so the
  // restore pop-up fires. Either way the origin is remembered first (E8).
  async function openCard(card) {
    setProfileOrigin({ page, userId: user.id, week });
    if (card.dataset.archived) return openByNumber(card.dataset.number);
    const [{ focusWorkOrder }, { showPage }] = await Promise.all([
      import("./workOrders.js"), import("./nav.js"),
    ]);
    focusWorkOrder(card.dataset.id);
    showPage("work-orders");
  }

  function wire(payload) {
    weekNav.innerHTML = `<button type="button" class="secondary-btn user-profile-prev" aria-label="Previous week">◀</button>
      <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
      <button type="button" class="secondary-btn user-profile-next" aria-label="Next week">▶</button>`;
    weekNav.querySelector(".user-profile-prev").addEventListener("click", () => load(shiftMonday(payload.week_start, -7)));
    weekNav.querySelector(".user-profile-next").addEventListener("click", () => load(shiftMonday(payload.week_start, 7)));
    body.querySelectorAll(".user-profile-wo-btn").forEach((button) => {
      button.addEventListener("click", () => { void openByNumber(button.dataset.number); });
    });
    body.querySelectorAll(".user-profile-wo-card").forEach((card) => {
      card.addEventListener("click", () => { void openCard(card); });
    });
    body.querySelectorAll(".hub-hours-edit").forEach((button) => {
      button.addEventListener("click", () => { editing = button.dataset.punch; paint(); });
    });
    body.querySelectorAll(".hub-hours-add").forEach((button) => {
      button.addEventListener("click", () => { editing = `add:${button.dataset.date}`; paint(); });
    });
    if (editing) mountEditor();
  }

  function findPunch(id) {
    for (const day of payload.days) {
      const punch = day.punches.find((p) => p.id === id && !p.carried);
      if (punch) return { punch, date: day.date };
    }
    return null;
  }

  // A write goes out, the week reloads; a refusal lands in the editor's own
  // message line, exactly as on the Timesheets tab.
  async function write(work) {
    try {
      await work();
      editing = null;
      await load(week);
    } catch (err) {
      const message = body.querySelector(".punch-editor-message");
      if (message) {
        message.className = "punch-editor-message error";
        message.textContent = friendlyError(err, "Could not save that punch.");
      }
    }
  }

  function mountEditor() {
    const adding = editing.startsWith("add:");
    const found = adding ? { punch: null, date: editing.slice(4) } : findPunch(editing);
    const host = found && body.querySelector(`.hub-hours-editor[data-date="${CSS.escape(found.date)}"]`);
    if (!host) { editing = null; return; }
    host.closest("details").open = true;
    mountPunchEditor(host, {
      punch: found.punch,
      date: found.date,
      onSave: (values) => write(() => (adding
        ? apiAddAttendancePunch({ userId: user.id, ...values })
        : apiEditAttendancePunch(editing, values))),
      onDelete: (reason) => write(() => apiDeleteAttendancePunch(editing, reason)),
      onCancel: () => { editing = null; paint(); },
    });
  }

  // Repaint from the held payload, keeping whichever days were open.
  function paint() {
    const open = new Set(Array.from(body.querySelectorAll("details[open]")).map((d) => d.dataset.date));
    body.innerHTML = weekHtml(payload, canEdit);
    body.querySelectorAll("details").forEach((d) => { if (open.has(d.dataset.date)) d.open = true; });
    wire(payload);
  }

  async function load(requested) {
    const id = ++requestId;
    body.innerHTML = `<table class="stack-table"><tbody>${skeletonTableRows(4, 7)}</tbody></table>`;
    try {
      const fresh = await apiGetPersonWeek(user.id, { week: requested });
      if (id !== requestId) return;
      const open = new Set(Array.from(body.querySelectorAll("details[open]")).map((d) => d.dataset.date));
      payload = fresh;
      week = payload.week_start;
      paintHeading(payload);
      body.innerHTML = weekHtml(payload, canEdit);
      body.querySelectorAll("details").forEach((d) => { if (open.has(d.dataset.date)) d.open = true; });
      wire(payload);
    } catch (err) {
      if (id !== requestId) return;
      body.innerHTML = `<p class="user-profile-error error">${escapeHtml(friendlyError(err, "Could not load this week."))} <button type="button" class="secondary-btn user-profile-retry">Retry</button></p>`;
      body.querySelector(".user-profile-retry").addEventListener("click", () => load(requested ?? week));
    }
  }

  void load(week);
}
