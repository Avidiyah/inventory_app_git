// Coverage for views/hubGraphs.js and views/hubGraphTrends.js: the tile grid
// and its grouping switch, the pop-up (pick a status, break a pie down, step
// back, close), the two trend charts and their range pills, and the red
// button's hand-off to Work Orders.
//
// Through the hub shell -- openHub then a click on the Graphs tab, which is
// what fires GET /hub/graphs.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { clearRequests, requests } from "../helpers/requests.js";
import { el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";
import { importView } from "../helpers/shell.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions, hubGraphBucket, hubGraphCell, hubGraphCommunity, hubGraphs } from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });     // the hand-off swaps pages

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
  window.history.replaceState({}, "", "/");
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
// menus.js answers every focus move with a zero-delay timer. A user-event
// action flushes it; a pop-up closed by code (Back, a role change) does not.
const flushFocusTimer = () => vi.advanceTimersByTimeAsync(0);
const panel = () => el.panel("graphs");
const sheet = () => document.querySelector(".hub-graph-sheet");
const sheetOpen = () => Boolean(sheet()) && !sheet().hidden;
const texts = (root, selector) => Array.from(root.querySelectorAll(selector)).map((node) => node.textContent);
const tiles = (root) => Array.from(root.querySelectorAll(".hub-graph-tile:not(.hub-trend-tile)"))
  .map((tile) => [tile.querySelector(".hub-graph-tile-label").textContent, Number(tile.querySelector(".hub-graph-tile-total").textContent)]);
const tile = (root, label) => Array.from(root.querySelectorAll(".hub-graph-tile"))
  .find((node) => node.querySelector(".hub-graph-tile-label").textContent === label);
const go = () => sheet().querySelector("[data-graph-go]").textContent;
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

// Maple Ridge: 3 assigned, 2 in progress, 1 completed. Oak Park shares the two
// in-progress Plumbing work orders, so they count in both communities but once
// under Plumbing. One completed Electrical work order has no priority.
const CELLS = [
  hubGraphCell({ communities: ["maple"], service_type: "Electrical", priority: "Normal", status: "assigned", count: 2 }),
  hubGraphCell({ communities: ["maple"], service_type: "Plumbing", priority: "Urgent", status: "assigned", count: 1 }),
  hubGraphCell({ communities: ["maple"], service_type: "Electrical", priority: null, status: "completed", count: 1 }),
  hubGraphCell({ communities: ["maple", "oak"], service_type: "Plumbing", priority: "Normal", status: "in_progress", count: 2 }),
];
const payloadFor = (overrides = {}) => hubGraphs({
  statuses: STATUSES,
  communities: [hubGraphCommunity(), hubGraphCommunity({ key: "oak", label: "Oak Park" }), hubGraphCommunity({ key: "elm", label: "Elm Court" })],
  cells: CELLS,
  ...overrides,
});

// The Work Orders page's own reference loads. Its filter options answer only
// AFTER the hand-off has set the dropdowns, which is the ordinary path: every
// role lands on the User Hub, so the page has usually never loaded them.
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions({
    service_types: ["Electrical", "Plumbing"],
    priorities: ["Normal", "Urgent"],
    communities: [{ value: "maple", label: "Maple Ridge" }, { value: "oak", label: "Oak Park" }],
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
async function openPie(label, root = panel()) {
  await user().click(tile(root, label));
  await vi.waitFor(() => expect(sheet().querySelector("#hub-graph-sheet-title").textContent).toBe(label));
}
async function openTrend(key, graphs) {
  await openGraphs(graphs);
  await user().click(panel().querySelector(`[data-graph-trend="${key}"]`));
  await vi.waitFor(() => expect(sheetOpen()).toBe(true));
}

describe("the tile grid", () => {
  it("a pie per community in payload order, an empty one kept but not openable", async () => {
    await openGraphs();
    expect(tiles(panel())).toEqual([["Maple Ridge", 6], ["Oak Park", 2], ["Elm Court", 0]]);
    expect(tile(panel(), "Maple Ridge").disabled).toBe(false);
    expect(tile(panel(), "Elm Court").disabled).toBe(true);
    expect(tile(panel(), "Maple Ridge").querySelector(".hub-donut").getAttribute("aria-label"))
      .toBe("Maple Ridge status distribution, 6 circulating work orders");
    expect(tile(panel(), "Elm Court").querySelector(".hub-donut-empty")).not.toBeNull();
    expect(sheet()).toBeNull();
  });

  it("one colour key names every status for the whole grid", async () => {
    await openGraphs();
    expect(texts(panel(), ".hub-graph-status-key li")).toEqual(["Assigned", "In-Progress", "Completed"]);
  });

  it("tile slices are not pickable: the whole tile is one button", async () => {
    await openGraphs();
    expect(panel().querySelector(".hub-graph-tile [data-status]")).toBeNull();
    expect(panel().querySelectorAll(".hub-graph-tile path.hub-graph-slice").length).toBeGreaterThan(0);
  });

  it("the switch regroups by service type, counting a two-community work order once", async () => {
    await openGraphs();
    const before = queries("/hub/graphs").length;
    await user().click(panel().querySelector('[data-graph-front="service_type"]'));
    // Largest first, then alphabetical.
    expect(tiles(panel())).toEqual([["Electrical", 3], ["Plumbing", 3]]);
    expect(queries("/hub/graphs")).toHaveLength(before);            // repainted from memory
    expect(panel().querySelector('[data-graph-front="service_type"]').getAttribute("aria-pressed")).toBe("true");
    expect(panel().querySelector('[data-graph-front="community"]').getAttribute("aria-pressed")).toBe("false");
    expect(document.activeElement).toBe(panel().querySelector('[data-graph-front="service_type"]'));
  });

  it("grouped by priority, a blank priority gets no pie", async () => {
    await openGraphs();
    await user().click(panel().querySelector('[data-graph-front="priority"]'));
    expect(tiles(panel())).toEqual([["Normal", 4], ["Urgent", 1]]);
  });

  it("the two-community warning shows only when grouped by community", async () => {
    await openGraphs();
    const warned = () => panel().textContent.includes("counted in each");
    expect(warned()).toBe(true);
    await user().click(panel().querySelector('[data-graph-front="priority"]'));
    expect(warned()).toBe(false);
  });

  it.each([
    ["priority", "No imported priorities"],
    ["service_type", "No circulating work orders"],
  ])("nothing to group by %s says so", async (dim, reason) => {
    await openGraphs(payloadFor({ cells: [] }));
    await user().click(panel().querySelector(`[data-graph-front="${dim}"]`));
    expect(texts(panel(), ".hub-graph-empty")).toEqual([reason]);
  });

  it("a payload with no communities and no cells still renders", async () => {
    await openGraphs(payloadFor({ communities: [], cells: [] }));
    expect(texts(panel(), ".hub-graph-empty")).toEqual(["No circulating work orders"]);
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

describe("a pie's pop-up", () => {
  it("opens over the page with its title, total, arcs and a legend row per non-zero status", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    expect(sheetOpen()).toBe(true);
    expect(sheet().parentElement.id).toBe("user-hub-page");          // not inside the re-rendered panel
    expect(sheet().querySelector('[role="dialog"]').getAttribute("aria-labelledby")).toBe("hub-graph-sheet-title");
    expect(sheet().querySelector(".hub-graph-sheet-head .hint").textContent).toBe("6 work orders in circulation");
    expect(Array.from(sheet().querySelectorAll(".hub-graph-pie path.hub-graph-slice")).map((p) => p.dataset.status))
      .toEqual(["assigned", "in_progress", "completed"]);
    expect(texts(sheet(), ".hub-graph-legend-row")).toEqual([
      "Assigned3 · 50.0%", "In-Progress2 · 33.3%", "Completed1 · 16.7%",
    ]);
    expect(sheet().querySelector(".hub-donut-total").textContent).toBe("6circulating");
    expect(go()).toBe("View 6 work ordersMaple Ridge · every status");
    expect(document.activeElement).toBe(sheet().querySelector("[data-graph-close]"));
  });

  it("a status with nothing in it gets no legend row", async () => {
    await openGraphs();
    await openPie("Oak Park");
    expect(texts(sheet(), ".hub-graph-legend-row")).toEqual(["In-Progress2 · 100.0%"]);
    expect(go()).toBe("View 2 work ordersOak Park · every status");
  });

  it("a pie that is all one status still draws its ring", async () => {
    // A full circle whose arc starts and ends on the same point is drawn as
    // nothing at all, which used to leave such a pie blank.
    await openGraphs();
    await openPie("Oak Park");
    const [, x1, y1, x2, y2] = sheet().querySelector(".hub-graph-pie path.hub-graph-slice").getAttribute("d")
      .match(/^M (\S+) (\S+) A 40 40 0 1 0 (\S+) (\S+)$/);
    expect([x1, y1]).not.toEqual([x2, y2]);
  });

  it("a legend row picks its status: pressed, the rest dimmed, and the button names it", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="in_progress"]'));
    const row = () => sheet().querySelector('.hub-graph-legend-row[data-status="in_progress"]');
    expect(row().getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(row());                      // focus follows the re-draw
    expect(Array.from(sheet().querySelectorAll(".hub-graph-pie .hub-graph-slice-dim")).map((p) => p.dataset.status))
      .toEqual(["assigned", "completed"]);
    expect(sheet().querySelector(".hub-donut-total").textContent).toBe("2In-Progress");
    expect(go()).toBe("View 2 work ordersMaple Ridge · In-Progress");
    expect(workOrdersPage().classList.contains("active")).toBe(false); // picking never navigates
  });

  it("picking the same status again un-picks it, and a slice picks like its row", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('.hub-graph-pie path[data-status="completed"]'));
    expect(go()).toBe("View 1 work orderMaple Ridge · Completed");
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="completed"]'));
    expect(go()).toBe("View 6 work ordersMaple Ridge · every status");
    expect(sheet().querySelector(".hub-graph-slice-dim")).toBeNull();
  });

  it("the red X closes it and hands focus back to the tile", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector("[data-graph-close]"));
    expect(sheetOpen()).toBe(false);
    expect(document.activeElement).toBe(tile(panel(), "Maple Ridge"));
  });

  it("Escape closes it too, and a click on the backdrop does not", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet());
    expect(sheetOpen()).toBe(true);
    await user().keyboard("{Escape}");
    expect(sheetOpen()).toBe(false);
    await user().keyboard("{Escape}");                                // no listener left behind
    expect(sheetOpen()).toBe(false);
  });

  it("Tab stays inside the pop-up, wrapping at both ends", async () => {
    await openGraphs();
    await openPie("Oak Park");
    const stops = Array.from(sheet().querySelectorAll("button:not([disabled])"));
    expect(document.activeElement).toBe(stops[0]);
    await user().tab({ shift: true });
    expect(document.activeElement).toBe(stops.at(-1));
    await user().tab();
    expect(document.activeElement).toBe(stops[0]);
  });

  it("browser Back closes it", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(sheetOpen()).toBe(false);
    await flushFocusTimer();
  });

  it("reopening starts clean: no status carried over from the last visit", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="assigned"]'));
    await user().click(sheet().querySelector("[data-graph-close]"));
    await openPie("Maple Ridge");
    expect(go()).toBe("View 6 work ordersMaple Ridge · every status");
  });
});

describe("breaking a pie down", () => {
  it("offers the two unused groupings, service type first, counting that community only", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    expect(texts(sheet(), "[data-graph-break]")).toEqual(["Service type", "Priority"]);
    expect(sheet().querySelector('[data-graph-break="service_type"]').getAttribute("aria-pressed")).toBe("true");
    expect(sheet().querySelector(".hub-graph-section h3").textContent).toBe("Break Maple Ridge down by");
    expect(sheet().querySelector(".hub-graph-section .hint").textContent)
      .toBe("These pies count Maple Ridge work orders only. Tap one to open it.");
    expect(tiles(sheet())).toEqual([["Electrical", 3], ["Plumbing", 3]]);
  });

  it("the same community cut by priority leaves the blank priority out", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('[data-graph-break="priority"]'));
    expect(tiles(sheet())).toEqual([["Normal", 4], ["Urgent", 1]]);
    expect(document.activeElement).toBe(sheet().querySelector('[data-graph-break="priority"]'));
  });

  it("an inner pie takes over the pop-up, scoped to everything picked so far", async () => {
    await openGraphs();
    await openPie("Oak Park");
    await openPie("Plumbing", sheet());
    expect(sheet().querySelector(".hub-graph-sheet-head .hint").textContent).toBe("2 work orders in Oak Park");
    expect(sheet().querySelector("[data-graph-up]").textContent).toBe("← Back to Oak Park");
    expect(go()).toBe("View 2 work ordersOak Park · Plumbing · every status");
    expect(document.activeElement).toBe(sheet().querySelector("[data-graph-up]"));
    // Only Priority is left, so there is nothing to switch between.
    expect(sheet().querySelector("[data-graph-break]")).toBeNull();
    expect(sheet().querySelector(".hub-graph-section h3").textContent).toBe("Oak Park · Plumbing by priority");
    expect(tiles(sheet())).toEqual([["Normal", 2]]);
  });

  it("the third level has nothing left to break down by, and its button lists all three", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await openPie("Plumbing", sheet());
    await openPie("Urgent", sheet());
    expect(sheet().querySelector(".hub-graph-tile")).toBeNull();
    expect(sheet().querySelector(".hub-graph-sheet-head .hint").textContent).toBe("1 work order in Maple Ridge · Plumbing");
    expect(go()).toBe("View 1 work orderMaple Ridge · Plumbing · Urgent · every status");
  });

  it("any grouping can come first: Plumbing then Maple Ridge is the same slice", async () => {
    await openGraphs();
    await user().click(panel().querySelector('[data-graph-front="service_type"]'));
    await openPie("Plumbing");
    expect(texts(sheet(), "[data-graph-break]")).toEqual(["Community", "Priority"]);
    // The shared work orders appear under both communities here.
    expect(tiles(sheet())).toEqual([["Maple Ridge", 3], ["Oak Park", 2]]);
    await openPie("Maple Ridge", sheet());
    expect(go()).toBe("View 3 work ordersPlumbing · Maple Ridge · every status");
  });

  it("Back returns to the parent with its status pick, its break-down and its scroll", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="assigned"]'));
    await user().click(sheet().querySelector('[data-graph-break="priority"]'));
    const body = sheet().querySelector(".hub-graph-sheet-body");
    body.scrollTop = 120;
    await openPie("Normal", sheet());
    expect(sheet().querySelector(".hub-graph-sheet-body")).toBe(body);  // never replaced
    expect(body.scrollTop).toBe(0);
    await user().click(sheet().querySelector("[data-graph-up]"));
    expect(sheet().querySelector("#hub-graph-sheet-title").textContent).toBe("Maple Ridge");
    expect(sheet().querySelector("[data-graph-up]")).toBeNull();
    expect(body.scrollTop).toBe(120);
    expect(go()).toBe("View 3 work ordersMaple Ridge · Assigned");
    expect(sheet().querySelector('[data-graph-break="priority"]').getAttribute("aria-pressed")).toBe("true");
  });

  it("a pie whose work orders all lack a priority says so", async () => {
    await openGraphs(payloadFor({ cells: [hubGraphCell({ priority: null, count: 2 })] }));
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector('[data-graph-break="priority"]'));
    expect(texts(sheet(), ".hub-graph-empty")).toEqual(["No imported priorities in Maple Ridge"]);
  });
});

describe("a refresh under an open pop-up", () => {
  const live = async () => {
    const graphs = { current: payloadFor() };
    await openHub({ role: "techfm_oa", handlers: [http.get("/hub/graphs", () => HttpResponse.json(graphs.current)), ...handOff()] });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-graphs")).not.toBeNull());
    const refresh = async (next) => {
      graphs.current = next;
      const before = queries("/hub/graphs").length;
      await vi.advanceTimersByTimeAsync(60000);                       // the hub's safety refresh
      await vi.waitFor(() => expect(queries("/hub/graphs").length).toBeGreaterThan(before));
    };
    return refresh;
  };

  it("re-draws the pop-up in place, keeping the drill path and the pick", async () => {
    const refresh = await live();
    await openPie("Maple Ridge");
    await openPie("Electrical", sheet());
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="assigned"]'));
    await refresh(payloadFor({ cells: [...CELLS, hubGraphCell({ communities: ["maple"], count: 5 })] }));
    await vi.waitFor(() => expect(go()).toBe("View 7 work ordersMaple Ridge · Electrical · Assigned"));
    expect(sheetOpen()).toBe(true);
    expect(tiles(panel())[0]).toEqual(["Maple Ridge", 11]);           // the page behind refreshed too
  });

  it("a pick whose status emptied out lapses, and an emptied pie says so", async () => {
    const refresh = await live();
    await openPie("Oak Park");
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="in_progress"]'));
    await refresh(payloadFor({ cells: [hubGraphCell({ communities: ["oak"], status: "assigned", count: 4 })] }));
    await vi.waitFor(() => expect(go()).toBe("View 4 work ordersOak Park · every status"));
    await refresh(payloadFor({ cells: [] }));
    await vi.waitFor(() => expect(texts(sheet(), ".hub-graph-empty")).toEqual(["No circulating work orders"]));
    expect(sheet().querySelector("[data-graph-go]")).toBeNull();
    expect(sheet().querySelector(".hub-graph-tile")).toBeNull();
  });
});

describe("destroyHubGraphs", () => {
  it("closes the pop-up and forgets the grouping", async () => {
    await openGraphs();
    await user().click(panel().querySelector('[data-graph-front="priority"]'));
    await openPie("Normal");
    const { destroyHubGraphs, mountHubGraphs } = await importView("views/hubGraphs.js");
    destroyHubGraphs();
    await flushFocusTimer();
    expect(sheet()).toBeNull();
    expect(() => destroyHubGraphs()).not.toThrow();                  // safe with nothing open
    mountHubGraphs(panel(), payloadFor());                            // callbacks are optional
    expect(panel().querySelector('[data-graph-front="community"]').getAttribute("aria-pressed")).toBe("true");
  });
});

describe("the trend tiles", () => {
  const weeks = (...buckets) => payloadFor({ duration: { range: { start: "2026-08-01", end: "2026-09-13" }, buckets } });

  it("headline the last full week, not the one in progress", async () => {
    await openGraphs(weeks(
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06", circulating_median_age_days: 3, closed_median_days: 1.5, on_time_pct: 82 }),
      hubGraphBucket({ start: "2026-09-07", end: "2026-09-13", partial: true }),
    ));
    const [days, ontime] = Array.from(panel().querySelectorAll(".hub-trend-tile"));
    expect(days.querySelector(".hub-graph-tile-label").textContent).toBe("Age and close-out time");
    expect(texts(days, ".hub-trend-stat")).toEqual(["3.0dopen age", "1.5dtime to close"]);
    expect(days.querySelector(".hub-trend-tile-foot").textContent).toBe("Week of Aug 31–Sep 6 · tap to open");
    expect(days.querySelectorAll(".hub-trend-spark polyline")).toHaveLength(2);
    expect(ontime.querySelector(".hub-graph-tile-label").textContent).toBe("Closed within 4 days");
    expect(texts(ontime, ".hub-trend-stat")).toEqual(["82%on time"]);
  });

  it("a week with no samples says so instead of printing a number", async () => {
    await openGraphs(weeks(hubGraphBucket({
      circulating_median_age_days: null, circulating_p90_age_days: null, circulating_count: 0,
      on_time_pct: null, on_time_count: 0, scheduled_closed_count: 0,
    })));
    const [days, ontime] = Array.from(panel().querySelectorAll(".hub-trend-tile"));
    expect(texts(days, ".hub-trend-stat")).toEqual(["–open age · no sample", "2.3dtime to close"]);
    expect(texts(ontime, ".hub-trend-stat")).toEqual(["–on time · no scheduled closes"]);
    expect(panel().querySelector(".hub-trend-spark polyline")).toBeNull();   // one point is not a line
  });

  it("with only the week in progress, that week is the headline", async () => {
    await openGraphs(weeks(hubGraphBucket({ partial: true })));
    expect(panel().querySelector(".hub-trend-tile-foot").textContent).toBe("Week of Sep 7–13 · tap to open");
  });

  it("no weeks at all: the tiles still open, with nothing to headline", async () => {
    await openGraphs();
    expect(texts(panel(), ".hub-trend-tile-foot")).toEqual(Array(2).fill("No weeks in this range · tap to open"));
    expect(panel().querySelector(".hub-trend-stat")).toBeNull();
  });
});

describe("the duration chart", () => {
  it("no non-null samples: the copy, and no chart", async () => {
    await openTrend("days", payloadFor());
    expect(sheet().querySelector("#hub-graph-sheet-title").textContent).toBe("Work-order age and close-out time");
    expect(sheet().querySelector(".hub-graph-sheet-head .hint").textContent).toBe("Week by week, last 12 weeks");
    expect(sheet().querySelector(".hub-duration-chart")).toBeNull();
    expect(texts(sheet(), ".hub-graph-empty")).toContain("No duration samples in this range.");
  });

  const noAge = { circulating_median_age_days: null, circulating_p90_age_days: null, circulating_count: 0 };
  const weeks = (...buckets) => payloadFor({ duration: { range: { start: "2026-08-01", end: "2026-09-13" }, buckets } });

  it("a null bucket splits that series' median line and p90 band in two; the other stays whole", async () => {
    await openTrend("days", weeks(
      hubGraphBucket({ start: "2026-08-10", end: "2026-08-16" }),
      hubGraphBucket({ start: "2026-08-17", end: "2026-08-23", ...noAge }),
      hubGraphBucket({ start: "2026-08-24", end: "2026-08-30" }),
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06" }),
    ));
    expect(sheet().querySelectorAll("polyline.hub-duration-age")).toHaveLength(2);
    expect(sheet().querySelectorAll("polyline.hub-duration-close")).toHaveLength(1);
    // A one-week run has no area to shade; its dot still shows it.
    expect(sheet().querySelectorAll("polygon.hub-duration-band-age")).toHaveLength(1);
    expect(sheet().querySelectorAll("polygon.hub-duration-band-close")).toHaveLength(1);
  });

  it("every non-null week gets a dot whose tooltip carries the exact figures", async () => {
    await openTrend("days", weeks(
      hubGraphBucket({ start: "2026-08-10", end: "2026-08-16" }),
      hubGraphBucket({ start: "2026-08-17", end: "2026-08-23", ...noAge }),
    ));
    expect(sheet().querySelectorAll(".hub-duration-point-age")).toHaveLength(1);
    expect(sheet().querySelectorAll(".hub-duration-point-close")).toHaveLength(2);
    expect(sheet().querySelector(".hub-duration-point-age title").textContent)
      .toBe("Circulating age, week of Aug 10–16: median 4.5d · p90 9.0d · n=6");
  });

  it("the week in progress is hollow and joined by a dashed segment", async () => {
    await openTrend("days", weeks(
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06" }),
      hubGraphBucket({ start: "2026-09-07", end: "2026-09-13", partial: true }),
    ));
    expect(sheet().querySelectorAll("line.hub-duration-partial.hub-duration-age")).toHaveLength(1);
    const partial = sheet().querySelectorAll(".hub-duration-point-age")[1];
    expect(partial.classList.contains("hub-duration-point-partial")).toBe(true);
    expect(partial.querySelector("title").textContent).toMatch(/\(in progress\)$/);
  });

  it("a week under five samples is faded and says so", async () => {
    await openTrend("days", weeks(hubGraphBucket({ start: "2026-08-31", end: "2026-09-06" })));
    // The factory's age has n=6, its close-out n=1.
    expect(sheet().querySelector(".hub-duration-point-age").classList.contains("hub-duration-point-low")).toBe(false);
    const close = sheet().querySelector(".hub-duration-point-close");
    expect(close.classList.contains("hub-duration-point-low")).toBe(true);
    expect(close.querySelector("title").textContent).toMatch(/· low sample$/);
  });

  it("labels round-number gridlines from 0 up to the highest p90", async () => {
    await openTrend("days", weeks(hubGraphBucket({ start: "2026-08-31", end: "2026-09-06", circulating_p90_age_days: 37 })));
    expect(texts(sheet(), ".hub-duration-days .hub-duration-tick")).toEqual(["0d", "10d", "20d", "30d", "40d"]);
  });

  it("the last date label hangs left of its tick so it cannot run off the chart", async () => {
    await openTrend("days", weeks(
      hubGraphBucket({ start: "2026-08-24", end: "2026-08-30" }),
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06" }),
    ));
    const dates = Array.from(sheet().querySelectorAll(".hub-duration-days text:not(.hub-duration-tick)"));
    expect(dates.map((text) => [text.textContent, text.getAttribute("text-anchor")]))
      .toEqual([["Aug 24", "middle"], ["Aug 31", "end"]]);
  });

  it("the legend names both medians, the p90 band, and the two point states", async () => {
    await openTrend("days", weeks(hubGraphBucket()));
    expect(texts(sheet(), ".hub-duration-legend li")).toEqual([
      "Circulating age (median)",
      "Time to close (median)",
      "Shaded up to p90",
      "Hollow: week in progress",
      "Faded: fewer than 5 work orders",
    ]);
  });

  it("the details table prints median / p90, on time, (partial), and No sample", async () => {
    await openTrend("days", weeks(
      hubGraphBucket({ start: "2026-09-07", end: "2026-09-13", partial: true }),
      hubGraphBucket({ start: "2026-08-31", end: "2026-09-06", ...noAge,
        on_time_pct: null, on_time_count: 0, scheduled_closed_count: 0, unscheduled_closed_count: 2 }),
    ));
    expect(texts(sheet(), ".hub-duration-details thead th"))
      .toEqual(["Week", "Circulating age (median / p90)", "Time to close (median / p90)", "Closed within 4 days of schedule"]);
    const rows = Array.from(sheet().querySelectorAll(".hub-duration-details tbody tr"));
    expect(rows[0].querySelector("th").textContent).toBe("2026-09-07 – 2026-09-13 (partial)");
    expect(Array.from(rows[0].querySelectorAll("td")).map((td) => td.textContent))
      .toEqual(["4.50 / 9.00 days (n=6)", "2.25 / 2.25 days (n=1)", "100.0% on time (1 of 1 scheduled · 0 unscheduled)"]);
    expect(rows[1].querySelectorAll("td")[2].textContent).toBe("No scheduled closes (2 unscheduled)");
    expect(rows[1].querySelector("th").textContent).toBe("2026-08-31 – 2026-09-06");
    expect(rows[1].querySelector("td").textContent).toBe("No sample");
  });
});

describe("the on-time chart", () => {
  const weeks = (...buckets) => payloadFor({ duration: { range: { start: "2026-08-01", end: "2026-09-13" }, buckets } });

  it("runs 0–100% with no legend of its own, and its dot names both counts", async () => {
    await openTrend("ontime", weeks(hubGraphBucket({
      start: "2026-08-31", end: "2026-09-06",
      on_time_pct: 82, on_time_count: 41, scheduled_closed_count: 50, unscheduled_closed_count: 6,
    })));
    expect(sheet().querySelector("#hub-graph-sheet-title").textContent).toBe("Closed within 4 days of schedule");
    expect(texts(sheet(), ".hub-ontime-chart .hub-duration-tick")).toEqual(["0%", "25%", "50%", "75%", "100%"]);
    expect(sheet().querySelector(".hub-duration-point-ontime title").textContent)
      .toBe("Week of Aug 31–Sep 6: 82% on time (41 of 50 scheduled · 6 unscheduled)");
    expect(sheet().querySelector(".hub-duration-legend")).toBeNull();
    expect(sheet().querySelector(".hub-duration-days")).toBeNull();
    expect(sheet().querySelector(".hub-duration-details")).not.toBeNull();
  });

  it("fades a thin week and breaks on a week with no scheduled closes", async () => {
    const none = { on_time_pct: null, on_time_count: 0, scheduled_closed_count: 0, unscheduled_closed_count: 3 };
    await openTrend("ontime", weeks(
      hubGraphBucket({ start: "2026-08-10", end: "2026-08-16" }),
      hubGraphBucket({ start: "2026-08-17", end: "2026-08-23", ...none }),
      hubGraphBucket({ start: "2026-08-24", end: "2026-08-30" }),
    ));
    expect(sheet().querySelectorAll("polyline.hub-duration-ontime")).toHaveLength(2);
    const dots = sheet().querySelectorAll(".hub-duration-point-ontime");
    expect(dots).toHaveLength(2);
    expect(dots[0].classList.contains("hub-duration-point-low")).toBe(true);
  });

  it("no scheduled closes anywhere: the on-time copy, and no chart", async () => {
    await openTrend("ontime", weeks(hubGraphBucket({ on_time_pct: null, on_time_count: 0, scheduled_closed_count: 0, unscheduled_closed_count: 1 })));
    expect(sheet().querySelector(".hub-ontime-chart")).toBeNull();
    expect(texts(sheet(), ".hub-graph-empty")).toContain("No scheduled work orders closed in this range.");
  });
});

describe("the range pills", () => {
  it("reflect the payload's weeks", async () => {
    await openTrend("days", payloadFor({ weeks: 26 }));
    expect(Array.from(sheet().querySelectorAll("[data-graph-weeks]")).map((pill) => [pill.textContent, pill.getAttribute("aria-pressed")]))
      .toEqual([["12 weeks", "false"], ["26 weeks", "true"], ["52 weeks", "false"]]);
  });

  it("a pill refetches that many weeks as a number, and the pop-up stays open on the new range", async () => {
    await openTrend("ontime");
    const before = queries("/hub/graphs").length;
    await user().click(sheet().querySelector('[data-graph-weeks="52"]'));
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    expect(queries("/hub/graphs").at(-1)).toEqual({ weeks: "52" });
    expect(sheetOpen()).toBe(true);
    expect(sheet().querySelector("#hub-graph-sheet-title").textContent).toBe("Closed within 4 days of schedule");
  });

  it("the trend pop-up ignores pie controls it does not have", async () => {
    await openTrend("days");
    await user().click(sheet().querySelector(".hub-graph-panel .hint"));
    expect(sheetOpen()).toBe(true);
  });
});

describe("the Work Orders hand-off", () => {
  it("the red button opens Work Orders filtered to the community, before that page has loaded its options", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    clearRequests();
    await user().click(sheet().querySelector("[data-graph-go]"));
    expect(sheetOpen()).toBe(false);
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    // The dropdown had no "maple" option yet; the value sticks anyway.
    expect(byId("work-orders-community-filter").value).toBe("maple");
    expect(byId("work-orders-status-filter").value).toBe("");
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1).community).toBe("maple");
    expect(listQueries().at(-1).status).toBeUndefined();
    expect(listQueries().at(-1).mine).toBeUndefined();               // every other filter is cleared
  });

  it("carries community, service type, priority and the picked status together", async () => {
    await openGraphs();
    await openPie("Maple Ridge");
    await openPie("Plumbing", sheet());
    await openPie("Urgent", sheet());
    await user().click(sheet().querySelector('.hub-graph-legend-row[data-status="assigned"]'));
    clearRequests();
    await user().click(sheet().querySelector("[data-graph-go]"));
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1)).toMatchObject({ community: "maple", service_type: "Plumbing", priority: "Urgent", status: "assigned" });
    expect(byId("work-orders-service-filter").value).toBe("Plumbing");
    expect(byId("work-orders-priority-filter").value).toBe("Urgent");
    expect(byId("work-orders-status-filter").value).toBe("assigned");
  });

  it("the selections survive the page loading its real options, and the chip reads the community's name", async () => {
    await openGraphs();
    await openPie("Oak Park");
    await openPie("Plumbing", sheet());
    clearRequests();
    await user().click(sheet().querySelector("[data-graph-go]"));
    await vi.waitFor(() => expect(requests().some((r) => r.url.includes("/work-orders/filter-options"))).toBe(true));
    await vi.waitFor(() => expect(byId("work-orders-community-filter").options.length).toBe(3));
    expect(byId("work-orders-community-filter").value).toBe("oak");
    expect(byId("work-orders-service-filter").value).toBe("Plumbing");
    await vi.waitFor(() => expect(texts(byId("work-orders-filter-chips"), ".wo-filter-chip span:first-of-type"))
      .toEqual(expect.arrayContaining(["Service type: Plumbing", "Community: Oak Park"])));
    // The stand-in options did not trigger a second, unfiltered reload.
    expect(listQueries().every((query) => query.community === "oak")).toBe(true);
  });

  it("a pie grouped without a community sends none", async () => {
    await openGraphs();
    await user().click(panel().querySelector('[data-graph-front="priority"]'));
    await openPie("Normal");
    clearRequests();
    await user().click(sheet().querySelector("[data-graph-go]"));
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().at(-1).priority).toBe("Normal");
    expect(listQueries().at(-1).community).toBeUndefined();
    expect(byId("work-orders-community-filter").value).toBe("");
  });

  it("a repaint does not double the click", async () => {
    await openGraphs();
    await user().click(panel().querySelector('[data-graph-front="service_type"]'));
    await user().click(panel().querySelector('[data-graph-front="community"]'));
    await openPie("Maple Ridge");
    await user().click(sheet().querySelector("[data-graph-close]"));
    await openPie("Maple Ridge");
    clearRequests();
    await user().click(sheet().querySelector("[data-graph-go]"));
    await vi.waitFor(() => expect(listQueries()).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(50);
    expect(listQueries()).toHaveLength(1);
  });
});
