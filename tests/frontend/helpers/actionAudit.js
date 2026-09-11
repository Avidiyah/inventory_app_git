// P2's mechanical completeness guarantee, generalised. A characterization
// suite is only as good as its coverage, and "we think every branch has a
// test" is not checkable by reading. This greps a view's delegated actions
// out of its source, freezes the inventory, checks rendered and handled
// agree, and fails BY NAME when a behaviour file never mentions one.
//
// Nothing here is view-specific: what counts as "rendered" and "handled" is
// a pair of regexes, because the views disagree -- Work Orders and Mass Stage
// write `data-action="x"` and branch on `action === "x"`; Items writes
// `<option value="x">` and branches the same way.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HELPERS_DIR = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(HELPERS_DIR, "..", "..", "..");
export const VIEWS_DIR = join(REPO_ROOT, "backend", "static", "views");
export const PAGES_DIR = join(REPO_ROOT, "backend", "static", "pages");

const matchAll = (text, pattern) => [...text.matchAll(pattern)].map((m) => m[1]);
const readAll = (paths) => paths.map((p) => readFileSync(p, "utf8")).join("\n");

export function readActionInventory({
  sources, fragments = [],
  renderedPattern = /data-action="([a-z-]+)"/g,
  handledPattern = /action === "([a-z-]+)"/g,
}) {
  const source = readAll(sources);
  const fragment = readAll(fragments);
  return {
    rendered: new Set([...matchAll(source, renderedPattern), ...matchAll(fragment, renderedPattern)]),
    handled: new Set(matchAll(source, handledPattern)),
  };
}

// Registers a `describe(name)` with P2's four checks. `sources` / `fragments`
// are absolute paths; `behaviourDir` is scanned for `*.test.js` minus
// `behaviourExclude`.
//
// One deliberate tightening over P2: the behaviour check matches the QUOTED
// action (`"add-item"`), where P2 matched the bare substring. The bare match
// let `"add-item"` be satisfied by `"add-item-row"` or by prose in a comment;
// the quoted form is what a `data-action` / `selectOptions` literal looks like.
//
// Still a TEXT check: any quoted mention satisfies it, including a render
// assertion that lists the option values (items.test.js's role table). It
// proves a test names the action, not that one drives it -- deleting the
// driving test alone does not go red if a render table still names it.
export function auditActions({
  name, sources, fragments = [], frozen, behaviourDir, behaviourExclude = [],
  renderedPattern, handledPattern,
}) {
  const { rendered, handled } = readActionInventory({ sources, fragments, renderedPattern, handledPattern });
  const behaviourFiles = readdirSync(behaviourDir)
    .filter((f) => f.endsWith(".test.js") && !behaviourExclude.includes(f));
  const behaviourText = readAll(behaviourFiles.map((f) => join(behaviourDir, f)));

  describe(name, () => {
    describe("the action inventory", () => {
      it(`is exactly the frozen ${frozen.length}`, () => {
        expect([...rendered].sort()).toEqual([...frozen].sort());
      });
      it("renders no action the delegation does not handle", () => {
        const orphans = [...rendered].filter((a) => !handled.has(a)).sort();
        expect(orphans, `rendered but never handled: ${orphans.join(", ")}`).toEqual([]);
      });
      it("handles no action nothing renders", () => {
        const orphans = [...handled].filter((a) => !rendered.has(a)).sort();
        expect(orphans, `handled but never rendered: ${orphans.join(", ")}`).toEqual([]);
      });
    });
    describe("every action is exercised by a behaviour test", () => {
      it("names the ones that are not", () => {
        expect(behaviourFiles.length).toBeGreaterThan(0);
        const missing = frozen.filter((a) => !behaviourText.includes(`"${a}"`));
        expect(missing, `no test mentions: ${missing.join(", ")}`).toEqual([]);
      });
    });
  });
}
