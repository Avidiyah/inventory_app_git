// The Timesheets tabpanel: who sees the sub-nav, which feature fetches
// what, and that each fetches only when opened.
//
// Entered the way a user does -- openHub, then a click on the tab -- so the
// lazy loads fire exactly as they do in the app.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { attendanceWeek } from "../helpers/factories.js";
import { connectHub, el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("timesheets");

async function openTimesheets(opts = {}) {
  const mounted = await openHub(opts);
  await user().click(el.tab("timesheets"));
  return mounted;
}

describe("Admin", () => {
  it("shows one page with no sub-tabs: roster, leaderboard, then daily hours", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await vi.waitFor(() => expect(panel().querySelector(".hub-roster-strip")).not.toBeNull());
    expect(panel().querySelectorAll(".sub-nav-btn")).toHaveLength(0);
    const order = [".hub-roster", ".hub-leaderboard-table", ".hub-hours .hub-hours-table"]
      .map((selector) => panel().querySelector(selector));
    expect(order[0].compareDocumentPosition(order[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(order[1].compareDocumentPosition(order[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // One week picker for the whole page, owned by the leaderboard.
    expect(panel().querySelectorAll('[aria-label="Previous week"]')).toHaveLength(1);
  });

  it("fetches the week once for both the leaderboard and the hours grid", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(queries("/hub/attendance/live")).toHaveLength(1);
  });

  it("pages the week and sends a Monday", async () => {
    await openTimesheets({ role: "admin", attendanceWeek: attendanceWeek() });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-timesheets-prev"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    expect(queries("/hub/attendance/week").at(-1)).toEqual({ week: "2026-09-07" });
  });

  it("explains a failed week load and retries", async () => {
    await openTimesheets({ role: "admin", attendanceWeek: 500 });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-message.error")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-retry"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });

  it("renders the week even when the roster fetch fails", async () => {
    await openTimesheets({
      role: "admin",
      handlers: [http.get("/hub/attendance/live", () => HttpResponse.json({ detail: "" }, { status: 500 }))],
    });
    await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboard-table")).not.toBeNull());
    expect(panel().querySelector(".hub-hours-table")).not.toBeNull();
    expect(panel().querySelector(".hub-roster-strip")).toBeNull();
  });

  it("refetches the roster and the week on attendance.changed", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(1));
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });

  it("leaves an open punch drill-down alone on a background refresh", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-cell"));
    expect(panel().querySelector(".hub-hours-detail-row")).not.toBeNull();
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(panel().querySelector(".hub-hours-detail-row")).not.toBeNull();
  });

  it("refreshes the roster on the hub's 60-second timer and starts no timer of its own", async () => {
    await openTimesheets({ role: "admin" });
    // Wait for the strip itself, not just the request: the roster's own tick
    // starts when the payload mounts, and counting before that would compare
    // against a number the poll is about to raise for an innocent reason.
    await vi.waitFor(() => expect(panel().querySelector(".hub-roster-strip")).not.toBeNull());
    const before = vi.getTimerCount();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(vi.getTimerCount()).toBe(before);
  });
});

// The write path: call, then refetch the week. The grid holds no optimistic
// state, so the only thing that proves a write landed is a second GET.
describe("the Admin punch writes", () => {
  const edited = {
    id: "punch-1", started_at: "2026-09-14T13:00:00.000Z",
    ended_at: "2026-09-14T21:00:00.000Z", start_source: "manual",
    end_source: "admin_edit", needs_review: false,
  };

  // Open the drill-down on Monday's cell and start editing its punch.
  async function openEditor() {
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-cell"));
    await user().click(panel().querySelector(".hub-hours-edit"));
    await vi.waitFor(() => expect(panel().querySelector(".punch-editor")).not.toBeNull());
  }

  it("refetches the week after a punch edit", async () => {
    await openTimesheets({
      role: "admin",
      handlers: [http.patch("/hub/attendance/punches/:id", () => HttpResponse.json(edited))],
    });
    await openEditor();
    expect(queries("/hub/attendance/week")).toHaveLength(1);

    await user().click(panel().querySelector(".punch-editor-save"));

    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });

  it("marks the week reviewed, refetches it, and says how many", async () => {
    await openTimesheets({
      role: "admin",
      attendanceWeek: attendanceWeek({ reviewable_count: 2 }),
      handlers: [http.post("/hub/attendance/week/review", () =>
        HttpResponse.json({ punches: 1, sessions: 1 }))],
    });
    await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboard-review-all")).not.toBeNull());

    await user().click(panel().querySelector(".hub-leaderboard-review-all"));

    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    await vi.waitFor(() => expect(panel().querySelector(".hub-leaderboard-message").textContent)
      .toBe("Marked 2 items reviewed."));
  });

  it("surfaces a 409 from an edit without losing the grid", async () => {
    await openTimesheets({
      role: "admin",
      handlers: [http.patch("/hub/attendance/punches/:id", () => HttpResponse.json(
        { detail: "That overlaps another punch for this person." }, { status: 409 }))],
    });
    await openEditor();

    await user().click(panel().querySelector(".punch-editor-save"));

    await vi.waitFor(() => expect(panel().querySelector(".punch-editor-message").textContent)
      .toMatch(/overlaps/i));
    expect(panel().querySelector(".hub-hours-table")).not.toBeNull();
  });

});
