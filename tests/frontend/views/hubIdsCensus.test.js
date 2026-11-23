// W7 census: every element a hub tab patches as a row or tile carries a
// unique id, so morph pairs it with the right neighbour (spec rule 1, risk 7).

import { afterEach, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import {
  attendanceMe, hubAdmin, hubCrew, hubCrewTechnician, hubOnClockEntry, hubPayload, hubReport, hubReportRow,
} from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  restoreHub();
});

const PATCHED = [
  ".hub-tile", ".hub-crew-card", ".hub-attention-row", ".hub-onclock-row", ".hub-exceptions-row[id]",
  ".hub-home-punch-row", ".hub-stocked-request", ".hub-roster-card", ".hub-day-card",
  ".hub-leaderboard-row", ".hub-report-row",
].join(", ");

function census(root) {
  const nodes = [...root.querySelectorAll(PATCHED)];
  const missing = nodes.filter((n) => !n.id).map((n) => n.className);
  const ids = nodes.map((n) => n.id).filter(Boolean);
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  return { count: nodes.length, missing, dupes };
}

it("every patched row and tile on every tab has a unique id", async () => {
  await openHub({
    role: "admin",
    hub: hubPayload({ stocked_requests: [{ item_name: "Elbow", work_order_number: "7001", quantity: 2, stocked_at: null }] }),
    attendance: attendanceMe({ week_punches: [
      { id: "p1", started_at: "2026-09-07T13:00:00Z", ended_at: "2026-09-07T21:00:00Z", needs_review: false, tags: [] },
      { id: "p2", started_at: "2026-09-08T13:00:00Z", ended_at: "2026-09-08T21:00:00Z", needs_review: false, tags: [] },
    ] }),
    crew: hubCrew({ technicians: [hubCrewTechnician(), hubCrewTechnician()] }),
    admin: hubAdmin({ on_the_clock: [hubOnClockEntry(), hubOnClockEntry({ technician_name: "Crew Two" })] }),
    report: hubReport({ rows: [hubReportRow({ number: "7001" }), hubReportRow({ number: "7002" })] }),
  });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  let total = 0;
  for (const tab of ["home", "dashboard", "timesheets", "leaderboards", "report"]) {
    await user.click(el.tab(tab));
    await vi.advanceTimersByTimeAsync(50);
    const result = census(el.panel(tab));
    expect(result.missing, tab).toEqual([]);
    expect(result.dupes, tab).toEqual([]);
    total += result.count;
  }
  expect(total).toBeGreaterThan(20);
});
