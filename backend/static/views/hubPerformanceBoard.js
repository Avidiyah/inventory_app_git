// View: the **performance board** -- one ranked table for a week or a month
// to date, from `GET /hub/performance`.
//
// Layer: views. Pure: no fetch, no state, no buttons. `hubLeaderboardsTab.js`
// owns the window and the paging. Every number here is the server's; this
// file formats and never computes, so the rule lives in one place
// (`domain/performance.py`, spec 2026-10-29).

import { escapeHtml, formatMoney } from "../format.js";
import { formatHm } from "./hubWeek.js";

const MEDALS = ["🥇", "🥈", "🥉"];

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

function rankHtml(rank) {
  if (rank === null || rank === undefined) return "—";
  const medal = MEDALS[rank - 1];
  return medal
    ? `<span aria-hidden="true">${medal}</span><span class="sr-only">${ordinal(rank)}</span>`
    : escapeHtml(String(rank));
}

const dayWord = (n) => (n === 1 ? "1 day" : `${n} days`);
const windowWord = (window) => (window === "month" ? "this month" : "this week");

// One line per kind of exclusion, in words: what was left out and why.
function notesHtml(row) {
  const notes = [];
  const days = row.day_reasons || [];
  if (days.length) {
    const total = days.reduce((sum, reason) => sum + reason.days, 0);
    const why = days.map((reason) => `${escapeHtml(reason.label)} ×${reason.days}`).join(", ");
    notes.push(`${dayWord(total)} left out: ${why}`);
  }
  for (const order of row.excluded_orders || []) {
    notes.push(`${escapeHtml(order.number)} left out: ${escapeHtml(order.label)}`);
  }
  return notes.map((text) => `<span class="hub-leaderboard-pending">${text}</span>`).join("");
}

function rowHtml(row) {
  const classes = ["hub-leaderboard-row"];
  if (row.rank && row.rank <= 3) classes.push("hub-leaderboard-top");
  if (row.below_floor) classes.push("hub-performance-unranked");
  return `<tr class="${classes.join(" ")}">
      <td class="hub-leaderboard-rank">${rankHtml(row.rank)}</td>
      <th scope="row">${escapeHtml(userName(row.user))}${notesHtml(row)}</th>
      <td class="hub-leaderboard-num hub-performance-score">${row.score}</td>
      <td class="hub-leaderboard-num">${escapeHtml(formatMoney(row.billed_dollars))}</td>
      <td class="hub-leaderboard-num">${row.efficiency_pct}%</td>
      <td class="hub-leaderboard-num">${row.accuracy_pct}%</td>
      <td class="hub-leaderboard-num">${row.counted_days} / ${row.active_days}</td>
      <td class="hub-leaderboard-num">${formatHm(row.clocked_minutes)}</td>
    </tr>`;
}

function bodyHtml(payload) {
  const ranked = payload.rows.filter((row) => !row.below_floor);
  const unranked = payload.rows.filter((row) => row.below_floor);
  const divider = unranked.length
    ? `<tr class="hub-performance-divider"><td colspan="8">Below ${Math.round(payload.floor_minutes / 60)} h ${windowWord(payload.window)}</td></tr>`
    : "";
  return [...ranked.map(rowHtml), divider, ...unranked.map(rowHtml)].join("");
}

export function mountPerformanceBoard(container, payload) {
  const table = payload.rows.length
    ? `<div class="hub-hours-table-wrap hub-leaderboard-wrap">
        <table class="hub-hours-table hub-leaderboard-table">
          <caption class="sr-only">Performance for ${escapeHtml(payload.start)} through ${escapeHtml(payload.end)}</caption>
          <thead><tr>
            <th scope="col">Rank</th><th scope="col">Person</th><th scope="col">Score</th>
            <th scope="col">Billed $</th><th scope="col">Efficiency</th><th scope="col">Accuracy</th>
            <th scope="col">Clean days</th><th scope="col">Clocked</th>
          </tr></thead>
          <tbody>${bodyHtml(payload)}</tbody>
        </table>
      </div>`
    : `<p class="hint hub-leaderboard-empty">Nobody has trusted time ${windowWord(payload.window)} yet.</p>`;
  container.innerHTML = `<section class="hub-leaderboard" aria-label="Performance board">${table}</section>`;
}
