// Characterization of views/smr.js -- the SMR27 audit tiles page (spec
// docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md D1/D7/D8):
// the count bar, the four filters, the Owner-only export, the untouched
// dimming and the tile hand-off to the Work Orders editor.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";
import { restoreBrowserStubs, stubObjectUrl, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions } from "../helpers/factories.js";

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
    ...overrides,
  };
}

function page(overrides = {}) {
  return {
    imported_at: "2026-10-23T14:14:00Z",
    counts: { orders: 3, edited: 1, untouched: 2, archived: 1 },
    delta: { labor_total: "58.40", materials_total: "18.40", total: "76.80" },
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

  it("hides the export for an Admin and shows it for an Owner, who downloads the workbook", async () => {
    await openSmr("admin");
    expect(byId("smr-export-btn").hidden).toBe(true);

    document.body.innerHTML = "";
    const { requestsFor } = await openSmr("owner");
    expect(byId("smr-export-btn").hidden).toBe(false);
    server.use(http.get("/work-orders/smr/export.xlsx", () => new HttpResponse(new Blob(["x"]), {
      headers: { "Content-Disposition": 'attachment; filename="smr27-audit-export.xlsx"' },
    })));
    const { createObjectURL } = stubObjectUrl();
    byId("smr-export-btn").click();
    await vi.waitFor(() => expect(requestsFor("/work-orders/smr/export.xlsx")).toHaveLength(1));
    await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
  });

  it("opens the Work Orders editor for a clicked tile", async () => {
    const { nav } = await openSmr();
    tiles()[0].click();
    await vi.waitFor(() => expect(nav.getActivePage()).toBe("work-orders"));
    expect(byId("work-orders-search").value).toBe("23281563");
  });

  it("shows the empty copy when nothing has been imported", async () => {
    server.use(http.get("/work-orders/smr", () => HttpResponse.json(page({ tiles: [], counts: { orders: 0, edited: 0, untouched: 0, archived: 0 } }))));
    await bootApp({ role: "admin", page: "smr" });
    await vi.waitFor(() => expect(byId("smr-tiles").textContent).toContain("NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS."));
  });
});
