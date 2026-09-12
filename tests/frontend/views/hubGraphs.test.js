// Characterization coverage for views/hubGraphs.js: the community donut and
// its legend, the two-level drill (community, then service type or priority),
// the duration chart and its exact-values table, the range select, and the
// drill-down's hand-off to Work Orders.
//
// Through the hub shell -- openHub then a click on the Graphs tab, which is
// what fires GET /hub/graphs. `largestCommunityKey` and `destroyHubGraphs` are
// pure and are driven directly (P6 deviation 5).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { clearRequests, requests } from "../helpers/requests.js";
import { el, mountHub, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";
import { importView } from "../helpers/shell.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions, hubGraphBucket, hubGraphCommunity, hubGraphDistribution, hubGraphs } from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });     // the drill-down hand-off swaps pages

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
  window.history.replaceState({}, "", "/");
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("graphs");
const workOrdersPage = () => document.getElementById("work-orders-page");
const byId = (id) => document.getElementById(id);
const listQueries = () => requests()
  .filter((r) => r.method === "GET" && /^\/work-orders\/(\?|$)/.test(r.url))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

const STATUSES = [
  { key: "assigned", label: "Assigned" },
  { key: "in_progress", label: "In-Progress" },
  { key: "completed", label: "Completed" },
];

const maple = (overrides = {}) => hubGraphCommunity({
  key: "maple", label: "Maple Ridge", total: 4, counts: { assigned: 3, completed: 1 }, ...overrides,
});
const payloadFor = (overrides = {}) => hubGraphs({ statuses: STATUSES, communities: [maple()], ...overrides });

// The Work Orders page's own reference loads, plus filter options whose
// values match this payload's labels -- so the drill-down hand-off is tested
// against a page that COULD hold the value, not one that never had the option.
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions({
    service_types: ["Electrical"],
    priorities: ["Normal"],
    communities: [{ value: "Maple Ridge", label: "Maple Ridge" }],
  }))),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
];

async function openGraphs(graphs = payloadFor(), role = "techfm_oa") {
  const mounted = await openHub({ role, graphs, handlers: handOff() });
  await user().click(el.tab("graphs"));
  await vi.waitFor(() => expect(panel().querySelector(".hub-graphs")).not.toBeNull());
  return mounted;
}

describe("largestCommunityKey", () => {
  async function load() {
    await mountHub({ role: "techfm_oa" });          // the shell, for tooltip.js; nothing fetched
    return importView("views/hubGraphs.js");
  }

  it.each([
    ["the largest wins", [maple({ key: "a", total: 1 }), maple({ key: "b", total: 9 })], "b"],
    ["a tie takes the payload's first", [maple({ key: "a", total: 3 }), maple({ key: "b", total: 3 })], "a"],
    ["no communities is null", [], null],
  ])("%s", async (_name, communities, expected) => {
    const { largestCommunityKey } = await load();
    expect(largestCommunityKey({ communities })).toBe(expected);
  });

  it("a payload with no communities key is null, and destroyHubGraphs is a safe no-op", async () => {
    const { largestCommunityKey, destroyHubGraphs } = await load();
    expect(largestCommunityKey({})).toBeNull();
    expect(() => destroyHubGraphs()).not.toThrow();
  });
});

describe("the community donut", () => {
  it("one arc per non-zero status in payload order, each drillable, with the total badge", async () => {
    await openGraphs();
    const card = panel().querySelector(".hub-graph-community .hub-graph-card");
    expect(card.querySelector("h3").textContent).toBe("Maple Ridge");
    expect(Array.from(card.querySelectorAll("path.hub-graph-slice")).map((p) => p.dataset.status))
      .toEqual(["assigned", "completed"]);
    expect(card.querySelector(".hub-donut").getAttribute("aria-label"))
      .toBe("Maple Ridge status distribution, 4 circulating work orders");
    expect(card.querySelector(".hub-donut-total").textContent).toBe("4circulating");
  });

  it("a zero total draws the empty block instead, with no arcs", async () => {
    await openGraphs(payloadFor({ communities: [maple({ total: 0, counts: {} })] }));
    const empty = panel().querySelector(".hub-graph-community .hub-graph-empty");
    expect(empty.getAttribute("role")).toBe("img");
    expect(empty.textContent).toBe("No circulating work orders");
    expect(panel().querySelector("path.hub-graph-slice")).toBeNull();
  });

  it("a legend row per status even at zero, and View all carries the total", async () => {
    await openGraphs();
    const rows = Array.from(panel().querySelectorAll(".hub-graph-community .hub-graph-legend-row"));
    expect(rows.map((r) => r.textContent)).toEqual([
      "Assigned3 · 75.0%", "In-Progress0 · 0.0%", "Completed1 · 25.0%",
    ]);
    expect(rows.map((r) => r.dataset.status)).toEqual(["assigned", "in_progress", "completed"]);
    expect(panel().querySelector(".hub-graph-card-all").textContent).toBe("View all 4");
  });

  it("an empty community still lists every status at 0.0%", async () => {
    await openGraphs(payloadFor({ communities: [maple({ total: 0, counts: {} })] }));
    expect(Array.from(panel().querySelectorAll(".hub-graph-community .hub-graph-legend-row"))
      .map((r) => r.textContent))
      .toEqual(["Assigned0 · 0.0%", "In-Progress0 · 0.0%", "Completed0 · 0.0%"]);
    expect(panel().querySelector(".hub-graph-card-all").textContent).toBe("View all 0");
  });
});

describe("the tab strips", () => {
  const twoCommunities = () => payloadFor({
    communities: [maple(), maple({ key: "oak", label: "Oak Park", total: 2, counts: { assigned: 2 } })],
  });

  it("a community tab per community, labelled with its total, the first active", async () => {
    await openGraphs(twoCommunities());
    const tabs = Array.from(panel().querySelectorAll("[data-graph-tab]"));
    expect(tabs.map((t) => t.textContent)).toEqual(["Maple Ridge (4)", "Oak Park (2)"]);
    expect(tabs.map((t) => t.getAttribute("aria-selected"))).toEqual(["true", "false"]);
    expect(tabs[0].classList.contains("active")).toBe(true);
  });

  it("the inner strip offers Service Type and Priority, service type active", async () => {
    await openGraphs();
    const tabs = Array.from(panel().querySelectorAll("[data-graph-inner]"));
    expect(tabs.map((t) => [t.dataset.graphInner, t.textContent, t.getAttribute("aria-selected")]))
      .toEqual([["service_type", "Service Type", "true"], ["priority", "Priority", "false"]]);
  });

  it("a community tab click repaints from memory with no new request", async () => {
    await openGraphs(twoCommunities());
    const before = queries("/hub/graphs").length;
    await user().click(panel().querySelectorAll("[data-graph-tab]")[1]);
    await vi.waitFor(() => expect(panel().querySelector(".hub-graph-community h3").textContent).toBe("Oak Park"));
    expect(queries("/hub/graphs")).toHaveLength(before);
    expect(panel().querySelectorAll("[data-graph-tab]")[1].getAttribute("aria-selected")).toBe("true");
  });

  it("opening the tab fetches the graphs twice -- renderActiveTab and the tab button both load", async () => {
    // Characterization (N-P6-CHARACTERIZED): showTab -> renderActiveTab sees
    // no payload and calls loadGraphs(), then the tab button's own listener
    // calls loadGraphs({background: false}) again. The request-id guard drops
    // the first render, not the first request, so the first entry costs two
    // /hub/graphs round trips.
    await openGraphs();
    expect(queries("/hub/graphs")).toEqual([{ weeks: "12" }, { weeks: "12" }]);
  });
});

describe("the inner grid", () => {
  it("a card per service type, carrying the community and the raw service-type label", async () => {
    await openGraphs(payloadFor({ communities: [maple({
      service_types: [hubGraphDistribution({ key: "electrical", label: "Electrical", total: 3, counts: { assigned: 3 } })],
    })] }));
    const cards = Array.from(panel().querySelectorAll(".hub-graph-grid .hub-graph-card"));
    expect(cards).toHaveLength(1);
    expect(cards[0].dataset.community).toBe("maple");
    expect(cards[0].dataset.serviceType).toBe("Electrical");
    expect(cards[0].dataset.priority).toBeUndefined();
    expect(cards[0].querySelector("h3").textContent).toBe("Electrical");
  });

  it("the Priority tab swaps in priority cards with data-priority", async () => {
    await openGraphs(payloadFor({ communities: [maple({
      service_types: [hubGraphDistribution()],
      priorities: [hubGraphDistribution({ key: "normal", label: "Normal", total: 1, counts: { assigned: 1 } })],
    })] }));
    await user().click(panel().querySelector('[data-graph-inner="priority"]'));
    await vi.waitFor(() => expect(panel().querySelector(".hub-graph-grid .hub-graph-card").dataset.priority).toBe("Normal"));
    expect(panel().querySelector(".hub-graph-grid .hub-graph-card").dataset.serviceType).toBeUndefined();
  });

  it.each([
    ["priority with circulating work", { total: 4, counts: { assigned: 3, completed: 1 } }, "priority",
      "No imported priorities in this community"],
    ["priority with nothing circulating", { total: 0, counts: {} }, "priority", "No circulating work orders"],
    ["service type, always", { total: 4, counts: { assigned: 3, completed: 1 } }, "service_type", "No circulating work orders"],
  ])("%s explains the empty grid: %s", async (_name, communityOverrides, inner, reason) => {
    await openGraphs(payloadFor({ communities: [maple(communityOverrides)] }));
    if (inner === "priority") {
      await user().click(panel().querySelector('[data-graph-inner="priority"]'));
      await vi.waitFor(() => expect(panel().querySelector('[data-graph-inner="priority"]')
        .getAttribute("aria-selected")).toBe("true"));
    }
    const empties = Array.from(panel().querySelectorAll(".hub-graph-empty")).map((e) => e.textContent);
    expect(empties).toContain(reason);
  });
});

describe("the duration chart", () => {
  it("no non-null samples: the copy, and no chart", async () => {
    await openGraphs(payloadFor({ duration: { range: { start: "2026-06-18", end: "2026-09-10" }, buckets: [] } }));
    expect(panel().querySelector(".hub-duration-chart")).toBeNull();
    expect(Array.from(panel().querySelectorAll(".hub-duration-section .hub-graph-empty")).map((e) => e.textContent))
      .toContain("No duration samples in this range.");
  });

  it("a null bucket splits that series into two polylines; the other stays whole", async () => {
    await openGraphs(payloadFor({ duration: { range: { start: "2026-08-01", end: "2026-09-10" }, buckets: [
      hubGraphBucket({ start: "2026-08-10", circulating_avg_age_days: 4 }),
      hubGraphBucket({ start: "2026-08-17", circulating_avg_age_days: null, circulating_count: 0 }),
      hubGraphBucket({ start: "2026-08-24", circulating_avg_age_days: 6 }),
      hubGraphBucket({ start: "2026-08-31", circulating_avg_age_days: 7 }),
    ] } }));
    expect(panel().querySelectorAll("polyline.hub-duration-age")).toHaveLength(2);
    expect(panel().querySelectorAll("polyline.hub-duration-close")).toHaveLength(1);
  });

  it("the details table prints exact values, (partial), and No sample", async () => {
    await openGraphs(payloadFor({ duration: { range: { start: "2026-08-01", end: "2026-09-13" }, buckets: [
      hubGraphBucket({ start: "2026-09-07", end: "2026-09-13", partial: true }),
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06", circulating_avg_age_days: null, circulating_count: 0 }),
    ] } }));
    const rows = Array.from(panel().querySelectorAll(".hub-duration-details tbody tr"));
    expect(rows[0].querySelector("th").textContent).toBe("2026-09-07 – 2026-09-13 (partial)");
    expect(Array.from(rows[0].querySelectorAll("td")).map((td) => td.textContent))
      .toEqual(["4.50 days (n=2)", "2.25 days (n=1)"]);
    expect(rows[1].querySelector("th").textContent).toBe("2026-08-31 – 2026-09-06");
    expect(rows[1].querySelector("td").textContent).toBe("No sample");
  });
});

describe("the range select", () => {
  it("reflects the payload's weeks", async () => {
    await openGraphs(payloadFor({ weeks: 26 }));
    expect(panel().querySelector(".hub-graphs-weeks").value).toBe("26");
  });

  it("a change refetches that many weeks as a number", async () => {
    await openGraphs();
    const before = queries("/hub/graphs").length;
    await user().selectOptions(panel().querySelector(".hub-graphs-weeks"), "52");
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    expect(queries("/hub/graphs").at(-1)).toEqual({ weeks: "52" });
  });
});

describe("the Work Orders hand-off", () => {
  const withCards = () => payloadFor({ communities: [maple({
    service_types: [hubGraphDistribution({ key: "electrical", label: "Electrical", total: 3, counts: { assigned: 3 } })],
  })] });

  it("a donut slice drills on its own status", async () => {
    await openGraphs(withCards());
    clearRequests();
    await user().click(panel().querySelector('path.hub-graph-slice[data-status="completed"]'));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(byId("work-orders-status-filter").value).toBe("completed");
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1).status).toBe("completed");
  });

  it("a service-type card's legend row drills on the card's dimensions too", async () => {
    await openGraphs(withCards());
    clearRequests();
    await user().click(panel().querySelector('.hub-graph-grid [data-status="assigned"]'));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(byId("work-orders-status-filter").value).toBe("assigned");
    // Characterization (N-P6-CHARACTERIZED): the community and service-type
    // values are written to the selects BEFORE the page has ever loaded its
    // filter options, so no matching <option> exists yet and the assignment is
    // dropped -- even though this test's /work-orders/filter-options answer
    // does carry "Maple Ridge" and "Electrical". Every role lands on the User
    // Hub, so this is the ordinary path: the drill-down arrives filtered by
    // status alone.
    expect(byId("work-orders-community-filter").value).toBe("");
    expect(byId("work-orders-service-filter").value).toBe("");
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1).community).toBeUndefined();
    expect(listQueries().at(-1).service_type).toBeUndefined();
  });

  it("View all drills with no status at all", async () => {
    await openGraphs(withCards());
    clearRequests();
    await user().click(panel().querySelector(".hub-graph-community .hub-graph-card-all"));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(byId("work-orders-status-filter").value).toBe("");
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1).status).toBeUndefined();
  });

  it("distributionClickBound: a repaint does not double the click", async () => {
    await openGraphs(payloadFor({
      communities: [maple(), maple({ key: "oak", label: "Oak Park", total: 2, counts: { assigned: 2 } })],
    }));
    await user().click(panel().querySelectorAll("[data-graph-tab]")[1]);
    await vi.waitFor(() => expect(panel().querySelector(".hub-graph-community h3").textContent).toBe("Oak Park"));
    clearRequests();
    await user().click(panel().querySelector('.hub-graph-community [data-status="assigned"]'));
    await vi.waitFor(() => expect(listQueries()).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(50);
    expect(listQueries()).toHaveLength(1);
  });
});
