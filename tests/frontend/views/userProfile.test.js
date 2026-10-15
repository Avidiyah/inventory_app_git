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
const { openSearch, showPage } = vi.hoisted(() => ({ openSearch: vi.fn(), showPage: vi.fn() }));
vi.mock("../../../backend/static/views/workOrders.js", () => ({ openWorkOrdersByNumberSearch: openSearch }));
vi.mock("../../../backend/static/views/nav.js", () => ({ showPage }));

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
  openSearch.mockClear(); showPage.mockClear();
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

  it("flags a day that needs review and notes an open shift", async () => {
    const week = personWeek();
    week.days[1] = { ...week.days[1], needs_review: true, has_open: true, clocked_minutes: 60 };
    serve(week);
    await mount();
    expect(rows()[1].querySelector(".hub-hours-flag-review")).not.toBeNull();
    expect(rows()[1].querySelector("summary").textContent).toContain("on shift");
  });

  it("hands a work order number to the Work Orders page", async () => {
    serve(personWeek());
    await mount();
    rows()[0].querySelector(".user-profile-wo-btn").click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
    expect(showPage).toHaveBeenCalledWith("work-orders");
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
});
