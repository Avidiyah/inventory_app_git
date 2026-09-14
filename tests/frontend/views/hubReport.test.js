// Characterization coverage for views/hubReport.js: the Admin weekly closed
// report -- the week picker, the status line, one section per service type,
// the row hand-off to Work Orders, and the skeleton / error / retry states
// userHub.js drives.
//
// Entered through the Report tab, which is what fires GET /hub/report. Week
// labels are computed in UTC from the payload's dates; stamps in Central.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { clearRequests, requestFor, requests } from "../helpers/requests.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";
import { filterOptions, hubReport, hubReportRow } from "../helpers/factories.js";

beforeEach(() => { stubScroll(); });     // a row hand-off swaps pages

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
  restoreBrowserStubs();
  window.history.replaceState({}, "", "/");
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const panel = () => el.panel("report");
const byId = (id) => document.getElementById(id);
const workOrdersPage = () => byId("work-orders-page");
const listQueries = () => requests()
  .filter((r) => r.method === "GET" && /^\/work-orders\/(\?|$)/.test(r.url))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

const sections = () => Array.from(panel().querySelectorAll(".hub-report-section"));
const section = (heading) => sections().find((s) => s.querySelector("h3").textContent === heading);
const bodyRows = (s) => Array.from(s.querySelectorAll("tbody tr"));
const cells = (tr) => Array.from(tr.children).map((td) => td.textContent.trim());
const headers = (s) => Array.from(s.querySelectorAll("thead th")).map((th) => th.textContent);
const text = (selector) => panel().querySelector(selector).textContent;

const atUtc = (iso) => new Date(`${iso}T00:00:00Z`);
const dayShort = (iso) => atUtc(iso).toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });
const dayShortYear = (iso) => atUtc(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const central = (instant) => new Date(instant).toLocaleString([], {
  month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago",
});

// The Work Orders page's reference loads, plus the courtesy lookup the
// archived-number search fires (answered "not found", so the restore prompt
// never opens).
const handOff = () => [
  http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
  http.get("/work-orders/lookup", () => HttpResponse.json({ found: false, archived: false, id: null })),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
];

async function openReport(report = hubReport(), role = "admin") {
  const mounted = await openHub({ role, report, handlers: handOff() });
  await user().click(el.tab("report"));
  await vi.waitFor(() => expect(panel().querySelector(".hub-report-header")).not.toBeNull());
  return mounted;
}

const completed = (overrides = {}) => hubReport({
  status: "completed", week_start: "2026-08-31", week_end: "2026-09-06",
  frozen_at: "2026-09-07T05:12:00Z", ...overrides,
});

describe("the header", () => {
  it("names the week, the in-progress status, the count, and the export link for that week", async () => {
    await openReport(hubReport({ count: 41, new_work_order_count: 3 }));
    expect(text(".hub-report-week")).toBe(`Week of ${dayShort("2026-09-07")} – ${dayShortYear("2026-09-13")}`);
    expect(text(".hub-report-status")).toBe(`In progress · generated ${central("2026-09-10T18:30:00Z")}`);
    expect(text(".hub-report-count")).toBe("41 closed work orders · 3 new work orders");
    expect(panel().querySelector(".hub-report-download").getAttribute("href")).toBe("/hub/report/export?week=2026-09-07");
  });

  it("a completed week says when it was frozen, and one row is singular", async () => {
    await openReport(completed({ count: 1, rows: [hubReportRow()] }));
    expect(text(".hub-report-status")).toBe(`Completed · frozen ${central("2026-09-07T05:12:00Z")}`);
    expect(text(".hub-report-count")).toBe("1 closed work order · 0 new work orders");
    expect(panel().querySelector(".hub-report-download").getAttribute("href")).toBe("/hub/report/export?week=2026-08-31");
  });
});

describe("the week picker", () => {
  it("the previous arrow fetches the Monday before; next is disabled on the week in progress", async () => {
    await openReport();
    expect(panel().querySelector(".hub-report-next").disabled).toBe(true);
    clearRequests();
    await user().click(panel().querySelector(".hub-report-prev"));
    await vi.waitFor(() => expect(requestFor("/hub/report?week=2026-08-31")).not.toBeNull());
  });

  it("on a completed week, next fetches the Monday after and This week fetches without a query", async () => {
    await openReport(completed());
    expect(panel().querySelector(".hub-report-next").disabled).toBe(false);
    clearRequests();
    await user().click(panel().querySelector(".hub-report-next"));
    await vi.waitFor(() => expect(requestFor("/hub/report?week=2026-09-07")).not.toBeNull());
    clearRequests();
    await user().click(panel().querySelector(".hub-report-this-week"));
    await vi.waitFor(() => expect(requestFor("/hub/report")).not.toBeNull());
    expect(requestFor("/hub/report").url).toBe("/hub/report");
  });

  it("re-entering the tab re-fetches the selected week, not the current one", async () => {
    await openReport();
    await user().click(panel().querySelector(".hub-report-prev"));
    await vi.waitFor(() => expect(requestFor("/hub/report?week=2026-08-31")).not.toBeNull());
    clearRequests();
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(requestFor("/hub/report?week=2026-08-31")).not.toBeNull());
  });
});

describe("the sections", () => {
  it("one per service type in payload order, with counts, headers, and raw cells", async () => {
    await openReport(hubReport({ count: 3, rows: [
      hubReportRow({ number: "7001" }),
      hubReportRow({ number: "7002", community: "academics", location: "Library", assigned_to: null, priority: null }),
      hubReportRow({ number: "7003", service_type_label: "Window Repair", service_type: "Window Repair" }),
    ] }));
    expect(sections().map((s) => s.querySelector("h3").textContent)).toEqual(["Maintenance (2)", "Window Repair (1)"]);
    const maintenance = section("Maintenance (2)");
    expect(headers(maintenance)).toEqual(["Community", "Number", "Assigned to", "Location", "Schedule date", "Priority", "Closed"]);
    const rows = bodyRows(maintenance);
    expect(cells(rows[0])).toEqual(["Scholars", "7001", "Belfor Dispatch", "Scholars 12-304", "7/21/2026", "Normal", central("2026-09-10T15:00:00Z")]);
    expect(cells(rows[1])).toEqual(["Academics", "7002", "—", "Library", "7/21/2026", "—", central("2026-09-10T15:00:00Z")]);
    expect(bodyRows(section("Window Repair (1)"))).toHaveLength(1);
  });

  it("an empty week shows its own copy and no sections", async () => {
    await openReport();
    expect(sections()).toHaveLength(0);
    expect(text(".hub-report-empty")).toBe("No work orders closed this week.");
  });
});

describe("the row hand-off", () => {
  it("a closed row routes to the exact-number search, which offers the restore prompt", async () => {
    await openReport(hubReport({ count: 1, rows: [hubReportRow({ number: "7001" })] }));
    clearRequests();
    const button = panel().querySelector(".hub-report-row-btn");
    expect(button.dataset.archived).toBe("1");
    await user().click(button);
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(byId("work-orders-search").value).toBe("7001");
    await vi.waitFor(() => expect(listQueries().some((q) => q.q === "7001")).toBe(true));
    await vi.waitFor(() => expect(requests().some((r) => r.url.startsWith("/work-orders/lookup"))).toBe(true));
  });
});

describe("loading and failure", () => {
  it("the skeleton shows while the first fetch is in flight", async () => {
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await openHub({ role: "admin", handlers: [
      http.get("/hub/report", async () => { await gate; return HttpResponse.json(hubReport()); }),
    ] });
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-report-loading")).not.toBeNull());
    expect(panel().querySelector(".hub-report-loading").textContent).toBe("Loading the report…");
    release();
    await vi.waitFor(() => expect(panel().querySelector(".hub-report-header")).not.toBeNull());
  });

  it("a failure offers Retry, and the retry renders the report", async () => {
    await openHub({ role: "admin", handlers: [
      http.get("/hub/report", () => HttpResponse.json({ detail: "Report is down" }, { status: 500 })),
    ] });
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-report-load-error")).not.toBeNull());
    expect(panel().querySelector(".hub-report-load-error .error").textContent).toBe("Report is down");
    server.use(http.get("/hub/report", () => HttpResponse.json(hubReport())));
    await user().click(panel().querySelector(".hub-report-retry"));
    await vi.waitFor(() => expect(panel().querySelector(".hub-report-header")).not.toBeNull());
    expect(panel().querySelector(".hub-report-load-error")).toBeNull();
  });
});
