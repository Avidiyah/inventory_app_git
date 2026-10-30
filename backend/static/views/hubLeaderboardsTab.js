// View: the User Hub's Admin **Leaderboards** tabpanel -- one performance
// board for a week or a month to date, with a Week / Month switch.
//
// Layer: views. Owns its own window and fetch (`GET /hub/performance`), so
// paging here never moves Timesheets. Every tab entry refetches; the skeleton
// shows only before the first payload.

import { apiGetHubPerformance } from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { skeletonCard } from "../skeleton.js";
import { tipHtml } from "../tooltip.js";
import { mountPerformanceBoard } from "./hubPerformanceBoard.js";
import { isoDate, shiftMonday, weekLabel } from "./hubWeek.js";

let window_ = "week";
let start = null;        // null = the window in progress
let current = {};        // per window: the start the server gave for `null`
let payload = null;
let requestId = 0;

const WORD = { week: "week", month: "month" };

function monthLabel(iso, toDate) {
  const text = isoDate(iso).toLocaleDateString([], { month: "long", year: "numeric", timeZone: "UTC" });
  return toDate ? `${text} (to date)` : text;
}

function shiftMonth(iso, months) {
  const first = isoDate(iso);
  first.setUTCMonth(first.getUTCMonth() + months, 1);
  return first.toISOString().slice(0, 10);
}

function shiftStart(iso, step) {
  return window_ === "month" ? shiftMonth(iso, step) : shiftMonday(iso, step * 7);
}

function render(panelEl) {
  const word = WORD[window_];
  const label = window_ === "month"
    ? monthLabel(payload.start, payload.to_date)
    : weekLabel(payload.start, payload.end);
  const atCurrent = current[window_] && payload.start >= current[window_];
  const switchButton = (name, text) =>
    `<button type="button" class="secondary-btn" data-window="${name}" aria-pressed="${window_ === name}">${text}</button>`;
  panelEl.innerHTML = `<div class="hub-hours-toolbar">
      <div class="hub-leaderboards-switch" role="group" aria-label="Window">
        ${switchButton("week", "Week")}${switchButton("month", "Month")}
      </div>
      <div class="hub-hours-week-nav">
        <button type="button" class="secondary-btn hub-leaderboards-prev" aria-label="Previous ${word}">◀</button>
        <strong>${escapeHtml(label)}</strong>
        <button type="button" class="secondary-btn hub-leaderboards-next" aria-label="Next ${word}"${atCurrent ? " disabled" : ""}>▶</button>
      </div>
      ${tipHtml("hub.leaderboard")}
    </div>
    <div class="hub-leaderboards-board"></div>`;
  mountPerformanceBoard(panelEl.querySelector(".hub-leaderboards-board"), payload);
  for (const button of panelEl.querySelectorAll(".hub-leaderboards-switch [data-window]")) {
    button.addEventListener("click", () => {
      if (button.dataset.window === window_) return;
      window_ = button.dataset.window;
      start = null;
      void load(panelEl);
    });
  }
  panelEl.querySelector(".hub-leaderboards-prev").addEventListener("click", () => {
    start = shiftStart(payload.start, -1);
    void load(panelEl);
  });
  panelEl.querySelector(".hub-leaderboards-next").addEventListener("click", () => {
    start = shiftStart(payload.start, 1);
    if (current[window_] && start >= current[window_]) start = null;
    void load(panelEl);
  });
}

async function load(panelEl) {
  const id = ++requestId;
  if (!payload) panelEl.innerHTML = `<div class="skel-grid">${skeletonCard({ lines: 6 })}</div>`;
  try {
    const next = await apiGetHubPerformance({ window: window_, start });
    if (id !== requestId) return;
    if (start === null) current[next.window] = next.start;
    payload = next;
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
  window_ = "week";
  start = null;
  current = {};
  payload = null;
  requestId += 1;
  panelEl?.replaceChildren();
}
