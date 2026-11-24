// Shared tutorial player -- the "How this page works" walk-throughs.
//
// Layer: shared helper (same tier as tooltip.js). Scripts are data in
// `tutorials/<page>.js`; sample records in `tutorials/<page>.sample.js`;
// `tutorials/index.js` maps a page to both. This module owns one overlay, the
// page buttons and the run. It never imports nav.js (nav imports it):
// `installTutorials` is handed `getActivePage`/`showPage`.
//
// Specs: docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md.
// Positions go through CSSOM (`el.style.left = ...`): the CSP drops `style=`.

import { setSampleResponder } from "./api.js";
import { messageDialog } from "./dom.js";
import { getCurrentUser } from "./state.js";
import { roleAtLeast } from "./roles.js";
import { mark } from "./tutorialProgress.js";
import { closeTip } from "./tooltip.js";
import { alreadyOpen, endReason, isTargetless, placeTargetless, restoreHubTab,
  snapshotHubTab } from "./tutorialStandalone.js";
import { WAIT_MS, blockKeys, clearExpectNav, expectNav, forwardTap, isExpectingNav, isWaitStep,
  resolveWait, roleVisible } from "./tutorialWait.js";

const GAP = 12;          // px between target and box, and from the screen edge
const PAD = 6;           // px of light around the lit target
const OPEN_WAIT_MS = 3000;
const POLL_MS = 50;
const SETTLE_MS = 300;   // visible steps unchanged this long = page has loaded
const RELOAD_WAIT_MS = 400; // start: the page's own reload lands first
const BUSY_TEXT = "Finish or end the current batch, then start the tutorial.";
const REFUSE_TEXT = "Finish or save what you typed, then start the tutorial. It reloads the page.";

// jsdom has no layout, so tests rely on the attribute rules alone; a real
// browser also drops anything CSS hides (no box to light).
const HAS_LAYOUT = !/jsdom/i.test(globalThis.navigator?.userAgent || "");

let deps = null;
let installed = false;
let running = null;      // { page, restore } while a tutorial is up
let run = null;          // the step run in progress (runSteps)
let nodes = null;
let unblockKeys = null;

// --- visibility and step selection ------------------------------------------

const strip = (sel) => (sel.startsWith("?") ? sel.slice(1) : sel);

// Visible = connected, not inside [hidden], not inside a closed <details>
// (its own <summary> excepted) and, in a browser, laid out.
export function isVisible(el) {
  if (!el || !el.isConnected || el.closest("[hidden]")) return false;
  for (let d = el.closest("details"); d; d = d.parentElement?.closest("details")) {
    if (d.open) continue;
    const summary = d.querySelector(":scope > summary");
    if (!summary || !summary.contains(el)) return false;
  }
  return !HAS_LAYOUT || el.getClientRects().length > 0;
}

const visibleSel = (sel) => isVisible(document.querySelector(sel));

export function sentences(step, role) {
  const v = step.textFor?.[role] ?? step.text;
  return Array.isArray(v) ? v : [v];
}

// A wait step is kept when its role can see `waitTap`; if not, it and the steps
// up to the next wait (they describe the page it opens) are dropped. Steps
// after a kept wait are not judged now: their page is not open yet.
export function visibleSteps(script, role) {
  const out = [];
  let skipping = false, afterWait = false;
  for (const step of script.steps) {
    if (isWaitStep(step)) {
      skipping = !roleVisible(document.querySelector(step.waitTap));
      afterWait = !skipping;
      if (skipping) continue;
    } else if (skipping || (!afterWait && !isTargetless(step) && !isVisible(document.querySelector(step.target)))) continue;
    out.push({ step, lines: sentences(step, role) });
  }
  return out;
}

// The last script for this role, in file order, whose `here` matches the
// page; else the first one for this role.
export function pickScript(scripts, role = getCurrentUser()?.role) {
  const mine = scripts.filter((s) => !s.minRole || roleAtLeast(role, s.minRole));
  let pick = mine[0] || scripts[0];
  for (const s of mine) if (s.here && document.querySelector(s.here)) pick = s;
  return pick;
}

// A later script for this role whose tab is reachable now (its last `open`
// selector exists).
function nextScript(scripts, current, role) {
  const later = scripts.slice(scripts.indexOf(current) + 1);
  return later.find((s) => (!s.minRole || roleAtLeast(role, s.minRole)) &&
    s.open?.length && document.querySelector(strip(s.open[s.open.length - 1]))) || null;
}

// --- placement (pure) -------------------------------------------------------

// Below the target, else above, else pinned to the bottom; never off-screen.
export function placeBox(rect, box, viewport) {
  const width = Math.min(box.width, viewport.width - 2 * GAP);
  const left = Math.max(GAP, Math.min(rect.left + rect.width / 2 - width / 2, viewport.width - width - GAP));
  if (rect.bottom + GAP + box.height <= viewport.height - GAP) return { left, top: rect.bottom + GAP, mode: "below" };
  if (rect.top - GAP - box.height >= GAP) return { left, top: rect.top - GAP - box.height, mode: "above" };
  return { left, top: Math.max(GAP, viewport.height - box.height - GAP), mode: "bottom" };
}

// --- overlay ----------------------------------------------------------------

function ensureNodes() {
  if (nodes?.overlay.isConnected) return nodes;
  const overlay = document.createElement("div");
  overlay.className = "tut-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Page tutorial");
  overlay.innerHTML =
    '<div class="tut-spot"></div>' +
    '<div class="tut-box" tabindex="-1"><p class="tut-title"></p><p class="tut-text"></p>' +
    '<div class="tut-foot"><span class="tut-count"></span><span class="tut-actions"></span></div></div>' +
    '<p class="tut-pill" hidden>Tap anywhere for the next step</p>' +
    '<button type="button" class="tut-act primary tut-end" data-tut-act="end">End tutorial</button>';
  overlay.addEventListener("click", onOverlayClick);
  overlay.addEventListener("wheel", (e) => e.preventDefault(), { passive: false });
  overlay.addEventListener("touchmove", (e) => e.preventDefault(), { passive: false });
  document.body.appendChild(overlay);
  const q = (c) => overlay.querySelector(c);
  nodes = { overlay, spot: q(".tut-spot"), box: q(".tut-box"), title: q(".tut-title"), text: q(".tut-text"),
    count: q(".tut-count"), actions: q(".tut-actions"), pill: q(".tut-pill"), end: q(".tut-end") };
  unblockKeys = blockKeys(onKey);
  window.addEventListener("resize", place);
  window.addEventListener("scroll", place, { capture: true, passive: true });
  return nodes;
}

function teardown() {
  unblockKeys?.();
  unblockKeys = null;
  window.removeEventListener("resize", place);
  window.removeEventListener("scroll", place, { capture: true });
  nodes?.overlay.remove();
  nodes = null;
}

function button(act, label) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = act === "next" || act === "done" ? "tut-act primary" : "tut-act";
  b.dataset.tutAct = act;
  b.textContent = label;
  return b;
}

// The element the current step lights (a wait step's is re-resolved each time).
function litEl() {
  const { step } = run.list[run.i];
  if (isTargetless(step)) return null;
  return isWaitStep(step) ? resolveWait(step).el : document.querySelector(step.target);
}

function place() {
  if (!run || !nodes) return;
  if (placeTargetless(run.list[run.i].step, nodes)) return;
  const el = litEl();
  if (!el) return; // vanished mid-refresh: keep the last position
  const r = el.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = { left: Math.max(0, r.left - PAD), top: Math.max(0, r.top - PAD),
    right: Math.min(vw, r.right + PAD), bottom: Math.min(vh, r.bottom + PAD) };
  rect.width = Math.max(0, rect.right - rect.left);
  rect.height = Math.max(0, rect.bottom - rect.top);
  Object.assign(nodes.spot.style, { left: `${rect.left}px`, top: `${rect.top}px`,
    width: `${rect.width}px`, height: `${rect.height}px` });
  if (nodes.box.hidden) return;
  const b = nodes.box.getBoundingClientRect();
  const p = placeBox(rect, { width: b.width, height: b.height }, { width: vw, height: vh });
  nodes.box.style.left = `${Math.round(p.left)}px`;
  nodes.box.style.top = `${Math.round(p.top)}px`;
}

function render({ scroll = false } = {}) {
  const { list, i, s } = run;
  const { step } = list[i];
  const wait = isWaitStep(step);
  const lines = wait ? [run.kind === "via" && step.viaText ? step.viaText : list[i].lines[0]] : list[i].lines;
  const last = i === list.length - 1;
  nodes.title.textContent = step.title || "";
  nodes.text.textContent = lines[s];
  nodes.count.textContent = `${i + 1} of ${list.length}`;
  nodes.actions.replaceChildren();
  const end = last && s === lines.length - 1;
  if (end) {
    if (run.next) nodes.actions.appendChild(button("next", `Next: ${run.next.title}`));
    nodes.actions.appendChild(button("done", "Done"));
  }
  nodes.box.hidden = run.boxHidden;
  nodes.pill.hidden = wait || end; // a tap anywhere does something on every other step
  nodes.pill.textContent = `${window.matchMedia?.("(pointer: coarse)").matches ? "Tap" : "Click"} anywhere for the next step`;
  if (scroll && !wait && !isTargetless(step)) document.querySelector(step.target)?.scrollIntoView?.({ block: "center" });
  place();
  requestAnimationFrame(place);
  if (!run.boxHidden) (nodes.actions.querySelector("button") || nodes.box).focus();
}

function show(i) {
  const step = run.list[i].step;
  Object.assign(run, { i, s: 0, boxHidden: false, pending: 0, idle: Date.now(),
    kind: isWaitStep(step) ? resolveWait(step).kind : null });
  // Reaching the last visible step is finishing (0b spec 5.3); End early never does.
  if (i === run.list.length - 1 && run.key) mark(run.key, "completed");
  render({ scroll: true });
}

// One tap: next sentence, else hide the box, else next step. The last step's
// box stays up until Next, Done or End.
function tap(event) {
  if (!run) return;
  if (isWaitStep(run.list[run.i].step)) { forward(event); return; }
  const { list, i, s } = run;
  if (s < list[i].lines.length - 1) { run.s += 1; render(); return; }
  if (i === list.length - 1) return;
  if (!run.boxHidden) { run.boxHidden = true; render(); return; }
  show(i + 1);
}

// A wait step: the person's tap (or Enter) goes to the lit control only.
function forward(event) {
  const el = litEl();
  if (run.pending || !el) return;
  const page = run.kind === "tap"; // waitTap itself: the page may change under us
  const hit = forwardTap(event, el, PAD, () => { if (page) { run.pending = Date.now(); expectNav(); } });
  if (hit && !page) tickWait(); // the opener was tapped: light waitTap now
}

// Every POLL_MS on scripts with a wait step: after waitTap, show the next
// step once its target is up (else end quietly after WAIT_MS); on a wait step,
// follow the lit control (via -> waitTap) and end quietly when none shows.
function tickWait() {
  if (!run) return;
  const nxt = run.list[run.i + 1];
  if (run.pending) {
    if (!nxt) finish({ result: "done" });
    else if (isWaitStep(nxt.step) || isVisible(document.querySelector(nxt.step.target))) { clearExpectNav(); show(run.i + 1); }
    else if (Date.now() - run.pending >= WAIT_MS) finish({ result: "end" });
    return;
  }
  if (!isWaitStep(run.list[run.i].step)) return;
  const { kind } = resolveWait(run.list[run.i].step);
  if (kind !== run.kind) { run.kind = kind; render(); } else place();
  if (kind === "tap" || kind === "via") run.idle = Date.now();
  else if (Date.now() - run.idle >= WAIT_MS) finish({ result: "end" });
}

function finish(result) {
  const r = run;
  run = null;
  if (r) { clearInterval(r.timer); clearExpectNav(); }
  r?.resolve(result);
}

function onOverlayClick(event) {
  event.stopPropagation();
  const act = event.target.closest?.("[data-tut-act]")?.dataset.tutAct;
  if (!act) { tap(event); return; }
  if (act === "next") finish({ result: "next", script: run.next });
  else finish({ result: act }); // "done" | "end"
}

function onKey(event) {
  if (!run) return;
  event.stopPropagation();
  const onButton = event.target.closest?.("[data-tut-act]");
  if (event.key === "Escape") { event.preventDefault(); finish({ result: "end" }); return; }
  if (event.key === "Enter" && onButton) return; // the button's own click
  if (event.key === "Enter" || event.key === "ArrowRight") { event.preventDefault(); tap(); return; }
  if (event.key === "Tab") {
    const btns = [...nodes.actions.querySelectorAll("button"), nodes.end];
    if (!btns.length) { event.preventDefault(); return; }
    const at = btns.indexOf(document.activeElement);
    const to = event.shiftKey ? (at <= 0 ? btns.length - 1 : at - 1) : (at + 1) % btns.length;
    event.preventDefault();
    btns[to].focus();
    return;
  }
  event.preventDefault();
}

// Plays one script's visible steps. Resolves { result: "done" | "end" | "next",
// script? } when the box closes; "empty" when no step is visible.
export function runSteps(script, role, { scripts = [script] } = {}) {
  const list = visibleSteps(script, role);
  if (!list.length) return Promise.resolve({ result: "empty" });
  ensureNodes();
  return new Promise((resolve) => {
    run = { list, i: 0, s: 0, boxHidden: false, resolve, key: script.key, next: nextScript(scripts, script, role) };
    if (script.key) mark(script.key, "seen");
    show(0);
    if (list.some(({ step }) => isWaitStep(step))) run.timer = setInterval(tickWait, POLL_MS);
  });
}

// --- session ----------------------------------------------------------------

function waitFor(fn, ms) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      const v = fn();
      if (v || Date.now() - start >= ms) resolve(v || null);
      else setTimeout(tick, POLL_MS);
    };
    tick();
  });
}

// Clicks `script.open` in order to reach its tab. A click is skipped when what
// it reveals is already visible (an open section is never toggled shut); a
// leading `?` marks a selector optional (absent = skipped at once). Resolves
// false when the tab never appears.
// A late re-render can wipe the clicks (a list reload landing after them), so
// a failed open is tried once more.
export async function runOpen(script, role = getCurrentUser()?.role) {
  return (await openOnce(script, role)) || (await openOnce(script, role));
}

async function openOnce(script, role) {
  const sels = script.open || [];
  const firstTargetVisible = () => visibleSteps(script, role).length > 0;
  for (let i = 0; i < sels.length; i += 1) {
    const optional = sels[i].startsWith("?");
    const sel = strip(sels[i]);
    // The last click reveals the script's tab: judged by `here` (that tab is
    // selected) when the script names one, else by its first step showing.
    const revealed = i + 1 < sels.length ? () => visibleSel(strip(sels[i + 1]))
      : script.here ? () => Boolean(document.querySelector(script.here)) : firstTargetVisible;
    if (revealed()) continue;
    const el = optional ? document.querySelector(sel) : await waitFor(() => document.querySelector(sel), OPEN_WAIT_MS);
    if (!el) { if (optional) continue; return false; }
    if (alreadyOpen(el)) continue; // an open toggle is never clicked shut
    el.focus?.();
    el.click();
  }
  if (!(await waitFor(firstTargetVisible, OPEN_WAIT_MS))) return false;
  // Later targets may still be loading (a list behind a fetch): wait until the
  // visible step count holds for SETTLE_MS, capped at OPEN_WAIT_MS.
  let last = -1, stableSince = Date.now();
  await waitFor(() => {
    const n = visibleSteps(script, role).length;
    if (n !== last) { last = n; stableSince = Date.now(); }
    return Date.now() - stableSince >= SETTLE_MS;
  }, OPEN_WAIT_MS);
  return true;
}

export function makeResponder(map) {
  return (path) => map["GET " + path];
}

const TEXT_TYPES = new Set(["text", "number", "email", "tel", "url"]);

function hasUnsavedText(page) {
  const root = document.getElementById(`${page}-page`);
  if (!root) return false;
  return [...root.querySelectorAll("textarea, input")].some((el) =>
    (el.tagName === "TEXTAREA" || TEXT_TYPES.has(el.type)) && el.value.trim() !== "");
}

// `onEnd(reason)`: "done" (Done tapped) or "ended" (End, Esc, leaving, nothing to
// show), called once after teardown. A standalone entry (`standalone: true`, no
// sample) also puts the Hub tab it began on back.
export async function startTutorial(page, key = null, { onEnd } = {}) {
  const entry = deps?.tutorials[page];
  if (running || !entry) { onEnd?.("ended"); return; }
  // A page marks live work (an open scanning batch) with [data-tutorial-busy].
  // An entry with no sample (the starter tours) reloads nothing and blocks all
  // input, so neither refusal applies to it.
  const busy = entry.sample && document.querySelector(`#${page}-page [data-tutorial-busy]`);
  if (busy && !busy.closest("[hidden]")) { messageDialog(BUSY_TEXT); onEnd?.("ended"); return; }
  if (entry.sample && hasUnsavedText(page)) { messageDialog(REFUSE_TEXT); onEnd?.("ended"); return; }
  closeTip();
  let script = (key && entry.scripts.find((s) => s.key === key)) || pickScript(entry.scripts);
  running = { page, restore: Boolean(entry.sample) };
  if (entry.sample) {
    setSampleResponder(makeResponder(entry.sample(getCurrentUser())));
    deps.showPage(page);
    // The reload is async: let it land before `open` clicks anything stale.
    await new Promise((r) => setTimeout(r, RELOAD_WAIT_MS));
  }
  const role = getCurrentUser()?.role;
  const hubTab = entry.standalone ? snapshotHubTab() : null;
  let last = "end";
  while (running && script) {
    if (!(await runOpen(script, role)) || !running) break;
    const out = await runSteps(script, role, { scripts: entry.scripts });
    last = out.result;
    script = out.result === "next" ? out.script : null;
  }
  endTutorial();
  if (entry.standalone) restoreHubTab(hubTab);
  onEnd?.(endReason(last));
}

// Ends the tutorial by any route. `restore: false` when the caller is already
// leaving the page (nav, sign-out), so real data is not reloaded behind it.
// `fromNav` (showPage): ignored while a forwarded tap's page change is awaited.
export function endTutorial({ restore = true, fromNav = false } = {}) {
  if (fromNav && isExpectingNav()) return;
  if (!running) return;
  const r = running;
  running = null;
  finish({ result: "end" });
  teardown();
  setSampleResponder(null);
  document.dispatchEvent(new CustomEvent("tutorial:end"));
  if (restore && r.restore) deps.showPage(deps.getActivePage());
}

export function isTutorialRunning() {
  return running !== null;
}

// --- page buttons -----------------------------------------------------------

// One "How this page works" pill per indexed page: inside the page's
// `[data-tutorial-slot]` if it has one, else at the end of its first h2.
export function installTutorials(d) {
  deps = d;
  for (const page of Object.keys(d.tutorials)) {
    const root = document.getElementById(`${page}-page`);
    if (!root || root.querySelector(".tut-btn")) continue;
    const host = root.querySelector("[data-tutorial-slot]") || root.querySelector("h2");
    if (!host) continue;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tut-btn";
    b.dataset.tutPage = page;
    b.textContent = "How this page works";
    host.appendChild(b);
  }
  if (installed) return;
  installed = true;
  document.addEventListener("click", (event) => {
    const b = event.target.closest?.(".tut-btn");
    if (b) startTutorial(b.dataset.tutPage);
  });
}
