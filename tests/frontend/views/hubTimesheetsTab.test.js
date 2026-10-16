// The Timesheets tabpanel: who sees the sub-nav, which feature fetches
// what, and that each fetches only when opened.
//
// Entered the way a user does -- openHub, then a click on the tab -- so the
// lazy loads fire exactly as they do in the app.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { attendanceWeek, personWeek } from "../helpers/factories.js";
import { restoreBrowserStubs, stubObjectUrl } from "../helpers/browserStubs.js";
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
  it("shows one page with no sub-tabs: roster, actions, then day cards", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await vi.waitFor(() => expect(panel().querySelector(".hub-roster-strip")).not.toBeNull());
    expect(panel().querySelectorAll(".sub-nav-btn")).toHaveLength(0);
    const order = [".hub-roster", ".hub-timesheets-export", ".hub-day-cards"]
      .map((selector) => panel().querySelector(selector));
    expect(order[0].compareDocumentPosition(order[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(order[1].compareDocumentPosition(order[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // One week picker for the whole page, owned by the day strip.
    expect(panel().querySelectorAll('[aria-label="Previous week"]')).toHaveLength(1);
  });

  it("fetches the week once for the day strip", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(queries("/hub/attendance/live")).toHaveLength(1);
  });

  it("pages the week and sends a Monday", async () => {
    await openTimesheets({ role: "admin", attendanceWeek: attendanceWeek() });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
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
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-cards")).not.toBeNull());
    expect(panel().querySelector(".hub-roster-strip")).toBeNull();
  });

  it("refetches the roster and the week on attendance.changed", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(1));
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });

  it("leaves an open punch editor alone on a background refresh", async () => {
    const { emit } = await connectHub();
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await user().click(panel().querySelector(".hub-day-card"));
    await user().click(panel().querySelector(".hub-hours-edit"));
    expect(panel().querySelector(".punch-editor")).not.toBeNull();
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(panel().querySelector(".punch-editor")).not.toBeNull();
  });

  it("opens a day page from a card, steps across the week edge, and Back restores the week", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    expect(panel().querySelector(".hub-day-card").textContent).toContain("1 clocked in");
    await user().click(panel().querySelector(".hub-day-card"));
    expect(panel().querySelector(".hub-day-page")).not.toBeNull();
    expect(panel().querySelector(".hub-day-person").textContent).toContain("Ann Lee");
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    await user().click(panel().querySelector(".hub-day-prev"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    expect(queries("/hub/attendance/week").at(-1)).toEqual({ week: "2026-09-07" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-page").textContent).toContain("Sunday"));
    await user().click(panel().querySelector(".hub-day-back"));
    expect(panel().querySelector(".hub-day-cards")).not.toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(2);
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

  // Open Monday's day page and start editing its punch.
  async function openEditor() {
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await user().click(panel().querySelector(".hub-day-card"));
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
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets-review-all")).not.toBeNull());

    await user().click(panel().querySelector(".hub-timesheets-review-all"));

    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets-message").textContent)
      .toBe("Marked 2 items reviewed."));
  });

  it("keeps Export CSV and Mark all reviewed, and reports the export", async () => {
    stubObjectUrl();
    await openTimesheets({
      role: "admin",
      attendanceWeek: attendanceWeek({ reviewable_count: 2 }),
      handlers: [http.get("/hub/attendance/export", () => new HttpResponse("x", {
        headers: { "Content-Disposition": 'attachment; filename="attendance_2026-09-14.csv"' },
      }))],
    });
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets-review-all")).not.toBeNull());
    expect(panel().querySelector(".hub-timesheets-review-all").textContent).toBe("Mark all reviewed (2)");
    await user().click(panel().querySelector(".hub-timesheets-export"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets-message").textContent)
      .toContain("attendance_2026-09-14.csv"));
    restoreBrowserStubs();
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
    expect(panel().querySelector(".hub-day-page")).not.toBeNull();
  });

});

describe("the profile", () => {
  const profileHandler = () => http.get("/hub/people/:id/week", () => HttpResponse.json(personWeek()));

  async function openProfile(opts = {}) {
    const mounted = await openTimesheets({ role: "admin", handlers: [profileHandler()], ...opts });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await user().click(panel().querySelector(".hub-day-card"));
    await user().click(panel().querySelector(".hub-hours-person"));
    await vi.waitFor(() => expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull());
    return mounted;
  }

  it("swaps the week area for the profile at the shown week, and Back restores the day page without a fetch", async () => {
    await openProfile();
    expect(panel().querySelector(".hub-timesheets-export")).toBeNull();
    expect(panel().querySelector(".hub-day-page")).toBeNull();
    await vi.waitFor(() => expect(queries("/hub/people/")).toEqual([{ week: "2026-09-14" }]));
    expect(panel().querySelector(".user-profile-back").textContent).toContain("timesheets");
    const before = queries("/hub/attendance/week").length;
    await user().click(panel().querySelector(".user-profile-back"));
    expect(panel().querySelector("#hub-timesheets-profile")).toBeNull();
    expect(panel().querySelector(".hub-day-page")).not.toBeNull();
    expect(panel().querySelector(".hub-day-person").textContent).toContain("Ann Lee");
    expect(queries("/hub/attendance/week")).toHaveLength(before);
  });

  it("leaves an open profile alone on a background refresh", async () => {
    const { emit } = await connectHub();
    await openProfile();
    const before = queries("/hub/attendance/week").length;
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(queries("/hub/attendance/week")).toHaveLength(before);
    expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull();
  });

  it("does not offer the link to a Team Lead viewer", async () => {
    await openTimesheets({ role: "supervisor" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    await user().click(panel().querySelector(".hub-day-card"));
    expect(panel().querySelector(".hub-hours-person")).toBeNull();
  });

  it("openTimesheetsProfile mounts after the hub loads", async () => {
    const { mod } = await openHub({ role: "admin", handlers: [profileHandler()] });
    const tab = await import("../../../backend/static/views/hubTimesheetsTab.js");
    tab.openTimesheetsProfile("10000000-0000-4000-8000-000000000001", { week: "2026-09-07" });
    mod.openHubTab("timesheets");
    await vi.waitFor(() => expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull());
    await vi.waitFor(() => expect(queries("/hub/people/")).toEqual([{ week: "2026-09-07" }]));
    expect(panel().querySelector("#user-profile-heading").textContent).toContain("Ann Lee");
  });
});
