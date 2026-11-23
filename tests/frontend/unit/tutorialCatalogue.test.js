import { describe, expect, it } from "vitest";
import { catalogue } from "../../../backend/static/tutorials/catalogue.js";

describe("catalogue", () => {
  it("flattens injected tutorials, tagging each entry with its page", () => {
    const t = {
      a: { scripts: [{ key: "a.one", title: "1", steps: [] }, { key: "a.two", title: "2", minRole: "supervisor", steps: [] }] },
      starter: { scripts: [{ key: "starter.x", title: "X", minRole: "technician", steps: [] }] },
    };
    expect(catalogue(t).map((e) => [e.page, e.key, e.minRole])).toEqual([
      ["a", "a.one", undefined], ["a", "a.two", "supervisor"], ["starter", "starter.x", "technician"]]);
  });
  it("defaults to the real registry", () => {
    const all = catalogue();
    expect(all.length).toBeGreaterThan(0);
    expect(all.every((e) => e.page && e.key)).toBe(true);
  });
});
