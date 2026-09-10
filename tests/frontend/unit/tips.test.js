import { beforeEach, describe, expect, it, vi } from "vitest";
import { assembleShell, mountShell, mountView } from "../helpers/shell.js";
import { TIPS } from "../../../backend/static/tips.js";

describe("the tip registry", () => {
  it("gives every key a label and plain-text copy", () => {
    for (const [key, tip] of Object.entries(TIPS)) {
      expect(typeof tip.label, key).toBe("string");
      expect(tip.label.length, key).toBeGreaterThan(0);
      expect(typeof tip.text, key).toBe("string");
      expect(tip.text.length, key).toBeGreaterThan(0);
      // Plain text only, by contract (spec D5) -- both fields are escaped at
      // render time, so markup here would show as literal angle brackets.
      expect(tip.text, key).not.toMatch(/<[a-z/]/i);
    }
  });

  it("uses the documented <area>.<thing> key form", () => {
    for (const key of Object.keys(TIPS)) {
      expect(key, key).toMatch(/^[a-z0-9]+(\.[a-z0-9-]+)+$/);
    }
  });
});

describe("the data-tip audit", () => {
  // Every hand-authored `?` in the shell must resolve to copy. A miss renders
  // a trigger that opens nothing, which installTooltips then hides -- invisible
  // in production, visible here.
  it("resolves every data-tip key in the assembled shell", () => {
    const keys = [...assembleShell().matchAll(/data-tip="([^"]+)"/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(0);
    const missing = [...new Set(keys)].filter((key) => !TIPS[key]);
    expect(missing, `data-tip keys with no entry in tips.js: ${missing.join(", ")}`).toEqual([]);
  });

  it("resolves every key the view modules pass to tipHtml", async () => {
    const { readdirSync, readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const dir = "backend/static/views";
    const keys = new Set();
    for (const file of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
      const source = readFileSync(join(dir, file), "utf8");
      for (const match of source.matchAll(/tipHtml\(\s*"([^"]+)"\s*\)/g)) keys.add(match[1]);
    }
    const missing = [...keys].filter((key) => !TIPS[key]);
    expect(missing, `tipHtml() keys with no entry in tips.js: ${missing.join(", ")}`).toEqual([]);
  });
});

describe("tipHtml", () => {
  let tooltip;
  beforeEach(async () => {
    tooltip = await mountView("tooltip.js");
  });

  it("emits a button carrying the key and the accessible name, never the copy", () => {
    const key = Object.keys(TIPS)[0];
    const html = tooltip.tipHtml(key);
    expect(html).toContain(`data-tip="${key}"`);
    expect(html).toContain(`aria-label="Help: ${TIPS[key].label}"`);
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain(TIPS[key].text);
  });

  it("returns nothing for an unknown key rather than a dead affordance", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(tooltip.tipHtml("nope.missing")).toBe("");
    expect(warn).toHaveBeenCalled();
  });
});
