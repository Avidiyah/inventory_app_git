// The Admin Timesheets **revenue leaderboard**: the money math, the ranking,
// the week picker, the CSV export and the empty state.
//
// A pure view except for the export blob, so the payload goes in directly and
// MSW is involved only for `/hub/attendance/export`.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { attendanceWeek } from "../helpers/factories.js";
import { restoreBrowserStubs, stubObjectUrl } from "../helpers/browserStubs.js";
import {
  computeLeaderboard,
  mountHubTimesheetLeaderboard,
} from "../../../backend/static/views/hubTimesheetLeaderboard.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
  stubObjectUrl();
});

afterEach(() => {
  restoreBrowserStubs();
});

const user = () => userEvent.setup();

function mount(payload = attendanceWeek(), options = {}) {
  mountHubTimesheetLeaderboard(host, payload, options);
  return host;
}

// Two people: Ann clocks 8:00 and charges 7:00; Bo clocks 10:00 and charges
// 9:00 on the clock plus 0:30 entered by hand.
function twoPeople() {
  const payload = attendanceWeek();
  const ann = payload.rows[0];
  const bo = structuredClone(ann);
  bo.user = { id: "user-2", first_name: "Bo", last_name: "Diaz", role: "technician" };
  bo.total_minutes = 600;
  bo.tracked_minutes = 540;
  bo.days[0].adjustment_minutes = 30;
  payload.rows = [ann, bo];
  return payload;
}

describe("computeLeaderboard", () => {
  it("prices charged and uncharged hours at the payload's rate", () => {
    const { entries } = computeLeaderboard(attendanceWeek());
    expect(entries[0]).toMatchObject({ charged: 420, uncharged: 60, made: 437.5, lost: 62.5 });
  });

  it("counts hand-entered labor as charged time", () => {
    const bo = computeLeaderboard(twoPeople()).entries.find((e) => e.name === "Bo Diaz");
    expect(bo).toMatchObject({ charged: 570, uncharged: 30 });
    expect(bo.made).toBeCloseTo(593.75);
  });

  it("never reports negative uncharged time when charged exceeds clocked", () => {
    const payload = attendanceWeek();
    payload.rows[0].tracked_minutes = 600;
    expect(computeLeaderboard(payload).entries[0]).toMatchObject({ uncharged: 0, lost: 0 });
  });

  it("ranks by money made, highest first, and totals the company", () => {
    const { entries, total } = computeLeaderboard(twoPeople());
    expect(entries.map((e) => [e.rank, e.name])).toEqual([[1, "Bo Diaz"], [2, "Ann Lee"]]);
    expect(total.made).toBeCloseTo(437.5 + 593.75);
    expect(total.lost).toBeCloseTo(62.5 + 31.25);
  });
});

describe("the leaderboard table", () => {
  it("prints hours and money in plain columns with a medal for first place", () => {
    mount(twoPeople());
    const first = host.querySelector(".hub-leaderboard-row");
    expect(first.querySelector("th").textContent).toBe("Bo Diaz");
    expect(first.querySelector(".hub-leaderboard-rank").textContent).toContain("🥇");
    expect(first.querySelector(".hub-leaderboard-rank").textContent).toContain("1st");
    expect(first.querySelector(".hub-leaderboard-made").textContent).toBe("$593.75");
    expect(first.querySelector(".hub-leaderboard-lost").textContent).toBe("$31.25");
    expect(host.querySelector("tfoot").textContent).toContain("Company total");
  });

  it("says the charged share in words and sizes the bar to match", () => {
    mount();
    const bar = host.querySelector(".hub-leaderboard-bar");
    expect(bar.getAttribute("aria-label")).toBe("88% of clocked time charged");
    expect(bar.querySelector(".hub-leaderboard-bar-made").style.width).toBe("88%");
    expect(bar.querySelector(".hub-leaderboard-bar-lost").style.width).toBe("12%");
  });

  it("carries the leaderboard tooltip and states the rate", () => {
    mount();
    expect(host.querySelector('[data-tip="hub.leaderboard"]')).not.toBeNull();
    expect(host.querySelector(".hub-leaderboard-legend").textContent).toContain("$62.50");
  });

  it("pages the week by a whole week at a time", async () => {
    const weeks = [];
    mount(attendanceWeek(), { onWeekChange: (w) => weeks.push(w) });
    await user().click(host.querySelector(".hub-timesheets-prev"));
    await user().click(host.querySelector(".hub-timesheets-next"));
    expect(weeks).toEqual(["2026-09-07", "2026-09-21"]);
  });

  it("downloads the CSV and reports the filename", async () => {
    server.use(http.get("/hub/attendance/export", () => new HttpResponse("x", {
      headers: { "Content-Disposition": 'attachment; filename="attendance_2026-09-14.csv"' },
    })));
    mount();
    await user().click(host.querySelector(".hub-timesheets-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-leaderboard-message").textContent)
      .toContain("attendance_2026-09-14.csv"));
  });

  it("explains a refused export without losing the table", async () => {
    server.use(http.get("/hub/attendance/export", () =>
      HttpResponse.json({ detail: "Nope." }, { status: 403 })));
    mount();
    await user().click(host.querySelector(".hub-timesheets-export"));
    await vi.waitFor(() => expect(host.querySelector(".hub-leaderboard-message").className)
      .toContain("error"));
    expect(host.querySelector(".hub-leaderboard-table")).not.toBeNull();
  });

  it("says nobody clocked in rather than drawing an empty table", () => {
    mount(attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-leaderboard-table")).toBeNull();
    expect(host.querySelector(".hub-leaderboard-empty")).not.toBeNull();
  });
});
