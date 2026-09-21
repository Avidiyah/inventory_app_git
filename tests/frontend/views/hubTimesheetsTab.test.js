// The Timesheets tabpanel: who sees the sub-nav, which feature fetches
// what, and that each fetches only when opened.
//
// Entered the way a user does -- openHub, then a click on the tab -- so the
// lazy loads fire exactly as they do in the app.

import { afterEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { attendanceWeek } from "../helpers/factories.js";
import { el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";

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

describe("below Admin", () => {
  it("shows the crew grid with no sub-nav", async () => {
    await openTimesheets({ role: "supervisor" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheet-table")).not.toBeNull());
    expect(panel().querySelector(".sub-nav")).toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(0);
  });
});

describe("Admin", () => {
  it("opens on Hours and fetches only the attendance week", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect(panel().querySelectorAll(".sub-nav-btn")).toHaveLength(2);
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(queries("/hub/timesheets")).toHaveLength(0);
  });

  it("fetches the crew grid only when that sub-tab is opened", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector('[data-feature="crew"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheet-table")).not.toBeNull());
    expect(queries("/hub/timesheets")).toHaveLength(1);
  });

  it("keeps each sub-tab's payload across a switch back", async () => {
    await openTimesheets({ role: "admin" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="crew"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheet-table")).not.toBeNull());
    await user().click(panel().querySelector('.sub-nav-btn[data-feature="hours"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect(queries("/hub/attendance/week")).toHaveLength(1);
    expect(queries("/hub/timesheets")).toHaveLength(1);
  });

  it("pages the week and sends a Monday", async () => {
    await openTimesheets({ role: "admin", attendanceWeek: attendanceWeek() });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-prev"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
    expect(queries("/hub/attendance/week").at(-1)).toEqual({ week: "2026-09-07" });
  });

  it("explains a failed Hours load and retries", async () => {
    await openTimesheets({ role: "admin", attendanceWeek: 500 });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-message.error")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-retry"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(2));
  });
});
