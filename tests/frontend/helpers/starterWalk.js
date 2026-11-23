// jsdom has no layout and loads no stylesheet, so `getClientRects` is empty for
// everything. `stubClientRects()` gives it the rules of `styles.css` that matter
// to the menu: a box unless
//   - the element or an ancestor is `[hidden]`,
//   - it sits in a `.page` that is not `.active`,
//   - it is a `.nav-group-toggle` outside `#main-nav.nav-compact`,
//   - it sits in a `.nav-group-menu` without `.open` inside a compact bar.
// `getBoundingClientRect` answers a fixed box per element (stacked by document
// order, so two elements never overlap) and zeros for an element with no box.

import { afterEach } from "vitest";

const originals = [];

function boxed(el) {
  if (!el.isConnected || el.closest("[hidden]")) return false;
  const page = el.closest(".page");
  if (page && !page.classList.contains("active")) return false;
  if (el.closest(".nav-group-toggle") && !el.closest("#main-nav.nav-compact")) return false;
  const menu = el.closest(".nav-group-menu");
  if (menu && menu.closest("#main-nav.nav-compact") && !menu.classList.contains("open")) return false;
  return true;
}

function rectOf(el) {
  if (!boxed(el)) return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 };
  const top = Array.prototype.indexOf.call(document.getElementsByTagName("*"), el) * 50;
  return { left: 10, top, right: 110, bottom: top + 30, width: 100, height: 30, x: 10, y: top };
}

export function restoreClientRects() {
  while (originals.length) originals.pop()();
}

export function stubClientRects() {
  const rects = Element.prototype.getClientRects;
  const bounding = Element.prototype.getBoundingClientRect;
  Element.prototype.getClientRects = function getClientRects() {
    return boxed(this) ? [rectOf(this)] : [];
  };
  Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return rectOf(this);
  };
  originals.push(() => {
    Element.prototype.getClientRects = rects;
    Element.prototype.getBoundingClientRect = bounding;
  });
  return restoreClientRects;
}

afterEach(restoreClientRects);
