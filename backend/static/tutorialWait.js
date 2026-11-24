// Wait-for-tap steps of the tutorial player (tutorials 5, "starter" tours).
//
// Layer: shared helper owned by tutorial.js (imports nothing). A wait step
// `{ waitTap, via?, viaText?, text }` lights a real control and forwards the
// person's tap to it; everything else on screen stays blocked. `via` is lit
// first while `waitTap` has no box (a closed menu popover).
//
// Visibility of a wait control is judged by layout (`getClientRects`) because a
// closed popover is hidden by CSS only; role-hidden controls are `[hidden]`.

export const WAIT_MS = 3000; // next target / lit control must show within this

let expecting = null;        // timer while a forwarded page tap may change page

export const isWaitStep = (step) => Boolean(step.waitTap);

export const hasRects = (el) => Boolean(el?.isConnected && el.getClientRects().length > 0);

// Role test: the control exists and nothing hides it with [hidden].
export const roleVisible = (el) => Boolean(el?.isConnected && !el.closest("[hidden]"));

// { el, kind }: "tap" (waitTap has a box), "via" (light the opener first),
// "none" (role-visible, no box yet), "skip" (this role never sees it).
export function resolveWait(step) {
  const tap = document.querySelector(step.waitTap);
  if (!roleVisible(tap)) return { el: null, kind: "skip" };
  if (hasRects(tap)) return { el: tap, kind: "tap" };
  // `via` may list several selectors (desktop toggle, phone picker): first one on screen wins.
  const via = step.via ? [...document.querySelectorAll(step.via)].find((v) => roleVisible(v) && hasRects(v)) : null;
  if (via) return { el: via, kind: "via" };
  return { el: null, kind: "none" };
}

// Clicks `el` when the tap landed inside it (plus `pad`); a keyboard event
// (no coordinates) always forwards. `before` runs just ahead of the click.
export function forwardTap(event, el, pad, before) {
  if (!el) return false;
  if (event?.clientX !== undefined) {
    const r = el.getBoundingClientRect();
    if (event.clientX < r.left - pad || event.clientX > r.right + pad ||
        event.clientY < r.top - pad || event.clientY > r.bottom + pad) return false;
  }
  before?.();
  el.click();
  return true;
}

// Whole-run key lock: `onKeydown` is the player's handler; every keyup is
// swallowed except on the box's own buttons, so a focused page button never
// activates on Space. Returns the remover.
export function blockKeys(onKeydown) {
  const onKeyup = (event) => {
    if (event.target.closest?.("[data-tut-act]")) return;
    event.preventDefault();
    event.stopPropagation();
  };
  document.addEventListener("keydown", onKeydown, true);
  document.addEventListener("keyup", onKeyup, true);
  return () => {
    document.removeEventListener("keydown", onKeydown, true);
    document.removeEventListener("keyup", onKeyup, true);
  };
}

// --- page change caused by the forwarded tap --------------------------------

export function expectNav() {
  clearTimeout(expecting);
  expecting = setTimeout(() => { expecting = null; }, WAIT_MS);
}

export function clearExpectNav() {
  clearTimeout(expecting);
  expecting = null;
}

export const isExpectingNav = () => expecting !== null;
