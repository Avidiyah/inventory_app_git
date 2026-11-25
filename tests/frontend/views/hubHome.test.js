// The Home tab: the punch hero and the relocated quick-start clock. The
// work-order clock's own behaviour stays in
// hubClock.test.js; this file only proves it landed here.
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { requestFor, clearRequests } from "../helpers/requests.js";
import { connectHub, el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { server } from "../helpers/handlers.js";
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

describe("shop hours", () => {
  const shopPunch = { id: "p1", started_at: "2026-09-10T10:00:00Z", start_source: "manual", shop: true };

  it("off shift offers Punch in to the shop", async () => {
    await openHub({ role: "technician", attendance: attendanceMe() });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-in-shop"]'));
    expect(requestFor("/attendance/punch-in?shop=true").method).toBe("POST");
  });

  it("in the shop reads IN THE SHOP and switches to work orders", async () => {
    await openHub({ role: "technician", attendance: attendanceMe({ open_punch: shopPunch }) });
    expect(punch().classList.contains("hub-punch-shop")).toBe(true);
    expect(punch().querySelector(".hub-punch-status").textContent).toContain("IN THE SHOP");
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-switch"]'));
    expect(requestFor("/attendance/switch?shop=false").method).toBe("POST");
  });

  it("on work-order time switches to the shop", async () => {
    await openHub({ role: "technician",
      attendance: attendanceMe({ open_punch: { ...shopPunch, shop: false } }) });
    expect(punch().querySelector(".hub-punch-status").textContent).toContain("ON SHIFT");
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-switch"]'));
    expect(requestFor("/attendance/switch?shop=true").method).toBe("POST");
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

describe("this week's punches (self-edit)", () => {
  const weekPunches = () => attendanceMe({
    week_punches: [
      { id: "p-mon", started_at: "2026-09-07T13:00:00Z", ended_at: "2026-09-07T21:00:00Z", needs_review: false, tags: ["self"] },
      { id: "p-tue", started_at: "2026-09-08T13:00:00Z", ended_at: null, needs_review: true, tags: [] },
    ],
  });
  const section = () => el.panel("home").querySelector(".hub-home-week-punches");

  async function pickTime(text) {
    const input = document.getElementById("prompt-time-input");
    await vi.waitFor(() => expect(document.getElementById("prompt-time-overlay").hidden).toBe(false));
    input.value = text;
    await user().click(document.getElementById("prompt-time-save"));
  }

  it("lists this week's punches with tags", async () => {
    await openHub({ role: "technician", attendance: weekPunches() });
    // A <section>, so it gets the panel surface and text colour like its
    // neighbours -- a bare <details> rendered dark text on the dark page.
    expect(section().tagName).toBe("SECTION");
    expect(section().querySelector("summary").textContent).toBe("This week's punches");
    const rows = section().querySelectorAll(".hub-home-punch-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("8 h 0 m");
    expect(rows[0].textContent).toContain("Self-edited");
    expect(rows[1].textContent).toContain("running");
    expect(rows[1].textContent).toContain("⚠ needs review");
    expect(rows[0].querySelector('[data-action="hub-home-edit-punch"]').dataset.punch).toBe("p-mon");
  });

  it("Edit opens the editor and PATCHes the punch", async () => {
    let patched = null;
    await openHub({ role: "technician", attendance: weekPunches(),
      handlers: [http.patch("/hub/attendance/punches/:id", ({ params }) => {
        patched = params.id;
        return HttpResponse.json({});
      })] });
    await user().click(section().querySelector('[data-punch="p-mon"]'));
    expect(section().querySelector(".hub-home-punch-editor .punch-editor")).not.toBeNull();
    await user().click(section().querySelector(".punch-editor-save"));
    await vi.waitFor(() => expect(patched).toBe("p-mon"));
    // The refresh repaints Home, which closes the editor.
    await vi.waitFor(() => expect(section().querySelector(".punch-editor")).toBeNull());
  });

  it("Add posts with the viewer's own user id", async () => {
    let posted = null;
    const { currentUser } = await openHub({ role: "technician", attendance: weekPunches(),
      handlers: [http.post("/hub/attendance/punches", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({}, { status: 201 });
      })] });
    await user().click(section().querySelector('[data-action="hub-home-add-punch"]'));
    await user().click(section().querySelector(".punch-editor-start"));
    await pickTime("8:00 AM");
    await user().click(section().querySelector(".punch-editor-end"));
    await pickTime("4:00 PM");
    await user().click(section().querySelector(".punch-editor-save"));
    await vi.waitFor(() => expect(posted?.user_id).toBe(currentUser.id));
    // The refresh repaints Home, which closes the editor.
    await vi.waitFor(() => expect(section().querySelector(".punch-editor")).toBeNull());
  });

  describe("Fix my time", () => {
    const flagged = () => attendanceMe({
      week_punches: [
        { id: "p-mon", started_at: "2026-09-07T13:00:00Z", ended_at: "2026-09-07T21:00:00Z", needs_review: false, end_source: "manual", tags: [] },
        { id: "p-tue", started_at: "2026-09-08T13:00:00Z", ended_at: "2026-09-09T05:00:00Z", needs_review: true, end_source: "auto_clock_out", tags: [] },
      ],
    });
    const fix = () => el.panel("home").querySelector('[data-action="hub-home-fix-time"]');
    const dialog = () => document.querySelector('.flagged-flow [role="dialog"]');

    it("shows Fix my time (1) above this week's punches", async () => {
      await openHub({ role: "technician", attendance: flagged() });
      expect(fix().textContent.trim()).toBe("Fix my time (1)");
      expect(fix().compareDocumentPosition(section()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("shows no button without a flagged punch", async () => {
      await openHub({ role: "technician", attendance: attendanceMe({ week_punches: [flagged().week_punches[0]] }) });
      expect(section()).not.toBeNull();
      expect(fix()).toBeNull();
    });

    it("opens the flow without Looks right; Save PATCHes then refreshes", async () => {
      let patched = null;
      let reads = 0;
      await openHub({ role: "technician", attendance: flagged(),
        handlers: [
          http.get("/attendance/me", () => { reads += 1; return HttpResponse.json(flagged()); }),
          http.patch("/hub/attendance/punches/:id", ({ params }) => {
            patched = params.id;
            return HttpResponse.json({});
          }),
        ] });
      const before = reads;
      await user().click(fix());
      await vi.waitFor(() => expect(dialog()).not.toBeNull());
      expect([...dialog().querySelectorAll("button")].some((b) => b.textContent.trim() === "Looks right")).toBe(false);
      await user().click(dialog().querySelector(".punch-editor-save"));
      await vi.waitFor(() => expect(patched).toBe("p-tue"));
      await vi.waitFor(() => expect(reads).toBeGreaterThan(before));
      dialog()?.querySelector('[aria-label="Close"]')?.click();
    });
  });

  it("a 403 shows the refusal copy in the editor", async () => {
    await openHub({ role: "technician", attendance: weekPunches(),
      handlers: [http.patch("/hub/attendance/punches/:id", () => HttpResponse.json(
        { detail: "You can only change your own time in the current week." }, { status: 403 }))] });
    await user().click(section().querySelector('[data-punch="p-mon"]'));
    await user().click(section().querySelector(".punch-editor-save"));
    await vi.waitFor(() => expect(section().querySelector(".punch-editor-message").textContent)
      .toBe("You can only change your own time in the current week."));
  });
});

describe("live (W7)", () => {
  const twoPunches = (extra = []) => attendanceMe({
    week_punches: [
      { id: "p-mon", started_at: "2026-09-07T13:00:00Z", ended_at: "2026-09-07T21:00:00Z", needs_review: false, tags: [] },
      ...extra,
    ],
  });
  const section = () => el.panel("home").querySelector(".hub-home-week-punches");
  const serveAttendance = (body) => server.use(http.get("/attendance/me", () => HttpResponse.json(body)));

  it("a live attendance change patches Home and keeps the week list open", async () => {
    await openHub({ role: "technician", attendance: twoPunches() });
    const { emit } = await connectHub();
    section().querySelector("details").open = true;
    const list = section().querySelector(".hub-home-punch-list");
    serveAttendance(twoPunches([{ id: "p-tue", started_at: "2026-09-08T13:00:00Z", ended_at: "2026-09-08T15:00:00Z", needs_review: false, tags: [] }]));
    emit("attendance.changed");
    await vi.waitFor(() => expect(section().querySelectorAll(".hub-home-punch-row")).toHaveLength(2));
    expect(section().querySelector("details").open).toBe(true);
    expect(section().querySelector(".hub-home-punch-list")).toBe(list);
    expect(document.getElementById("hub-home-punch-p-tue").classList.contains("just-changed")).toBe(true);
    expect(document.getElementById("hub-home-punch-p-mon").classList.contains("just-changed")).toBe(false);
  });

  it("an open punch editor survives a patch", async () => {
    await openHub({ role: "technician", attendance: twoPunches() });
    const { emit } = await connectHub();
    await user().click(section().querySelector('[data-punch="p-mon"]'));
    const editor = section().querySelector(".punch-editor");
    emit("attendance.changed");
    await vi.waitFor(() => expect(requestFor("/attendance/me")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    expect(section().querySelector(".punch-editor")).toBe(editor);
  });

  it("an editor whose punch is gone closes with the note", async () => {
    await openHub({ role: "technician", attendance: twoPunches() });
    const { emit } = await connectHub();
    await user().click(section().querySelector('[data-punch="p-mon"]'));
    serveAttendance(attendanceMe({ week_punches: [] }));
    emit("attendance.changed");
    await vi.waitFor(() => expect(section().querySelector(".punch-editor")).toBeNull());
    expect(document.getElementById("hub-punch-message").textContent).toBe("That punch was changed on another device.");
  });

  it("own punch-in uses the targeted refresh, not a full reload", async () => {
    await openHub({ role: "supervisor", attendance: attendanceMe() });
    clearRequests();
    await user().click(punch().querySelector('[data-action="hub-punch-in"]'));
    await vi.waitFor(() => expect(requestFor("/attendance/me")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    expect(requestFor("/hub/crew")).toBeNull();
  });

  it("the clock node survives a Home patch and keeps its running time", async () => {
    const payload = hubPayload({ clock: { running_session: { work_order_id: "w1", number: "7001", started_at: "2026-09-10T11:00:00Z" }, total_minutes_today: 0 } });
    await openHub({ role: "technician", hub: payload });
    const { emit } = await connectHub();
    const clock = el.clockMount();
    const hero = clock.querySelector(".hub-clock-hero").textContent;
    emit("attendance.changed");
    await vi.waitFor(() => expect(requestFor("/attendance/me")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    expect(el.panel("home").contains(clock)).toBe(true);
    expect(el.clockMount()).toBe(clock);
    expect(clock.querySelector(".hub-clock-hero").textContent).toBe(hero);
    expect(clock.querySelector(".just-changed")).toBeNull();
  });

  it("labor.session.changed refreshes the clock from another device", async () => {
    await openHub({ role: "technician" });
    const { emit } = await connectHub();
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ clock: { running_session: { work_order_id: "w1", number: "7001", started_at: "2026-09-10T11:00:00Z" }, total_minutes_today: 0 } }))));
    emit("labor.session.changed");
    await vi.waitFor(() => expect(el.clockMount().querySelector(".hub-clock-on")).not.toBeNull());
  });
});
