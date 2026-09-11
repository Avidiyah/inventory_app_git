// scan/frame-debouncer.js: the consecutive-streak rule the live decoder
// feeds. Pure, so these pin the contract by number: three identical decodes
// in a row accept, a differing one resets, and an accepted text sticks
// until reset().

import { describe, expect, it } from "vitest";
import { FrameDebouncer } from "../../../backend/static/scan/frame-debouncer.js";

describe("FrameDebouncer", () => {
  it("accepts on the third consecutive identical decode by default", () => {
    const d = new FrameDebouncer();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("A")).toBe("A");
  });

  it("a differing decode resets the streak to one", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A");
    expect(d.pushAndCheck("B")).toBeNull();
    expect(d.pushAndCheck("B")).toBeNull();
    expect(d.pushAndCheck("B")).toBe("B");
  });

  it("once accepted, every later push returns the accepted text regardless of input", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A"); d.pushAndCheck("A");
    expect(d.pushAndCheck("B")).toBe("A");
    expect(d.pushAndCheck("C")).toBe("A");
  });

  it("reset clears the streak and the accepted text", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A"); d.pushAndCheck("A");
    d.reset();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("B")).toBeNull();
  });

  it.each([[1, 1], [2, 2], [5, 5]])("threshold %i accepts on push %i", (threshold, n) => {
    const d = new FrameDebouncer(threshold);
    for (let i = 1; i < n; i += 1) expect(d.pushAndCheck("X")).toBeNull();
    expect(d.pushAndCheck("X")).toBe("X");
  });

  it("misses never reach it, so two pushes separated by silence still count as consecutive", () => {
    // The contract: the caller only pushes successful decodes.
    const d = new FrameDebouncer();
    d.pushAndCheck("A");
    d.pushAndCheck("A");
    expect(d.pushAndCheck("A")).toBe("A");
  });

  it("distinguishes empty string from null and treats it as a real text", () => {
    // ZXing never returns "", so this is unreachable in production; pinned
    // so the null-vs-empty distinction cannot silently flip.
    const d = new FrameDebouncer(2);
    expect(d.pushAndCheck("")).toBeNull();
    expect(d.pushAndCheck("")).toBe("");
  });
});
