// One **leaderboard board** (Accuracy or Efficiency): the % math, the
// ranking, the money columns and the empty state.
//
// A pure view: the week payload goes in directly, nothing is fetched.

import { beforeEach, describe, expect, it } from "vitest";
import { attendanceWeek } from "../helpers/factories.js";
import {
  computeLeaderboard,
  mountLeaderboardBoard,
} from "../../../backend/static/views/hubTimesheetLeaderboard.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
});

function mount(payload = attendanceWeek(), kind = "accuracy") {
  mountLeaderboardBoard(host, payload, { kind });
  return host;
}

// Ann clocks 8:00 and charges 7:00 live (88%). Bo clocks 10:00, charges 9:00
// live (90%) plus 2:00 keyed by hand.
function twoPeople() {
  const payload = attendanceWeek();
  const ann = payload.rows[0];
  const bo = structuredClone(ann);
  bo.user = { id: "user-2", first_name: "Bo", last_name: "Diaz", role: "technician" };
  bo.total_minutes = 600;
  bo.tracked_minutes = 540;
  bo.adjustment_minutes = 120;
  payload.rows = [ann, bo];
  return payload;
}

const entryFor = (payload, name, kind) =>
  computeLeaderboard(payload, { kind }).entries.find((e) => e.name === name);

describe("computeLeaderboard", () => {
  it("uses server row totals as-is", () => {
    // The server already left the pending day out of total_minutes.
    const payload = attendanceWeek();
    payload.rows[0].days[1] = { ...payload.rows[0].days[1], clocked_minutes: 600, pending_review: true };
    const entry = computeLeaderboard(payload, { kind: "accuracy" }).entries[0];
    expect(entry).toMatchObject({ clocked: 480, charged: 420, uncharged: 60, pendingDays: 1 });
  });

  it("accuracy ranks by live % and ignores hand-entered", () => {
    const { entries } = computeLeaderboard(twoPeople(), { kind: "accuracy" });
    expect(entries.map((e) => [e.rank, e.name, e.pct])).toEqual([[1, "Bo Diaz", 90], [2, "Ann Lee", 88]]);
    expect(entries[0]).toMatchObject({ charged: 540, uncharged: 60 });
    expect(entries[0].made).toBeCloseTo(562.5);
  });

  it("efficiency adds adjustment_minutes and may exceed 100", () => {
    const bo = entryFor(twoPeople(), "Bo Diaz", "efficiency");
    expect(bo).toMatchObject({ charged: 660, uncharged: 0, pct: 110, lost: 0 });
  });

  it("zero clocked with charge is 100%, with none is 0%", () => {
    const payload = twoPeople();
    payload.rows[0].total_minutes = 0;
    payload.rows[0].tracked_minutes = 0;
    payload.rows[1].total_minutes = 0;
    expect(entryFor(payload, "Ann Lee", "accuracy").pct).toBe(0);
    expect(entryFor(payload, "Bo Diaz", "accuracy").pct).toBe(100);
  });

  it("breaks a % tie on money made, then name", () => {
    const payload = twoPeople();
    payload.rows[1].total_minutes = 960;
    payload.rows[1].tracked_minutes = 840; // 88%, more money than Ann
    const { entries, total } = computeLeaderboard(payload, { kind: "accuracy" });
    expect(entries.map((e) => e.name)).toEqual(["Bo Diaz", "Ann Lee"]);
    expect(total.made).toBeCloseTo(437.5 + 875);
  });
});

describe("the board", () => {
  it("prints the % and the hours and money columns, with a medal for first", () => {
    mount(twoPeople());
    const headers = [...host.querySelectorAll("thead th")].map((th) => th.textContent);
    expect(headers).toEqual(["Rank", "Person", "%", "Clocked", "Charged", "Uncharged", "Made", "Lost"]);
    const first = host.querySelector(".hub-leaderboard-row");
    expect(first.querySelector("th").textContent).toBe("Bo Diaz");
    expect(first.querySelector(".hub-leaderboard-rank").textContent).toContain("🥇");
    expect(first.querySelector(".hub-leaderboard-rank").textContent).toContain("1st");
    expect(first.querySelector(".hub-leaderboard-pct").textContent).toBe("90%");
    expect(first.querySelector(".hub-leaderboard-made").textContent).toBe("$562.50");
    expect(host.querySelector("tfoot").textContent).toContain("Company total");
  });

  it("titles each kind and carries its tip", () => {
    mount(attendanceWeek(), "accuracy");
    expect(host.querySelector(".hub-leaderboard-heading").textContent).toContain("Accuracy");
    expect(host.querySelector('[data-tip="hub.leaderboard-accuracy"]')).not.toBeNull();
    mount(attendanceWeek(), "efficiency");
    expect(host.querySelector(".hub-leaderboard-heading").textContent).toContain("Efficiency");
    expect(host.querySelector('[data-tip="hub.leaderboard-efficiency"]')).not.toBeNull();
  });

  it("has no action buttons, only its tip", () => {
    mount(twoPeople());
    expect(host.querySelectorAll("button:not([data-tip])")).toHaveLength(0);
  });

  it("flags a person's pending days in words beside their name", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0].pending_review = true;
    mount(payload);
    expect(host.querySelector(".hub-leaderboard-pending").textContent).toBe("⚠ 1 day pending review");
  });

  it("says nobody clocked in rather than drawing an empty table", () => {
    mount(attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-leaderboard-table")).toBeNull();
    expect(host.querySelector(".hub-leaderboard-empty")).not.toBeNull();
  });
});
