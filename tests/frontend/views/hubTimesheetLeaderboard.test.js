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
// live (90%) plus 1:00 keyed by hand, all on Monday. The board sums days,
// so a test that changes a person's week sets Monday's figures.
function twoPeople() {
  const payload = attendanceWeek();
  const ann = payload.rows[0];
  const bo = structuredClone(ann);
  bo.user = { id: "user-2", first_name: "Bo", last_name: "Diaz", role: "technician" };
  bo.days[0] = { ...bo.days[0], clocked_minutes: 600, paid_minutes: 570, tracked_minutes: 540, adjustment_minutes: 60 };
  bo.total_minutes = 600;
  bo.tracked_minutes = 540;
  bo.adjustment_minutes = 60;
  payload.rows = [ann, bo];
  return payload;
}

const entryFor = (payload, name, kind) =>
  computeLeaderboard(payload, { kind }).entries.find((e) => e.name === name);

describe("computeLeaderboard", () => {
  it("sums the counted days and leaves a pending day out", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[1] = { ...payload.rows[0].days[1], clocked_minutes: 600, tracked_minutes: 500, pending_review: true };
    const entry = computeLeaderboard(payload, { kind: "accuracy" }).entries[0];
    expect(entry).toMatchObject({ clocked: 480, charged: 420, uncharged: 60, pendingDays: 1, overDays: 0 });
  });

  it("a day charged past its clocked time is left out whole, hours and all, so % never passes 100", () => {
    const payload = twoPeople();
    const bo = payload.rows[1];
    // Bo: Mon 600 clocked / 540 live + 60 by hand; Tue 300 clocked but 19 h keyed by hand.
    bo.days[1] = { ...bo.days[1], clocked_minutes: 300, tracked_minutes: 0, adjustment_minutes: 1140 };
    const eff = entryFor(payload, "Bo Diaz", "efficiency");
    expect(eff).toMatchObject({ clocked: 600, charged: 600, pct: 100, overDays: 1 });
    // Accuracy ignores hand-entered labor, so the same Tuesday counts there.
    const acc = entryFor(payload, "Bo Diaz", "accuracy");
    expect(acc).toMatchObject({ clocked: 900, charged: 540, overDays: 0 });
  });

  it("accuracy ranks by live % and ignores hand-entered", () => {
    const { entries } = computeLeaderboard(twoPeople(), { kind: "accuracy" });
    expect(entries.map((e) => [e.rank, e.name, e.pct])).toEqual([[1, "Bo Diaz", 90], [2, "Ann Lee", 88]]);
    expect(entries[0]).toMatchObject({ charged: 540, uncharged: 60 });
    expect(entries[0].made).toBeCloseTo(562.5);
  });

  it("efficiency adds a day's hand-entered labor while it fits in the clocked time", () => {
    expect(entryFor(twoPeople(), "Bo Diaz", "efficiency")).toMatchObject({ clocked: 600, charged: 600, uncharged: 0, pct: 100, lost: 0 });
  });

  it("no time at all is left off; a charge with no clock is an over-charged day, kept at 0% with its note", () => {
    const payload = twoPeople();
    payload.rows[0].days[0] = { ...payload.rows[0].days[0], clocked_minutes: 0, tracked_minutes: 0 };
    payload.rows[1].days[0] = { ...payload.rows[1].days[0], clocked_minutes: 0, adjustment_minutes: 0 };
    expect(entryFor(payload, "Ann Lee", "accuracy")).toBeUndefined();
    expect(entryFor(payload, "Bo Diaz", "accuracy")).toMatchObject({ clocked: 0, charged: 0, pct: 0, overDays: 1 });
  });

  it("breaks a % tie on money made, then name", () => {
    const payload = twoPeople();
    payload.rows[1].days[0] = { ...payload.rows[1].days[0], clocked_minutes: 960, tracked_minutes: 840 }; // 88%, more money than Ann
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
    payload.rows[0].days[1] = { ...payload.rows[0].days[1], clocked_minutes: 480, tracked_minutes: 400 };
    mount(payload);
    expect(host.querySelector(".hub-leaderboard-pending").textContent).toBe("⚠ 1 day pending review");
  });

  it("names the days left out for charging more than clocked", () => {
    const payload = attendanceWeek();
    payload.rows[0].days[0] = { ...payload.rows[0].days[0], adjustment_minutes: 1140 };
    payload.rows[0].days[1] = { ...payload.rows[0].days[1], clocked_minutes: 480, tracked_minutes: 400 };
    mount(payload, "efficiency");
    expect(host.querySelector(".hub-leaderboard-pending").textContent)
      .toBe("⚠ 1 day charged more than clocked, left out");
  });

  it("says nobody clocked in rather than drawing an empty table", () => {
    mount(attendanceWeek({ rows: [], totals_by_day: [], total_minutes: 0 }));
    expect(host.querySelector(".hub-leaderboard-table")).toBeNull();
    expect(host.querySelector(".hub-leaderboard-empty")).not.toBeNull();
  });
});
