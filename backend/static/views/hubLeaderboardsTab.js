// View: the User Hub's Admin **Leaderboards** tabpanel -- an Accuracy board
// and an Efficiency board for one week, side by side.
//
// Layer: views. Owns its own week and fetch (`GET /hub/attendance/week`, the
// payload the Timesheets tab reads), so paging here never moves Timesheets.
// Every tab entry refetches; the skeleton shows only before the first payload.

import { apiGetHubAttendanceWeek } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { skeletonCard } from "../skeleton.js";
import { tipHtml } from "../tooltip.js";
import { mountLeaderboardBoard } from "./hubTimesheetLeaderboard.js";
import { shiftMonday, weekLabel } from "./hubWeek.js";

let week = null;
let payload = null;
let requestId = 0;

function render(panelEl) {
  panelEl.innerHTML = `<div class="hub-hours-toolbar">
      <div class="hub-hours-week-nav">
        <button type="button" class="secondary-btn hub-leaderboards-prev" aria-label="Previous week">◀</button>
        <strong>${escapeHtml(weekLabel(payload.week_start, payload.week_end))}</strong>
        <button type="button" class="secondary-btn hub-leaderboards-next" aria-label="Next week">▶</button>
      </div>
      ${tipHtml("hub.leaderboard")}
    </div>
    <div class="hub-leaderboards-grid">
      <div class="hub-leaderboards-accuracy"></div>
      <div class="hub-leaderboards-efficiency"></div>
    </div>`;
  for (const kind of ["accuracy", "efficiency"]) {
    mountLeaderboardBoard(panelEl.querySelector(`.hub-leaderboards-${kind}`), payload, { kind });
  }
  panelEl.querySelector(".hub-leaderboards-prev").addEventListener("click", () => {
    week = shiftMonday(payload.week_start, -7);
    void load(panelEl);
  });
  panelEl.querySelector(".hub-leaderboards-next").addEventListener("click", () => {
    week = shiftMonday(payload.week_start, 7);
    void load(panelEl);
  });
}

async function load(panelEl) {
  const id = ++requestId;
  if (!payload) panelEl.innerHTML = `<div class="skel-grid">${skeletonCard({ lines: 6 }).repeat(2)}</div>`;
  try {
    const next = await apiGetHubAttendanceWeek({ week });
    if (id !== requestId) return;
    payload = next;
    week = next.week_start;
    render(panelEl);
  } catch (err) {
    if (id !== requestId) return;
    const message = escapeHtml(friendlyError(err, "Could not load the leaderboards."));
    panelEl.innerHTML = `<p class="hub-hours-message error">${message} <button type="button" class="secondary-btn hub-leaderboards-retry">Retry</button></p>`;
    panelEl.querySelector(".hub-leaderboards-retry").addEventListener("click", () => { void load(panelEl); });
  }
}

export function renderLeaderboardsTab(panelEl) {
  if (!panelEl) return;
  if (payload) render(panelEl);
  void load(panelEl);
}

// A different person signed in, or this viewer lost the tab.
export function resetLeaderboardsTab(panelEl) {
  week = null;
  payload = null;
  requestId += 1;
  panelEl?.replaceChildren();
}
