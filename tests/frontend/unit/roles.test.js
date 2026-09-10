import { describe, expect, it } from "vitest";
import {
  ALL_ROLES, assignableRoles, canBeWorkOrderSupervisor, canBeWorkOrderTechnician,
  canManage, roleAtLeast, roleLabel,
} from "../../../backend/static/roles.js";

// The rank/label VALUES are pinned against the Python module by
// backend/tests/test_role_mirror_parity.py. These tests cover the predicates
// that only exist on the JS side.

describe("roleLabel", () => {
  it("renders the one label capitalisation cannot produce", () => {
    expect(roleLabel("techfm_oa")).toBe("TechFM OA");
  });
  it("passes an unrecognised role through unchanged", () => {
    expect(roleLabel("contractor")).toBe("contractor");
  });
  it("never returns blank, so the Tools custody separator has something to sit beside", () => {
    expect(roleLabel(null)).toBe("Unknown role");
    expect(roleLabel("")).toBe("Unknown role");
  });
});

describe("roleAtLeast", () => {
  it.each([
    ["owner", "technician", true], ["technician", "technician", true],
    ["supervisor", "admin", false], ["techfm_oa", "supervisor", true],
  ])("roleAtLeast(%s, %s)", (role, minimum, expected) => {
    expect(roleAtLeast(role, minimum)).toBe(expected);
  });

  it("treats an unknown role as below everything", () => {
    expect(roleAtLeast("contractor", "technician")).toBe(false);
  });

  it("returns true when both sides are unknown, because both rank -1", () => {
    // Recorded, not endorsed: an unknown role satisfies an unknown minimum.
    expect(roleAtLeast("contractor", "vendor")).toBe(true);
  });
});

describe("work-order assignment eligibility", () => {
  it.each(ALL_ROLES)("canBeWorkOrderSupervisor(%s)", (role) => {
    expect(canBeWorkOrderSupervisor(role)).toBe(["admin", "techfm_oa", "supervisor"].includes(role));
  });
  it.each(ALL_ROLES)("canBeWorkOrderTechnician(%s)", (role) => {
    expect(canBeWorkOrderTechnician(role)).toBe(["supervisor", "technician"].includes(role));
  });
  it("excludes owner from both, deliberately", () => {
    expect(canBeWorkOrderSupervisor("owner")).toBe(false);
    expect(canBeWorkOrderTechnician("owner")).toBe(false);
  });
});

describe("canManage", () => {
  it("requires strictly greater rank", () => {
    expect(canManage("admin", "admin")).toBe(false);
    expect(canManage("admin", "supervisor")).toBe(true);
    expect(canManage("supervisor", "admin")).toBe(false);
  });
  it("refuses an unknown target role even for an owner", () => {
    expect(canManage("owner", "contractor")).toBe(false);
  });
});

describe("assignableRoles", () => {
  it("lists everything below the actor, most senior first", () => {
    expect(assignableRoles("admin")).toEqual(["techfm_oa", "supervisor", "technician"]);
  });
  it("is empty for a technician", () => {
    expect(assignableRoles("technician")).toEqual([]);
  });
  it("is empty for an unknown role", () => {
    expect(assignableRoles("contractor")).toEqual([]);
  });
  it("gives an owner every other role", () => {
    expect(assignableRoles("owner")).toEqual(["admin", "techfm_oa", "supervisor", "technician"]);
  });
});
