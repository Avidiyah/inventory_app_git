// Characterization of views/smr.js -- the SMR27 audit tiles page (spec
// docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md D1/D7/D8):
// the count bar, the four filters, the Owner-only export, the untouched
// dimming and the tile hand-off to the Work Orders editor.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";
import { restoreBrowserStubs, stubObjectUrl, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions, workOrderDetail } from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });
afterEach(() => { restoreBrowserStubs(); });

const byId = (id) => document.getElementById(id);
const tiles = () => Array.from(document.querySelectorAll("#smr-tiles .smr-tile"));

function totals(overrides = {}) {
  return { materials_total: "0.00", real_minutes: 0, skilled_minutes: 0, labor_total: "0.00", total: "0.00", ...overrides };
}

function tile(overrides = {}) {
  return {
    id: "11111111-1111-1111-1111-111111111111", number: "23281563",
    building_number: "Young Hall", unit_number: "108A", location: "Young Hall:1st Floor,108A", vendor_assignee: "Chris Coburn",
    status: "completed", archived_at: null, edited: false,
    before: totals(), after: totals(), delta: totals(), after_line_count: 0,
    target: null,
    ...overrides,
  };
}

function page(overrides = {}) {
  return {
    imported_at: "2026-10-23T14:14:00Z",
    counts: { orders: 3, edited: 1, untouched: 2, archived: 1, matched: 0, short: 0, no_target: 3 },
    delta: { labor_total: "58.40", materials_total: "18.40", total: "76.80" },
    remaining: { hours: "0", materials_total: "0.00" },
    matched: 3,
    filter_options: {
      priorities: ["Emergency", "Normal"],
      supervisors: [{ id: "s1", name: "Chris Coburn" }],
      technicians: [{ id: "t1", name: "Hayden Hurst" }],
      communities: [{ value: "young_hall", label: "Young Hall" }, { value: "scholars", label: "Scholars Inn" }],
    },
    tiles: [
      tile({ edited: true, after: totals({ skilled_minutes: 30, labor_total: "31.25", total: "49.65" }), delta: totals({ skilled_minutes: 30, labor_total: "31.25", materials_total: "18.40", total: "49.65" }), after_line_count: 2 }),
      tile({ id: "22222222-2222-2222-2222-222222222222", number: "23282567", archived_at: "2026-10-22T10:00:00Z" }),
      tile({ id: "33333333-3333-3333-3333-333333333333", number: "23296828", unit_number: "208W", building_number: "Sanford" }),
    ],
    ...overrides,
  };
}

async function openSmr(role = "admin", payload = page()) {
  server.use(
    http.get("/work-orders/smr", () => HttpResponse.json(payload)),
    http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
    http.get("/work-orders/lookup", () => HttpResponse.json({ found: false, archived: false, id: null })),
  );
  const app = await bootApp({ role, page: "smr" });
  await vi.waitFor(() => expect(tiles().length).toBeGreaterThan(0));
  return app;
}

describe("the SMR page", () => {
  it("renders the bar counts and deltas from the payload", async () => {
    await openSmr();
    expect(byId("smr-heading").textContent).toContain("SMR27");
    const bar = byId("smr-bar").textContent;
    expect(bar).toContain("3 ORDERS");
    expect(bar).toContain("1 EDITED");
    expect(bar).toContain("2 UNTOUCHED");
    expect(bar).toContain("+$58.40");
    expect(bar).toContain("+$18.40");
    expect(bar).toContain("+$76.80");
  });

  it("renders one tile per order, untouched ones dimmed and archived ones marked", async () => {
    await openSmr();
    expect(tiles().map((t) => t.dataset.number)).toEqual(["23281563", "23282567", "23296828"]);
    const [edited, archived, untouched] = tiles();
    expect(edited.classList.contains("smr-tile--untouched")).toBe(false);
    expect(edited.textContent).toContain("+$49.65");
    expect(edited.textContent).toContain("EDITED");
    expect(archived.classList.contains("smr-tile--archived")).toBe(true);
    expect(archived.textContent).toContain("ARCHIVED");
    expect(untouched.classList.contains("smr-tile--untouched")).toBe(true);
    expect(untouched.textContent).toContain("UNTOUCHED");
  });

  it("filters tiles by edited, untouched and archived", async () => {
    await openSmr();
    byId("smr-filter-edited").click();
    expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["23281563"]);
    byId("smr-filter-untouched").click();
    expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["23282567", "23296828"]);
    byId("smr-filter-archived").click();
    expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["23282567"]);
    byId("smr-filter-all").click();
    expect(tiles().filter((t) => !t.hidden)).toHaveLength(3);
  });

  // The client's target (spec 2026-10-23-smr-target-match): bar counts, the
  // remaining totals, a line per tile, and the Short / Matched filters.
  function target(overrides = {}) {
    return {
      hours: "2", current_hours: "0", gap_hours: "-2", remaining_hours: "2", matched: false,
      labor_total: "125.00", total: "192.16", materials_total: "67.16", current_materials_total: "0.00",
      gap_materials_total: "-67.16", remaining_materials_total: "67.16",
      ...overrides,
    };
  }

  it("bar shows match counts and remaining; Short and Matched filters select by target", async () => {
    await openSmr("admin", page({
      counts: { orders: 3, edited: 1, untouched: 2, archived: 0, matched: 1, short: 1, no_target: 1 },
      remaining: { hours: "2.5", materials_total: "134.32" },
      tiles: [
        tile({ number: "A", target: target() }),
        tile({ id: "22222222-2222-2222-2222-222222222222", number: "B", edited: true,
          target: target({ current_hours: "2", gap_hours: "0", remaining_hours: "0", matched: true,
            current_materials_total: "70.00", gap_materials_total: "2.84", remaining_materials_total: "0.00" }) }),
        tile({ id: "33333333-3333-3333-3333-333333333333", number: "C" }),
      ],
    }));
    const bar = byId("smr-bar").textContent;
    expect(bar).toContain("1 MATCHED");
    expect(bar).toContain("1 SHORT");
    expect(bar).toContain("1 NO TARGET");
    expect(bar).toContain("REMAINING 2.5 H");
    expect(bar).toContain("REMAINING $134.32");
    expect(tiles()[0].querySelector(".smr-tile-target").textContent).toBe("2.0 H · $67.16 TO GO");
    expect(tiles()[1].querySelector(".smr-tile-target").textContent).toBe("MATCHED");
    expect(tiles()[1].classList.contains("smr-tile--matched")).toBe(true);
    expect(tiles()[2].querySelector(".smr-tile-target").textContent).toBe("NO TARGET");
    byId("smr-filter-short").click();
    expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["A"]);
    byId("smr-filter-matched").click();
    expect(tiles().filter((t) => !t.hidden).map((t) => t.dataset.number)).toEqual(["B"]);
    expect(Array.from(document.querySelectorAll(".smr-controls .smr-btn[data-filter]")).map((b) => b.dataset.filter))
      .toEqual(["untouched", "short", "short_checked", "checked", "edited", "archived", "matched", "all"]);
  });

  it("paper check: badge, bar counts, and the Checked-still-short / Paper checked filters (Short unchanged)", async () => {
    const check = { checked_at: "2026-10-27T14:14:00Z", checked_by_name: "Pat Keyer" };
    const matchedTarget = target({ current_hours: "2", gap_hours: "0", remaining_hours: "0", matched: true,
      current_materials_total: "70.00", gap_materials_total: "2.84", remaining_materials_total: "0.00" });
    await openSmr("admin", page({
      counts: { orders: 4, edited: 0, untouched: 4, archived: 0, matched: 1, short: 2, no_target: 1, paper_checked: 2, short_checked: 1 },
      tiles: [
        tile({ number: "SC", target: target(), paper_check: check }),
        tile({ id: "22222222-2222-2222-2222-222222222222", number: "MC", target: matchedTarget, paper_check: check }),
        tile({ id: "33333333-3333-3333-3333-333333333333", number: "SO", target: target() }),
        tile({ id: "44444444-4444-4444-4444-444444444444", number: "NT" }),
      ],
    }));
    const shown = () => tiles().filter((t) => !t.hidden).map((t) => t.dataset.number);
    const bar = byId("smr-bar").textContent;
    expect(bar).toContain("2 PAPER CHECKED");
    expect(bar).toContain("1 CHECKED, STILL SHORT");
    expect(tiles().map((t) => Boolean(t.querySelector(".smr-tile-paper")))).toEqual([true, true, false, false]);
    expect(tiles()[0].classList.contains("smr-tile--checked")).toBe(true);
    byId("smr-filter-checked").click();
    expect(shown()).toEqual(["SC", "MC"]);
    byId("smr-filter-short-checked").click();
    expect(shown()).toEqual(["SC"]);
    byId("smr-filter-short").click();
    expect(shown()).toEqual(["SC", "SO"]);
  });

  it("hides the export for an Admin and shows it for an Owner, who downloads the workbook", async () => {
    await openSmr("admin");
    expect(byId("smr-export-btn").hidden).toBe(true);

    document.body.innerHTML = "";
    const { requestsFor } = await openSmr("owner");
    expect(byId("smr-export-btn").hidden).toBe(false);
    // A string body, as the other download tests use: CI's Node rejects a
    // Blob body inside MSW's Response ("object.stream is not a function").
    server.use(http.get("/work-orders/smr/export.xlsx", () => new HttpResponse("x", {
      headers: { "Content-Disposition": 'attachment; filename="smr27-audit-export.xlsx"' },
    })));
    const { createObjectURL } = stubObjectUrl();
    byId("smr-export-btn").click();
    await vi.waitFor(() => expect(requestsFor("/work-orders/smr/export.xlsx")).toHaveLength(1));
    await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
  });

  it("opens the Work Orders card page for a clicked tile by id, not through the live list", async () => {
    // The live list excludes SMR rows (spec D1), so a number search would
    // find nothing; the card page must be fetched by id.
    const { nav, requestsFor } = await openSmr();
    const detail = workOrderDetail({ id: "11111111-1111-1111-1111-111111111111", number: "23281563", smr: true });
    server.use(
      http.get("/work-orders/11111111-1111-1111-1111-111111111111", () => HttpResponse.json(detail)),
      http.get("/work-orders/11111111-1111-1111-1111-111111111111/requests", () => HttpResponse.json([])),
    );
    tiles()[0].click();
    await vi.waitFor(() => expect(nav.getActivePage()).toBe("work-orders"));
    await vi.waitFor(() => expect(requestsFor("/work-orders/11111111-1111-1111-1111-111111111111")).toHaveLength(1));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/workorder_card/23281563"));
    expect(document.querySelector("#work-orders-list details.wo-card").dataset.number).toBe("23281563");
    expect(requestsFor("/work-orders/?q=23281563")).toHaveLength(0);
    window.history.replaceState({}, "", "/");
  });

  it("shows the empty copy when nothing has been imported", async () => {
    server.use(http.get("/work-orders/smr", () => HttpResponse.json(page({ tiles: [], counts: { orders: 0, edited: 0, untouched: 0, archived: 0 } }))));
    await bootApp({ role: "admin", page: "smr" });
    await vi.waitFor(() => expect(byId("smr-tiles").textContent).toContain("NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS."));
  });

  // --- search and filters: the Work Orders row minus service type ----------

  it("fills the dropdowns from filter_options and shows the result count", async () => {
    await openSmr();
    const text = (id) => Array.from(byId(id).options).map((o) => o.textContent);
    expect(text("smr-priority-filter")).toEqual(["All priorities", "Emergency", "Normal"]);
    expect(text("smr-supervisor-filter")).toEqual(["All Team Leads", "Chris Coburn"]);
    expect(text("smr-technician-filter")).toEqual(["All technicians", "Hayden Hurst"]);
    expect(text("smr-community-filter")).toEqual(["All communities", "Young Hall", "Scholars Inn"]);
    expect(byId("smr-result-count").textContent).toBe("3 OF 3 ORDERS");
    expect(byId("smr-service-filter")).toBeNull();
  });

  it("sends every control as the Work Orders list's query params on Search", async () => {
    const { requests, clearRequests } = await openSmr();
    byId("smr-status-filter").value = "completed";
    byId("smr-priority-filter").value = "Emergency";
    byId("smr-supervisor-filter").value = "s1";
    byId("smr-technician-filter").value = "t1";
    byId("smr-community-filter").value = "scholars";
    byId("smr-date-filter").value = "2026-07-20";
    byId("smr-search").value = " 2328 ";
    byId("smr-location-search").value = "Young";
    byId("smr-task-search").value = "blinds";
    clearRequests();
    byId("smr-search-btn").click();
    const smrCalls = () => requests().filter((r) => r.url.startsWith("/work-orders/smr?"));
    await vi.waitFor(() => expect(smrCalls()).toHaveLength(1));
    const url = new URL(smrCalls()[0].url, "http://t");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: "completed", priority: "Emergency", supervisor_id: "s1", assigned_to_id: "t1",
      community: "scholars", scheduled_date: "2026-07-20", q: "2328", location_q: "Young",
      task_q: "blinds", sort: "scheduled_desc",
    });
  });

  it("reloads on a dropdown change and on Enter in a search box", async () => {
    const { requests, clearRequests } = await openSmr();
    const withQuery = (fragment) => requests().filter((r) => r.url.includes(fragment));
    clearRequests();
    byId("smr-community-filter").value = "young_hall";
    byId("smr-community-filter").dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(withQuery("community=young_hall")).toHaveLength(1));
    byId("smr-task-search").value = "drawer";
    byId("smr-task-search").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await vi.waitFor(() => expect(withQuery("task_q=drawer")).toHaveLength(1));
  });

  it("Clear filters empties every control and reloads unfiltered", async () => {
    const { requests, requestsFor, clearRequests } = await openSmr();
    byId("smr-status-filter").value = "completed";
    byId("smr-search").value = "2328";
    byId("smr-date-filter").value = "2026-07-20";
    clearRequests();
    byId("smr-clear-filters").click();
    await vi.waitFor(() => expect(requestsFor("/work-orders/smr")).toHaveLength(1));
    expect(requests()[0].url).toBe("/work-orders/smr?sort=scheduled_desc");
    expect(byId("smr-status-filter").value).toBe("");
    expect(byId("smr-search").value).toBe("");
    expect(byId("smr-date-filter").value).toBe("");
  });

  it("the sort toggle flips the sort param and remembers it", async () => {
    const { requests, clearRequests } = await openSmr();
    clearRequests();
    byId("smr-sort").querySelector("[data-sort=\"scheduled_asc\"]").click();
    await vi.waitFor(() => expect(requests().filter((r) => r.url.includes("sort=scheduled_asc"))).toHaveLength(1));
    expect(byId("smr-sort").querySelector("[data-sort=\"scheduled_asc\"]").getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("smr.sort")).toBe("scheduled_asc");
  });

  it("the result count reflects matched over the whole population", async () => {
    await openSmr("admin", page({ matched: 1, tiles: [tile()] }));
    expect(byId("smr-result-count").textContent).toBe("1 OF 3 ORDERS");
  });
});
