// Characterization coverage for views/hubTechnician.js: the Dashboard tab's
// count tiles, Time today, the timeline strip's local-time math, tools out
// and stocked requests, the techfm_oa+ omissions and the always-present
// mounts; and the My Work Orders tab's hand-offs around the list mount P2
// already covers (filters.test.js -> "mountWorkOrderList").

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";
import {
  filterOptions, hubAdjustment, hubPayload, hubRunningSession, hubStockedRequest, hubTimelineEntry,
  hubToolOut, workOrderCard, workOrderDetail,
} from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });    // the page swap scrolls; jsdom logs otherwise

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
  // A card-page hand-off leaves /workorder_card/<n> in the address bar.
  window.history.replaceState({}, "", "/");
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const dash = () => el.panel("dashboard");
const workOrdersPage = () => document.getElementById("work-orders-page");

// hubTechnician.js does its timeline math in LOCAL time (getHours), so these
// fixtures are built from local components and serialised -- never typed as
// a Z instant, which would shift with the machine's zone.
const local = (h, m = 0) => new Date(2026, 8, 10, h, m).toISOString();
const axisLabels = () => Array.from(dash().querySelectorAll(".hub-timeline-hour")).map((s) => s.textContent);

// The list requests only: `/work-orders/` with or without a query, never
// `/work-orders/<id>`, `/work-orders/<id>/requests` or `/work-orders/filter-options`.
const listQueries = () => requests()
  .filter((r) => r.method === "GET" && /^\/work-orders\/(\?|$)/.test(r.url))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

// Everything a card click or a stocked-request click fires once
// showPage("work-orders") consumes the pending number: the reference lists,
// the number search (mountHub's own /work-orders/ handler answers it), the
// detail and its requests strip. filter-options precedes :id because :id
// matches any segment.
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
  http.get("/work-orders/:id/requests", () => HttpResponse.json([])),
  http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ number: "7001" }))),
];

describe("count tiles", () => {
  it("renders the three tiles in order; the Ready sub only when non-zero", async () => {
    await openHub({ role: "technician", hub: hubPayload({ counts: { assigned: 3, in_progress: 1, ready_to_complete: 0 } }) });
    const tiles = Array.from(dash().querySelector(":scope > .hub-tile-grid").querySelectorAll(".hub-tile"));
    expect(tiles.map((t) => t.querySelector(".hub-tile-label").textContent))
      .toEqual(["Assigned to me", "In progress", "Ready to complete"]);
    expect(tiles.map((t) => t.querySelector(".hub-tile-value").textContent)).toEqual(["3", "1", "0"]);
    expect(tiles[0].querySelector(".hub-tile-sub").textContent).toBe("work orders");
    expect(tiles[1].querySelector(".hub-tile-sub")).toBeNull();
    expect(tiles[2].querySelector(".hub-tile-sub")).toBeNull();
  });

  it("Ready to complete carries 'waiting on supervisor' when non-zero", async () => {
    await openHub({ role: "technician", hub: hubPayload({ counts: { assigned: 3, in_progress: 1, ready_to_complete: 2 } }) });
    const tiles = dash().querySelector(":scope > .hub-tile-grid").querySelectorAll(".hub-tile");
    expect(tiles[2].querySelector(".hub-tile-sub").textContent).toBe("waiting on supervisor");
  });
});

describe("Time today", () => {
  it("hero, Charged, the running badge and one line per adjustment", async () => {
    const payload = hubPayload();
    payload.clock = {
      ...payload.clock,
      running_session: hubRunningSession(),
      closed_minutes_today: 100, running_minutes_today: 25, adjustment_minutes_today: 30,
      total_minutes_today: 155, adjustments: [hubAdjustment()],
    };
    await openHub({ role: "technician", hub: payload });
    const section = dash().querySelector(".hub-time-today");
    expect(section.querySelector(".hub-clock-hero").textContent).toBe("2 h 35 m");
    expect(section.querySelector(".hub-time-today-line").textContent).toContain("2 h 5 m");   // closed + running
    expect(section.querySelector(".hub-running-badge")).not.toBeNull();
    const lines = section.querySelectorAll(".hub-adjustment-line");
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toContain("30 m");
    expect(lines[0].textContent).toContain("recorded by Sue Super");
    expect(lines[0].textContent).toContain("WO 7001");
  });

  it("no running session: no badge, and the empty-timeline hint", async () => {
    await openHub({ role: "technician" });
    const section = dash().querySelector(".hub-time-today");
    expect(section.querySelector(".hub-running-badge")).toBeNull();
    expect(section.querySelector(".hub-adjustment-line")).toBeNull();
    expect(section.querySelector(".hint").textContent).toContain("No time charged yet today");
    expect(section.querySelector(".hub-timeline")).toBeNull();
  });

  it("a running session with no entries draws the axis with no blocks", async () => {
    const payload = hubPayload({ server_now: local(12) });
    payload.clock = { ...payload.clock, running_session: hubRunningSession({ started_at: local(11) }) };
    await openHub({ role: "technician", hub: payload });
    expect(dash().querySelector(".hub-timeline")).not.toBeNull();
    expect(dash().querySelectorAll(".hub-timeline-block")).toHaveLength(0);
    expect(axisLabels()).toEqual(["8a", "9a", "10a", "11a", "12p", "1p", "2p", "3p", "4p", "5p"]);
  });
});

describe("timeline", () => {
  const entry = (h, m = 0, extra = {}) =>
    hubTimelineEntry({ started_at: local(h, m), ended_at: local(h + 1, m), minutes: 60, ...extra });

  it("the axis runs 8a..5p when work starts after 8 and now is before 5", async () => {
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(12), timeline: [entry(9)] }) });
    expect(axisLabels()).toEqual(["8a", "9a", "10a", "11a", "12p", "1p", "2p", "3p", "4p", "5p"]);
  });

  it("an early start extends the axis left", async () => {
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(12), timeline: [entry(6, 30)] }) });
    expect(axisLabels()[0]).toBe("6a");
    expect(axisLabels().at(-1)).toBe("5p");
  });

  it("a late now extends the axis right", async () => {
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(19, 15), timeline: [entry(9)] }) });
    expect(axisLabels()[0]).toBe("8a");
    expect(axisLabels().at(-1)).toBe("8p");
  });

  it("positions a block through CSSOM from the range, with the title and no running class", async () => {
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(12), timeline: [entry(9)] }) });
    const block = dash().querySelector(".hub-timeline-block");
    // range 8:00 (480) -> 17:00 (1020), span 540; the block starts at 9:00 (540).
    expect(parseFloat(block.style.left)).toBeCloseTo(((540 - 480) / 540) * 100, 6);
    expect(parseFloat(block.style.width)).toBeCloseTo((60 / 540) * 100, 6);
    expect(block.dataset.left).toBe(String(((540 - 480) / 540) * 100));
    expect(block.classList.contains("hub-timeline-block-running")).toBe(false);
    expect(block.textContent).toBe("7001");
    expect(block.title).toBe("WO 7001 — 1 h 0 m");
  });

  it("a 1-minute block gets the 0.5 % width floor", async () => {
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(12), timeline: [entry(9, 0, { minutes: 1 })] }) });
    expect(dash().querySelector(".hub-timeline-block").style.width).toBe("0.5%");
  });

  it("a running entry carries the running class and label; auto_closed marks the title", async () => {
    const running = entry(11, 0, { ended_at: null, minutes: 60 });
    const estimate = entry(9, 0, { auto_closed: true });
    await openHub({ role: "technician", hub: hubPayload({ server_now: local(12), timeline: [estimate, running] }) });
    const blocks = dash().querySelectorAll(".hub-timeline-block");
    expect(blocks[0].title).toBe("WO 7001 — 1 h 0 m (auto-closed estimate)");
    expect(blocks[1].classList.contains("hub-timeline-block-running")).toBe(true);
    expect(blocks[1].textContent).toBe("7001 (running)");
  });
});

describe("tools out", () => {
  it("empty: the hint", async () => {
    await openHub({ role: "technician" });
    expect(dash().querySelector(".hub-tools-out .hint").textContent).toBe("No tools currently checked out.");
    expect(dash().querySelector(".hub-tools-out .hub-tile-count")).toBeNull();
  });

  it("rows: a count, the name and a weekday since; a null since renders an empty date", async () => {
    await openHub({ role: "technician", hub: hubPayload({ tools_out: [
      hubToolOut({ name: "Drill", since: "2026-09-08T12:00:00Z" }),
      hubToolOut({ name: "Saw", since: null }),
    ] }) });
    const section = dash().querySelector(".hub-tools-out");
    expect(section.querySelector(".hub-tile-count").textContent).toBe("2");
    const rows = section.querySelectorAll("li");
    expect(rows).toHaveLength(2);
    expect(rows[0].firstElementChild.textContent).toBe("Drill");
    const since = new Date("2026-09-08T12:00:00Z").toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
    expect(rows[0].querySelector(".hub-tool-since").textContent).toBe(`since ${since}`);
    // A tool with no `since` still gets the "since " prefix over nothing.
    // Characterization -- see open-work.md N-P6-CHARACTERIZED.
    expect(rows[1].querySelector(".hub-tool-since").textContent).toBe("since ");
  });
});

describe("stocked requests", () => {
  it("omitted entirely when empty", async () => {
    await openHub({ role: "technician" });
    expect(dash().querySelector(".hub-stocked-requests")).toBeNull();
  });

  it("one row per request: escaped item, the number button, the hint with or without a stocked time", async () => {
    await openHub({ role: "technician", hub: hubPayload({ stocked_requests: [
      hubStockedRequest({ item_name: "<b>Bulb</b>", quantity: "2", stocked_at: "2026-09-10T11:30:00Z" }),
      hubStockedRequest({ item_name: "Tape", work_order_number: "7002", quantity: "5", stocked_at: null }),
    ] }) });
    const rows = dash().querySelectorAll(".hub-stocked-request");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".hub-stocked-item").textContent).toBe("<b>Bulb</b>");
    expect(rows[0].querySelector("b")).toBeNull();
    expect(rows[0].querySelector(".hub-stocked-wo").textContent).toBe("7001");
    expect(rows[0].querySelector(".hint").textContent)
      .toBe(`requested 2 · stocked ${new Date("2026-09-10T11:30:00Z").toLocaleString()}`);
    expect(rows[1].querySelector(".hub-stocked-wo").textContent).toBe("7002");
    expect(rows[1].querySelector(".hint").textContent).toBe("requested 5");
  });

  it("the number button focuses the work order and swaps to Work Orders", async () => {
    await openHub({
      role: "technician",
      hub: hubPayload({ stocked_requests: [hubStockedRequest({ work_order_number: "7001" })] }),
      workOrders: [workOrderCard({ number: "7001" })],
      handlers: handOff(),
    });
    clearRequests();
    await user().click(dash().querySelector(".hub-stocked-wo"));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    await vi.waitFor(() => expect(requestFor("/work-orders/?q=7001")).not.toBeNull());
  });
});

describe("by role", () => {
  it.each(["technician", "admin"])("%s: the priorities, admin and crew mounts are present", async (role) => {
    await openHub({ role });
    expect(dash().querySelector("#hub-priorities-mount")).not.toBeNull();
    expect(dash().querySelector("#hub-admin-mount")).not.toBeNull();
    expect(dash().querySelector("#hub-crew-mount")).not.toBeNull();
  });

  it("techfm_oa+ omits Time today and Tools out", async () => {
    await openHub({ role: "techfm_oa", hub: hubPayload({ tools_out: [hubToolOut()] }) });
    expect(dash().querySelector(".hub-time-today")).toBeNull();
    expect(dash().querySelector(".hub-tools-out")).toBeNull();
  });

  it("a technician keeps both", async () => {
    await openHub({ role: "technician", hub: hubPayload({ tools_out: [hubToolOut()] }) });
    expect(dash().querySelector(".hub-time-today")).not.toBeNull();
    expect(dash().querySelector(".hub-tools-out")).not.toBeNull();
  });
});

describe("My Work Orders tab", () => {
  it("a card click focuses the number and swaps to Work Orders", async () => {
    await openHub({ role: "technician", workOrders: [workOrderCard({ number: "7001" })], handlers: handOff() });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(el.panel("work-orders").querySelector("summary.wo-summary")).not.toBeNull());
    clearRequests();
    await user().click(el.panel("work-orders").querySelector("summary.wo-summary"));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    await vi.waitFor(() => expect(requestFor("/work-orders/?q=7001")).not.toBeNull());
  });

  it("View all swaps to Work Orders and loads the page's own list, with no number search", async () => {
    await openHub({ role: "technician", workOrders: [workOrderCard()], handlers: handOff() });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(el.panel("work-orders").querySelector(".hub-wo-list")).not.toBeNull());
    clearRequests();
    await user().click(el.panel("work-orders").querySelector('[data-action="hub-view-all-work-orders"]'));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().every((q) => !("q" in q))).toBe(true);
  });

  it("the 60 s personal refresh refetches the tab's list while it is open", async () => {
    await openHub({ role: "technician", workOrders: [workOrderCard()] });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(listQueries()).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(listQueries()).toHaveLength(2));
    expect(listQueries()[1]).toEqual({ limit: "10" });
  });
});
