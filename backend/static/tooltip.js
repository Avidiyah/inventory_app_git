// Shared field-help tooltips -- the `?` bubbles beside labels and headings.
//
// Layer: shared helper (same tier as format.js / dom.js / skeleton.js).
// `tipHtml()` is a pure string builder that views interpolate into their
// existing `innerHTML` templates; the rest of the module owns one singleton
// bubble node and a single set of delegated listeners on `document`.
//
// See docs/superpowers/specs/2026-08-23-tooltips-design.md. The copy itself
// lives in tips.js -- markup at each anchor declares only the key.
//
// Two constraints from that spec are load-bearing here:
//
// 1. The app's CSP has no `style-src`, so it falls back to `default-src 'self'`
//    and the browser silently drops `style=` attributes parsed out of markup
//    (the same trap `views/hubTechnician.js` and `skeleton.js` document). This
//    module owns its bubble node, so it writes coordinates through CSSOM
//    (`bubble.style.left = ...`), which is outside CSP's scope. A template
//    literal emitting `style="left:…"` would fail silently.
// 2. Table wrappers set `overflow-x: auto`, which clips anything positioned
//    inside them. The bubble is therefore `position: fixed` and parented to
//    `<body>`, outside every scroll container in the page.

import { TIPS } from "./tips.js";
import { escapeHtml } from "./format.js";

// Gap in px between the trigger and the bubble, and between the bubble and the
// viewport edge when it gets clamped.
const GAP = 8;

const BUBBLE_ID = "tip-bubble";

// Desktop pointers get hover-to-open in addition to click. Touch devices only
// ever click, so this is the one branch in the module -- everything downstream
// is a single code path (spec D2).
const HOVER_CAPABLE =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(hover: hover)").matches;

let bubble = null;
let activeTrigger = null;
// True when the open was started by a click/tap. A pinned tip survives the
// pointer leaving the trigger; a hover-opened one does not.
let pinned = false;
let installed = false;

// --- markup ---------------------------------------------------------------

// The `?` trigger for `key`, as an HTML string. Views interpolate this into
// their templates exactly the way they interpolate `skeletonCard()`; static
// HTML pages hand-author the identical markup. Both paths produce the same DOM.
//
// The button carries only the key, never the copy (D1) -- the accessible name
// is looked up here, and `installTooltips()` fills it in for hand-authored
// markup that omits it.
//
// An unknown key returns the empty string rather than a `?` that opens nothing;
// a visible affordance that does nothing is worse than no affordance (§4.8).
export function tipHtml(key) {
  const tip = TIPS[key];
  if (!tip) {
    console.warn(`tooltip: unknown tip key "${key}"`);
    return "";
  }
  // escapeHtml, not textContent: these are attribute values inside a string
  // that the caller will assign to innerHTML.
  return (
    `<button type="button" class="tip-btn" data-tip="${escapeHtml(key)}"` +
    ` aria-expanded="false" aria-label="Help: ${escapeHtml(tip.label)}">?</button>`
  );
}

// --- the singleton bubble -------------------------------------------------

// One node, reused for every tip. Per-trigger bubbles would mean ~30 parked
// DOM nodes, most of them inside markup that is destroyed and rebuilt on every
// refresh -- and an orphaned bubble whose trigger was re-rendered away would
// linger on screen (§4.4).
function ensureBubble() {
  if (bubble) return bubble;
  bubble = document.createElement("div");
  bubble.className = "tip-bubble";
  bubble.id = BUBBLE_ID;
  bubble.setAttribute("role", "tooltip");
  bubble.hidden = true;
  document.body.appendChild(bubble);
  return bubble;
}

// Preferred placement is below the trigger and horizontally centred on it,
// flipping above when there is no room and clamping to the viewport so a `?`
// on a right-hand table column still shows its bubble in full.
//
// Everything here is viewport coordinates because the bubble is `fixed`, so
// there is no scroll-offset arithmetic.
function position(trigger) {
  const rect = trigger.getBoundingClientRect();
  // The bubble must be visible before it can be measured.
  const box = bubble.getBoundingClientRect();

  let top = rect.bottom + GAP;
  if (top + box.height > window.innerHeight - GAP) {
    top = rect.top - box.height - GAP;
  }
  // A bubble taller than the space both above and below still starts on screen.
  top = Math.max(GAP, top);

  let left = rect.left + rect.width / 2 - box.width / 2;
  left = Math.max(GAP, Math.min(left, window.innerWidth - box.width - GAP));

  // CSSOM, not an attribute -- see the header note on the CSP.
  bubble.style.left = `${Math.round(left)}px`;
  bubble.style.top = `${Math.round(top)}px`;
}

function openTip(trigger, isPinned) {
  const key = trigger.dataset.tip;
  const tip = TIPS[key];
  if (!tip) {
    console.warn(`tooltip: unknown tip key "${key}"`);
    trigger.hidden = true;
    return;
  }

  if (activeTrigger && activeTrigger !== trigger) closeTip();

  ensureBubble();
  // textContent, not innerHTML: tips are plain text by contract (D5), and this
  // makes that contract unbypassable rather than merely observed.
  bubble.textContent = tip.text;
  bubble.hidden = false;

  activeTrigger = trigger;
  pinned = isPinned;
  trigger.setAttribute("aria-expanded", "true");
  trigger.setAttribute("aria-describedby", BUBBLE_ID);

  position(trigger);

  // Hover-opened tips close when the pointer leaves. `pointerleave` does not
  // bubble, so this is bound to the trigger itself and torn down on close
  // rather than delegated.
  if (!isPinned) trigger.addEventListener("pointerleave", onTriggerLeave);
}

// Close the open tip, if any. Exported so the page-change path in `nav.js` can
// call it -- a `fixed` bubble left open across a page swap would hang over
// markup it has nothing to do with.
export function closeTip() {
  if (!activeTrigger) return;
  activeTrigger.removeEventListener("pointerleave", onTriggerLeave);
  activeTrigger.setAttribute("aria-expanded", "false");
  activeTrigger.removeAttribute("aria-describedby");
  activeTrigger = null;
  pinned = false;
  if (bubble) {
    bubble.hidden = true;
    bubble.textContent = "";
  }
}

function onTriggerLeave() {
  if (!pinned) closeTip();
}

// A background refresh can re-render the card the open trigger was sitting in,
// leaving the bubble anchored to a node that is no longer in the document.
// Every interaction checks first (§4.7).
function dropOrphan() {
  if (activeTrigger && !document.contains(activeTrigger)) closeTip();
}

// --- installation ---------------------------------------------------------

// Bind the delegated listeners and fill in accessible names for hand-authored
// markup. Called once from main.js.
//
// One set of listeners on `document`, matching on `closest("[data-tip]")`, is
// what makes this work for the ~half of anchors that live in markup destroyed
// and rebuilt on every refresh. Per-element listeners would need re-binding
// after every render in every view, and one missed re-bind is a silently dead
// `?` (§4.3).
export function installTooltips() {
  if (installed) return;
  installed = true;

  ensureBubble();
  labelStaticTriggers();

  document.addEventListener("click", (event) => {
    dropOrphan();
    const trigger = event.target.closest && event.target.closest("[data-tip]");
    if (!trigger) {
      closeTip();
      return;
    }
    // Second click on the open trigger toggles it shut -- the tap-to-open
    // affordance needs a tap-to-close.
    if (trigger === activeTrigger && pinned) {
      closeTip();
      return;
    }
    openTip(trigger, true);
  });

  if (HOVER_CAPABLE) {
    document.addEventListener("pointerover", (event) => {
      if (event.pointerType && event.pointerType !== "mouse") return;
      const trigger = event.target.closest && event.target.closest("[data-tip]");
      if (!trigger || trigger === activeTrigger) return;
      openTip(trigger, false);
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !activeTrigger) return;
    const trigger = activeTrigger;
    closeTip();
    // Focus goes back where the keyboard user left it.
    if (document.contains(trigger)) trigger.focus();
  });

  // The bubble is `fixed`, so it does not travel with the page -- on scroll it
  // would visibly detach from its anchor. Closing is cheaper and more honest
  // than repositioning on every scroll frame. Capture phase so scrolls inside
  // the app's own overflow containers are caught too, and passive so this can
  // never block scrolling.
  window.addEventListener("scroll", closeTip, { capture: true, passive: true });
  window.addEventListener("resize", closeTip);
}

// Static HTML partials hand-author `<button class="tip-btn" data-tip="…">?`
// without the accessible name, so that no prose lives outside tips.js. Fill it
// in here, and hide any trigger naming a key that does not exist -- an
// authoring error, so console is the right channel for it (§4.8).
function labelStaticTriggers() {
  document.querySelectorAll("[data-tip]").forEach((trigger) => {
    const tip = TIPS[trigger.dataset.tip];
    if (!tip) {
      console.warn(`tooltip: unknown tip key "${trigger.dataset.tip}"`);
      trigger.hidden = true;
      return;
    }
    if (!trigger.hasAttribute("aria-label")) {
      trigger.setAttribute("aria-label", `Help: ${tip.label}`);
    }
    if (!trigger.hasAttribute("aria-expanded")) {
      trigger.setAttribute("aria-expanded", "false");
    }
  });
}
