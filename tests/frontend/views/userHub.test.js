// Characterization coverage for views/userHub.js: loadUserHub per role, tab
// switching and the lazy tabs, per-tab failure isolation, the crew safety
// interval and the visibility lifecycle, the clock hand-off, and the three
// realtime subscriptions driven through the fake socket.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import {
  connectHub, el, mountHub, openHub, queries, restoreHub, restoreHubVisibility, stopClock,
} from "../helpers/hub.js";
import { filterOptions, hubGraphs, hubPayload, workOrderCard } from "../helpers/factories.js";

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);   // checked while fake timers are still on; anything left is a leak
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("mountHub", () => {
  it("mounts with the home tab active and nothing fetched", async () => {
    const { mod } = await mountHub();
    expect(typeof mod.loadUserHub).toBe("function");
    expect(typeof mod.refreshUserHub).toBe("function");
    expect(el.tab("home").classList.contains("active")).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});

describe("loadUserHub by role", () => {
  // D6: Timesheets is the pay record now, so it moved up to Admin+ with the
  // routes behind it. A Supervisor keeps the Dashboard crew board, which
  // shows live crew status at their own scope.
  it.each([
    ["technician", { timesheets: false, graphs: false, report: false }, ["/hub", "/attendance/me"], "My Work Orders (0)"],
    ["supervisor", { timesheets: false, graphs: false, report: false }, ["/hub", "/attendance/me", "/hub/crew"], "My Work Orders (0)"],
    ["techfm_oa", { timesheets: false, graphs: true, report: false }, ["/hub", "/attendance/me", "/hub/crew", "/hub/admin"], "Work Orders"],
    ["admin", { timesheets: true, graphs: true, report: true }, ["/hub", "/attendance/me", "/hub/crew", "/hub/admin"], "Work Orders"],
    ["owner", { timesheets: true, graphs: true, report: true }, ["/hub", "/attendance/me", "/hub/crew", "/hub/admin"], "Work Orders"],
  ])("%s: tabs %j, requests %j, label %s", async (role, tabs, expected, label) => {
    await openHub({ role, hub: hubPayload({ mine_total: 0 }) });
    expect(requests().map((r) => r.url)).toEqual(expected);
    expect(el.tab("timesheets").hidden).toBe(!tabs.timesheets);
    expect(el.tab("graphs").hidden).toBe(!tabs.graphs);
    expect(el.tab("report").hidden).toBe(!tabs.report);
    expect(el.tab("work-orders").textContent).toBe(label);
    // The clock is reparented into the Home panel for every role now --
    // there is no longer an admin-only position at the bottom of the page.
    expect(el.panel("home").contains(el.clockMount())).toBe(true);
    expect(el.clockMount().querySelector(".hub-clock-status")).not.toBeNull();
    // The hub opens on Home, so the Dashboard body -- Priorities included --
    // is not built until that tab is opened. It then paints for every role,
    // the crew and admin payloads having been fetched during the load.
    expect(el.panel("dashboard").querySelector(".hub-priorities")).toBeNull();
    await user().click(el.tab("dashboard"));
    expect(el.panel("dashboard").querySelector(".hub-priorities")).not.toBeNull();
  });

  it("a technician must never fire /hub/admin or /hub/crew, even after a tab tour", async () => {
    await openHub({ role: "technician" });
    await user().click(el.tab("work-orders"));
    await user().click(el.tab("dashboard"));
    expect(requestFor("/hub/admin")).toBeNull();
    expect(requestFor("/hub/crew")).toBeNull();
  });

  it("mine_total drives the technician label; a second load updates it", async () => {
    const { mod, payload } = await openHub({ role: "technician", hub: hubPayload({ mine_total: 3 }) });
    expect(el.tab("work-orders").textContent).toBe("My Work Orders (3)");
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ mine_total: 5, user: payload.user }))));
    await mod.loadUserHub();
    expect(el.tab("work-orders").textContent).toBe("My Work Orders (5)");
  });

  it("first load paints a skeleton grid in home; a return visit does not", async () => {
    let release;
    const { mod } = await mountHub({ role: "technician", handlers: [http.get("/hub", () =>
      new Promise((r) => { release = () => r(HttpResponse.json(hubPayload())); }))] });
    const first = mod.loadUserHub();
    expect(el.panel("home").querySelector(".skel-grid")).not.toBeNull();
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    release(); release = null; await first;
    const second = mod.loadUserHub();
    expect(el.panel("home").querySelector(".skel-grid")).toBeNull();
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    release(); await second;
  });

  it("a failing /hub writes the error into the clock mount and stops", async () => {
    const { mod } = await mountHub({ role: "supervisor", handlers: [http.get("/hub", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await mod.loadUserHub();
    expect(el.clockMount().querySelector("p.error")).not.toBeNull();
    expect(requestFor("/hub/crew")).toBeNull();
    expect(vi.getTimerCount()).toBe(0); // nothing started
  });

  it("a user change resets to the home tab and clears the lazy payloads", async () => {
    const { mod } = await openHub({ role: "admin" });
    await user().click(el.tab("timesheets"));
    await vi.waitFor(() => expect(requestFor("/hub/attendance/week")).not.toBeNull());
    await vi.waitFor(() => expect(el.panel("timesheets").querySelector(".hub-hours-table")).not.toBeNull());
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ user: { id: "someone-else", role: "admin" } }))));
    clearRequests();
    await mod.loadUserHub();
    expect(el.tab("home").classList.contains("active")).toBe(true);
    expect(el.panel("timesheets").children).toHaveLength(0);
  });

  it("a role downgrade off a hidden tab lands on home", async () => {
    const { mod } = await openHub({ role: "techfm_oa" });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(requestFor("/hub/graphs")).not.toBeNull());
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ user: { id: "u", role: "supervisor" } }))));
    await mod.loadUserHub();
    expect(el.tab("graphs").hidden).toBe(true);
    expect(el.tab("home").classList.contains("active")).toBe(true);
    expect(el.panel("graphs").children).toHaveLength(0);
  });
});

describe("tabs", () => {
  it("clicking a tab moves active/aria-selected and shows exactly one panel", async () => {
    await openHub({ role: "technician" });
    await user().click(el.tab("work-orders"));
    expect(el.tab("work-orders").getAttribute("aria-selected")).toBe("true");
    expect(el.tab("dashboard").getAttribute("aria-selected")).toBe("false");
    for (const name of ["dashboard", "timesheets", "work-orders", "graphs", "report"]) {
      expect(el.panel(name).hidden).toBe(name !== "work-orders");
    }
  });

  // `mine=true` is a supervisor-only flag: a technician is already scoped by
  // role on the server, and techfm_oa+ is deliberately unscoped (P4 Tab 3).
  it.each([
    ["technician", { limit: "10" }],
    ["supervisor", { mine: "true", limit: "10" }],
    ["admin", { limit: "10" }],
  ])("My Work Orders mounts the capped list: %s sends %j", async (role, expected) => {
    await openHub({ role, workOrders: [workOrderCard()] });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(queries("/work-orders/")).toHaveLength(1));
    expect(queries("/work-orders/")[0]).toEqual(expected);
    expect(el.panel("work-orders").querySelector(".hub-wo-list")).not.toBeNull();
  });

  it("Graphs fetches with weeks=12, re-renders from memory on return, and a range change refetches", async () => {
    await openHub({ role: "techfm_oa" });
    await user().click(el.tab("graphs"));
    // The first open fetches TWICE: showTab -> renderActiveTab -> loadGraphs()
    // (no payload yet), then the click handler's own loadGraphs(). The
    // request-id guard makes the first response a no-op. Characterization --
    // see open-work.md N-P5-CHARACTERIZED.
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(2));
    expect(queries("/hub/graphs")).toEqual([{ weeks: "12" }, { weeks: "12" }]);
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("graphs"));           // background refetch, from memory first
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(3));
    await user().selectOptions(el.panel("graphs").querySelector(".hub-graphs-weeks"), "26");
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(4));
    expect(queries("/hub/graphs")[3]).toEqual({ weeks: "26" });
  });

  it("Graphs: a community tab click re-renders from memory; the choice survives a range change", async () => {
    const graphs = hubGraphs({ communities: [
      { key: "maple", label: "Maple", total: 5, counts: { assigned: 5 }, service_types: [], priorities: [] },
      { key: "oak", label: "Oak", total: 1, counts: { assigned: 1 }, service_types: [], priorities: [] },
    ] });
    await openHub({ role: "admin", graphs });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    expect(el.panel("graphs").querySelector('[data-graph-tab="maple"]').classList.contains("active")).toBe(true); // largest first
    const before = queries("/hub/graphs").length;
    await user().click(el.panel("graphs").querySelector('[data-graph-tab="oak"]'));
    expect(queries("/hub/graphs")).toHaveLength(before);
    expect(el.panel("graphs").querySelector('[data-graph-tab="oak"]').classList.contains("active")).toBe(true);
    await user().selectOptions(el.panel("graphs").querySelector(".hub-graphs-weeks"), "52");
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector('[data-graph-tab="oak"]').classList.contains("active")).toBe(true));
  });

  it("Graphs distribution click hands off to Work Orders with the filter", async () => {
    const { mod } = await openHub({ role: "admin", handlers: [
      http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
      http.get("/items/", () => HttpResponse.json([])),
      http.get("/users/", () => HttpResponse.json([])),
    ] });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graph-card-all")).not.toBeNull());
    await user().click(el.panel("graphs").querySelector(".hub-graph-card-all"));
    expect(document.getElementById("work-orders-page").classList.contains("active")).toBe(true);
    expect(mod).toBeTruthy();
  });

  it("Report (admin+): skeleton, then re-fetched on every re-entry", async () => {
    await openHub({ role: "admin" });
    await user().click(el.tab("report"));
    expect(el.panel("report").querySelector(".hub-report-loading")).not.toBeNull();
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(1));
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(2));
  });

  it("a techfm_oa never fetches the report", async () => {
    await openHub({ role: "techfm_oa" });
    expect(el.tab("report").hidden).toBe(true);
    expect(requestFor("/hub/report")).toBeNull();
  });
});

describe("failure isolation", () => {
  it("crew fails on first load: inline error in the crew mount; dashboard and admin still render", async () => {
    // The Dashboard body holds all three mounts and is built on the click.
    await openHub({ role: "admin", crew: 500, tab: "dashboard" });
    expect(el.crewMount().querySelector("p.error").textContent).toBe("Could not load your crew.");
    expect(el.adminMount().children.length).toBeGreaterThan(0);
    expect(el.prioritiesMount().querySelector(".hub-priorities")).not.toBeNull();
  });

  it("admin fails on first load: inline error in the admin mount only", async () => {
    await openHub({ role: "admin", admin: 500, tab: "dashboard" });
    expect(el.adminMount().querySelector("p.error").textContent).toBe("Could not load the company summary.");
    expect(el.crewMount().querySelector("p.error")).toBeNull();
  });

  it("a background crew failure keeps the last good board", async () => {
    await openHub({ role: "supervisor", tab: "dashboard" });
    expect(el.crewMount().querySelector(".hub-crew-card")).not.toBeNull();
    server.use(http.get("/hub/crew", () => HttpResponse.json({ detail: "x" }, { status: 500 })));
    await vi.advanceTimersByTimeAsync(60000);           // safety refresh
    await vi.waitFor(() => expect(queries("/hub/crew")).toHaveLength(2));
    expect(el.crewMount().querySelector(".hub-crew-card")).not.toBeNull();
    expect(el.crewMount().querySelector("p.error")).toBeNull();
  });

  it("graphs fail: error with Retry; a later background failure keeps the last good render", async () => {
    await openHub({ role: "admin", graphs: 500 });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs-load-error")).not.toBeNull());
    server.use(http.get("/hub/graphs", () => HttpResponse.json(hubGraphs())));
    await user().click(el.panel("graphs").querySelector(".hub-graphs-retry"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    const before = queries("/hub/graphs").length;
    server.use(http.get("/hub/graphs", () => HttpResponse.json({ detail: "x" }, { status: 500 })));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull();
  });

  it("an empty graphs payload is swallowed: the skeleton stays and no error shows", async () => {
    // mountHubGraphs reads `activeCommunity.key` with no communities and throws;
    // loadGraphs has already stored the payload, so its catch returns early.
    // Characterization -- see open-work.md N-P5-CHARACTERIZED.
    await openHub({ role: "admin", graphs: hubGraphs({ communities: [] }) });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(queries("/hub/graphs").length).toBeGreaterThan(0));
    await vi.advanceTimersByTimeAsync(50);
    expect(el.panel("graphs").querySelector(".skel-grid")).not.toBeNull();
    expect(el.panel("graphs").querySelector(".hub-graphs-load-error")).toBeNull();
  });

  it("report fails: error with Retry", async () => {
    await openHub({ role: "owner" });                    // fixture answers /hub/report with 500
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(el.panel("report").querySelector(".hub-report-load-error")).not.toBeNull());
    expect(el.panel("report").querySelector("p.error").textContent).toBe("Could not load the report.");
    await user().click(el.panel("report").querySelector(".hub-report-retry"));
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(2));
  });
});

describe("crew safety refresh", () => {
  it("every 60 s refetches personal (+ crew for supervisor+, + admin for techfm_oa+), in the background", async () => {
    await openHub({ role: "admin" });
    clearRequests();
    await vi.advanceTimersByTimeAsync(59999);
    expect(requests()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub", "/hub/admin", "/hub/crew"]));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requests()).toHaveLength(6));
  });

  it("a technician's interval refetches only /hub", async () => {
    await openHub({ role: "technician" });
    clearRequests();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
  });

  it("adds graphs only while the Graphs tab is open", async () => {
    await openHub({ role: "admin" });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    const before = queries("/hub/graphs").length;
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    await user().click(el.tab("dashboard"));
    const hubs = queries("/hub").length;
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub").length).toBeGreaterThan(hubs));
    expect(queries("/hub/graphs")).toHaveLength(before + 1);
  });

  it("is cleared on hide and restarted on show only while the hub page is active", async () => {
    await openHub({ role: "supervisor" });
    stopClock();                                          // visibilitychange, hidden
    expect(vi.getTimerCount()).toBe(0);
    clearRequests();
    await vi.advanceTimersByTimeAsync(120000);
    expect(requests()).toHaveLength(0);
    // show again with the hub NOT the active page: nothing restarts
    restoreHubVisibility();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(vi.getTimerCount()).toBe(0);
    // show again WITH the hub active: both timers come back
    el.page().classList.add("active");
    document.dispatchEvent(new Event("visibilitychange"));
    // Exactly 2 (clock tick + safety interval) when this test runs alone.
    // In the full file every earlier test's userHub.js instance still has
    // its own `visibilitychange` listener on the shared `document` (module
    // registry resets do not remove listeners), and each of those restarts
    // its own pair too -- a harness artifact, so the assertion is the shape:
    // a positive multiple of two. The afterEach hide stops all of them.
    expect(vi.getTimerCount()).toBeGreaterThanOrEqual(2);
    expect(vi.getTimerCount() % 2).toBe(0);
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requestFor("/hub/crew")).not.toBeNull());
  });

  it("a second loadUserHub does not stack a second interval", async () => {
    const { mod } = await openHub({ role: "technician" });
    await mod.loadUserHub();
    await mod.loadUserHub();
    clearRequests();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub")).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(10);
    expect(queries("/hub")).toHaveLength(1);
  });
});

describe("clock hand-off", () => {
  it("the clock's onChanged refreshes the whole hub (one /hub fetch serves clock and tabs)", async () => {
    const { payload } = await openHub({ role: "technician", hub: hubPayload({ startable: [{
      work_order_id: "w1", number: "7001", status: "assigned", community: null, building_number: null, unit_number: null, location: null,
    }] }), handlers: [http.post("/work-orders/:id/tracking/start", () => HttpResponse.json({}))] });
    clearRequests();
    const start = el.clockMount().querySelector(".hub-clock-start-btn");
    expect(start.dataset.action).toBe("hub-clock-start");
    await user().click(start);
    await vi.waitFor(() => expect(requestFor("/tracking/start", "POST")).not.toBeNull());
    await vi.waitFor(() => expect(requestFor("/hub", "GET")).not.toBeNull());
    expect(payload).toBeTruthy();
  });
});

describe("realtime", () => {
  it("labor.session.changed on the hub page refreshes crew (+ admin for techfm_oa+) in the background", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    clearRequests();
    emit("labor.session.changed");
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub/admin", "/hub/crew"]));
    expect(requests().some((r) => r.url === "/hub")).toBe(false);
  });

  it("work_order.status.changed refreshes personal, crew, admin; graphs only while that tab is open", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    clearRequests();
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub", "/hub/admin", "/hub/crew"]));
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    const before = queries("/hub/graphs").length;
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
  });

  it("user_request.changed refreshes only the personal payload", async () => {
    await openHub({ role: "supervisor" });
    const { emit } = await connectHub();
    clearRequests();
    emit("user_request.changed");
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
    await vi.advanceTimersByTimeAsync(10);
    expect(requests()).toHaveLength(1);
  });

  it("a technician on work_order.status.changed refetches /hub only", async () => {
    await openHub({ role: "technician" });
    const { emit } = await connectHub();
    clearRequests();
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
    await vi.advanceTimersByTimeAsync(10);
    expect(requests()).toHaveLength(1);
  });

  it("an unrelated event, or the hub not being the active page, does nothing", async () => {
    await openHub({ role: "admin" });
    const { emit, ws } = await connectHub();
    clearRequests();
    emit("item.changed", { id: "i1" });
    await vi.advanceTimersByTimeAsync(50);
    expect(requests()).toHaveLength(0);
    const realtime = await import("../../../backend/static/realtime.js");
    realtime.setActivePageGetter(() => "history");
    emit("labor.session.changed");
    await vi.advanceTimersByTimeAsync(50);
    expect(requests()).toHaveLength(0);
    expect(ws.sockets).toHaveLength(1);
  });

  it("the personal refresh repaints the work-orders tab label and the open tab", async () => {
    const { payload } = await openHub({ role: "technician", hub: hubPayload({ mine_total: 1 }) });
    const { emit } = await connectHub();
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ mine_total: 4, user: payload.user }))));
    emit("user_request.changed");
    await vi.waitFor(() => expect(el.tab("work-orders").textContent).toBe("My Work Orders (4)"));
  });
});
