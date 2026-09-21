// The Admin Hours grid: cells, tally, drill-down, flags, DST footer.
//
// A pure view test -- the module fetches nothing, so the payload goes in
// directly and no MSW handler is involved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceWeek } from "../helpers/factories.js";
import { mountHubAttendanceHours } from "../../../backend/static/views/hubAttendanceHours.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
});

const cells = () => Array.from(host.querySelectorAll(".hub-hours-cell"));

describe("the grid", () => {
  it("renders one row per person and seven day cells", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(cells()).toHaveLength(7);
    expect(host.textContent).toContain("Ann Lee");
  });

  it("prints clocked time as h:mm and tallies the week", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(cells()[0].textContent).toContain("8:00");
    expect(host.querySelector(".hub-hours-row-total").textContent).toContain("8:00");
    expect(host.querySelector("tfoot").textContent).toContain("8:00");
  });

  it("shows the empty state when nobody is in the payload", () => {
    mountHubAttendanceHours(host, attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-hours-empty")).not.toBeNull();
    expect(host.querySelector("table")).toBeNull();
  });
});

describe("the drill-down", () => {
  it("opens a day's punch rows on a cell click and closes on a second", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown")).not.toBeNull();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("8:00");
    expect(cells()[0].getAttribute("aria-expanded")).toBe("true");
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown")).toBeNull();
  });

  it("says so when a day has no punches", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    cells()[1].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("No punches");
  });

  it("marks a carried punch and offers no edit affordance", () => {
    const week = attendanceWeek();
    week.rows[0].days[1] = {
      date: "2026-09-15", clocked_minutes: 120, needs_review: false, has_open: false,
      punches: [{ id: "punch-1", started_at: "2026-09-15T03:00:00Z",
                  ended_at: "2026-09-15T07:00:00Z", start_source: "manual",
                  end_source: "manual", needs_review: false, minutes: 120,
                  carried: true, open: false }],
    };
    mountHubAttendanceHours(host, week);
    cells()[1].click();
    const drill = host.querySelector(".hub-hours-drilldown");
    expect(drill.textContent).toContain("carried from");
    expect(drill.querySelectorAll("button")).toHaveLength(0);
  });
});

describe("flags", () => {
  it("flags a needs_review day in the cell and the drill-down", () => {
    const week = attendanceWeek();
    week.rows[0].days[0].needs_review = true;
    week.rows[0].days[0].punches[0].needs_review = true;
    week.rows[0].days[0].punches[0].end_source = "self_reported";
    mountHubAttendanceHours(host, week);
    expect(cells()[0].querySelector(".hub-hours-flag-review")).not.toBeNull();
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("needs review");
  });

  it("flags an open punch as running", () => {
    const week = attendanceWeek();
    week.rows[0].days[0].has_open = true;
    week.rows[0].days[0].punches[0].open = true;
    week.rows[0].days[0].punches[0].ended_at = null;
    week.rows[0].days[0].punches[0].end_source = null;
    mountHubAttendanceHours(host, week);
    expect(cells()[0].querySelector(".hub-hours-flag-open")).not.toBeNull();
    cells()[0].click();
    expect(host.querySelector(".hub-hours-drilldown").textContent).toContain("running");
  });
});

describe("the week bar", () => {
  it("steps back and forward by whole weeks", () => {
    const onWeekChange = vi.fn();
    mountHubAttendanceHours(host, attendanceWeek(), { onWeekChange });
    host.querySelector(".hub-hours-prev").click();
    expect(onWeekChange).toHaveBeenCalledWith("2026-09-07");
    host.querySelector(".hub-hours-next").click();
    expect(onWeekChange).toHaveBeenCalledWith("2026-09-21");
  });

  it("names a short DST week in the footer and stays quiet on a normal one", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.querySelector(".hub-hours-dst")).toBeNull();
    mountHubAttendanceHours(host, attendanceWeek({ week_hours: 167 }));
    expect(host.querySelector(".hub-hours-dst").textContent).toContain("167");
  });
});

describe("the edit controls", () => {
  it("offers Edit on an owned punch and withholds it on a carried one", () => {
    const payload = attendanceWeek();          // existing factory
    const row = payload.rows[0];
    row.days[0].punches = [
      { id: "p-own", started_at: "2026-09-14T13:00:00.000Z",
        ended_at: "2026-09-14T21:00:00.000Z", start_source: "manual",
        end_source: "manual", needs_review: false, minutes: 480,
        carried: false, open: false },
      { id: "p-carried", started_at: "2026-09-13T22:00:00.000Z",
        ended_at: "2026-09-14T02:00:00.000Z", start_source: "manual",
        end_source: "manual", needs_review: false, minutes: 120,
        carried: true, open: false },
    ];
    mountHubAttendanceHours(host, payload, { onSavePunch: vi.fn() });
    host.querySelector(".hub-hours-cell").click();

    const rows = host.querySelectorAll(".hub-hours-drilldown-row");
    expect(rows[0].querySelector(".hub-hours-edit")).not.toBeNull();
    expect(rows[1].querySelector(".hub-hours-edit")).toBeNull();
  });

  it("clears a needs_review flag through its own button", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].punches = [
      { id: "p-flagged", started_at: "2026-09-14T13:00:00.000Z",
        ended_at: "2026-09-14T21:00:00.000Z", start_source: "manual",
        end_source: "self_reported", needs_review: true, minutes: 480,
        carried: false, open: false },
    ];
    const onClearReview = vi.fn();
    mountHubAttendanceHours(host, payload, { onClearReview, onSavePunch: vi.fn() });
    host.querySelector(".hub-hours-cell").click();
    host.querySelector(".hub-hours-clear-review").click();

    expect(onClearReview).toHaveBeenCalledWith("p-flagged");
  });

  it("renders no edit affordances at all when no callbacks are given", () => {
    const payload = attendanceWeek();
    mountHubAttendanceHours(host, payload, {});
    host.querySelector(".hub-hours-cell").click();
    expect(host.querySelector(".hub-hours-edit")).toBeNull();
    expect(host.querySelector(".hub-hours-add")).toBeNull();
  });
});

describe("the CSP rule", () => {
  it("emits no inline style attributes", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.innerHTML).not.toMatch(/\sstyle="/);
  });
});
