// Cross-page starter walk for the guard. Clicks the real nav itself (no player),
// so it proves each wait step is reachable on the real markup for a role.
// jsdom has no layout: stubRects() applies the rules of styles.css.

import { expect } from "vitest";

const WAIT_PAGE = /^\.nav-btn\[data-page="([a-z-]+)"\]$/;

function hasRects(el) {
  for (let n = el; n; n = n.parentElement) {
    if (n.hidden) return false;
    if (n.classList.contains("page") && !n.classList.contains("active")) return false;
  }
  const compact = !!el.closest("#main-nav.nav-compact");
  if (el.classList.contains("nav-group-toggle") && !compact) return false;
  const menu = el.closest(".nav-group-menu");
  if (menu && compact && !menu.classList.contains("open")) return false;
  return true;
}

let original = null;
export function stubRects() {
  if (!original) original = Element.prototype.getClientRects;
  Element.prototype.getClientRects = function () {
    return hasRects(this) ? [{ top: 0, left: 0, width: 10, height: 10 }] : [];
  };
}
export function restoreRects() {
  if (original) Element.prototype.getClientRects = original;
  original = null;
}

const visible = (el) => !!el && el.getClientRects().length > 0;
const roleVisible = (el) => !!el && !el.closest("[hidden]");

// Walk one script; returns the pages opened by wait taps, in order.
export function walkWaits(script, role, canAccessPage) {
  const visited = [];
  let skipping = false;
  for (const step of script.steps) {
    if (step.waitTap) {
      skipping = false;
      const m = WAIT_PAGE.exec(step.waitTap);
      expect(m, `${script.key} waitTap shape`).not.toBeNull();
      const page = m[1];
      const btn = document.querySelector(step.waitTap);
      if (!roleVisible(btn)) {
        expect(canAccessPage(role, page), `${script.key}: ${page} hidden but ${role} may open it`).toBe(false);
        skipping = true;
        continue;
      }
      if (!visible(btn)) {
        expect(step.via, `${script.key}: ${page} needs a via`).toBeTruthy();
        const via = [...document.querySelectorAll(step.via)].find(visible);
        expect(via && via.classList.contains("nav-group-toggle"), `${script.key} via shape`).toBe(true);
        expect(visible(via), `${script.key}: via not visible for ${role}`).toBe(true);
        via.click();
      }
      expect(visible(btn), `${script.key}: ${page} not tappable for ${role}`).toBe(true);
      btn.click();
      expect(document.getElementById(`${page}-page`).classList.contains("active"), `${script.key}: ${page} did not open`).toBe(true);
      visited.push(page);
    } else if (!skipping && step.target) {
      const el = document.querySelector(step.target);
      expect(visible(el), `${script.key}: ${step.target} not visible for ${role}`).toBe(true);
    }
  }
  return visited;
}
