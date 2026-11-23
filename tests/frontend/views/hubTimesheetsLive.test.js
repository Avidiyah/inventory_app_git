// W7 T6: the Timesheets roster and day strip patch in place.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { queries, connectHub, el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { attendanceLive, attendanceWeek } from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("timesheets");
const person = (id, first) => ({ id, first_name: first, last_name: "X", role: "technician" });
const onShift = (id, first, extra = {}) => ({
  user: person(id, first), punch_started_at: "2026-09-10T11:00:00Z", charging_since: null,
  idle_since: "2026-09-10T11:00:00Z", work_order_number: null, ...extra,
});

async function openTimesheets(live) {
  await openHub({ role: "supervisor", attendanceLive: live });
  await user().click(el.tab("timesheets"));
  await vi.waitFor(() => expect(panel().querySelector(".hub-roster")).not.toBeNull());
  return connectHub();
}

describe("roster", () => {
  it("a live change keeps unchanged cards and the open absent list; the changed card glows", async () => {
    const live = attendanceLive({
      on_shift: [onShift("u1", "Ann"), onShift("u2", "Bo")], on_shift_count: 2, idle_count: 2,
      absent: [{ user: person("u3", "Cy") }],
    });
    const { emit } = await openTimesheets(live);
    const ann = panel().querySelector("#ts-roster-u1");
    panel().querySelector(".hub-roster-absent").open = true;
    server.use(http.get("/hub/attendance/live", () => HttpResponse.json({
      ...live,
      on_shift: [onShift("u1", "Ann"), onShift("u2", "Bo", { charging_since: "2026-09-10T11:30:00Z", work_order_number: "7001" })],
      charging_count: 1, idle_count: 1,
    })));
    emit("attendance.changed");
    await vi.waitFor(() => expect(panel().querySelector("#ts-roster-u2").dataset.state).toBe("green"));
    expect(panel().querySelector("#ts-roster-u1")).toBe(ann);
    expect(panel().querySelector(".hub-roster-absent").open).toBe(true);
    expect(panel().querySelector("#ts-roster-u2").classList.contains("just-changed")).toBe(true);
    expect(ann.classList.contains("just-changed")).toBe(false);
  });

  it("the one-second tick does not glow a card", async () => {
    await openTimesheets(attendanceLive({ on_shift: [onShift("u1", "Ann")], on_shift_count: 1, idle_count: 1 }));
    await vi.advanceTimersByTimeAsync(3000);
    expect(panel().querySelector(".just-changed")).toBeNull();
  });
});

describe("day strip", () => {
  it("a week refetch patches the day cards in place, and a day card still opens its day", async () => {
    const { emit } = await openTimesheets(attendanceLive());
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-card")).not.toBeNull());
    const first = panel().querySelector(".hub-day-card");
    const weeks = queries("/hub/attendance/week").length;
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/week").length).toBeGreaterThan(weeks));
    await vi.advanceTimersByTimeAsync(10);
    expect(panel().querySelector(".hub-day-card")).toBe(first);
    await user().click(first);
    await vi.waitFor(() => expect(panel().querySelector(".hub-day-page")).not.toBeNull());
  });

  it("prev/next still change the week after a patch", async () => {
    const { emit } = await openTimesheets(attendanceLive());
    await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets-prev")).not.toBeNull());
    emit("attendance.changed");
    await vi.advanceTimersByTimeAsync(10);
    const before = queries("/hub/attendance/week").length;
    await user().click(panel().querySelector(".hub-timesheets-prev"));
    await vi.waitFor(() => expect(queries("/hub/attendance/week")).toHaveLength(before + 1));
    expect(queries("/hub/attendance/week").at(-1).week).toBeTruthy();
  });
});

void attendanceWeek;
