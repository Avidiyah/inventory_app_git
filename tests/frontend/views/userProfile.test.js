// The Users-page profile panel: header, week picker, seven <details> rows,
// totals, the drill-down lists, the Work Orders hand-off, and the error/retry
// state. Fetches through MSW; the hand-off modules are mocked.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { clearRequests, requests, startRecording, stopRecording } from "../helpers/requests.js";
import { personWeek } from "../helpers/factories.js";

// `vi.mock` is hoisted above every import, so the fns it closes over must be
// hoisted too.
const { openSearch, focusWorkOrder, showPage } = vi.hoisted(() => ({
  openSearch: vi.fn(), focusWorkOrder: vi.fn(), showPage: vi.fn(),
}));
vi.mock("../../../backend/static/views/workOrders.js", () => ({
  openWorkOrdersByNumberSearch: openSearch, focusWorkOrder,
}));
vi.mock("../../../backend/static/views/nav.js", () => ({ showPage }));
const promptTime = vi.fn();
vi.mock("../../../backend/static/dom.js", () => ({ promptTime }));
import { setCurrentUser } from "../../../backend/static/state.js";
import { peekProfileOrigin, clearProfileOrigin } from "../../../backend/static/views/profileOrigin.js";

const { mountUserProfile } = await import("../../../backend/static/views/userProfile.js");

const USER = { id: "10000000-0000-4000-8000-000000000001", first_name: "Ann",
               last_name: "Lee", role: "technician", archived_at: null };
let host;
const flush = () => new Promise((r) => setTimeout(r, 0));
const weekQueries = () => requests()
  .filter((r) => r.url.includes("/hub/people/"))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

function serve(payloadOrStatus) {
  server.use(http.get("/hub/people/:id/week", ({ request }) => {
    if (typeof payloadOrStatus === "number") {
      return HttpResponse.json({ detail: "week cannot be in the future." }, { status: payloadOrStatus });
    }
    const week = new URL(request.url).searchParams.get("week");
    return HttpResponse.json(week ? { ...payloadOrStatus, week_start: week } : payloadOrStatus);
  }));
}

async function mount(user = USER, options = {}) {
  mountUserProfile(host, user, options);
  await flush(); await flush();
}

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
  startRecording(); clearRequests();
  openSearch.mockClear(); showPage.mockClear(); focusWorkOrder.mockClear(); clearProfileOrigin();
  promptTime.mockReset();
  setCurrentUser({ id: "viewer", role: "technician" });
});
afterEach(() => stopRecording());

const rows = () => Array.from(host.querySelectorAll("details.user-profile-day"));

describe("the panel", () => {
  it("renders the header, seven day rows and the week totals", async () => {
    serve(personWeek());
    await mount();
    expect(host.querySelector(".user-profile-header").textContent).toContain("Ann Lee");
    expect(host.querySelector(".user-profile-header").textContent).toContain("Technician");
    expect(rows()).toHaveLength(7);
    expect(rows()[0].querySelector("summary").textContent).toContain("8:00");
    expect(rows()[0].querySelector("summary").textContent).toContain("3:00");
    expect(host.querySelector(".user-profile-totals").textContent).toContain("8:00");
    expect(host.querySelector(".user-profile-totals").textContent).toContain("1");
  });

  it("tags an archived person", async () => {
    serve(personWeek({ archived: true }));
    await mount({ ...USER, archived_at: "2026-09-01T00:00:00Z" });
    expect(host.querySelector(".user-profile-header").textContent).toContain("(archived)");
  });

  it("steps the week and refetches with the shifted Monday", async () => {
    serve(personWeek());
    await mount();
    clearRequests();
    host.querySelector(".user-profile-prev").click();
    await flush(); await flush();
    expect(weekQueries()).toEqual([{ week: "2026-09-07" }]);
    host.querySelector(".user-profile-next").click();
    await flush(); await flush();
    expect(weekQueries().at(-1)).toEqual({ week: "2026-09-14" });
  });

  it("lists completed, charged, adjustments and punches inside a day", async () => {
    serve(personWeek());
    await mount();
    const body = rows()[0].querySelector(".user-profile-day-body").textContent;
    expect(body).toContain("WO-1");
    expect(body).toContain("Bldg 4");
    expect(body).toContain("auto-stopped");
    expect(body).toContain("Dee Ops");
    expect(body).toContain("0:30");
    expect(rows()[1].querySelector(".user-profile-day-body").textContent).toContain("Nothing recorded");
  });

  it("prints punch and charge clock times beside the day totals", async () => {
    const week = personWeek();
    week.days[0].charged[0].spans = [{ started_at: "2026-09-14T14:00:00Z", ended_at: "2026-09-14T17:00:00Z" }];
    serve(week);
    await mount();
    const cells = rows()[0].querySelectorAll("summary .user-profile-col");
    expect(cells[0].textContent).toContain("8:00 AM – 4:00 PM");
    expect(cells[1].textContent).toContain("9:00 AM – 12:00 PM");
    expect(rows()[0].querySelector(".user-profile-day-body").textContent).toContain("WO-1 · 3:00 9:00 AM – 12:00 PM");
  });

  it("flags a day that needs review and notes an open shift", async () => {
    const week = personWeek();
    week.days[1] = { ...week.days[1], needs_review: true, has_open: true, clocked_minutes: 60 };
    serve(week);
    await mount();
    expect(rows()[1].querySelector(".hub-hours-flag-review")).not.toBeNull();
    expect(rows()[1].querySelector("summary").textContent).toContain("on shift");
  });

  it("colours each day by clocked minutes", async () => {
    const week = personWeek();
    [0, 479, 480, 600, 601].forEach((m, i) => { week.days[i] = { ...week.days[i], clocked_minutes: m }; });
    serve(week);
    await mount();
    expect(rows().slice(0, 5).map((r) => r.className)).toEqual([
      "user-profile-day user-profile-day-none", "user-profile-day user-profile-day-short",
      "user-profile-day user-profile-day-full", "user-profile-day user-profile-day-full",
      "user-profile-day user-profile-day-over",
    ]);
  });

  it("renders each completed work order as a card with its status badge", async () => {
    serve(personWeek());
    await mount();
    const card = rows()[0].querySelector(".user-profile-wo-card");
    expect(card.tagName).toBe("BUTTON");
    expect(card.classList.contains("user-profile-wo-completed")).toBe(true);
    expect(card.querySelector(".wo-status-completed")).not.toBeNull();
    expect(card.textContent).toContain("WO-1");
    expect(card.textContent).toContain("Bldg 4");
    expect(card.querySelector(".wo-archived-tag")).toBeNull();
    expect(card.querySelector("button")).toBeNull();
  });

  it("renders a card without a location", async () => {
    const week = personWeek();
    week.days[0].completed[0] = { ...week.days[0].completed[0], location: null };
    serve(week);
    await mount();
    expect(rows()[0].querySelector(".user-profile-wo-location")).toBeNull();
  });

  it("tags an archived work order and sends it through the number search", async () => {
    const week = personWeek();
    week.days[0].completed[0] = { ...week.days[0].completed[0], archived: true };
    serve(week);
    await mount();
    const card = rows()[0].querySelector(".user-profile-wo-card");
    expect(card.querySelector(".wo-archived-tag").textContent).toBe("Archived");
    card.click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
    expect(focusWorkOrder).not.toHaveBeenCalled();
    expect(showPage).toHaveBeenCalledWith("work-orders");
  });

  it("opens a live work order by id and records the origin", async () => {
    serve(personWeek());
    await mount(USER, { page: "user-hub" });
    rows()[0].querySelector(".user-profile-wo-card").click();
    await flush(); await flush();
    expect(focusWorkOrder).toHaveBeenCalledWith("wo-1");
    expect(openSearch).not.toHaveBeenCalled();
    expect(showPage).toHaveBeenCalledWith("work-orders");
    expect(peekProfileOrigin()).toEqual({ page: "user-hub", userId: USER.id, week: "2026-09-14" });
  });

  it("still hands charged and adjustment numbers to the number search", async () => {
    serve(personWeek());
    await mount();
    rows()[0].querySelector(".user-profile-wo-btn").click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
  });

  it("fetches the requested week first and labels Back by page", async () => {
    serve(personWeek());
    await mount(USER, { week: "2026-09-07", page: "user-hub" });
    expect(weekQueries()).toEqual([{ week: "2026-09-07" }]);
    expect(host.querySelector(".user-profile-back").textContent).toContain("Back to timesheets");
  });

  it("paints the heading from the payload when only an id is given", async () => {
    serve(personWeek());
    await mount({ id: USER.id });
    expect(host.querySelector("#user-profile-heading").textContent).toContain("Ann Lee");
  });

  it("calls onBack from the Back link", async () => {
    serve(personWeek());
    const onBack = vi.fn();
    await mount(USER, { onBack });
    host.querySelector(".user-profile-back").click();
    expect(onBack).toHaveBeenCalled();
  });

  it("shows the error and a Retry on failure, and recovers", async () => {
    serve(422);
    await mount();
    expect(host.querySelector(".user-profile-error").textContent).toContain("future");
    serve(personWeek());
    host.querySelector(".user-profile-retry").click();
    await flush(); await flush();
    expect(rows()).toHaveLength(7);
  });

  describe("punch editing", () => {
    const punchWrites = () => requests().filter((r) => r.url.includes("/hub/attendance/punches"));

    it("shows no Edit or Add punch controls to a non-Admin viewer", async () => {
      serve(personWeek());
      await mount();
      expect(host.querySelector(".hub-hours-edit")).toBeNull();
      expect(host.querySelector(".hub-hours-add")).toBeNull();
    });

    it("an Admin edits a punch inline; the save PATCHes and the week reloads", async () => {
      setCurrentUser({ id: "viewer", role: "admin" });
      promptTime.mockResolvedValue(new Date("2026-09-14T13:30:00.000Z"));
      server.use(http.patch("/hub/attendance/punches/:id", () => HttpResponse.json({ ok: true })));
      serve(personWeek());
      await mount();
      rows()[0].querySelector(".hub-hours-edit").click();
      const day = rows()[0];
      expect(day.open).toBe(true);
      expect(day.querySelector(".punch-editor")).not.toBeNull();
      day.querySelector(".punch-editor-start").click();
      await flush();
      day.querySelector(".punch-editor-save").click();
      await flush(); await flush(); await flush();
      const patch = punchWrites().find((r) => r.method === "PATCH");
      expect(patch.url).toContain("/hub/attendance/punches/punch-1");
      expect(weekQueries()).toHaveLength(2);
      expect(host.querySelector(".punch-editor")).toBeNull();
    });

    it("an Admin adds a punch for that day and user", async () => {
      setCurrentUser({ id: "viewer", role: "admin" });
      promptTime.mockResolvedValue(new Date("2026-09-15T13:00:00.000Z"));
      let posted = null;
      server.use(http.post("/hub/attendance/punches", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json({ ok: true }, { status: 201 });
      }));
      serve(personWeek());
      await mount();
      rows()[1].querySelector(".hub-hours-add").click();
      const day = rows()[1];
      day.querySelector(".punch-editor-start").click();
      await flush();
      day.querySelector(".punch-editor-end").click();
      await flush();
      day.querySelector(".punch-editor-save").click();
      await flush(); await flush(); await flush();
      expect(posted.user_id).toBe(USER.id);
      expect(weekQueries()).toHaveLength(2);
    });

    it("a refused save stays open with the server's message", async () => {
      setCurrentUser({ id: "viewer", role: "admin" });
      promptTime.mockResolvedValue(new Date("2026-09-14T13:30:00.000Z"));
      server.use(http.patch("/hub/attendance/punches/:id", () =>
        HttpResponse.json({ detail: "overlaps another punch." }, { status: 409 })));
      serve(personWeek());
      await mount();
      rows()[0].querySelector(".hub-hours-edit").click();
      const day = rows()[0];
      day.querySelector(".punch-editor-save").click();
      await flush(); await flush(); await flush();
      expect(day.querySelector(".punch-editor-message").textContent).toContain("overlaps");
      expect(weekQueries()).toHaveLength(1);
    });

    it("Cancel closes the editor and keeps the day open", async () => {
      setCurrentUser({ id: "viewer", role: "admin" });
      serve(personWeek());
      await mount();
      const day = rows()[0];
      day.querySelector(".hub-hours-edit").click();
      rows()[0].querySelector(".punch-editor-cancel").click();
      expect(rows()[0].open).toBe(true);
      expect(host.querySelector(".punch-editor")).toBeNull();
    });
  });
});
