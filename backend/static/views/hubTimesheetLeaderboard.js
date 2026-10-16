// View: one weekly **leaderboard board** -- Accuracy or Efficiency.
//
// Layer: views. Pure: no fetch, no state, no buttons. `hubLeaderboardsTab.js`
// owns the week and mounts one board per kind from the same payload.
//
// One rule per column:
//   clocked   = the row's total_minutes (the server already left out
//               pending-review days, so nothing is subtracted here)
//   charged   = live work-order clock time; Efficiency adds hand-entered labor
//   uncharged = clocked - charged, never below zero
//   %         = charged / clocked, uncapped -- Efficiency can pass 100% when
//               more labor was keyed than clocked
//   made/lost = charged / uncharged x the billing labor rate
// Ranked by %, then money made, then name. This is an estimate at the hourly
// rate, not the invoice: billing rounds a work order's labor up to 30 minutes.

import { escapeHtml, formatMoney } from "../format.js";
import { tipHtml } from "../tooltip.js";
import { formatHm } from "./hubWeek.js";

const MEDALS = ["🥇", "🥈", "🥉"];
const TITLES = { accuracy: "Accuracy", efficiency: "Efficiency" };

function userName(user) {
  return `${user?.first_name || ""} ${user?.last_name || ""}`.trim() || "Unknown";
}

function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
}

// Pure: the ranked rows and the company total. Exported for the tests.
export function computeLeaderboard(payload, { kind = "accuracy" } = {}) {
  const rate = Number(payload.labor_rate) || 0;
  const price = (minutes) => (minutes * rate) / 60;
  const entries = payload.rows.map((row) => {
    const clocked = row.total_minutes || 0;
    const charged = (row.tracked_minutes || 0) + (kind === "efficiency" ? row.adjustment_minutes || 0 : 0);
    const uncharged = Math.max(0, clocked - charged);
    return {
      user: row.user,
      name: userName(row.user),
      pendingDays: row.days.filter((day) => day.pending_review).length,
      clocked,
      charged,
      uncharged,
      pct: clocked ? Math.round((charged / clocked) * 100) : (charged ? 100 : 0),
      made: price(charged),
      lost: price(uncharged),
    };
  });
  entries.sort((a, b) => b.pct - a.pct || b.made - a.made || a.name.localeCompare(b.name));
  entries.forEach((entry, index) => { entry.rank = index + 1; });
  const total = entries.reduce((sum, entry) => ({
    clocked: sum.clocked + entry.clocked,
    charged: sum.charged + entry.charged,
    uncharged: sum.uncharged + entry.uncharged,
    made: sum.made + entry.made,
    lost: sum.lost + entry.lost,
  }), { clocked: 0, charged: 0, uncharged: 0, made: 0, lost: 0 });
  return { rate, entries, total };
}

function rankHtml(rank) {
  const medal = MEDALS[rank - 1];
  return medal
    ? `<span aria-hidden="true">${medal}</span><span class="sr-only">${ordinal(rank)}</span>`
    : escapeHtml(String(rank));
}

function pendingHtml(entry) {
  if (!entry.pendingDays) return "";
  const days = entry.pendingDays === 1 ? "1 day" : `${entry.pendingDays} days`;
  return `<span class="hub-leaderboard-pending">⚠ ${days} pending review</span>`;
}

function moneyCells(row) {
  return `<td class="hub-leaderboard-num">${formatHm(row.clocked)}</td>
      <td class="hub-leaderboard-num">${formatHm(row.charged)}</td>
      <td class="hub-leaderboard-num">${formatHm(row.uncharged)}</td>
      <td class="hub-leaderboard-num hub-leaderboard-made">${escapeHtml(formatMoney(row.made))}</td>
      <td class="hub-leaderboard-num hub-leaderboard-lost">${escapeHtml(formatMoney(row.lost))}</td>`;
}

function rowHtml(entry) {
  return `<tr class="hub-leaderboard-row${entry.rank <= 3 ? " hub-leaderboard-top" : ""}">
      <td class="hub-leaderboard-rank">${rankHtml(entry.rank)}</td>
      <th scope="row">${escapeHtml(entry.name)}${pendingHtml(entry)}</th>
      <td class="hub-leaderboard-num hub-leaderboard-pct">${entry.pct}%</td>
      ${moneyCells(entry)}
    </tr>`;
}

export function mountLeaderboardBoard(container, payload, { kind = "accuracy" } = {}) {
  const { entries, total } = computeLeaderboard(payload, { kind });
  const title = TITLES[kind];
  const headingId = `hub-leaderboard-heading-${kind}`;
  const table = entries.length
    ? `<div class="hub-hours-table-wrap hub-leaderboard-wrap">
        <table class="hub-hours-table hub-leaderboard-table">
          <caption class="sr-only">${title} leaderboard for ${escapeHtml(payload.week_start)} through ${escapeHtml(payload.week_end)}</caption>
          <thead><tr>
            <th scope="col">Rank</th><th scope="col">Person</th><th scope="col">%</th>
            <th scope="col">Clocked</th><th scope="col">Charged</th><th scope="col">Uncharged</th>
            <th scope="col">Made</th><th scope="col">Lost</th>
          </tr></thead>
          <tbody>${entries.map(rowHtml).join("")}</tbody>
          <tfoot><tr>
            <td></td><th scope="row">Company total</th><td></td>
            ${moneyCells(total)}
          </tr></tfoot>
        </table>
      </div>`
    : `<p class="hint hub-leaderboard-empty">Nobody clocked in this week.</p>`;
  container.innerHTML = `<section class="hub-leaderboard" aria-labelledby="${headingId}">
      <h3 id="${headingId}" class="hub-leaderboard-heading">${title} ${tipHtml(`hub.leaderboard-${kind}`)}</h3>
      ${table}
    </section>`;
}
