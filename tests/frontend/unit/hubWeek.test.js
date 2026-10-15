import { describe, expect, it } from "vitest";
import { formatHm, shiftMonday, weekLabel } from "../../../backend/static/views/hubWeek.js";

describe("hubWeek helpers", () => {
  it("prints minutes as h:mm, floored at zero", () => {
    expect(formatHm(480)).toBe("8:00");
    expect(formatHm(65)).toBe("1:05");
    expect(formatHm(-5)).toBe("0:00");
    expect(formatHm(undefined)).toBe("0:00");
  });
  it("shifts a Monday by whole weeks in UTC", () => {
    expect(shiftMonday("2026-09-14", 7)).toBe("2026-09-21");
    expect(shiftMonday("2026-09-14", -7)).toBe("2026-09-07");
  });
  it("labels a week from its two dates", () => {
    expect(weekLabel("2026-09-14", "2026-09-20")).toContain("Sep 14");
    expect(weekLabel("2026-09-14", "2026-09-20")).toContain("Sep 20");
  });
});
