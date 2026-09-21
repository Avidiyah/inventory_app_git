// The Admin **Charged vs clocked** grid: three numbers per cell, two flags in
// opposite directions, the week nav, the CSV export and the empty state.
//
// A pure view except for the export blob, so the payload goes in directly and
// MSW is involved only for `/hub/attendance/export`.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { attendanceLive, attendanceWeek } from "../helpers/factories.js";
import { restoreBrowserStubs, stubObjectUrl } from "../helpers/browserStubs.js";
import { mountHubAttendanceCompare } from "../../../backend/static/views/hubAttendanceCompare.js";
import { destroyHubAttendanceRoster } from "../../../backend/static/views/hubAttendanceRoster.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
  stubObjectUrl();
});

afterEach(() => {
  // The strip owns an interval; this view is mounted without the hub shell,
  // so nothing else here would stop it.
  destroyHubAttendanceRoster();
  restoreBrowserStubs();
});

const user = () => userEvent.setup();

function mount(payload = attendanceWeek(), options = {}) {
  mountHubAttendanceCompare(host, payload, options);
  return host;
}

describe("the comparison grid", () => {
  it("prints clocked over charged with the gap between them", () => {
    mount();
    const cell = host.querySelector(".hub-compare-cell");
    expect(cell.querySelector(".hub-compare-clocked").textContent).toBe("8:00");
    expect(cell.querySelector(".hub-compare-tracked").textContent).toBe("7:00");
    expect(cell.querySelector(".hub-compare-delta").textContent).toContain("1:00");
  });

  it("names every number in the cell's accessible label, not by colour alone", () => {
    mount();
    const label = host.querySelector(".hub-compare-cell").getAttribute("aria-label");
    expect(label).toContain("8:00 clocked");
    expect(label).toContain("7:00 charged");
    expect(label).toContain("1:00 off job");
  });

  it("flags charged time outside the shift with a glyph and words", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].outside_shift_minutes = 45;
    mount(payload);
    const flag = host.querySelector(".hub-compare-flag-outside");
    expect(flag).not.toBeNull();
    expect(flag.textContent).toContain("0:45 charged outside shift");
  });

  it("shows an adjustment beside the wall-clock numbers, never inside them", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].adjustment_minutes = 30;
    mount(payload);
    const cell = host.querySelector(".hub-compare-cell");
    expect(cell.textContent).toContain("+0:30 adjusted");
    expect(cell.querySelector(".hub-compare-tracked").textContent).toBe("7:00");
  });

  it("hides the adjustment line when there is none", () => {
    mount();
    expect(host.querySelector(".hub-compare-adjustment")).toBeNull();
  });

  it("pages the week by a whole week at a time", async () => {
    const weeks = [];
    mount(attendanceWeek(), { onWeekChange: (w) => weeks.push(w) });
    await user().click(host.querySelector(".hub-compare-prev"));
    await user().click(host.querySelector(".hub-compare-next"));
    expect(weeks).toEqual(["2026-09-07", "2026-09-21"]);
  });

  it("says a short week is short rather than letting it read as lost hours", () => {
    mount(attendanceWeek({ week_hours: 167 }));
    expect(host.querySelector(".hub-compare-dst").textContent).toContain("167");
  });

  it("downloads the CSV and reports the filename", async () => {
    server.use(http.get("/hub/attendance/export", () => new HttpResponse("x", {
      headers: { "Content-Disposition": 'attachment; filename="attendance_2026-09-14.csv"' },
    })));
    mount();
    await user().click(host.querySelector(".hub-compare-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-compare-message").textContent)
      .toContain("attendance_2026-09-14.csv"));
  });

  it("explains a refused export without losing the grid", async () => {
    server.use(http.get("/hub/attendance/export", () =>
      HttpResponse.json({ detail: "Nope." }, { status: 403 })));
    mount();
    await user().click(host.querySelector(".hub-compare-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-compare-message").className)
      .toContain("error"));
    expect(host.querySelector(".hub-compare-table")).not.toBeNull();
  });

  it("says nobody clocked in rather than drawing an empty table", () => {
    mount(attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-compare-table")).toBeNull();
    expect(host.querySelector(".hub-compare-empty")).not.toBeNull();
  });

  it("mounts the roster strip above the grid when given a live payload", () => {
    mount(attendanceWeek(), { live: attendanceLive() });
    const section = host.querySelector(".hub-compare");
    expect(section.querySelector(".hub-roster-strip")).not.toBeNull();
    // Above: the strip is the headline, the grid is the record.
    expect(section.querySelector(".hub-roster").compareDocumentPosition(
      section.querySelector(".hub-compare-table-wrap"),
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders the grid with no strip when there is no live payload", () => {
    mount(attendanceWeek());
    expect(host.querySelector(".hub-compare-table")).not.toBeNull();
    expect(host.querySelector(".hub-roster-strip")).toBeNull();
  });
});
