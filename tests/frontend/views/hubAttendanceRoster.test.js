// The roster strip: what each colour says in words, what the footer hides,
// and that a card recolours on the tick without the list reordering.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attendanceLive } from "../helpers/factories.js";

let view;
let host;

beforeEach(async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-16T15:00:00Z"));
  host = document.createElement("div");
  document.body.appendChild(host);
  view = await import("../../../backend/static/views/hubAttendanceRoster.js");
});

afterEach(() => {
  view.destroyHubAttendanceRoster();
  expect(vi.getTimerCount()).toBe(0);
  host.remove();
  vi.useRealTimers();
});

const cards = () => [...host.querySelectorAll(".hub-roster-card")];

describe("the roster strip", () => {
  it("renders the server's order and never re-sorts it", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    expect(cards().map((c) => c.dataset.state)).toEqual(["red", "yellow", "green"]);
  });

  it("says every state in words, not colour alone", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const text = cards().map((c) => c.textContent);
    expect(text[0]).toMatch(/idle/i);
    expect(text[2]).toMatch(/charging/i);
    expect(text[2]).toContain("WO-1042");
  });

  it("prints the three counts", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const counts = host.querySelector(".hub-roster-counts").textContent;
    expect(counts).toContain("3 on shift");
    expect(counts).toContain("1 charging");
    expect(counts).toContain("2 idle");
  });

  it("hides absent people behind an expandable footer", async () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const footer = host.querySelector(".hub-roster-absent");
    expect(footer.tagName).toBe("DETAILS");
    expect(footer.open).toBe(false);
    expect(footer.querySelector("summary").textContent).toContain("1 not clocked in");
    expect(footer.textContent).toContain("Dee Park");
  });

  it("omits the footer entirely when everybody is clocked in", () => {
    view.mountHubAttendanceRoster(host, attendanceLive({ absent: [] }));
    expect(host.querySelector(".hub-roster-absent")).toBeNull();
  });

  it("ticks the idle figure without refetching", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    const before = cards()[1].querySelector(".hub-roster-detail").textContent;
    vi.advanceTimersByTime(120000);
    const after = cards()[1].querySelector(".hub-roster-detail").textContent;
    expect(after).not.toBe(before);
    expect(cards()[1].dataset.state).toBe("yellow");
  });

  it("recolours a card that crosses the red threshold, in place", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    expect(cards()[1].dataset.state).toBe("yellow");
    // Bo is 3 minutes idle at server_now; 8 more crosses 10.
    vi.advanceTimersByTime(8 * 60000);
    expect(cards()[1].dataset.state).toBe("red");
    // In place: the list order is the server's until the next fetch.
    expect(cards().map((c) => c.dataset.user)).toEqual(["user-1", "user-2", "user-3"]);
  });

  it("stops and restarts on the tab's visibility, leaving no timer behind", () => {
    view.mountHubAttendanceRoster(host, attendanceLive());
    view.stopHubRosterTicking();
    expect(vi.getTimerCount()).toBe(0);
    view.startHubRosterTicking();
    expect(vi.getTimerCount()).toBe(1);
  });

  it("escapes a name and a work-order number", () => {
    const payload = attendanceLive();
    payload.on_shift[2].work_order_number = "<img src=x>";
    payload.on_shift[0].user.last_name = "<b>Lee</b>";
    view.mountHubAttendanceRoster(host, payload);
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("b")).toBeNull();
  });
});
