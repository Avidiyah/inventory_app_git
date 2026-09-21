// The Timesheets tabpanel: who sees the sub-nav, which feature fetches
// what, and that each fetches only when opened.
//
// Entered the way a user does -- openHub, then a click on the tab -- so the
// lazy loads fire exactly as they do in the app.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
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

  it("gives a Supervisor no edit controls at all", async () => {
    await openTimesheets({ role: "supervisor" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheet-table")).not.toBeNull());
    expect(panel().querySelector(".hub-hours-edit")).toBeNull();
  });
});
