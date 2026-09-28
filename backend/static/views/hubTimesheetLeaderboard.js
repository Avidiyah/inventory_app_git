// View: the Admin Timesheets tab's weekly **revenue leaderboard**.
//
// Layer: views. No fetch but the export blob, no state: everything on screen
// comes from the week payload `hubTimesheetsTab.js` hands in -- the same
// payload the Hours grid below it reads, so the two cannot disagree.
//
// Owns the page's one week picker and the CSV export, because the
// leaderboard is the headline of the week and the Hours grid is its record.
//
// The money is written for a layperson, one rule per column:
//   charged   = time on a work-order clock + hand-entered labor
//   uncharged = clocked - charged, never below zero
//   made      = charged x the billing labor rate
//   lost      = uncharged x the same rate
// Hand-entered labor counts on purpose (see the `hub.leaderboard` tip). This
// is an estimate at the hourly rate, not the invoice: billing rounds a whole
// work order's labor up to 30 minutes, which no per-person number can honestly
// reproduce.
//
// The made/lost bar is sized through CSSOM after the markup lands -- the CSP
// drops `style=` attributes parsed from a template (csp-blocks-inline-styles).

import { apiExportHubAttendance } from "../api.js";
import { escapeHtml, formatMoney, friendlyError } from "../format.js";
import { tipHtml } from "../tooltip.js";

const MEDALS = ["🥇", "🥈", "🥉"];

// `8:00`, the Hours grid's own clock-style figure.
function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

function weekLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

// Pure: the ranked rows and the company total. Exported for the tests, which
// pin the money math without going through the DOM.
export function computeLeaderboard(payload) {
  const rate = Number(payload.labor_rate) || 0;
  const price = (minutes) => (minutes * rate) / 60;
  const entries = payload.rows.map((row) => {
    const adjusted = row.days.reduce((sum, day) => sum + (day.adjustment_minutes || 0), 0);
    const charged = row.tracked_minutes + adjusted;
    const uncharged = Math.max(0, row.total_minutes - charged);
    return {
      user: row.user,
      name: userName(row.user),
      clocked: row.total_minutes,
      charged,
      uncharged,
      made: price(charged),
      lost: price(uncharged),
    };
  });
  entries.sort((a, b) => b.made - a.made || a.lost - b.lost || a.name.localeCompare(b.name));
  entries.forEach((entry, index) => { entry.rank = index + 1; });
  const total = entries.reduce((sum, entry) => ({
    charged: sum.charged + entry.charged,
    uncharged: sum.uncharged + entry.uncharged,
    made: sum.made + entry.made,
    lost: sum.lost + entry.lost,
  }), { charged: 0, uncharged: 0, made: 0, lost: 0 });
  return { rate, entries, total };
}

// Share of on-the-clock time that was charged, 0-100. Someone who charged
// with no punch at all counts as fully charged rather than dividing by zero.
function chargedPercent(entry) {
  const whole = entry.charged + entry.uncharged;
  return whole ? Math.round((entry.charged / whole) * 100) : 100;
}

function barHtml(entry) {
  const pct = chargedPercent(entry);
  return `<div class="hub-leaderboard-bar" role="img" aria-label="${pct}% of clocked time charged" data-pct="${pct}">
      <span class="hub-leaderboard-bar-made"></span><span class="hub-leaderboard-bar-lost"></span>
    </div>
    <span class="hub-leaderboard-pct">${pct}% charged</span>`;
}

function rankHtml(rank) {
  const medal = MEDALS[rank - 1];
  return medal
    ? `<span aria-hidden="true">${medal}</span><span class="sr-only">${ordinal(rank)}</span>`
    : escapeHtml(String(rank));
}

function rowHtml(entry) {
  return `<tr class="hub-leaderboard-row${entry.rank <= 3 ? " hub-leaderboard-top" : ""}">
      <td class="hub-leaderboard-rank">${rankHtml(entry.rank)}</td>
      <th scope="row">${escapeHtml(entry.name)}</th>
      <td class="hub-leaderboard-num">${formatHm(entry.charged)}</td>
      <td class="hub-leaderboard-num">${formatHm(entry.uncharged)}</td>
      <td class="hub-leaderboard-num hub-leaderboard-made">${escapeHtml(formatMoney(entry.made))}</td>
      <td class="hub-leaderboard-num hub-leaderboard-lost">${escapeHtml(formatMoney(entry.lost))}</td>
      <td class="hub-leaderboard-split">${barHtml(entry)}</td>
    </tr>`;
}

function setStatus(container, message, type = "") {
  const status = container.querySelector(".hub-leaderboard-message");
  if (!status) return;
  status.textContent = message;
  status.className = `hub-leaderboard-message${type ? ` ${type}` : ""}`;
}

export function mountHubTimesheetLeaderboard(container, payload, { onWeekChange } = {}) {
  async function downloadCsv(button) {
    button.disabled = true;
    setStatus(container, "Preparing export…");
    try {
      const { blob, filename } = await apiExportHubAttendance({ week: payload.week_start });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setStatus(container, `Exported ${filename}.`, "success");
    } catch (err) {
      setStatus(container, friendlyError(err, "Could not export attendance."), "error");
    } finally {
      button.disabled = false;
    }
  }

  const { rate, entries, total } = computeLeaderboard(payload);
  const rateText = escapeHtml(formatMoney(rate));
  const table = entries.length
    ? `<div class="hub-hours-table-wrap hub-leaderboard-wrap">
        <table class="hub-hours-table hub-leaderboard-table">
          <caption class="sr-only">Revenue leaderboard for ${escapeHtml(payload.week_start)} through ${escapeHtml(payload.week_end)}</caption>
          <thead><tr>
            <th scope="col">Rank</th><th scope="col">Person</th>
            <th scope="col">Charged hours</th><th scope="col">Uncharged hours</th>
            <th scope="col">Money made</th><th scope="col">Money lost</th>
            <th scope="col">Charged vs uncharged</th>
          </tr></thead>
          <tbody>${entries.map(rowHtml).join("")}</tbody>
          <tfoot><tr>
            <td></td><th scope="row">Company total</th>
            <td class="hub-leaderboard-num">${formatHm(total.charged)}</td>
            <td class="hub-leaderboard-num">${formatHm(total.uncharged)}</td>
            <td class="hub-leaderboard-num hub-leaderboard-made">${escapeHtml(formatMoney(total.made))}</td>
            <td class="hub-leaderboard-num hub-leaderboard-lost">${escapeHtml(formatMoney(total.lost))}</td>
            <td></td>
          </tr></tfoot>
        </table>
      </div>
      <p class="hint hub-leaderboard-legend">Charged hours are time spent on a work order. Uncharged hours are time clocked in but not on a work order. Each hour is worth ${rateText}: charged hours are money made, uncharged hours are money lost. Ranked by money made.</p>`
    : `<p class="hint hub-leaderboard-empty">Nobody clocked in this week.</p>`;

  container.innerHTML = `<section class="hub-leaderboard" aria-labelledby="hub-leaderboard-heading">
      <div class="hub-leaderboard-toolbar">
        <div class="hub-leaderboard-week-nav">
          <button type="button" class="secondary-btn hub-timesheets-prev" aria-label="Previous week">◀</button>
          <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
          <button type="button" class="secondary-btn hub-timesheets-next" aria-label="Next week">▶</button>
        </div>
        <button type="button" class="secondary-btn hub-timesheets-export">Export CSV</button>
      </div>
      <h3 id="hub-leaderboard-heading" class="hub-leaderboard-heading">Leaderboard ${tipHtml("hub.leaderboard")}</h3>
      <p class="hub-leaderboard-message" aria-live="polite"></p>
      ${table}
    </section>`;

  container.querySelectorAll(".hub-leaderboard-bar").forEach((bar) => {
    const pct = Number(bar.dataset.pct);
    bar.querySelector(".hub-leaderboard-bar-made").style.width = `${pct}%`;
    bar.querySelector(".hub-leaderboard-bar-lost").style.width = `${100 - pct}%`;
  });
  container.querySelector(".hub-timesheets-prev")?.addEventListener("click", () => {
    onWeekChange?.(shiftMonday(payload.week_start, -7));
  });
  container.querySelector(".hub-timesheets-next")?.addEventListener("click", () => {
    onWeekChange?.(shiftMonday(payload.week_start, 7));
  });
  container.querySelector(".hub-timesheets-export")?.addEventListener("click", (event) => {
    void downloadCsv(event.currentTarget);
  });
}
