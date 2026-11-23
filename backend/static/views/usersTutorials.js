// Tutorial progress on the Users page (0b spec 5.8): the "N of M tutorials"
// line on each row and the not-finished list on a profile.
//
// Layer: views. Owns the GET /tutorials/progress/users map and the catalogue.
// relevance.js and catalogue.js reach nav.js, which imports users.js, so they
// load dynamically inside fetchTutorialCounts to keep this module's graph flat.

import { apiGetTutorialProgressUsers } from "../api.js";
import { escapeHtml } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { getRole } from "../state.js";

let map = null;        // user id -> [completed keys]; null = unknown, line hidden
let relevant = null;
let entries = [];
let override = null;

// Tests inject a fixture catalogue instead of the live registry.
export function setTutorialEntries(list) { override = list; }

// The endpoint is Team Lead+, the same people who can open the Users page.
export async function fetchTutorialCounts() {
  if (!roleAtLeast(getRole(), "supervisor")) { map = null; return; }
  try {
    const [data, rel, cat] = await Promise.all([
      apiGetTutorialProgressUsers(),
      import("../tutorials/relevance.js"),
      import("../tutorials/catalogue.js"),
    ]);
    relevant = rel.relevant;
    entries = override ?? cat.catalogue();
    map = data;
  } catch {
    map = null;
  }
}

function relevantFor(user) {
  return entries.filter((entry) => relevant(entry, user.role));
}

// { done, total } or null when the line should stay hidden.
export function countFor(user) {
  if (!map) return null;
  const mine = relevantFor(user);
  if (!mine.length) return null;
  const finished = new Set(map[user.id] ?? []);
  return { done: mine.filter((entry) => finished.has(entry.key)).length, total: mine.length };
}

export function tutorialTagHtml(user) {
  const count = user.archived_at ? null : countFor(user);
  return count
    ? ` <span class="muted users-tut-count">${count.done} of ${count.total} tutorials</span>`
    : "";
}

const pageLabel = (page) =>
  document.querySelector(`.nav-btn[data-page="${CSS.escape(page)}"]`)?.textContent.trim()
  || page.charAt(0).toUpperCase() + page.slice(1).replace(/-/g, " ");

// "" when the map is unknown; otherwise the unfinished scripts grouped by page.
export function tutorialBlockHtml(user) {
  if (!countFor(user)) return "";
  const finished = new Set(map[user.id] ?? []);
  const groups = new Map();
  for (const entry of relevantFor(user)) {
    if (finished.has(entry.key)) continue;
    groups.set(entry.page, [...(groups.get(entry.page) ?? []), entry.title]);
  }
  const body = groups.size
    ? [...groups].map(([page, titles]) =>
      `<li><strong>${escapeHtml(pageLabel(page))}</strong>: ${titles.map(escapeHtml).join(", ")}</li>`).join("")
    : "";
  return `<h3 class="user-profile-list-title">Tutorials</h3>${body
    ? `<p class="hint">Not finished yet:</p><ul class="users-profile-tut-list">${body}</ul>`
    : `<p class="hint">Everything finished.</p>`}`;
}
