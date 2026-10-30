// The Admin Leaderboards tab: one scored board, a Week / Month switch, and
// ◀/▶ paging inside the chosen window.
//
// Entered the way a user does -- openHub, then a click on the tab.

import { afterEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { performanceWindow } from "../helpers/factories.js";
import { el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("leaderboards");
const label = () => panel().querySelector(".hub-hours-week-nav strong").textContent;
const switchButton = (name) => panel().querySelector(`.hub-leaderboards-switch [data-window="${name}"]`);

// The server answers month and week by the `window` it was asked for.
const byWindow = () => http.get("/hub/performance", ({ request }) => {
  const url = new URL(request.url);
  const start = url.searchParams.get("start");
  if (url.searchParams.get("window") === "month") {
    return HttpResponse.json(performanceWindow({
      window: "month", floor_minutes: 3600,
      start: start || "2026-09-01", end: start ? "2026-08-31".replace("08", start.slice(5, 7)) : "2026-09-16",
      to_date: !start,
    }));
  }
  return HttpResponse.json(performanceWindow({ start: start || "2026-09-14", end: "2026-09-20" }));
});

async function openTab(options = {}) {
  await openHub({ role: "admin", handlers: [byWindow()], ...options });
  await user().click(el.tab("leaderboards"));
  await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboard-table")).not.toBeNull());
}

describe("hubLeaderboardsTab", () => {
  it("opens on the current week with the board and the week label", async () => {
    await openTab();
    expect(queries("/hub/performance")).toEqual([{ window: "week" }]);
    expect(label()).toContain("Sep 14, 2026");
    expect(switchButton("week").getAttribute("aria-pressed")).toBe("true");
    expect(switchButton("month").getAttribute("aria-pressed")).toBe("false");
    expect(panel().querySelector('[aria-label="Next week"]').disabled).toBe(true);
  });

  it("steps back a week and forward again", async () => {
    await openTab();
    await user().click(panel().querySelector('[aria-label="Previous week"]'));
    await vi.waitFor(() => expect(queries("/hub/performance")).toHaveLength(2));
    expect(queries("/hub/performance").at(-1)).toEqual({ window: "week", start: "2026-09-07" });
    await vi.waitFor(() => expect(panel().querySelector('[aria-label="Next week"]').disabled).toBe(false));
    await user().click(panel().querySelector('[aria-label="Next week"]'));
    await vi.waitFor(() => expect(queries("/hub/performance")).toHaveLength(3));
    // Landing back on the week in progress asks for it by omission, so ▶ disables again.
    expect(queries("/hub/performance").at(-1)).toEqual({ window: "week" });
    await vi.waitFor(() => expect(panel().querySelector('[aria-label="Next week"]').disabled).toBe(true));
  });

  it("switches to the month in progress and pages by calendar month", async () => {
    await openTab();
    await user().click(switchButton("month"));
    await vi.waitFor(() => expect(queries("/hub/performance").at(-1)).toEqual({ window: "month" }));
    await vi.waitFor(() => expect(label()).toBe("September 2026 (to date)"));
    expect(switchButton("month").getAttribute("aria-pressed")).toBe("true");
    expect(panel().querySelector('[aria-label="Next month"]').disabled).toBe(true);

    await user().click(panel().querySelector('[aria-label="Previous month"]'));
    await vi.waitFor(() => expect(queries("/hub/performance").at(-1)).toEqual({ window: "month", start: "2026-08-01" }));
    await vi.waitFor(() => expect(label()).toBe("August 2026"));
    expect(panel().querySelector('[aria-label="Next month"]').disabled).toBe(false);

    // Back to Week starts over at the current week, not where the week paging left off.
    await user().click(switchButton("week"));
    await vi.waitFor(() => expect(queries("/hub/performance").at(-1)).toEqual({ window: "week" }));
  });

  it("explains a failed load and retries", async () => {
    await openHub({ role: "admin", performance: 500 });
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboards-retry")).not.toBeNull());
    await user().click(panel().querySelector(".hub-leaderboards-retry"));
    await vi.waitFor(() => expect(queries("/hub/performance")).toHaveLength(2));
  });

  it("uses no inline styles and nests no buttons", async () => {
    await openTab();
    expect(panel().querySelector("[style]")).toBeNull();
    expect(panel().querySelector("button button")).toBeNull();
  });
});
