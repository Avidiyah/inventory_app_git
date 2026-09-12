// Characterization coverage for views/hubReport.js: the Admin daily report's
// three rendered sections (over the payload's five), its row cells and
// badges, the two row hand-offs to Work Orders, and the skeleton / error /
// retry states userHub.js drives.
//
// Entered through the Report tab, which is what fires GET /hub/report. Every
// stamp is computed here with the module's own Intl options -- the day and
// week labels in UTC, the row and "Generated" stamps in Central.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { clearRequests, requests } from "../helpers/requests.js";
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

const section = (heading) => Array.from(panel().querySelectorAll(".hub-report-section"))
  .find((s) => s.querySelector("h3").textContent === heading);
const countsIn = (heading) => Array.from(section(heading).querySelectorAll(".hub-report-count"))
  .map((c) => [c.querySelector(".hub-report-count-label").textContent, c.querySelector(".hub-report-count-value").textContent]);
const bodyRows = (heading) => Array.from(section(heading).querySelectorAll("tbody tr"));
const cells = (tr) => Array.from(tr.children).map((td) => td.textContent.trim());
const headers = (heading) => Array.from(section(heading).querySelectorAll("thead th")).map((th) => th.textContent);

const atUtc = (iso) => new Date(`${iso}T00:00:00Z`);
const dayLong = (iso) => atUtc(iso).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const dayShort = (iso) => atUtc(iso).toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });
const central = (instant) => new Date(instant).toLocaleString([], {
  month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago",
});

// The Work Orders page's reference loads, plus the courtesy lookup the
// archived-number search fires (answered "not found", so the restore prompt --
// P2's own territory -- never opens).
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

describe("the header", () => {
  it("names the week, the day, the generated stamp and the export link", async () => {
    await openReport();
    expect(panel().querySelector(".hub-report-week").textContent)
      .toBe(`Week of ${dayShort("2026-09-07")} – ${dayShort("2026-09-13")} · week to date`);
    expect(panel().querySelector(".hub-report-day").textContent).toBe(dayLong("2026-09-10"));
    expect(panel().querySelector(".hub-report-generated").textContent)
      .toBe(`Generated ${central("2026-09-10T18:30:00Z")}`);
    expect(panel().querySelector(".hub-report-download").getAttribute("href")).toBe("/hub/report/export");
  });
});

describe("Closed", () => {
  it("empty: zero counts, the empty copy, and the live-view footnote", async () => {
    await openReport();
    expect(countsIn("Closed")).toEqual([["Today", "0"], ["This week", "0"]]);
    expect(section("Closed").querySelector(".hub-report-empty").textContent).toBe("Nothing closed yet today.");
    expect(section("Closed").querySelector(".hub-report-footnote").textContent)
      .toContain("A live view, not an archival record");
  });

  it("counts come from the payload, rows from the week, and Today marks only today's numbers", async () => {
    const today = hubReportRow({ number: "7001", archived_at: "2026-09-10T16:05:00Z" });
    const earlier = hubReportRow({ number: "7002", archived_at: "2026-09-08T09:30:00Z", legacy: true });
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      closed_today: { count: 1, rows: [today] },
      closed_week: { count: 9, rows: [today, earlier] },      // count is not a row tally
    } }));
    expect(countsIn("Closed")).toEqual([["Today", "1"], ["This week", "9"]]);
    expect(headers("Closed").at(-1)).toBe("Closed");
    const rows = bodyRows("Closed");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".hub-report-badge.is-today").textContent).toBe("Today");
    expect(rows[0].querySelector(".is-legacy")).toBeNull();
    expect(cells(rows[0]).at(-1)).toBe(central("2026-09-10T16:05:00Z"));
    expect(rows[1].querySelector(".is-today")).toBeNull();
    expect(rows[1].querySelector(".hub-report-badge.is-legacy").textContent).toBe("Legacy");
    expect(cells(rows[1]).at(-1)).toBe(central("2026-09-08T09:30:00Z"));
  });
});

describe("a row's cells", () => {
  const withRow = (overrides) => hubReport({ sections: {
    ...hubReport().sections,
    closed_week: { count: 1, rows: [hubReportRow(overrides)] },
  } });

  it("place is community · building-unit · location, in that order", async () => {
    await openReport(withRow({ community: "Scholars", building_number: "3", unit_number: "12", location: "Roof" }));
    expect(cells(bodyRows("Closed")[0])[2]).toBe("Scholars · 3-12 · Roof");
  });

  it("every missing field falls back to an em dash", async () => {
    await openReport(withRow({
      community: null, building_number: null, unit_number: null, location: null,
      service_type: null, supervisor_name: null, technician_names: [], archived_at: null,
    }));
    const row = cells(bodyRows("Closed")[0]);
    expect(row.slice(2)).toEqual(["—", "—", "—", "—", "—"]);
  });

  it("technician names are joined, and a known status is relabelled", async () => {
    await openReport(withRow({ status: "in_progress", technician_names: ["Crew One", "Crew Two"] }));
    const row = cells(bodyRows("Closed")[0]);
    expect(row[1]).toBe("In progress");
    expect(row[5]).toBe("Crew One, Crew Two");
  });

  it("an unmapped status renders raw", async () => {
    await openReport(withRow({ status: "some_new_status" }));
    expect(cells(bodyRows("Closed")[0])[1]).toBe("some_new_status");
  });
});

describe("Closing", () => {
  it("the pipeline count, the by_status breakdown in lifecycle order, skipping zeros", async () => {
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      closing: {
        count: 12,
        by_status: { review: 2, ready_to_complete: 7, completed: 0 },
        truncated: false,
        rows: [hubReportRow({ status: "ready_to_complete", created_at: "2026-09-09T12:00:00Z" })],
      },
    } }));
    expect(countsIn("Closing")).toEqual([["In the pipeline", "12"]]);
    expect(section("Closing").querySelector(".hub-report-breakdown").textContent)
      .toBe("ready to complete 7 · review 2");
    expect(headers("Closing").at(-1)).toBe("Created");
    expect(cells(bodyRows("Closing")[0]).at(-1)).toBe(central("2026-09-09T12:00:00Z"));
    expect(section("Closing").querySelector(".hub-report-truncated")).toBeNull();
  });

  it("a capped list says so, and the counts stay authoritative", async () => {
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      closing: { count: 99, by_status: {}, truncated: true, rows: [hubReportRow()] },
    } }));
    expect(section("Closing").querySelector(".hub-report-truncated").textContent)
      .toContain("Showing the first rows only");
    expect(countsIn("Closing")[0]).toEqual(["In the pipeline", "99"]);
    expect(section("Closing").querySelector(".hub-report-breakdown")).toBeNull();
  });

  it("nothing closing: its own empty copy", async () => {
    await openReport();
    expect(section("Closing").querySelector(".hub-report-empty").textContent)
      .toBe("Nothing is sitting in a closing status.");
  });
});

describe("New", () => {
  it("counts, the Created column and the Today badge", async () => {
    const fresh = hubReportRow({ number: "7100", created_at: "2026-09-10T08:15:00Z" });
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      new_today: { count: 1, rows: [fresh] },
      new_week: { count: 4, rows: [fresh] },
    } }));
    expect(countsIn("New")).toEqual([["Today", "1"], ["This week", "4"]]);
    expect(headers("New").at(-1)).toBe("Created");
    expect(bodyRows("New")[0].querySelector(".is-today").textContent).toBe("Today");
    expect(cells(bodyRows("New")[0]).at(-1)).toBe(central("2026-09-10T08:15:00Z"));
  });

  it("nothing new: its own empty copy", async () => {
    await openReport();
    expect(section("New").querySelector(".hub-report-empty").textContent)
      .toBe("Nothing new has arrived today.");
  });
});

describe("the row hand-offs", () => {
  it("a live row focuses its card and swaps to Work Orders", async () => {
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      new_week: { count: 1, rows: [hubReportRow({ number: "7100", archived_at: null })] },
    } }));
    clearRequests();
    const button = section("New").querySelector(".hub-report-row-btn");
    expect(button.dataset.archived).toBe("");
    await user().click(button);
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    await vi.waitFor(() => expect(listQueries().some((q) => q.q === "7100")).toBe(true));
  });

  it("an archived row routes to the exact-number search instead", async () => {
    await openReport(hubReport({ sections: {
      ...hubReport().sections,
      closed_week: { count: 1, rows: [hubReportRow({ number: "7001", archived_at: "2026-09-10T16:05:00Z" })] },
    } }));
    clearRequests();
    const button = section("Closed").querySelector(".hub-report-row-btn");
    expect(button.dataset.archived).toBe("1");
    await user().click(button);
    await vi.waitFor(() => expect(workOrdersPage().classList.contains("active")).toBe(true));
    expect(byId("work-orders-search").value).toBe("7001");
    await vi.waitFor(() => expect(listQueries().some((q) => q.q === "7001")).toBe(true));
    // The courtesy lookup that decides whether to offer a restore.
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
    expect(panel().querySelector(".hub-report-loading").textContent).toBe("Loading the daily report…");
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
