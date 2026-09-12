// Characterization coverage for views/hubClock.js: the off/on renders, the
// Track and Stop actions at the wire, the 1 s tick and the two long-session
// warnings on fake timers, and the click once-guard. The Start -> refresh
// hand-off itself is P5f's (userHub.test.js -> "clock hand-off").

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { hubPayload, hubRunningSession, hubStartable } from "../helpers/factories.js";

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const clock = () => el.clockMount().querySelector(".hub-clock");
const message = () => document.getElementById("hub-clock-message");
const hero = () => clock().querySelector(".hub-clock-hero");
const warning = () => clock().querySelector(".hub-clock-warning");

// An ISO instant `minutes` before `iso`.
const minus = (iso, minutes) => new Date(new Date(iso).getTime() - minutes * 60000).toISOString();

// A payload whose clock has been running for `minutesAgo` at its server_now.
// Elapsed is rendered against the payload's own server_now (skew), so the
// fake clock's absolute value never matters -- only how far it is advanced.
function onClock(minutesAgo, overrides = {}) {
  const payload = hubPayload(overrides);
  payload.clock.running_session = hubRunningSession({ started_at: minus(payload.server_now, minutesAgo) });
  return payload;
}

describe("off the clock", () => {
  it("renders the status, today's total and the no-startable hint; the tick is a no-op", async () => {
    const clockBlock = { ...hubPayload().clock, closed_minutes_today: 95, total_minutes_today: 95 };
    await openHub({ role: "technician", hub: hubPayload({ clock: clockBlock }) });
    expect(clock().classList.contains("hub-clock-off")).toBe(true);
    expect(clock().querySelector(".hub-clock-status").textContent).toContain("Not clocked in");
    expect(clock().querySelector(".hub-clock-today").textContent).toContain("1 h 35 m");
    expect(clock().querySelector(".hub-clock-start-btn")).toBeNull();
    expect(clock().querySelector(".hint").textContent).toBe("Nothing assigned to start a clock on yet.");
    const before = clock().innerHTML;
    vi.advanceTimersByTime(60000);
    expect(clock().innerHTML).toBe(before);
  });

  it.each([
    [{ community: "Scholars", building_number: "3", unit_number: "12" }, "Track WO 7001 — Scholars · Bldg 3 · Unit 12"],
    [{ location: "Roof" }, "Track WO 7001 — Roof"],
    [{ community: "Scholars", location: "Roof" }, "Track WO 7001 — Scholars"],  // location is the fallback only
    [{}, "Track WO 7001"],
  ])("the Track button composes the place %j -> %s", async (place, label) => {
    await openHub({ role: "technician", hub: hubPayload({ startable: [hubStartable(place)] }) });
    const btn = clock().querySelector(".hub-clock-start-btn");
    expect(btn.textContent).toBe(label);
    expect(btn.dataset.action).toBe("hub-clock-start");
  });

  it("offers only the top startable, carrying its work_order_id", async () => {
    const first = hubStartable({ number: "7001", work_order_id: "w-first" });
    const second = hubStartable({ number: "7002", work_order_id: "w-second" });
    await openHub({ role: "technician", hub: hubPayload({ startable: [first, second] }) });
    const buttons = clock().querySelectorAll(".hub-clock-start-btn");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].dataset.value).toBe("w-first");
    expect(buttons[0].textContent).toBe("Track WO 7001");
  });

  it("a failing start writes the detail into the message and does not refetch", async () => {
    await openHub({
      role: "technician",
      hub: hubPayload({ startable: [hubStartable({ work_order_id: "w1" })] }),
      handlers: [http.post("/work-orders/w1/tracking/start", () =>
        HttpResponse.json({ detail: "Clock is locked" }, { status: 500 }))],
    });
    clearRequests();
    await user().click(clock().querySelector(".hub-clock-start-btn"));
    await vi.waitFor(() => expect(message().textContent).toBe("Clock is locked"));
    // setMessage assigns className wholesale, so `hub-clock-message` is gone
    // after the first message -- harmless here (the module finds it by id).
    expect(message().className).toBe("error");
    expect(requestFor("/tracking/start", "POST").body).toEqual({});
    expect(requests().filter((r) => r.url === "/hub")).toHaveLength(0);
  });
});

describe("on the clock", () => {
  it("renders the session: subject, elapsed hero, started time, Stop", async () => {
    const payload = onClock(75);
    await openHub({ role: "technician", hub: payload });
    expect(clock().classList.contains("hub-clock-on")).toBe(true);
    expect(clock().querySelector(".hub-clock-status").textContent).toContain("ON THE CLOCK");
    expect(clock().querySelector(".hub-clock-subject").textContent).toBe("WO 7001");
    expect(hero().textContent).toBe("1 h 15 m");
    const started = new Date(payload.clock.running_session.started_at)
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    expect(clock().querySelector(".hub-clock-started").textContent).toBe(`started ${started}`);
    expect(clock().querySelector(".hub-clock-stop-btn").dataset.action).toBe("hub-clock-stop");
    expect(warning()).toBeNull();
  });

  it("Stop posts /work-orders/{id}/tracking/stop with an empty body, then refetches /hub", async () => {
    const payload = onClock(10);
    const woId = payload.clock.running_session.work_order_id;
    await openHub({
      role: "technician", hub: payload,
      handlers: [http.post("/work-orders/:id/tracking/stop", () => HttpResponse.json({}))],
    });
    clearRequests();
    await user().click(clock().querySelector(".hub-clock-stop-btn"));
    await vi.waitFor(() => expect(requestFor("/tracking/stop", "POST")).not.toBeNull());
    expect(requestFor("/tracking/stop", "POST").url).toBe(`/work-orders/${woId}/tracking/stop`);
    expect(requestFor("/tracking/stop", "POST").body).toEqual({});
    await vi.waitFor(() => expect(requestFor("/hub", "GET")).not.toBeNull());
  });

  it("a failing stop writes the detail and does not refetch", async () => {
    await openHub({
      role: "technician", hub: onClock(10),
      handlers: [http.post("/work-orders/:id/tracking/stop", () =>
        HttpResponse.json({ detail: "Nope" }, { status: 500 }))],
    });
    clearRequests();
    await user().click(clock().querySelector(".hub-clock-stop-btn"));
    await vi.waitFor(() => expect(message().textContent).toBe("Nope"));
    expect(requests().filter((r) => r.url === "/hub")).toHaveLength(0);
  });

  it("the 1 s tick advances the hero; nothing moves after the hide", async () => {
    await openHub({ role: "technician", hub: onClock(75) });
    expect(hero().textContent).toBe("1 h 15 m");
    vi.advanceTimersByTime(60000);
    expect(hero().textContent).toBe("1 h 16 m");
    stopClock();
    vi.advanceTimersByTime(60000);
    expect(hero().textContent).toBe("1 h 16 m");
  });

  it("crossing 8 h inserts the long-session warning by a one-time re-render", async () => {
    await openHub({ role: "technician", hub: onClock(479) });
    expect(warning()).toBeNull();
    expect(hero().textContent).toBe("7 h 59 m");
    vi.advanceTimersByTime(60000);
    expect(warning().textContent).toContain("Still on the clock after 8 h");
    expect(hero().textContent).toBe("8 h 0 m");
  });

  it("a session already past 11 h renders the cap warning on mount", async () => {
    await openHub({ role: "technician", hub: onClock(661) });
    expect(warning().textContent).toContain("At 12 h this session is capped");
  });

  it("crossing 11 h by tick does NOT swap the 8 h text for the cap text", async () => {
    // tick() re-renders only when a warning appears or disappears. With the 8 h
    // warning already on screen and the fresh one now the cap copy, neither
    // branch fires, so the stale text stays until the next mount.
    // Characterization -- see open-work.md N-P6-CHARACTERIZED.
    await openHub({ role: "technician", hub: onClock(659) });
    expect(warning().textContent).toContain("after 8 h");
    vi.advanceTimersByTime(120000);
    expect(hero().textContent).toBe("11 h 1 m");
    expect(warning().textContent).toContain("after 8 h");
  });

  it("the click handler is bound once per container: a second load, one Stop, one request", async () => {
    const { mod } = await openHub({
      role: "technician", hub: onClock(10),
      handlers: [http.post("/work-orders/:id/tracking/stop", () => HttpResponse.json({}))],
    });
    await mod.loadUserHub();            // same #hub-clock-mount, dataset.wired already set
    clearRequests();
    await user().click(clock().querySelector(".hub-clock-stop-btn"));
    await vi.waitFor(() => expect(requestFor("/hub", "GET")).not.toBeNull());
    expect(requests().filter((r) => r.url.endsWith("/tracking/stop"))).toHaveLength(1);
  });
});
