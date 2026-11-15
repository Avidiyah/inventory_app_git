// Patch a container in place instead of wiping and rebuilding it.
//
// Layer: shared helper. One caller family (the Work Orders list); other pages
// adopt it only by their own design. The comparing is idiomorph's; this adds
// two rules: `open` on a <details> belongs to the user, and elements that are
// new or changed can be flagged with `just-changed` for a one-shot highlight.

import { Idiomorph } from "./vendor/idiomorph-0.7.4.esm.js";

const FLASH = "just-changed";
const cleaned = new WeakSet();

// `newNodes` is consumed (moved out of its parent). Elements matched by
// `flashSelector` must carry an id. A container that held no match before the
// call flags nothing: a first draw must not light every card.
export function morphInto(
  container,
  newNodes,
  { flashSelector = null, flashKey = (el) => el.textContent } = {},
) {
  const before = new Map();
  if (flashSelector) {
    container.querySelectorAll(flashSelector).forEach((el) => before.set(el.id, flashKey(el)));
  }

  // The new tree never carries the flag, so the class sync below also clears
  // any flag a previous call left behind.
  Idiomorph.morph(container, newNodes, {
    morphStyle: "innerHTML",
    ignoreActiveValue: true,
    callbacks: {
      beforeAttributeUpdated: (name, node) => !(name === "open" && node.localName === "details"),
    },
  });

  if (before.size) {
    container.querySelectorAll(flashSelector).forEach((el) => {
      if (before.get(el.id) !== flashKey(el)) el.classList.add(FLASH);
    });
  }
  if (!cleaned.has(container)) {
    cleaned.add(container);
    container.addEventListener("animationend", (event) => event.target.classList.remove(FLASH));
  }
}
