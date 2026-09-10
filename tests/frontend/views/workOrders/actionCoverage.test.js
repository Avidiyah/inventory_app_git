// The mechanical guarantee P4 leans on.
//
// `views/workOrders.js` is 2,800 lines about to be split into modules. A
// characterization suite is only as good as its completeness, and "we think
// we covered every branch" is not checkable by reading. This greps the 26
// `data-action` strings out of the source and fails, by name, when one has
// no test -- so a branch that P4 moves and breaks cannot be one nobody was
// asserting on.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..", "..");
const SOURCE = join(REPO_ROOT, "backend", "static", "views", "workOrders.js");
const FRAGMENT = join(REPO_ROOT, "backend", "static", "pages", "work-orders.html");

const source = readFileSync(SOURCE, "utf8");
const fragment = readFileSync(FRAGMENT, "utf8");

const matchAll = (text, pattern) => [...text.matchAll(pattern)].map((m) => m[1]);

// Rendered: every `data-action="…"` this module writes, plus any the static
// fragment carries. Handled: every `action === "…"` comparison in the click
// delegation.
const rendered = new Set([
  ...matchAll(source, /data-action="([a-z-]+)"/g),
  ...matchAll(fragment, /data-action="([a-z-]+)"/g),
]);
const handled = new Set(matchAll(source, /action === "([a-z-]+)"/g));

// Frozen. Adding an action to the source lands here deliberately rather than
// silently widening what the audit calls "covered".
const ACTIONS = [
  "add-item", "add-labor", "archive-wo", "back-to-work-orders", "cancel-edit",
  "complete-wo", "edit-item", "edit-labor", "hold-assigned-wo",
  "notify-supervisor-wo", "open-netfacilities-wo", "pick-combo-option",
  "pick-item", "pick-technician", "remove-item", "remove-labor",
  "remove-technician", "reopen-wo", "resume-assigned-wo", "review-wo",
  "save-details", "save-notes", "send-back-wo", "start-tracking-wo",
  "stop-tracking-wo", "toggle-combo",
];

// The eleven exports other views import. P4 must re-export every one.
const EXPORTS = [
  "comboHtml",
  "focusWorkOrder",
  "focusWorkOrderNumber",
  "loadIntegrationsPage",
  "loadWorkOrders",
  "mountWorkOrderList",
  "openWorkOrdersByNumberSearch",
  "openWorkOrdersFilteredByDistribution",
  "openWorkOrdersFilteredByStatus",
  "soloNumberFromPath",
  "workOrderCardClass",
];

const behaviourFiles = readdirSync(HERE)
  .filter((name) => name.endsWith(".test.js") && name !== "actionCoverage.test.js");
const behaviourText = behaviourFiles
  .map((name) => readFileSync(join(HERE, name), "utf8"))
  .join("\n");

describe("the action inventory", () => {
  it("is exactly the frozen 26", () => {
    expect([...rendered].sort()).toEqual(ACTIONS);
  });

  it("renders no action the delegation does not handle", () => {
    const orphanRenderers = [...rendered].filter((a) => !handled.has(a)).sort();
    expect(orphanRenderers, `rendered but never handled: ${orphanRenderers.join(", ")}`)
      .toEqual([]);
  });

  it("handles no action nothing renders", () => {
    const orphanHandlers = [...handled].filter((a) => !rendered.has(a)).sort();
    expect(orphanHandlers, `handled but never rendered: ${orphanHandlers.join(", ")}`)
      .toEqual([]);
  });
});

describe("every action is exercised by a behaviour test", () => {
  it("names the ones that are not", () => {
    expect(behaviourFiles.length).toBeGreaterThan(0);
    const missing = ACTIONS.filter((action) => !behaviourText.includes(action));
    expect(missing, `no test mentions: ${missing.join(", ")}`).toEqual([]);
  });
});

describe("the export surface", () => {
  it("is exactly the frozen eleven", async () => {
    const mod = await import(
      /* @vite-ignore */ new URL("../../../../backend/static/views/workOrders.js", import.meta.url).href
    ).catch(() => null);
    // The module captures DOM ids at import time; a bare import outside the
    // shell fixture is fine for reading its export names, and null means the
    // environment refused it -- fall back to the static export list then.
    const names = mod
      ? Object.keys(mod).sort()
      : matchAll(source, /^export (?:async )?function ([A-Za-z]+)/gm).sort();
    expect(names).toEqual(EXPORTS);
  });

  it("declares each of them with an `export` keyword in the source", () => {
    const declared = matchAll(source, /^export (?:async )?function ([A-Za-z]+)/gm).sort();
    expect(declared).toEqual(EXPORTS);
  });
});
