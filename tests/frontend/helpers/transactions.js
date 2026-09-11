// The Transaction page fixture.
//
// transactions.js pulls nav.js (and so most of the spine) but nothing fetches
// at import; the gate fetches only when enterTransactionPage() runs, and the
// batch fetches /items/ once. Both are answered off the arguments the test
// passed.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests, requestFor } from "./requests.js";
import { workOrderCard } from "./factories.js";

export { BATCH_KEY, savedBatch, seedBatch } from "./auth.js";
export { requests, requestFor, clearRequests } from "./requests.js";

// Getters, not nodes: every mount replaces `document.documentElement`, so a
// captured node would be a corpse from the previous test.
const byId = (id) => () => document.getElementById(id);

export const el = {
  page: (name) => document.getElementById(`${name}-page`),
  gate: byId("wo-gate"), gateInput: byId("wo-gate-input"), gateMessage: byId("wo-gate-message"),
  gateCards: byId("wo-gate-cards"), gateCardsMessage: byId("wo-gate-cards-message"),
  gateSearchCard: byId("wo-gate-search-card"), gateCardsSection: byId("wo-gate-cards-section"),
  active: byId("scango-active"), woLabel: byId("scango-wo-label"), changeWoBtn: byId("scango-change-wo-btn"),
  type: byId("scango-type"), direction: byId("scango-direction"),
  segStock: () => document.querySelector(".scango-seg-stock"),
  segDispense: () => document.querySelector(".scango-seg-dispense"),
  directionFixed: byId("scango-direction-fixed"), advancedToggle: byId("scango-advanced-toggle"),
  quickToggle: byId("scango-quickmode-toggle"), quantity: byId("scango-quantity"),
  summary: byId("scango-summary"), log: byId("scango-log"), message: byId("scango-message"),
  scanSection: byId("txn-scan-section"), manualSection: byId("txn-manual-section"),
  search: byId("txn-item-search"), results: byId("txn-item-search-results"),
};

export const logLines = () => Array.from(el.log().querySelectorAll(".scango-log-line"));
export const cardEls = () => Array.from(el.gateCards().querySelectorAll("button.wo-card"));

// --- per-test answers -------------------------------------------------------

export function answerTransaction(txnOrStatus, { detail = "Insufficient stock to dispense." } = {}) {
  server.use(http.post("/transactions/", () => (
    typeof txnOrStatus === "number"
      ? HttpResponse.json({ detail }, { status: txnOrStatus })
      : HttpResponse.json(txnOrStatus, { status: 201 })
  )));
}

export function answerVoid(status = 204) {
  server.use(http.delete("/transactions/:id", () => (
    status === 204
      ? new HttpResponse(null, { status })
      : HttpResponse.json({ detail: "no" }, { status })
  )));
}

export function answerStart(detailOrStatus) {
  server.use(http.post("/work-orders/:id/start", () => (
    typeof detailOrStatus === "number"
      ? HttpResponse.json({ detail: "already started" }, { status: detailOrStatus })
      : HttpResponse.json(detailOrStatus)
  )));
}

// --- mount ------------------------------------------------------------------

export async function mountTransactions({ role = "technician", workOrders = [], items = [], handlers = [] } = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's override must precede the fixture defaults.
  server.use(
    ...handlers,
    http.get("/work-orders/", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      return HttpResponse.json(q ? workOrders.filter((w) => w.number.includes(q)) : workOrders);
    }),
    http.get("/items/", () => HttpResponse.json(items)),
  );
  stubUserMedia();
  stubPermissions("prompt");
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/transactions.js");
  clearRequests();
  return { mod, currentUser };
}

export async function openGate(opts = {}) {
  const mounted = await mountTransactions(opts);
  mounted.mod.enterTransactionPage();
  await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
  await vi.waitFor(() => expect(el.gateCardsMessage().textContent).not.toMatch(/Loading|Searching/));
  return mounted;
}

export async function inBatch({ role = "technician", items = [], wo = null, handlers = [] } = {}) {
  const card = wo ?? workOrderCard({ number: "7001", status: "in_progress" });
  const mounted = await openGate({ role, workOrders: [card], items, handlers });
  await userEvent.setup().click(cardEls()[0]);
  await vi.waitFor(() => expect(el.active().hidden).toBe(false));
  await vi.waitFor(() => expect(requestFor("/items/", "GET")).not.toBeNull());
  clearRequests();
  return { ...mounted, wo: card, items };
}

export async function pickManual(name) {
  const user = userEvent.setup();
  await user.clear(el.search());
  await user.type(el.search(), name);
  await vi.waitFor(() => expect(el.results().querySelector(".manual-item-card")).not.toBeNull());
  await user.click(el.results().querySelector(".manual-item-card"));
}

export function restoreTransactions() {
  stopRecording();
  restoreMediaStubs();
  vi.useRealTimers();
}
