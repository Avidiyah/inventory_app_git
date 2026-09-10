import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";

let api;
let calls;

beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
  server.use(http.all("*", () => HttpResponse.json({})));
  calls = installFetchSpy();
});

afterEach(() => restoreFetchSpy());

const lastUrl = () => calls.at(-1).url;

describe("query parameters are omitted, not nulled", () => {
  it("apiListItems sends no query when none is given", async () => {
    await api.apiListItems();
    expect(lastUrl()).toBe("/items/");
  });

  it("apiListItems sends an empty q when the query is the empty string", async () => {
    // Deliberate: `query = ""` is `!== null`, so the parameter IS sent. A
    // cleared search box asking for everything and a blank filter are the
    // same request today.
    await api.apiListItems({ query: "" });
    expect(lastUrl()).toBe("/items/?q=");
  });

  it("apiListWorkOrders drops every falsy filter", async () => {
    await api.apiListWorkOrders({ status: null, community: "", q: null, mine: false, limit: null });
    expect(lastUrl()).toBe("/work-orders/");
  });

  it("apiListWorkOrders sends mine as the string true and keeps limit 0", async () => {
    await api.apiListWorkOrders({ mine: true, limit: 0 });
    // `limit != null` -- a 0 limit survives where `community: ""` does not.
    expect(lastUrl()).toBe("/work-orders/?mine=true&limit=0");
  });

  it("apiListWorkOrders encodes a query containing a space and an ampersand", async () => {
    await api.apiListWorkOrders({ q: "unit 4 & 5" });
    expect(lastUrl()).toBe("/work-orders/?q=unit+4+%26+5");
  });

  it("apiListTransactions always sends page and page_size, filters only when truthy", async () => {
    await api.apiListTransactions({ page: 2, pageSize: 10, itemId: null, userId: 0, workOrder: "WO-1" });
    expect(lastUrl()).toBe("/transactions/?page=2&page_size=10&work_order_number=WO-1");
  });

  it("apiGetHubTimesheets omits the query entirely when unfiltered", async () => {
    await api.apiGetHubTimesheets();
    expect(lastUrl()).toBe("/hub/timesheets");
  });
});

describe("path segments are encoded", () => {
  it("apiGetItemByBarcode escapes a barcode containing a slash", async () => {
    await api.apiGetItemByBarcode("AB/12#3");
    expect(lastUrl()).toBe("/items/AB%2F12%233");
  });

  it("apiGetNetFacilitiesEnrichment escapes the job id", async () => {
    await api.apiGetNetFacilitiesEnrichment("a b");
    expect(lastUrl()).toBe("/integrations/netfacilities/work-orders/enrich/a%20b");
  });
});

describe("apiCreateTransaction builds its body explicitly", () => {
  it("drops unknown keys the backend schema would reject", async () => {
    await api.apiCreateTransaction({
      item_id: 1, transaction_type: "out", quantity: 2,
      user_id: 99, note: "should not travel",
    });
    expect(JSON.parse(calls.at(-1).init.body)).toEqual({
      item_id: 1, transaction_type: "out", quantity: 2,
    });
  });

  it("sends work_order_id when scanning from a card", async () => {
    await api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1, work_order_id: 7 });
    expect(JSON.parse(calls.at(-1).init.body)).toMatchObject({ work_order_id: 7 });
  });

  it("sends work_order_number for a typed number", async () => {
    await api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1, work_order_number: "WO-9" });
    expect(JSON.parse(calls.at(-1).init.body)).toMatchObject({ work_order_number: "WO-9" });
  });
});

describe("multipart uploads", () => {
  it("apiDecodeBarcode posts FormData and sets no Content-Type by hand", async () => {
    const file = new File(["x"], "photo.png", { type: "image/png" });
    await api.apiDecodeBarcode(file);
    const { init } = calls.at(-1);
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get("file")).toBe(file);
    // The browser must add the multipart boundary itself; a hand-set header
    // produces a boundary-less request the server cannot parse.
    expect(init.headers).toBeUndefined();
  });

  it("apiImportWorkOrders posts FormData to the import route", async () => {
    const file = new File(["a,b"], "wo.csv", { type: "text/csv" });
    await api.apiImportWorkOrders(file);
    expect(calls.at(-1).url).toBe("/work-orders/import");
    expect(calls.at(-1).init.body.get("file")).toBe(file);
  });
});

describe("blob downloads", () => {
  it("apiExportWorkOrders returns the blob and the server filename", async () => {
    server.use(http.get("/work-orders/export", () =>
      new HttpResponse("a,b\n1,2", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="20260910_all.csv"' },
      })));
    const result = await api.apiExportWorkOrders("all");
    expect(await result.blob.text()).toBe("a,b\n1,2");
    expect(result.filename).toBe("20260910_all.csv");
  });

  it("apiExportWorkOrders falls back when the header is stripped", async () => {
    server.use(http.get("/work-orders/export", () => new HttpResponse("a,b")));
    const result = await api.apiExportWorkOrders("mine", { variant: "client" });
    expect(result.filename).toBe("work-orders-client-mine.csv");
  });

  it("apiExportWorkOrders carries the active filters", async () => {
    server.use(http.get("/work-orders/export", () => new HttpResponse("x")));
    await api.apiExportWorkOrders("all", { filters: { serviceType: "HVAC", q: "unit 4", community: "" } });
    expect(lastUrl()).toBe("/work-orders/export?scope=all&variant=full&service_type=HVAC&q=unit+4");
  });

  it("apiExportWorkOrders still throws {status, detail} on a failure", async () => {
    server.use(http.get("/work-orders/export", () =>
      HttpResponse.json({ detail: "Admin only" }, { status: 403 })));
    await expect(api.apiExportWorkOrders("all")).rejects.toEqual({ status: 403, detail: "Admin only" });
  });

  it("apiExportHubTimesheets defaults its filename to timesheet.csv", async () => {
    server.use(http.get("/hub/timesheets/export", () => new HttpResponse("x")));
    const result = await api.apiExportHubTimesheets({ start: "2026-09-01" });
    expect(lastUrl()).toBe("/hub/timesheets/export?start=2026-09-01");
    expect(result.filename).toBe("timesheet.csv");
  });
});
