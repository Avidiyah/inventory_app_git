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
import { mountView } from "../../helpers/shell.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..", "..");
const VIEWS = join(REPO_ROOT, "backend", "static", "views");
// Every module the Work Orders view is split across. A new sibling is picked
// up automatically; a renamed one shows up as a missing action, loudly.
// workOrderRequests.js shares the prefix but is a different view with its own
// delegation (`action === "pick"`, `"send"`), so it is not part of this set.
const SOURCE_FILES = readdirSync(VIEWS)
  .filter((n) => (n === "workOrders.js" || /^workOrder[A-Z]/.test(n))
    && n !== "workOrderRequests.js")
  .map((n) => join(VIEWS, n));
const FRAGMENT = join(REPO_ROOT, "backend", "static", "pages", "work-orders.html");

const source = SOURCE_FILES.map((p) => readFileSync(p, "utf8")).join("\n");
const fragment = readFileSync(FRAGMENT, "utf8");

const matchAll = (text, pattern) => [...text.matchAll(pattern)].map((m) => m[1]);

// `export function x` in the module that owns it, or `export { x } from "..."`
// in the barrel. Both are declarations of the public surface.
const declaredNames = (text) => [
  ...matchAll(text, /^export (?:async )?function ([A-Za-z]+)/gm),
  ...[...text.matchAll(/^export \{([^}]+)\} from/gm)]
      .flatMap((m) => m[1].split(",").map((s) => s.trim()).filter(Boolean)),
];

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
    // A real import, against the real shell: a barrel re-export whose owner
    // renamed the function is a load-time error here, not a text match. (The
    // former `new URL(...).href` form resolved to http:// under jsdom and
    // never loaded, so this test was silently the static scan below.)
    const mod = await mountView("views/workOrders.js");
    expect(Object.keys(mod).sort()).toEqual(EXPORTS);
    // Vite's module transform keeps the key of a dangling re-export and
    // hands back undefined, so the names alone are not proof of a binding.
    const unbound = EXPORTS.filter((name) => typeof mod[name] !== "function");
    expect(unbound, `re-exported but not bound: ${unbound.join(", ")}`).toEqual([]);
  });

  it("declares each of them somewhere in the module set", () => {
    // Containment, not equality: after the split the siblings export plenty
    // of names of their own. Exactness of the public surface is the barrel's
    // job, asserted below.
    const declared = new Set(declaredNames(source));
    const undeclared = EXPORTS.filter((name) => !declared.has(name));
    expect(undeclared, `not declared anywhere: ${undeclared.join(", ")}`).toEqual([]);
  });

  it("re-exports all eleven from the barrel itself", () => {
    const barrel = readFileSync(join(VIEWS, "workOrders.js"), "utf8");
    expect([...new Set(declaredNames(barrel))].sort()).toEqual(EXPORTS);
  });
});
