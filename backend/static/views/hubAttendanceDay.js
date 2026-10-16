// View: the Admin Timesheets tab's **day strip** and the **day page** it
// opens -- one card per day of the week, and one page per day listing
// everyone who clocked in, with the audited punch editor.
//
// Layer: views (no fetch; state is which punch is being edited). Both mounts
// read the one week payload from `GET /hub/attendance/week`, so opening a
// day never starts a request. The strip owns the tab's week picker; the day
// page steps a day at a time and asks the tab (`onDayChange`) for a date,
// which may fall in another week -- the tab then refetches and remounts.
//
// Editing reuses the Hours grid's drill-down (`drilldownHtml`), one block per
// person, so the day page and the profile grid print a punch the same way.

import { escapeHtml } from "../format.js";
import { mountPunchEditor } from "./hubAttendancePunchEditor.js";
import { drilldownHtml, PROFILABLE_ROLES } from "./hubAttendanceHours.js";
import { formatHm, isoDate, shiftMonday, spanList, weekLabel } from "./hubWeek.js";

function cardLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC",
  });
}

function longLabel(iso) {
  return isoDate(iso).toLocaleDateString([], {
    weekday: "long", month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });
}

export function mondayOf(iso) {
  const offset = (isoDate(iso).getUTCDay() + 6) % 7;
  return shiftMonday(iso, -offset);
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

// Rows (people) with time on the given date, each paired with that day.
function peopleOn(payload, date) {
  return payload.rows
    .map((row) => ({ row, day: row.days.find((d) => d.date === date) }))
    .filter(({ day }) => day && (day.clocked_minutes > 0 || day.punches.length));
}

// --- The strip: week picker + seven day cards ------------------------------

export function mountHubAttendanceDays(container, payload, { onWeekChange, onOpenDay } = {}) {
  const cards = payload.days.map((date) => {
    const people = peopleOn(payload, date);
    const minutes = payload.totals_by_day.find((t) => t.date === date)?.paid_minutes ?? 0;
    const flags = people.some(({ day }) => day.has_open) ? `<span class="hub-hours-flag hub-hours-flag-open"><span aria-hidden="true">●</span><span class="sr-only"> someone still on shift</span></span>` : "";
    const count = `${people.length} clocked in`;
    const punches = people.flatMap(({ day }) => day.punches);
    const span = punches.length ? spanList([{
      started_at: punches.map((p) => p.started_at).sort()[0],
      ended_at: punches.some((p) => !p.ended_at) ? null : punches.map((p) => p.ended_at).sort().at(-1),
    }]) : "";
    return `<button type="button" class="hub-day-card" data-date="${escapeHtml(date)}" aria-label="${escapeHtml(`${longLabel(date)}, ${count}, ${formatHm(minutes)} paid`)}">
      <span class="hub-day-card-date">${escapeHtml(cardLabel(date))}${flags}</span>
      <span class="hub-day-card-count">${escapeHtml(count)}</span>
      <span class="hub-day-card-hours">${formatHm(minutes)}</span>
      ${span ? `<span class="hub-hours-punch-note">${escapeHtml(span)}</span>` : ""}
    </button>`;
  }).join("");
  // 167 or 169. Said out loud so a short week does not read as lost hours.
  const dst = payload.week_hours === 168
    ? ""
    : `<p class="hint hub-hours-dst">Daylight saving: this week is ${escapeHtml(String(payload.week_hours))} hours long, not 168.</p>`;
  container.innerHTML = `<section class="hub-days" aria-labelledby="hub-days-heading">
      <div class="hub-hours-toolbar">
        <div class="hub-hours-week-nav">
          <button type="button" class="secondary-btn hub-timesheets-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
          <button type="button" class="secondary-btn hub-timesheets-next" aria-label="Next week">▶</button>
        </div>
      </div>
      <h3 id="hub-days-heading" class="sr-only">Days</h3>
      <p class="hint hub-days-hint">Tap a day to see who clocked in.</p>
      <div class="hub-day-cards">${cards}</div>
      ${dst}
    </section>`;
  container.querySelectorAll(".hub-day-card").forEach((button) => {
    button.addEventListener("click", () => onOpenDay?.(button.dataset.date));
  });
  container.querySelector(".hub-timesheets-prev").addEventListener("click", () => {
    onWeekChange?.(shiftMonday(payload.week_start, -7));
  });
  container.querySelector(".hub-timesheets-next").addEventListener("click", () => {
    onWeekChange?.(shiftMonday(payload.week_start, 7));
  });
}

// --- The day page: everyone clocked in on one date -------------------------

export function mountHubAttendanceDayPage(container, payload, date, {
  onBack, onDayChange, onOpenProfile, onSavePunch, onAddPunch, onDeletePunch, onClearReview, onToggleLunch,
} = {}) {
  // A punch id, `add:<userId>`, or null.
  let editing = null;
  const canEdit = Boolean(onSavePunch);
  const people = peopleOn(payload, date);
  // A needs-review day is listed but never added (spec 2026-10-16 U9).
  const total = people.reduce((sum, { day }) => sum + (day.pending_review ? 0 : day.paid_minutes), 0);

  function findPunch(punchId) {
    for (const { day } of people) {
      const punch = day.punches.find((p) => p.id === punchId);
      if (punch) return punch;
    }
    return null;
  }

  function render() {
    const blocks = people.map(({ row, day }) => {
      const name = userName(row.user);
      const link = onOpenProfile && PROFILABLE_ROLES.includes(row.user?.role)
        ? `<button type="button" class="hub-link-btn hub-hours-person" data-user="${escapeHtml(row.user.id)}">${escapeHtml(name)}</button>`
        : escapeHtml(name);
      return `<article class="hub-day-person" data-user="${escapeHtml(row.user?.id ?? "")}">
        <h4 class="hub-day-person-name">${link}</h4>
        ${drilldownHtml(day, name, { canEdit, userId: row.user?.id ?? "" })}
      </article>`;
    }).join("");
    container.innerHTML = `<section class="hub-day-page" aria-labelledby="hub-day-heading">
      <div class="hub-hours-toolbar">
        <button type="button" class="secondary-btn hub-day-back">‹ Back to week</button>
        <div class="hub-hours-week-nav">
          <button type="button" class="secondary-btn hub-day-prev" aria-label="Previous day">◀</button>
          <strong>${escapeHtml(longLabel(date))}</strong>
          <button type="button" class="secondary-btn hub-day-next" aria-label="Next day">▶</button>
        </div>
      </div>
      <h3 id="hub-day-heading" class="hub-hours-heading">Day timesheet · ${people.length} clocked in · ${formatHm(total)}</h3>
      <p class="hub-hours-message" aria-live="polite"></p>
      ${blocks || `<p class="hint hub-hours-empty">Nobody clocked in this day.</p>`}
    </section>`;

    container.querySelector(".hub-day-back").addEventListener("click", () => onBack?.());
    container.querySelector(".hub-day-prev").addEventListener("click", () => onDayChange?.(shiftMonday(date, -1)));
    container.querySelector(".hub-day-next").addEventListener("click", () => onDayChange?.(shiftMonday(date, 1)));
    container.querySelectorAll(".hub-hours-person").forEach((button) => {
      const row = payload.rows.find((r) => r.user?.id === button.dataset.user);
      button.addEventListener("click", () => onOpenProfile?.(row.user));
    });
    container.querySelectorAll(".hub-hours-edit").forEach((button) => {
      button.addEventListener("click", () => { editing = button.dataset.punch; render(); });
    });
    container.querySelectorAll(".hub-hours-add").forEach((button) => {
      button.addEventListener("click", () => { editing = `add:${button.dataset.user}`; render(); });
    });
    container.querySelectorAll(".hub-hours-clear-review").forEach((button) => {
      button.addEventListener("click", () => onClearReview?.(button.dataset.punch));
    });
    container.querySelectorAll(".hub-hours-lunch").forEach((button) => {
      button.addEventListener("click", () =>
        onToggleLunch?.(button.dataset.punch, button.dataset.waive === "true"));
    });

    if (!editing) return;
    const adding = editing.startsWith("add:");
    const userId = adding
      ? editing.slice(4)
      : people.find(({ day }) => day.punches.some((p) => p.id === editing))?.row.user?.id;
    const host = container.querySelector(`.hub-hours-editor[data-user="${CSS.escape(userId ?? "")}"]`);
    if (!host) return;
    mountPunchEditor(host, {
      punch: adding ? null : findPunch(editing),
      date,
      onSave: (values) => (adding ? onAddPunch?.(userId, values) : onSavePunch?.(editing, values)),
      onDelete: (reason) => onDeletePunch?.(editing, reason),
      onCancel: () => { editing = null; render(); },
    });
  }

  render();
}
