// View: one crew member's week on the Users page -- per day, work orders
// completed, labor charged, time clocked (spec
// 2026-10-15-user-profile-week-design.md). An Admin+ viewer also edits, adds
// and deletes punches here through the same inline editor and endpoints the
// Timesheets tab uses; everyone else reads.
//
// Layer: views. Owns its fetch (`apiGetPersonWeek`) and two pieces of state,
// the week and which punch is being edited. The week totals lead; each day
// is a native <details> card: labelled totals and a charged-share bar in the
// summary, the day in time order and three lists in the body. Wall-clock
// minutes only; no money.
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
import { dayTimelineHtml } from "./dayTimeline.js";
import { formatHm, isoDate, shiftMonday, timeLabel, weekLabel } from "./hubWeek.js";
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

// The edge colour's meaning in words, so the colour never stands alone.
const BAND_LABEL = { short: "under 8h", full: "8–10h", over: "over 10h" };

function bandHtml(minutes) {
  const band = dayBand(minutes);
  return BAND_LABEL[band] ? ` <span class="user-profile-band user-profile-band-${band}">${BAND_LABEL[band]}</span>` : "";
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

function editTagsHtml(tags, word) {
  return (tags || []).map((t) =>
    ` <span class="day-tl-tag day-tl-tag-${t}">${t === "self" ? "Self" : "Admin"}-${word}</span>`).join("");
}

function dayBodyHtml(day, canEdit, now) {
  const completed = day.completed.map(woCard);
  const adjustments = day.adjustments.map((a) =>
    `<li>${woButton(a.work_order_number)} · ${formatHm(a.minutes)} · entered by ${escapeHtml(a.recorded_by_name)}${editTagsHtml([a.recorded_by_self ? "self" : "admin"], "entered")}</li>`);
  const marks = Object.fromEntries((day.punch_marks || []).map((m) => [m.punch_id, m.tags]));
  const punches = day.punches.map((p) => {
    const ended = p.open ? "running" : timeLabel(p.ended_at);
    const notes = [];
    if (p.carried) notes.push("carried");
    if (p.start_source === "auto_work_order") notes.push("auto, from a work-order clock");
    if (p.end_source === "auto_clock_out") notes.push("auto-closed at midnight");
    if (p.needs_review) notes.push("needs review");
    if (p.crosses_midnight) notes.push("crossed midnight, fix the end");
    const note = notes.length ? ` <span class="hub-hours-punch-note">${notes.join(" · ")}</span>` : "";
    const edit = canEdit && !p.carried
      ? ` <button type="button" class="hub-link-btn hub-hours-edit" data-punch="${escapeHtml(p.id)}">Edit</button>`
      : "";
    return `<li>${escapeHtml(timeLabel(p.started_at))} – ${escapeHtml(ended)} · ${formatHm(p.minutes)}${editTagsHtml(marks[p.id], "edited")}${note}${edit}</li>`;
  });
  const html = dayTimelineHtml(day, { now })
    + listHtml("Entered by hand (no clock times)", adjustments)
    + listHtml("Work orders completed", completed) + listHtml("Punches", punches);
  const editor = canEdit
    ? `<button type="button" class="secondary-btn hub-hours-add" data-date="${escapeHtml(day.date)}">+ Add punch</button>
       <div class="hub-hours-editor" data-date="${escapeHtml(day.date)}"></div>`
    : "";
  return (html || `<p class="hint">Nothing recorded.</p>`) + editor;
}

function flagsHtml(day) {
  return day.needs_review
    ? ` <span class="hub-hours-flag hub-hours-flag-review"><span aria-hidden="true">&#9888;</span> needs review</span>`
    : "";
}

// Every number carries its own words, so no column head is needed (the
// self-explanation rule). Charged includes hand-entered labor (spec U6).
function figuresHtml(t) {
  const split = t.hand
    ? ` <span class="user-profile-split">(incl. ${formatHm(t.hand)} by hand)</span>`
    : "";
  const done = `${t.completed} work order${t.completed === 1 ? "" : "s"} completed`;
  return `<span class="user-profile-figures">
      <span class="user-profile-figure">Paid <strong>${formatHm(t.paid)}</strong>${t.onShift || ""}</span>
      <span class="user-profile-figure">Charged to work orders <strong>${formatHm(t.charged)}</strong>${split}</span>
      <span class="user-profile-figure">Not charged <strong>${formatHm(t.uncharged)}</strong></span>
      <span class="user-profile-figure">${done}</span>
    </span>${shareHtml(t.paid, t.charged)}`;
}

// The bar is a native <progress>; the sentence beside it says what it means.
function shareHtml(paid, charged) {
  if (!paid) return "";
  const pct = Math.round((charged / paid) * 100);
  return `<span class="user-profile-share"><progress max="${paid}" value="${Math.min(charged, paid)}" aria-hidden="true"></progress><span>${pct}% of paid time charged to work orders</span></span>`;
}

function dayHtml(day, canEdit, now) {
  const empty = !day.paid_minutes && !day.charged_minutes && !day.completed_count
    && !day.punches.length && !day.has_open;
  const figures = empty
    ? `<span class="hint">Nothing recorded</span>`
    : figuresHtml({
      paid: day.paid_minutes, charged: day.charged_minutes, hand: day.adjustment_minutes,
      uncharged: day.uncharged_minutes, completed: day.completed_count,
      onShift: day.has_open ? ` <span class="hub-hours-punch-note">(on shift now)</span>` : "",
    });
  const pending = day.pending_review ? " user-profile-day-pending" : "";
  return `<details class="user-profile-day user-profile-day-${dayBand(day.paid_minutes)}${pending}" data-date="${escapeHtml(day.date)}">
    <summary class="user-profile-summary">
      <span class="user-profile-day-head"><strong>${escapeHtml(dayLabel(day.date))}</strong>${bandHtml(day.paid_minutes)}${flagsHtml(day)}<span class="user-profile-toggle" aria-hidden="true"></span></span>
      ${figures}
    </summary>
    <div class="user-profile-day-body">${dayBodyHtml(day, canEdit, now)}</div>
  </details>`;
}

function weekHtml(payload, canEdit) {
  return `<div class="user-profile-summary user-profile-totals">
      <span class="user-profile-day-head"><strong>This week</strong></span>
      ${figuresHtml({
        paid: payload.total_paid_minutes, charged: payload.total_charged_minutes,
        hand: payload.total_adjustment_minutes, uncharged: payload.total_uncharged_minutes,
        completed: payload.total_completed,
      })}
    </div>
    ${payload.days.some((d) => d.pending_review) ? `<p class="hint">Days marked ⚠ need review and are left out of the week totals.</p>` : ""}
    <div class="user-profile-table-wrap">
      ${payload.days.map((day) => dayHtml(day, canEdit, payload.server_now)).join("")}
    </div>`;
}

const BACK_LABEL = { users: "‹ Back to users", "user-hub": "‹ Back to timesheets" };

export function mountUserProfile(container, user, { onBack, week: initialWeek = null, page = "users" } = {}) {
  let week = initialWeek;
  let requestId = 0;
  let payload = null;
  let editing = null;          // punch id, or "add:<date>"
  const canEdit = roleAtLeast(getRole(), "supervisor");

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
