// The Admin Leaderboards tab: its own week, two boards, ◀/▶ paging.
//
// Entered the way a user does -- openHub, then a click on the tab.

import { afterEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("leaderboards");

describe("hubLeaderboardsTab", () => {
  it("renders both boards and steps weeks", async () => {
    await openHub({ role: "admin" });
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(panel().querySelectorAll(".hub-leaderboard-table")).toHaveLength(2));
    const headings = [...panel().querySelectorAll(".hub-leaderboard-heading")].map((h) => h.textContent);
    expect(headings[0]).toContain("Accuracy");
    expect(headings[1]).toContain("Efficiency");
    expect(panel().querySelector(".hub-leaderboards-grid")).not.toBeNull();

    await user().click(panel().querySelector('[aria-label="Previous week"]'));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    expect(queries("/hub/attendance/week").at(-1)).toEqual({ week: "2026-09-07" });
  });

  it("explains a failed load and retries", async () => {
    await openHub({ role: "admin", attendanceWeek: 500 });
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboards-retry")).not.toBeNull());
    await user().click(panel().querySelector(".hub-leaderboards-retry"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });
});
