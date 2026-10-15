// The Home tab: the punch hero and the relocated quick-start clock. The
// work-order clock's own behaviour stays in
// hubClock.test.js; this file only proves it landed here.
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { requestFor, clearRequests } from "../helpers/requests.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { attendanceMe, hubPayload } from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const punch = () => el.panel("home").querySelector(".hub-punch");

describe("the Home tab is the hub's first tab", () => {
  it("is active on load and holds the clock widget", async () => {
    await openHub({ role: "technician" });
    expect(el.tab("home").classList.contains("active")).toBe(true);
    expect(el.panel("home").hidden).toBe(false);
    expect(el.panel("home").contains(el.clockMount())).toBe(true);
  });

  it("is where an Admin lands too -- the widget is no longer at the bottom", async () => {
    await openHub({ role: "admin" });
    expect(el.panel("home").contains(el.clockMount())).toBe(true);
  });
});

describe("off shift", () => {
  it("offers Punch in and reports today's clocked total", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ clocked_minutes_today: 95 }) });
    expect(punch().classList.contains("hub-punch-off")).toBe(true);
    expect(punch().querySelector(".hub-punch-today").textContent).toContain("1 h 35 m");
    expect(punch().querySelector('[data-action="hub-punch-in"]')).not.toBeNull();
  });

  it("punches in and refreshes", async () => {
    await openHub({ role: "technician", attendance: attendanceMe() });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-in"]'));
    expect(requestFor("/attendance/punch-in").method).toBe("POST");
  });
});

describe("on shift", () => {
  it("shows the elapsed hero and offers Punch out", async () => {
    const payload = hubPayload();
    await openHub({ role: "technician", hub: payload,
      attendance: attendanceMe({
        server_now: payload.server_now,
        open_punch: { id: "p1", started_at: "2026-09-10T10:00:00Z",
                      start_source: "manual" },
      }) });
    expect(punch().classList.contains("hub-punch-on")).toBe(true);
    expect(punch().querySelector(".hub-punch-hero").textContent).toBe("2 h 0 m");
    expect(punch().querySelector('[data-action="hub-punch-out"]')).not.toBeNull();
  });

  it("punches out at the wire", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-10T10:00:00Z", start_source: "manual" } }) });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-out"]'));
    expect(requestFor("/attendance/punch-out").method).toBe("POST");
  });
});

describe("no self-close prompt (M5)", () => {
  it("renders any open punch as on shift, never Close it", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { id: "p1",
        started_at: "2026-09-09T13:00:00Z", start_source: "manual", stale: true } }) });
    expect(punch().classList.contains("hub-punch-stale")).toBe(false);
    expect(punch().querySelector('[data-action="hub-punch-out"]')).not.toBeNull();
    expect(punch().querySelector('[data-action="hub-punch-self-close"]')).toBeNull();
  });
});

describe("a failed attendance fetch", () => {
  it("renders a retry inside the punch card rather than blanking Home", async () => {
    await openHub({ role: "technician",
      handlers: [http.get("/attendance/me", () => HttpResponse.json({ detail: "" }, { status: 500 }))] });
    expect(punch().querySelector(".hub-punch-retry")).not.toBeNull();
    // The work-order clock still mounted -- the two are independent.
    expect(el.clockMount().querySelector(".hub-clock")).not.toBeNull();
  });
});

it("emits no inline style attribute -- CSP drops them", async () => {
  await openHub({ role: "technician", attendance: attendanceMe() });
  expect(el.panel("home").querySelectorAll("[style]")).toHaveLength(0);
});
