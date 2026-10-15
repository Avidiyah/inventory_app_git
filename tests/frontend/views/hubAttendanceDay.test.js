// The Admin day strip and the day page it opens: cards, week paging, the
// per-person list, day stepping, and the punch editor wiring.
//
// A pure view test -- the module fetches nothing, so the payload goes in
// directly and no MSW handler is involved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { attendanceWeek } from "../helpers/factories.js";
import {
  mondayOf, mountHubAttendanceDayPage, mountHubAttendanceDays,
} from "../../../backend/static/views/hubAttendanceDay.js";

let host;
const user = () => userEvent.setup();

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
});

describe("the day strip", () => {
  it("renders seven cards with headcount and clocked time", () => {
    mountHubAttendanceDays(host, attendanceWeek());
    const cards = host.querySelectorAll(".hub-day-card");
    expect(cards).toHaveLength(7);
    expect(cards[0].textContent).toContain("1 clocked in");
    expect(cards[0].textContent).toContain("8:00");
    expect(cards[0].textContent).toContain("8:00 AM – 4:00 PM");
    expect(cards[1].textContent).toContain("0 clocked in");
  });

  it("opens a day and pages the week by a whole week", async () => {
    const opened = [];
    const weeks = [];
    mountHubAttendanceDays(host, attendanceWeek(), {
      onOpenDay: (d) => opened.push(d), onWeekChange: (w) => weeks.push(w),
    });
    await user().click(host.querySelectorAll(".hub-day-card")[2]);
    await user().click(host.querySelector(".hub-timesheets-prev"));
    await user().click(host.querySelector(".hub-timesheets-next"));
    expect(opened).toEqual(["2026-09-16"]);
    expect(weeks).toEqual(["2026-09-07", "2026-09-21"]);
  });
});

describe("the day page", () => {
  it("lists everyone clocked in that day and the empty state otherwise", () => {
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-14");
    expect(host.querySelectorAll(".hub-day-person")).toHaveLength(1);
    expect(host.textContent).toContain("Ann Lee");
    expect(host.textContent).toContain("1 clocked in");
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-15");
    expect(host.querySelector(".hub-hours-empty")).not.toBeNull();
  });

  it("steps a day at a time and goes Back", async () => {
    const days = [];
    const onBack = vi.fn();
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-14", { onDayChange: (d) => days.push(d), onBack });
    await user().click(host.querySelector(".hub-day-prev"));
    await user().click(host.querySelector(".hub-day-next"));
    await user().click(host.querySelector(".hub-day-back"));
    expect(days).toEqual(["2026-09-13", "2026-09-15"]);
    expect(onBack).toHaveBeenCalled();
  });

  it("offers Edit and Add only with the write callbacks, and adds for the right person", async () => {
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-14");
    expect(host.querySelector(".hub-hours-edit")).toBeNull();
    expect(host.querySelector(".hub-hours-add")).toBeNull();
    const onSavePunch = vi.fn();
    const onAddPunch = vi.fn();
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-14", { onSavePunch, onAddPunch });
    await user().click(host.querySelector(".hub-hours-add"));
    expect(host.querySelector(".hub-hours-editor[data-user='user-1'] .punch-editor")).not.toBeNull();
    await user().click(host.querySelector(".punch-editor-cancel"));
    expect(host.querySelector(".punch-editor")).toBeNull();
    await user().click(host.querySelector(".hub-hours-edit"));
    expect(host.querySelector(".punch-editor")).not.toBeNull();
  });

  it("links a profilable name only with onOpenProfile", async () => {
    mountHubAttendanceDayPage(host, attendanceWeek(), "2026-09-14");
    expect(host.querySelector(".hub-hours-person")).toBeNull();
    const onOpenProfile = vi.fn();
    const week = attendanceWeek();
    mountHubAttendanceDayPage(host, week, "2026-09-14", { onOpenProfile });
    await user().click(host.querySelector(".hub-hours-person"));
    expect(onOpenProfile).toHaveBeenCalledWith(week.rows[0].user);
  });
});

describe("mondayOf", () => {
  it("returns the Monday of any date", () => {
    expect(mondayOf("2026-09-13")).toBe("2026-09-07");
    expect(mondayOf("2026-09-14")).toBe("2026-09-14");
    expect(mondayOf("2026-09-20")).toBe("2026-09-14");
  });
});
