// Patch a container in place instead of wiping and rebuilding it.
//
// Layer: shared helper. Callers: the Work Orders list and card body, the User
// Requests page. The comparing is idiomorph's; this adds two rules: `open` on
// a <details> belongs to the user, and elements that are new or changed can be
// flagged with `just-changed` for a one-shot highlight. `isDirty` and
// `keepPlace` are the pieces every live page needs around a patch.

import { Idiomorph } from "./vendor/idiomorph-0.8.0.esm.js";

const FLASH = "just-changed";
const cleaned = new WeakSet();

// The value a field had when it was drawn. A select with no `selected`
// option shows its first, so that one is its default (not a typed value).
export function defaultOf(field) {
  if (field.localName === "select") {
    const options = [...field.options];
    return (options.find((o) => o.defaultSelected) || options[0])?.value ?? "";
  }
  if (field.type === "checkbox" || field.type === "radio") return String(field.defaultChecked);
  return field.defaultValue;
}

export function isDirty(field) {
  if (field.type === "checkbox" || field.type === "radio") return field.checked !== field.defaultChecked;
  return field.value !== defaultOf(field);
}

function selectionOf(el) {
  try {
    return el.selectionStart === null || el.selectionStart === undefined ? null : [el.selectionStart, el.selectionEnd];
  } catch {
    return null;
  }
}

// Call before a patch of `container`; call the returned function after it.
// Puts back focus and caret (iOS Safari has no moveBefore, so a moved element
// loses focus there) and, where the browser does not anchor scrolling itself,
// the reading position: the focused element, else the first child on screen.
export function keepPlace(container) {
  const active = document.activeElement;
  const inside = container.contains(active) && active !== container;
  const caret = inside ? selectionOf(active) : null;
  let anchor = inside ? active : null;
  let anchorTop = anchor?.getBoundingClientRect().top;
  for (const el of anchor ? [] : container.children) {
    const rect = el.getBoundingClientRect();
    if (rect.bottom > 0) {
      [anchor, anchorTop] = [el, rect.top];
      break;
    }
  }
  return () => {
    if (inside && active.isConnected && container.contains(active) && document.activeElement !== active) {
      active.focus({ preventScroll: true });
      if (caret) {
        try { active.setSelectionRange(...caret); } catch { /* not a text field */ }
      }
    }
    // Chrome and Firefox anchor scrolling themselves; a second correction jumps.
    if (!globalThis.CSS?.supports?.("overflow-anchor", "auto") && anchor?.isConnected) {
      const moved = anchor.getBoundingClientRect().top - anchorTop;
      if (moved) window.scrollBy(0, moved);
    }
  };
}

// `newNodes` is consumed (moved out of its parent). Elements matched by
// `flashSelector` must carry an id. A container that held no match before the
// call flags nothing: a first draw must not light every card.
// `skip(oldEl, newEl)` returning true leaves that element and its subtree as
// they are (called for elements only); an element absent from the new tree is
// still removed.
export function morphInto(
  container,
  newNodes,
  { flashSelector = null, flashKey = (el) => el.textContent, skip = null } = {},
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
      beforeNodeMorphed: (oldNode, newNode) => !(skip && oldNode.nodeType === 1 && skip(oldNode, newNode)),
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
