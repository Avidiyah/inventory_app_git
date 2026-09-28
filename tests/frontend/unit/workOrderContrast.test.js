// Each work-order status pill's text/fill pair clears WCAG AA (4.5:1), read
// from the live token values in styles.css -- so retuning a --wo-status-*
// hue (they also drive the Hub Graphs donuts) cannot quietly make a pill
// unreadable.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "backend", "static", "styles.css"),
  "utf8"
);

function token(name) {
  const match = new RegExp(`${name}:\\s*(#[0-9A-Fa-f]{6})`).exec(CSS);
  if (!match) throw new Error(`no hex value for ${name}`);
  return match[1];
}

function luminance(hex) {
  const channel = (i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Which text token each pill's rule uses: `color: var(--color-ink)` on the
// rule, else the base `.wo-status` white.
function pillText(status) {
  const rule = new RegExp(`\\.wo-status-${status} \\{([^}]*)\\}`).exec(CSS);
  if (!rule) throw new Error(`no .wo-status-${status} rule`);
  const fill = /background-color:\s*var\((--wo-status-[a-z-]+)\)/.exec(rule[1]);
  expect(fill, `.wo-status-${status} fills from its token`).not.toBeNull();
  const text = /color:\s*var\((--color-[a-z]+)\)\s*;/.exec(rule[1].replace(/background-color[^;]*;/, ""));
  return { fill: token(fill[1]), text: token(text ? text[1] : "--color-white") };
}

describe("status pill contrast", () => {
  it.each(["created", "assigned", "in_progress", "on_hold", "ready_to_complete", "completed", "review"])(
    "%s text is >= 4.5:1 on its fill", (status) => {
      const { fill, text } = pillText(status);
      expect(contrast(fill, text)).toBeGreaterThanOrEqual(4.5);
    });
});
