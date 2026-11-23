// Standalone tutorials (the welcome tour): scripts tied to no page, no sample.
//
// Layer: shared helper owned by tutorial.js (imports nothing). Holds what a
// standalone run needs beyond a page tutorial: the targetless centred step, the
// Hub tab snapshot/restore, and the `onEnd` reason. A standalone entry is
// `{ scripts, standalone: true }` (no `sample`); tutorial.js calls in here.
// Spec: docs/superpowers/specs/2026-11-23-tutorials-6-welcome-design.md 5.3.

const PICKER = "#hub-picker-toggle";

// A step with no `target` key is a centred box with nothing lit. A step that
// names a target (even a missing one) is not targetless: it is skipped instead.
export const isTargetless = (step) => step.target === undefined && !step.waitTap;

// Centres the box and parks the spot (zero size, no outline) when `step` is
// targetless, else undoes it. True when it took over placement.
export function placeTargetless(step, nodes) {
  const on = isTargetless(step);
  nodes.overlay.classList.toggle("tut-targetless", on);
  if (!on) return false;
  Object.assign(nodes.spot.style, { left: "50%", top: "50%", width: "0px", height: "0px" });
  nodes.box.style.left = "";
  nodes.box.style.top = "";
  return true;
}

// An `open` click whose control already reports aria-expanded="true" is done.
export const alreadyOpen = (el) => el.getAttribute?.("aria-expanded") === "true";

// The Hub tab that is active now (null off the Hub); restored when a standalone
// run ends, with the phone picker left collapsed either way.
export const snapshotHubTab = () => document.querySelector(".hub-tab.active");

export function restoreHubTab(tab) {
  if (tab && tab.isConnected && !tab.classList.contains("active")) tab.click(); // also collapses the picker
  const toggle = document.querySelector(PICKER);
  if (toggle && alreadyOpen(toggle)) toggle.click();
}

// What `onEnd` receives: "done" when the person tapped Done, else "ended"
// (End, Esc, leaving the page, a tab that never opened).
export const endReason = (result) => (result === "done" ? "done" : "ended");
