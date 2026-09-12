// Characterization coverage for views/hubAdmin.js: the company-wide summary a
// techfm_oa+ viewer gets above the crew board -- the on-the-clock list, the
// two Time tiles, the six pipeline tiles and their hand-off to Work Orders,
// the exceptions list and the billing block.
//
// Through openHub throughout (one mount per test -- a second mount in a file
// gets the cached userHub.js instance and paints into a detached shell).
// `refreshAdmin()` mounts the summary on the initial load, so no direct call
// is needed; the pipeline's once-guard is driven by the socket refresh, which
// remounts on the same container node the way production does.

import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { clearRequests, requests } from "../helpers/requests.js";
import { connectHub, el, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions, hubAdmin, hubOnClockEntry } from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });    // the pipeline hand-off swaps pages

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
  window.history.replaceState({}, "", "/");
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const summary = () => el.adminMount();
const workOrdersPage = () => document.getElementById("work-orders-page");
const openAdmin = (admin = {}, role = "techfm_oa") => openHub({ role, admin: hubAdmin(admin), handlers: handOff() });

// Everything the Work Orders page fetches on entry; the fixture's own
// /work-orders/ handler answers the list itself.
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
];

const listQueries = () => requests()
  .filter((r) => r.method === "GET" && /^\/work-orders\/(\?|$)/.test(r.url))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

const onClockRows = () => Array.from(summary().querySelectorAll(".hub-onclock-row"));
const rowPairs = (root) => Array.from(root.querySelectorAll(".hub-exceptions-row"))
  .map((li) => Array.from(li.querySelectorAll("span")).map((s) => s.textContent));
const pipelineTiles = () => Array.from(summary().querySelectorAll(".hub-tile-pipeline-item")).map((tile) => ({
  status: tile.dataset.status,
  label: tile.querySelector(".hub-tile-label").textContent,
  value: tile.querySelector(".hub-tile-value").textContent,
}));

// The module claims its tile labels match the Work Orders page's own status
// <option>s verbatim. Read them off that page rather than retyping them, so a
// relabel there fails here instead of silently disagreeing in the UI.
const statusOptionLabels = () => {
  const html = readFileSync("backend/static/pages/work-orders.html", "utf8");
  const block = html.match(/<select id="work-orders-status-filter">([\s\S]*?)<\/select>/)[1];
  return Object.fromEntries(
    [...block.matchAll(/<option value="([^"]+)">([^<]+)<\/option>/g)].map((m) => [m[1], m[2]]));
};

describe("on the clock now", () => {
  it("empty: the hint, a zero badge and no list", async () => {
    await openAdmin();
    const section = summary().querySelector(".hub-onclock-section");
    expect(section.querySelector(".hub-tile-label").textContent).toContain("On the clock now");
    expect(section.querySelector(".hub-tile-label .tip-btn").dataset.tip).toBe("hub.clock-attention");
    expect(section.querySelector(".hub-tile-count").textContent).toBe("0");
    expect(section.querySelector(".hub-onclock-list")).toBeNull();
    expect(section.querySelector(".hint").textContent).toBe("Nobody is on the clock right now.");
  });

  it("one row per session: name, WO · community, elapsed; the community drops when null", async () => {
    await openAdmin({ on_the_clock: [
      hubOnClockEntry({ technician_name: "Crew One", elapsed_minutes: 95 }),
      hubOnClockEntry({ technician_name: "Crew Two", work_order_number: "7002", community: null, elapsed_minutes: 5 }),
    ] });
    expect(summary().querySelector(".hub-onclock-section .hub-tile-count").textContent).toBe("2");
    const rows = onClockRows();
    expect(rows.map((r) => r.querySelector(".hub-onclock-name").textContent)).toEqual(["Crew One", "Crew Two"]);
    expect(rows.map((r) => r.querySelector(".hub-onclock-subject").textContent))
      .toEqual(["WO 7001 · Scholars", "WO 7002"]);
    expect(rows[0].querySelector(".hub-onclock-elapsed").textContent).toBe("1 h 35 m");
    expect(rows[1].querySelector(".hub-onclock-elapsed").textContent).toBe("5 m");
    expect(rows[0].querySelector(".hub-attention-icon")).toBeNull();
  });

  it.each([
    ["long_session", "⚠ long session"],
    ["approaching_cap", "⚠ approaching cap"],
    // This module's FLAG_LABELS has no `assigned_idle` row, so the one flag
    // hubSupervisor.js renders as "idle" falls through to the snake-case
    // fallback here. Characterization -- open-work.md N-P6-CHARACTERIZED.
    ["assigned_idle", "⚠ assigned idle"],
    ["odd_flag", "⚠ odd flag"],
  ])("a %s flag renders as %s beside the elapsed time", async (flag, expected) => {
    await openAdmin({ on_the_clock: [hubOnClockEntry({ flag, elapsed_minutes: 95 })] });
    const elapsed = onClockRows()[0].querySelector(".hub-onclock-elapsed");
    expect(elapsed.querySelector(".hub-attention-icon").textContent).toBe(expected);
    expect(elapsed.textContent).toBe(`1 h 35 m ${expected}`);
  });
});

describe("time tiles", () => {
  it("Supervisor Time and Technician Time through formatHm", async () => {
    await openAdmin({ supervisor_minutes_today: 185, technician_minutes_today: 0 });
    const tiles = Array.from(summary().querySelector(".hub-tile-grid").querySelectorAll(".hub-tile"));
    expect(tiles.map((t) => t.querySelector(".hub-tile-label").textContent))
      .toEqual(["Supervisor Time", "Technician Time"]);
    expect(tiles.map((t) => t.querySelector(".hub-tile-value").textContent)).toEqual(["3 h 5 m", "0 m"]);
  });
});

describe("the pipeline", () => {
  const pipeline = (overrides = {}) => ({
    created: 1, assigned: 2, in_progress: 3, ready_to_complete: 0, completed: 4, review: 5, ...overrides,
  });

  it("six tiles in lifecycle order, labelled off the Work Orders page's own options", async () => {
    await openAdmin({ pipeline: pipeline() });
    const labels = statusOptionLabels();
    expect(pipelineTiles()).toEqual([
      { status: "created", label: labels.created, value: "1" },
      { status: "assigned", label: labels.assigned, value: "2" },
      { status: "in_progress", label: labels.in_progress, value: "3" },
      { status: "ready_to_complete", label: labels.ready_to_complete, value: "0" },
      { status: "completed", label: labels.completed, value: "4" },
      { status: "review", label: labels.review, value: "5" },
    ]);
    // The page offers a seventh status the pipeline has no tile for, so an
    // On-Hold work order is in no roll-up here. Characterization --
    // open-work.md N-P6-CHARACTERIZED.
    expect(labels.on_hold).toBe("On-Hold");
    expect(pipelineTiles().map((t) => t.status)).not.toContain("on_hold");
  });

  it("Ready to Complete alone carries the attention flag, and only when non-zero", async () => {
    await openAdmin({ pipeline: pipeline({ ready_to_complete: 2 }) });
    const flagged = pipelineTiles().filter((t) => t.label.includes("⚠"));
    expect(flagged.map((t) => t.status)).toEqual(["ready_to_complete"]);
  });

  it("no flag anywhere when nothing is ready to complete", async () => {
    await openAdmin({ pipeline: pipeline({ ready_to_complete: 0 }) });
    expect(summary().querySelector(".hub-tile-pipeline-item .hub-attention-icon")).toBeNull();
  });

  it("a tile click sets the page's status filter, swaps pages and loads that status", async () => {
    await openAdmin({ pipeline: pipeline({ review: 5 }) });
    clearRequests();
    await user().click(summary().querySelector('[data-status="review"]'));
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(document.getElementById("work-orders-status-filter").value).toBe("review");
    await vi.waitFor(() => expect(listQueries().length).toBeGreaterThan(0));
    expect(listQueries().every((q) => q.status === "review")).toBe(true);
  });

  it("pipelineBound: three mounts on one container still handle a click once", async () => {
    await openAdmin({ pipeline: pipeline() });
    const { emit } = await connectHub();
    emit("labor.session.changed");
    await vi.waitFor(() => expect(queries("/hub/admin")).toHaveLength(2));
    emit("labor.session.changed");
    await vi.waitFor(() => expect(queries("/hub/admin")).toHaveLength(3));
    clearRequests();
    await user().click(summary().querySelector('[data-status="completed"]'));
    await vi.waitFor(() => expect(listQueries()).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(50);
    expect(listQueries()).toHaveLength(1);
  });
});

describe("exceptions", () => {
  it("five rows; the first three read 'N open' and the last two are bare counts", async () => {
    await openAdmin({ exceptions: {
      inventory_recounts: 2, missing_item_price: 0, catalogue_requests: 5,
      admin_review_queue: 3, stale_work_orders: 4,
    } });
    const section = summary().querySelector(".hub-exceptions");
    expect(section.querySelector(".hub-tile-label .tip-btn").dataset.tip).toBe("hub.exceptions");
    expect(rowPairs(section)).toEqual([
      ["Inventory recounts", "2 open"],
      ["Missing price / link", "0 open"],
      ["Catalogue requests", "5 open"],
      ["Admin review queue", "3"],
      ["Stale > 3 days", "4"],
    ]);
  });
});

describe("billing · this week", () => {
  const billing = (overrides = {}) => ({
    materials_total: "1234.5", labor_total: "300", total: "1534.5",
    avg_days_to_complete: 3.4, completed_per_day: [0, 4, 8], legacy_live_count: null, ...overrides,
  });

  it("the three money rows, the total's own class, the avg and the sparkline", async () => {
    await openAdmin({ billing: billing() });
    const section = summary().querySelector(".hub-billing");
    const pairs = rowPairs(section);
    expect(pairs).toHaveLength(5);                       // no legacy row
    expect(pairs[0][0]).toBe("Materials");
    expect(pairs[0][1]).toMatch(/1,234\.50/);
    expect(pairs[1][0]).toBe("Labor");
    expect(pairs[1][1]).toMatch(/300\.00/);
    expect(pairs[2][0]).toBe("Total");
    expect(section.querySelector(".hub-billing-total span:last-child").textContent).toMatch(/1,534\.50/);
    expect(pairs[3]).toEqual(["Avg time to complete", "3.4 d"]);
    // max -> the top glyph, zero -> the bottom one.
    expect(section.querySelector(".hub-billing-sparkline").textContent).toBe("▁▄█");
  });

  it("an unknown average reads an em dash; a flat week is all floor glyphs", async () => {
    await openAdmin({ billing: billing({ avg_days_to_complete: null, completed_per_day: [0, 0, 0] }) });
    const section = summary().querySelector(".hub-billing");
    expect(rowPairs(section)[3]).toEqual(["Avg time to complete", "—"]);
    expect(section.querySelector(".hub-billing-sparkline").textContent).toBe("▁▁▁");
  });

  it("no samples: the sparkline span is empty", async () => {
    await openAdmin({ billing: billing({ completed_per_day: [] }) });
    expect(summary().querySelector(".hub-billing-sparkline").textContent).toBe("");
  });

  it("a legacy count adds a sixth row; null keeps it off", async () => {
    await openAdmin({ billing: billing({ legacy_live_count: 7 }) });
    expect(rowPairs(summary().querySelector(".hub-billing")).at(-1))
      .toEqual(["Legacy work orders live", "7"]);
  });
});
