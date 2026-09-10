import { describe, expect, it } from "vitest";
import { skeletonCard, skeletonList, skeletonTableRows } from "../../../backend/static/skeleton.js";

// CSP drops style attributes parsed out of markup here (see the module header
// and docs/current-state.md), so "no inline style" is a correctness assertion,
// not a style preference.
const NO_INLINE_STYLE = /style=/;

describe("skeletonTableRows", () => {
  it("emits rowCount rows of colCount cells", () => {
    const html = skeletonTableRows(3, 2);
    expect(html.match(/<tr class="skel-row">/g)).toHaveLength(2);
    expect(html.match(/<td>/g)).toHaveLength(6);
  });

  it("announces loading exactly once, in the first cell", () => {
    const html = skeletonTableRows(3, 4);
    expect(html.match(/sr-only/g)).toHaveLength(1);
    expect(html.indexOf("sr-only")).toBeLessThan(html.indexOf("</td>"));
  });

  it("snaps a caller width onto the 5% class ladder", () => {
    expect(skeletonTableRows(1, 1, { widths: ["37%"] })).toContain("skel-w-35");
  });

  it("clamps a width to the ladder's ends", () => {
    expect(skeletonTableRows(1, 1, { widths: ["5%"] })).toContain("skel-w-25");
    expect(skeletonTableRows(1, 1, { widths: ["150%"] })).toContain("skel-w-95");
  });

  it("falls back to the deterministic cycle for a non-percentage width", () => {
    expect(skeletonTableRows(1, 1, { widths: ["auto"] })).toContain("skel-w-90");
  });

  it("uses classes only -- never an inline style", () => {
    expect(skeletonTableRows(2, 2, { widths: ["40%", "60%"] })).not.toMatch(NO_INLINE_STYLE);
  });

  it("is deterministic, so a repeat render is pixel-identical", () => {
    expect(skeletonTableRows(3, 3)).toBe(skeletonTableRows(3, 3));
  });
});

describe("skeletonCard", () => {
  it("renders a header bar plus the requested body lines", () => {
    const html = skeletonCard({ lines: 2 });
    expect(html).toContain("skel-line--head");
    // One `skel-w-*` per bar. `skel-line` itself is not countable -- the
    // header's `skel-line--head` contains it as a prefix, and the sr-only
    // announcement is a <span> too.
    expect(html.match(/skel-w-/g)).toHaveLength(3); // head + 2 body
  });

  it("omits the header when asked", () => {
    expect(skeletonCard({ hasHeader: false })).not.toContain("skel-line--head");
  });

  it("defaults to three body lines and one announcement", () => {
    const html = skeletonCard();
    expect(html.match(/sr-only/g)).toHaveLength(1);
    expect(html.match(/skel-w-/g)).toHaveLength(4); // head + 3 body
  });

  it("renders no lines at all when asked for zero", () => {
    expect(skeletonCard({ lines: 0, hasHeader: false })).toBe(
      '<div class="skel-card"><span class="sr-only">Loading…</span></div>');
  });
});

describe("skeletonList", () => {
  it("renders two bars per item and announces once", () => {
    const html = skeletonList(3);
    expect(html.match(/skel-list-item/g)).toHaveLength(3);
    expect(html.match(/skel-line--sub/g)).toHaveLength(3);
    expect(html.match(/sr-only/g)).toHaveLength(1);
  });

  it("uses classes only", () => {
    expect(skeletonList()).not.toMatch(NO_INLINE_STYLE);
  });
});
