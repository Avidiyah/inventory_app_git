// Characterization coverage for views/hubTimesheets.js: the grid the
// Timesheets tab fetches lazily, its per-cell drill-down, the week nav's
// hand-off back through userHub.js, and the CSV export.
//
// Entered the way a user does -- openHub, then a click on the tab, which is
// what fires GET /hub/timesheets. One mount per test (setup.js resets modules
// per test, so a second mount inside one test paints into a detached shell).
//
// Every date label is computed here with the module's own Intl options: the
// grid is cut in UTC, the drill-down's session times in Central.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor } from "../helpers/requests.js";
import { el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";
import { restoreBrowserStubs, stubObjectUrl } from "../helpers/browserStubs.js";
import {
  hubAdjustment, hubTimelineEntry, hubTimesheetDay, hubTimesheetDayTotal, hubTimesheetRow,
  hubTimesheets,
} from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("timesheets");
const message = () => panel().querySelector(".hub-timesheet-message");
const table = () => panel().querySelector(".hub-timesheet-table");
const headerCells = () => Array.from(table().querySelectorAll("thead th")).map((th) => th.textContent);
const footerCells = () => Array.from(table().querySelectorAll("tfoot th, tfoot td")).map((c) => c.textContent);
const bodyRows = () => Array.from(table().querySelectorAll("tbody tr"));
const cellFor = (row, date) =>
  panel().querySelector(`.hub-timesheet-cell[data-row="${row}"][data-date="${date}"]`);

// The module's own label helpers, re-derived rather than retyped.
const atUtc = (iso) => new Date(`${iso}T00:00:00Z`);
const utcShort = (iso) => atUtc(iso).toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC" });
const utcLong = (iso) => atUtc(iso).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const utcRange = (iso) => atUtc(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const central = (instant) => new Date(instant).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" });

const DATES = ["2026-09-07", "2026-09-08"];
const dayTotals = (minutes) => DATES.map((date, i) => hubTimesheetDayTotal({ date, minutes: minutes[i] }));

// Open the hub, switch to Timesheets, wait for the grid (or the empty hint).
async function openSheet(timesheets, role = "supervisor") {
  const mounted = await openHub({ role, timesheets });
  await user().click(el.tab("timesheets"));
  await vi.waitFor(() => expect(panel().querySelector(".hub-timesheets")).not.toBeNull());
  return mounted;
}

describe("the grid", () => {
  it("a header per day, a row per person, and a missing day as 0:00", async () => {
    await openSheet(hubTimesheets({
      crew_totals_by_day: dayTotals([90, 30]),
      rows: [hubTimesheetRow({
        days: [hubTimesheetDay({ date: DATES[0], tracked_minutes: 90, total_minutes: 90 })],
        total_minutes: 90,
      })],
    }));
    expect(headerCells()).toEqual(["Technician", utcShort(DATES[0]), utcShort(DATES[1]), "Total"]);
    expect(bodyRows()).toHaveLength(1);
    expect(bodyRows()[0].querySelector("th").textContent).toBe("Crew One");
    expect(cellFor(0, DATES[0]).textContent).toBe("1:30");
    expect(cellFor(0, DATES[1]).textContent).toBe("0:00");   // no days entry at all
    expect(bodyRows()[0].querySelector(".hub-timesheet-row-total").textContent).toBe("1:30");
  });

  it("footer totals come from crew_totals_by_day, and the grand total is their sum", async () => {
    await openSheet(hubTimesheets({
      crew_totals_by_day: dayTotals([90, 45]),
      rows: [hubTimesheetRow({ total_minutes: 135 })],
    }));
    expect(footerCells()).toEqual(["Crew total", "1:30", "0:45", "2:15"]);
  });

  it("a nameless user reads Unknown", async () => {
    await openSheet(hubTimesheets({
      crew_totals_by_day: dayTotals([0, 0]),
      rows: [hubTimesheetRow({ user: { id: "u1", first_name: null, last_name: null, role: "technician" } })],
    }));
    expect(bodyRows()[0].querySelector("th").textContent).toBe("Unknown");
  });

  it("the range label reads both ends in UTC, with the tip", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    const nav = panel().querySelector(".hub-timesheet-week-nav strong");
    expect(nav.textContent).toContain(`${utcRange("2026-09-07")} – ${utcRange("2026-09-13")}`);
    expect(nav.querySelector(".tip-btn").dataset.tip).toBe("hub.timesheets");
  });
});

describe("flags", () => {
  const withFlags = (flags) => hubTimesheets({
    crew_totals_by_day: dayTotals([60, 0]),
    rows: [hubTimesheetRow({
      days: [hubTimesheetDay({ date: DATES[0], tracked_minutes: 60, total_minutes: 60, flags })],
      total_minutes: 60,
    })],
  });

  it.each([
    ["running", "●", "running"],
    ["assigned_idle", "⚠", "assigned but idle"],
    ["some_new_flag", "⚠", "some new flag"],      // the fallback: glyph plus snake-case words
  ])("%s renders %s with the sr-only label %s", async (flag, glyph, label) => {
    await openSheet(withFlags([flag]));
    const cell = cellFor(0, DATES[0]);
    const mark = cell.querySelector(`.hub-timesheet-flag-${flag}`);
    expect(mark.querySelector("[aria-hidden]").textContent).toBe(glyph);
    expect(mark.querySelector(".sr-only").textContent).toBe(` ${label}`);
    expect(cell.getAttribute("aria-label"))
      .toBe(`Crew One, ${utcLong(DATES[0])}, 1:00, ${label}`);
  });

  it("no flags: the aria-label stops at the total", async () => {
    await openSheet(withFlags([]));
    expect(cellFor(0, DATES[0]).getAttribute("aria-label")).toBe(`Crew One, ${utcLong(DATES[0])}, 1:00`);
    expect(cellFor(0, DATES[0]).querySelector(".hub-timesheet-flag")).toBeNull();
  });
});

describe("scope copy", () => {
  it("a supervisor sees the crew framing and the routed-to-you empty hint", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]), rows: [] }));
    expect(panel().querySelector(".hub-timesheet-empty").textContent)
      .toBe("No one is currently routed to you. Crew hours appear here after a work order is routed to you and assigned.");
    expect(table()).toBeNull();
  });

  it("a supervisor's table is captioned Crew, footed Crew total", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    expect(table().querySelector("caption").textContent)
      .toBe("Crew timesheets for 2026-09-07 through 2026-09-13");
    expect(footerCells()[0]).toBe("Crew total");
  });

  it("techfm_oa+ gets the company framing and its own empty hint", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]), rows: [] }), "techfm_oa");
    expect(panel().querySelector(".hub-timesheet-empty").textContent)
      .toBe("No live Supervisors or Technicians to show.");
  });

  it("techfm_oa+ captions the table Company", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }), "techfm_oa");
    expect(table().querySelector("caption").textContent)
      .toBe("Company timesheets for 2026-09-07 through 2026-09-13");
    expect(footerCells()[0]).toBe("Company total");
  });
});

describe("the drill-down", () => {
  const session = (extra = {}) => hubTimelineEntry({
    started_at: "2026-09-07T14:00:00Z", ended_at: "2026-09-07T15:00:00Z", minutes: 60, ...extra,
  });
  const detailed = (dayOverrides = {}) => hubTimesheets({
    crew_totals_by_day: dayTotals([90, 0]),
    rows: [hubTimesheetRow({
      days: [
        hubTimesheetDay({
          date: DATES[0], tracked_minutes: 60, adjustment_minutes: 30, total_minutes: 90,
          sessions: [session()], adjustments: [hubAdjustment()], ...dayOverrides,
        }),
        hubTimesheetDay({ date: DATES[1] }),
      ],
      total_minutes: 90,
    })],
  });
  const drill = () => panel().querySelector(".hub-timesheet-drilldown");

  it("a cell click opens the day: heading, sessions, Charged, adjustments, Total", async () => {
    await openSheet(detailed());
    expect(drill()).toBeNull();
    await user().click(cellFor(0, DATES[0]));
    const heading = drill().querySelector(".hub-timesheet-drilldown-heading");
    expect(heading.textContent).toContain(`Crew One · ${utcLong(DATES[0])}`);
    expect(heading.textContent).toContain("1:30 total");
    const rows = Array.from(drill().querySelectorAll(".hub-timesheet-drilldown-row"));
    expect(rows[0].textContent).toContain(
      `${central("2026-09-07T14:00:00Z")} – ${central("2026-09-07T15:00:00Z")} · Work order 7001`);
    expect(rows[0].querySelector("span:last-child").textContent).toBe("1:00");
    expect(drill().querySelector(".hub-timesheet-subtotal").textContent).toBe("Charged1:00");
    expect(rows.find((r) => r.textContent.includes("Adjustment")).textContent)
      .toContain("Adjustment · Work order 7001 by Sue Super");
    expect(drill().querySelector(".hub-timesheet-total").textContent).toBe("Total1:30");
    // The detail row spans the whole grid: a name column, each day, the total.
    expect(panel().querySelector(".hub-timesheet-detail-row td").getAttribute("colspan")).toBe("4");
  });

  it("a running session reads 'running'; an auto-closed one is marked an estimate", async () => {
    await openSheet(detailed({ sessions: [session({ ended_at: null }), session({ auto_closed: true })] }));
    await user().click(cellFor(0, DATES[0]));
    const rows = Array.from(drill().querySelectorAll(".hub-timesheet-drilldown-row"));
    expect(rows[0].textContent).toContain(`${central("2026-09-07T14:00:00Z")} – running`);
    expect(rows[1].querySelector(".hub-timesheet-estimate").textContent).toBe("⚠ estimate");
  });

  it("aria-expanded and aria-controls follow the open cell, and a second click collapses", async () => {
    await openSheet(detailed());
    expect(cellFor(0, DATES[0]).getAttribute("aria-expanded")).toBe("false");
    expect(cellFor(0, DATES[0]).getAttribute("aria-controls")).toBe("hub-timesheet-detail-0");
    await user().click(cellFor(0, DATES[0]));
    expect(cellFor(0, DATES[0]).getAttribute("aria-expanded")).toBe("true");
    expect(panel().querySelector("#hub-timesheet-detail-0")).not.toBeNull();
    await user().click(cellFor(0, DATES[0]));
    expect(drill()).toBeNull();
    expect(cellFor(0, DATES[0]).getAttribute("aria-expanded")).toBe("false");
  });

  it("clicking another day in the same row moves the open detail", async () => {
    await openSheet(detailed());
    await user().click(cellFor(0, DATES[0]));
    await user().click(cellFor(0, DATES[1]));
    expect(cellFor(0, DATES[0]).getAttribute("aria-expanded")).toBe("false");
    expect(cellFor(0, DATES[1]).getAttribute("aria-expanded")).toBe("true");
    expect(drill().querySelector(".hub-timesheet-no-detail").textContent)
      .toBe("No sessions or adjustments recorded.");
  });
});

describe("week navigation", () => {
  it("previous week refetches the range shifted back seven days", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    await user().click(panel().querySelector(".hub-timesheet-prev"));
    await vi.waitFor(() => expect(queries("/hub/timesheets").length).toBeGreaterThan(1));
    expect(queries("/hub/timesheets").at(-1)).toEqual({ start: "2026-08-31", end: "2026-09-06" });
  });

  it("next week shifts forward seven days", async () => {
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    await user().click(panel().querySelector(".hub-timesheet-next"));
    await vi.waitFor(() => expect(queries("/hub/timesheets").length).toBeGreaterThan(1));
    expect(queries("/hub/timesheets").at(-1)).toEqual({ start: "2026-09-14", end: "2026-09-20" });
  });
});

describe("the CSV export", () => {
  const csv = (filename) => new HttpResponse("a,b\n1,2", {
    status: 200,
    headers: filename ? { "Content-Disposition": `attachment; filename="${filename}"` } : {},
  });
  const exportBtn = () => panel().querySelector(".hub-timesheet-export");

  it("sends the rendered range, reports the filename, and disables the button meanwhile", async () => {
    const urls = stubObjectUrl();
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    server.use(http.get("/hub/timesheets/export", async () => { await gate; return csv("crew-week.csv"); }));
    await user().click(exportBtn());
    await vi.waitFor(() => expect(message().textContent).toBe("Preparing export…"));
    expect(exportBtn().disabled).toBe(true);
    release();
    await vi.waitFor(() => expect(message().textContent).toBe("Exported crew-week.csv."));
    expect(message().className).toBe("hub-timesheet-message success");
    expect(exportBtn().disabled).toBe(false);
    expect(Object.fromEntries(new URL(requestFor("/hub/timesheets/export").url, "http://t").searchParams))
      .toEqual({ start: "2026-09-07", end: "2026-09-13" });
    expect(urls.createObjectURL).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);            // the queued revokeObjectURL
    expect(urls.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("a response with no Content-Disposition falls back to timesheet.csv", async () => {
    stubObjectUrl();
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    server.use(http.get("/hub/timesheets/export", () => csv(null)));
    await user().click(exportBtn());
    await vi.waitFor(() => expect(message().textContent).toBe("Exported timesheet.csv."));
    await vi.advanceTimersByTimeAsync(1);
  });

  it("a failure writes the detail and re-enables the button", async () => {
    stubObjectUrl();
    await openSheet(hubTimesheets({ crew_totals_by_day: dayTotals([0, 0]) }));
    server.use(http.get("/hub/timesheets/export",
      () => HttpResponse.json({ detail: "Export is locked" }, { status: 500 })));
    await user().click(exportBtn());
    await vi.waitFor(() => expect(message().className).toBe("hub-timesheet-message error"));
    expect(message().textContent).toBe("Export is locked");
    expect(exportBtn().disabled).toBe(false);
  });
});

describe("its own formatHm", () => {
  it("renders h:mm, not format.js's 'N h M m' -- two renderings, one name", async () => {
    // Characterization, filed under N-P6-CHARACTERIZED: hubTimesheets.js
    // defines a private formatHm whose output shape differs from the
    // format.js export of the same name, and the hub shows both at once
    // (the Dashboard's "1 h 30 m" beside this grid's "1:30").
    await openSheet(hubTimesheets({
      crew_totals_by_day: dayTotals([90, 5]),
      rows: [hubTimesheetRow({ total_minutes: 95 })],
    }));
    expect(footerCells().slice(1)).toEqual(["1:30", "0:05", "1:35"]);
  });
});
