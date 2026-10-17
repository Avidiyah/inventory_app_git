// The profile's day in time order: one "On the clock" line, then each
// work-order stretch and each not-charged gap as its own row (spec
// 2026-10-16 U5-U7, reworked for self-explanation). Pure markup.

import { describe, expect, it } from "vitest";
import { dayTimelineHtml, subtractSpans } from "../../../backend/static/views/dayTimeline.js";

// 13:00Z is 8:00 AM CDT on 2026-09-14.
function day(overrides = {}) {
  return {
    date: "2026-09-14", pending_review: false, lunch_minutes: 30,
    punches: [{ id: "p1", started_at: "2026-09-14T13:00:00Z", ended_at: "2026-09-14T21:00:00Z",
                minutes: 480, carried: false, open: false, needs_review: false }],
    charged: [{ work_order_id: "w1", number: "WO-1", minutes: 120, auto_closed: false, running: false,
                spans: [{ started_at: "2026-09-14T14:00:00Z", ended_at: "2026-09-14T16:00:00Z" }] }],
    adjustments: [],
    punch_marks: [],
    ...overrides,
  };
}

function render(d, now) {
  const host = document.createElement("div");
  host.innerHTML = dayTimelineHtml(d, now ? { now } : undefined);
  return host;
}

const runs = (host) => Array.from(host.querySelectorAll(".day-run"))
  .map((r) => r.textContent.replace(/\s+/g, " ").trim());

describe("subtractSpans", () => {
  it("removes charged time from punched time", () => {
    expect(subtractSpans([[480, 720]], [[540, 600]])).toEqual([[480, 540], [600, 720]]);
  });

  it("drops a fully covered span and ignores charge outside the shift", () => {
    expect(subtractSpans([[480, 540]], [[400, 600]])).toEqual([]);
    expect(subtractSpans([[480, 540]], [[600, 700]])).toEqual([[480, 540]]);
  });
});

describe("dayTimelineHtml", () => {
  it("says when they were on the clock, with lunch", () => {
    expect(render(day()).querySelector(".day-tl-clock").textContent)
      .toBe("On the clock 8:00 AM – 4:00 PM · lunch −0:30");
  });

  it("lists charged stretches and the gaps between them in time order", () => {
    const host = render(day());
    expect(runs(host)).toEqual([
      "8:00 AM – 9:00 AMNot charged to a work order1:00",
      "9:00 AM – 11:00 AMWO-12:00",
      "11:00 AM – 4:00 PMNot charged to a work order5:00",
    ]);
    expect(host.querySelector(".day-run-charged .user-profile-wo-btn").dataset.number).toBe("WO-1");
    expect(host.querySelectorAll(".day-run-gap")).toHaveLength(2);
  });

  it("a running clock and an open punch end at now", () => {
    const host = render(day({
      punches: [{ ...day().punches[0], ended_at: null, open: true }],
      charged: [{ ...day().charged[0], spans: [{ started_at: "2026-09-14T14:00:00Z", ended_at: null }] }],
    }), "2026-09-14T15:00:00Z");
    expect(runs(host)).toEqual([
      "8:00 AM – 9:00 AMNot charged to a work order1:00",
      "9:00 AM – nowWO-1 running1:00",
    ]);
  });

  it("an auto-stopped clock says so, and labor without clock times still gets a line", () => {
    const host = render(day({ charged: [
      { ...day().charged[0], auto_closed: true },
      { work_order_id: "w2", number: "WO-2", minutes: 45, auto_closed: false, spans: [] },
    ] }));
    expect(runs(host)).toContain("9:00 AM – 11:00 AMWO-1 auto-stopped2:00");
    expect(runs(host).at(-1)).toBe("times not recordedWO-20:45");
  });

  it("pending day is greyed and labelled Not counted", () => {
    const host = render(day({ pending_review: true }));
    expect(host.querySelector(".day-tl.day-tl-pending")).not.toBeNull();
    expect(host.textContent).toContain("Not counted in the week — needs review");
  });

  it("an empty day renders nothing", () => {
    expect(dayTimelineHtml(day({ punches: [], charged: [] }))).toBe("");
  });
});
