// View: the User Hub "Tutorials" tab (0b spec 5.6) and its red dot.
//
// Layer: views. Reads the progress cache and the catalogue synchronously; owns
// no fetch. Sub-tabs are a list of definitions, so another (e.g. Starter) is one
// more entry. Replaying a finished script sends nothing: the player only marks
// what is not yet recorded.

import { escapeHtml } from "../format.js";
import { getCurrentUser } from "../state.js";
import { hasSeen, isDone, onChange } from "../tutorialProgress.js";
import { startTutorial } from "../tutorial.js";
import { catalogue } from "../tutorials/catalogue.js";
import { audienceLabel, relevant } from "../tutorials/relevance.js";
import { showPage } from "./nav.js";

const isStarter = (e) => e.page === "starter";
// count: what the "(N)" shows; null hides it. The Starter list keeps finished
// entries (tagged Done), so its count is the unfinished number.
const SUBTABS = [
  { id: "todo", label: "To do", empty: "You have finished every tutorial.", has: (e) => !isDone(e.key), count: (l) => l.length },
  { id: "completed", label: "Completed", empty: "Nothing finished yet.", has: (e) => isDone(e.key), count: (l) => l.length },
  { id: "starter", label: "Starter", empty: "No starter tutorials for your role.", has: isStarter,
    count: (l) => l.filter((e) => !isDone(e.key)).length || null },
];
const DOT_LABEL = "Tutorials, you have not finished them all yet";

let current = SUBTABS[0].id;
let unsubscribe = null;

const mine = () => catalogue().filter((e) => relevant(e, getCurrentUser()?.role));

// The nav button's own label names the page; the Hub's button shows the user.
function pageTitle(page) {
  if (page === "user-hub") return "User Hub";
  if (page === "starter") return "Menu";
  if (page === "welcome") return "Welcome";
  const btn = document.querySelector(`.nav-btn[data-page="${page}"]`);
  return btn?.textContent.trim() || page;
}

function entryHtml(e, tag) {
  return `<button type="button" class="hub-tut-entry" data-tut-page="${escapeHtml(e.page)}" data-tut-key="${escapeHtml(e.key)}">`
    + `<span class="hub-tut-title">${escapeHtml(e.title)}</span>`
    + `<span class="hub-tut-meta">${escapeHtml(audienceLabel(e))}</span>`
    + (tag ? `<span class="hub-tut-tag">${tag}</span>` : "")
    + `</button>`;
}

function tagFor(def, e) {
  if (def.id === "starter") return isDone(e.key) ? "Done · Replay" : hasSeen(e.key) ? "Started" : "New";
  return def.id === "completed" ? "Replay" : hasSeen(e.key) ? "Started" : "";
}

function listHtml(def, list) {
  if (!list.length) return `<p class="hub-tut-empty">${def.empty}</p>`;
  if (def.id === "starter") return list.map((e) => entryHtml(e, tagFor(def, e))).join("");
  const pages = [...new Set(list.map((e) => e.page))];
  return pages.map((page) => `<section class="hub-tut-group"><h3 class="hub-tut-page">${escapeHtml(pageTitle(page))}</h3>`
    + list.filter((e) => e.page === page)
      .map((e) => entryHtml(e, tagFor(def, e)))
      .join("")
    + `</section>`).join("");
}

// "To do (3)" as plain text; the Starter count is its own span, absent at 0.
function countHtml(def, list) {
  const n = def.count(list);
  if (n === null) return "";
  return def.id === "starter" ? ` <span class="hub-tut-count">(${n})</span>` : ` (${n})`;
}

// Opens the tab on a sub-tab by id (batch 6 uses "starter").
export function setTutorialsSub(name) {
  if (SUBTABS.some((d) => d.id === name)) current = name;
}

function render(panel) {
  const all = mine();
  const lists = SUBTABS.map((def) => all.filter(def.has));
  const def = SUBTABS.find((d) => d.id === current) || SUBTABS[0];
  panel.innerHTML = `<div class="hub-tut-subtabs">`
    + SUBTABS.map((d, i) => `<button type="button" class="hub-tut-sub${d === def ? " active" : ""}" data-tut-sub="${d.id}" aria-pressed="${d === def}">${d.label}${countHtml(d, lists[i])}</button>`).join("")
    + `</div>${listHtml(def, lists[SUBTABS.indexOf(def)])}`;
}

export function repaintTutorialsTabDot() {
  const tab = document.getElementById("hub-tab-tutorials");
  if (!tab) return;
  const pending = mine().some((e) => !isDone(e.key));
  tab.classList.toggle("hub-tab-dot", pending);
  if (pending) { tab.setAttribute("aria-label", DOT_LABEL); tab.title = DOT_LABEL; }
  else { tab.removeAttribute("aria-label"); tab.removeAttribute("title"); }
}

// The dot follows the cache whether or not the tab is open.
onChange(repaintTutorialsTabDot);

export function resetHubTutorials() {
  unsubscribe?.();
  unsubscribe = null;
}

export function mountHubTutorials(panel) {
  resetHubTutorials();
  render(panel);
  repaintTutorialsTabDot();
  unsubscribe = onChange(() => { if (panel.hidden) resetHubTutorials(); else render(panel); });
  if (panel.dataset.wired) return;
  panel.dataset.wired = "1";
  panel.addEventListener("click", (event) => {
    const subBtn = event.target.closest("[data-tut-sub]");
    if (subBtn) {
      current = subBtn.dataset.tutSub;
      render(panel);
      panel.querySelector(`[data-tut-sub="${current}"]`)?.focus();
      return;
    }
    const entry = event.target.closest(".hub-tut-entry");
    if (!entry) return;
    if (!isStarter({ page: entry.dataset.tutPage }) && entry.dataset.tutPage !== "welcome") showPage(entry.dataset.tutPage);
    void startTutorial(entry.dataset.tutPage, entry.dataset.tutKey);
  });
}
