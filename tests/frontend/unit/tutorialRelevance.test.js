import { beforeEach, describe, expect, it } from "vitest";
import { mountView } from "../helpers/shell.js";

let audienceLabel, pageMinRole, relevant;
beforeEach(async () => {
  ({ audienceLabel, pageMinRole, relevant } = await mountView("tutorials/relevance.js"));
});

describe("relevant", () => {
  it("follows PAGE_ACCESS", () => {
    expect(relevant({ page: "work-orders" }, "technician")).toBe(true);
    expect(relevant({ page: "saved-users" }, "technician")).toBe(false);
    expect(relevant({ page: "saved-users" }, "supervisor")).toBe(true);
  });
  it("minRole narrows a page", () => {
    const e = { page: "user-hub", minRole: "supervisor" };
    expect(relevant(e, "technician")).toBe(false);
    for (const r of ["supervisor", "techfm_oa", "admin", "owner"]) expect(relevant(e, r)).toBe(true);
  });
  it("unknown role is false", () => {
    expect(relevant({ page: "work-orders" }, "ghost")).toBe(false);
    expect(relevant({ page: "work-orders" }, undefined)).toBe(false);
  });
  it("a starter (no page in PAGE_ACCESS) is judged by minRole alone", () => {
    const s = { page: "starter", minRole: "supervisor" };
    expect(relevant(s, "technician")).toBe(false);
    expect(relevant(s, "admin")).toBe(true);
    expect(relevant({ page: "starter", minRole: "technician" }, "technician")).toBe(true);
    expect(relevant({ page: "starter" }, "owner")).toBe(false);
  });
});

describe("audienceLabel", () => {
  it("Everyone when the page minimum is technician and no minRole", () => {
    expect(audienceLabel({ page: "work-orders" })).toBe("Everyone");
  });
  it("uses the higher of page minimum and minRole, with role labels", () => {
    expect(audienceLabel({ page: "user-hub", minRole: "supervisor" })).toBe("Team Lead and above");
    expect(audienceLabel({ page: "saved-users" })).toBe("Team Lead and above");
    expect(audienceLabel({ page: "low-stock", minRole: "supervisor" })).toBe("TechFM OA and above");
    expect(audienceLabel({ page: "starter", minRole: "admin" })).toBe("Admin and above");
    expect(audienceLabel({ page: "starter", minRole: "technician" })).toBe("Everyone");
  });
  it("pageMinRole is the lowest listed role", () => {
    expect(pageMinRole("create-item")).toBe("techfm_oa");
    expect(pageMinRole("nope")).toBeNull();
  });
});
