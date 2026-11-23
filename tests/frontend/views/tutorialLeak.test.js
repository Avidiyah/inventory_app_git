// No sample record survives a tutorial, and typed text is never lost to one.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { bootApp } from "../helpers/app.js";
import { restoreBrowserStubs, stubScrollIntoView } from "../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../helpers/factories.js";
import { dismissMessageDialog } from "../helpers/workOrders.js";

const real = workOrderCard({ number: "REAL-1", status: "in_progress" });
const handlers = [
  http.get("/work-orders/", () => HttpResponse.json([real])),
  http.get("/work-orders/filter-options", () => HttpResponse.json({ service_types: [], priorities: [], supervisors: [], communities: [] })),
  http.get("/work-orders/:id/requests", () => HttpResponse.json([])),
  http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...real }))),
  http.get("/items/", () => HttpResponse.json([])),
  http.get("/users/", () => HttpResponse.json([])),
];
const text = () => document.body.textContent;
const pill = () => document.querySelector("#work-orders-page .tut-btn");

describe("tutorial leak", () => {
  it("after End the real list is back, fetched from the server, with no sample left", async () => {
    stubScrollIntoView();
    const { clearRequests, requestsFor } = await bootApp({ role: "supervisor", page: "work-orders", handlers });
    await vi.waitFor(() => expect(text()).toContain("REAL-1"));
    pill().click();
    await vi.waitFor(() => expect(document.querySelector(".tut-box")).not.toBeNull());
    expect(text()).toContain("SAMPLE-1");
    expect(text()).not.toContain("REAL-1");
    clearRequests();
    document.querySelector('[data-tut-act="end"]').click();
    await vi.waitFor(() => expect(text()).toContain("REAL-1"));
    expect(text()).not.toContain("SAMPLE-");
    expect(requestsFor("/work-orders/").length).toBeGreaterThan(0);
    expect(requestsFor("/items/").length).toBeGreaterThan(0);
    expect(requestsFor("/users/").length).toBeGreaterThan(0);
    expect(location.pathname).toBe("/");
    restoreBrowserStubs();
  });

  it("refuses to start over an unsaved note and keeps it", async () => {
    const { requestsFor, clearRequests } = await bootApp({ role: "supervisor", page: "work-orders", handlers });
    await vi.waitFor(() => expect(document.querySelector('details.wo-card[data-number="REAL-1"]')).not.toBeNull());
    document.querySelector('details.wo-card[data-number="REAL-1"] [data-peek-open]').click();
    await vi.waitFor(() => expect(document.getElementById("wo-notes-input")).not.toBeNull());
    const note = document.getElementById("wo-notes-input");
    note.value = "unsaved words";
    pill().click();
    expect(await dismissMessageDialog()).toMatch(/Finish or save what you typed/);
    expect(document.querySelector(".tut-overlay")).toBeNull();
    expect(document.getElementById("wo-notes-input").value).toBe("unsaved words");
    clearRequests();
    const api = await import("../../../backend/static/api.js");
    await api.apiListWorkOrders();
    expect(requestsFor("/work-orders/")).toHaveLength(1);
  });
});
