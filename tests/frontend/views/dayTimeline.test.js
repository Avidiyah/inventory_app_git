// The profile's day timeline: punched / charged / uncharged lanes on one
// Central hour axis, with hand-entered labor set apart as untimed chips
// (spec 2026-10-16 U5-U7). Pure markup; positions land through CSSOM.

import { describe, expect, it } from "vitest";
import {
  applyTimelinePositions, dayTimelineHtml, subtractSpans,
} from "../../../backend/static/views/dayTimeline.js";

// 13:00Z is 8:00 AM CDT on 2026-09-14.
function day(overrides = {}) {
  return {
    date: "2026-09-14", pending_review: false,
    punches: [{ id: "p1", started_at: "2026-09-14T13:00:00Z", ended_at: "2026-09-14T21:00:00Z",
                minutes: 480, carried: false, open: false, needs_review: false }],
    charged: [{ work_order_id: "w1", number: "WO-1", minutes: 120, auto_closed: false, running: false,
                spans: [{ started_at: "2026-09-14T14:00:00Z", ended_at: "2026-09-14T16:00:00Z" }] }],
    adjustments: [{ minutes: 60, recorded_by_name: "Ann Lee", work_order_number: "WO-9",
                    labor_id: "l1", recorded_by_self: true }],
    punch_marks: [],
    ...overrides,
  };
}

function render(d) {
  const host = document.createElement("div");
  host.innerHTML = dayTimelineHtml(d);
  return host;
}

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
  it("renders three timed lanes and a separated hand-entered lane", () => {
    const host = render(day());
    expect(host.querySelector(".day-tl-lane-punched .day-tl-punch")).not.toBeNull();
    expect(host.querySelector(".day-tl-lane-charged .day-tl-charged").textContent).toContain("WO-1");
    expect(host.querySelectorAll(".day-tl-lane-uncharged .day-tl-gap")).toHaveLength(2);
    expect(host.querySelector(".day-tl-divider")).not.toBeNull();
    const chip = host.querySelector(".day-tl-lane-hand .day-tl-chip");
    expect(chip.dataset.number).toBe("WO-9");
    expect(chip.textContent).toContain("1:00");
    expect(chip.textContent).toContain("Self-entered");
    expect(host.querySelector(".day-tl-legend")).not.toBeNull();
  });

  it("chip width scales with minutes and never implies a time", () => {
    const chip = render(day()).querySelector(".day-tl-chip");
    expect(chip.dataset.left).toBeUndefined();
    expect(Number(chip.dataset.width)).toBeGreaterThan(0);
  });

  it("edited punch shows striped block and text tag", () => {
    const marks = (tags) => [{ punch_id: "p1", tags, edits: [
      { by_name: "Dee Ops", self: tags[0] === "self", field: "ended_at",
        old: "2026-09-14T20:00:00+00:00", new: "2026-09-14T21:00:00+00:00", at: "2026-09-15T01:00:00Z" }] }];
    const self = render(day({ punch_marks: marks(["self"]) })).querySelector(".day-tl-punch");
    expect(self.classList.contains("day-tl-edited")).toBe(true);
    expect(self.querySelector(".day-tl-tag-self").textContent).toBe("Self-edited");
    expect(self.getAttribute("aria-label")).toContain("3:00 PM → 4:00 PM");
    const admin = render(day({ punch_marks: marks(["admin"]) })).querySelector(".day-tl-punch");
    expect(admin.querySelector(".day-tl-tag-admin").textContent).toBe("Admin-edited");
    const plain = render(day()).querySelector(".day-tl-punch");
    expect(plain.classList.contains("day-tl-edited")).toBe(false);
  });

  it("an Admin-entered chip says so", () => {
    const chip = render(day({ adjustments: [{ minutes: 30, recorded_by_name: "Dee Ops",
      work_order_number: "WO-2", labor_id: "l2", recorded_by_self: false }] })).querySelector(".day-tl-chip");
    expect(chip.textContent).toContain("Admin-entered");
  });

  it("pending day is greyed and labelled Not counted", () => {
    const host = render(day({ pending_review: true }));
    expect(host.querySelector(".day-tl.day-tl-pending")).not.toBeNull();
    expect(host.textContent).toContain("Not counted — needs review");
  });

  it("an empty day renders nothing", () => {
    expect(dayTimelineHtml(day({ punches: [], charged: [], adjustments: [] }))).toBe("");
  });
});

describe("applyTimelinePositions", () => {
  it("sets left and width through CSSOM", () => {
    const host = render(day());
    applyTimelinePositions(host);
    const block = host.querySelector(".day-tl-punch");
    expect(parseFloat(block.style.left)).toBeCloseTo(Number(block.dataset.left), 3);
    expect(parseFloat(block.style.width)).toBeCloseTo(Number(block.dataset.width), 3);
    expect(block.style.width.endsWith("%")).toBe(true);
  });
});
