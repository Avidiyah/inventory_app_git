// Characterization: the socket-driven refresh paths.
//
// Driven through the REAL dispatcher rather than a mocked emitter:
// `realtime.js` exports no test hook, and adding one would be a production
// change P2 is not allowed to make. `installFakeWebSocket` replaces the
// transport, so `parseEnvelope`, the generation guards and the reconnect
// ladder all execute exactly as they do in the browser.

import { afterEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket } from "../../helpers/fakeSocket.js";
import {
  cardEls, expandCard, listEl, mountWorkOrders, openCard, requests, seedDetail, seedList, state,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs, stubScroll } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

const EVENT = "work_order.status.changed";

let ws;
let realtime;

afterEach(() => {
  realtime?.disconnectRealtime();
  ws?.restore();
  realtime = null;
  ws = null;
  restoreBrowserStubs();
});

// Mount `cards`, then bring the socket up on the Work Orders page.
async function mountConnected({ cards, details = [], role = "admin", activePage = "work-orders" }) {
  stubScroll();
  ws = installFakeWebSocket();
  const mounted = await mountWorkOrders({ role, cards, details });
  realtime = await import("../../../../backend/static/realtime.js");
  realtime.setActivePageGetter(() => activePage);
  realtime.connectRealtime();
  ws.last().emitOpen();
  return mounted;
}

const emit = (payload) => ws.last().emitMessage(JSON.stringify(payload));
const statusChanged = (id) => emit({ type: EVENT, id: String(id), req: null });

const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;
const listGets = () =>
  requests().filter((r) => r.url.startsWith("/work-orders/?") || r.url === "/work-orders/").length;

const quiet = () => new Promise((resolve) => setTimeout(resolve, 30));

describe("a frame naming a rendered card", () => {
  it("repaints that card's summary in place", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    const listCard = workOrderCard({ id: detail.id, number: "4242", status: "assigned" });
    await mountConnected({ cards: [listCard], details: [detail] });
    seedDetail({ ...detail, status: "completed", priority: "Urgent" });

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(cardEls()[0].querySelector(".wo-status").textContent).toBe("Completed"));
    expect(cardEls()[0].className).toBe("wo-card wo-card-status-completed");
    expect(detailGets(detail.id)).toBe(1);
    expect(listGets()).toBe(0);
  });

  it("leaves an open, unheld card open and repaints its body too", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    const cardEl = await expandCard(0);
    seedDetail({ ...detail, status: "completed" });

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(cardEl.querySelector(".wo-status").textContent).toBe("Completed"));
    expect(cardEl.open).toBe(true);
    // The body's actions follow the badge: no Completed badge over a live
    // "Mark Completed" button.
    expect(cardEl.querySelector('[data-action="complete-wo"]')).toBeNull();
    expect(cardEl.querySelector('[data-action="reopen-wo"]')).not.toBeNull();
  });

  it("drops the loaded flag on a collapsed card so the next expansion re-fetches", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    expect(cardEls()[0].dataset.loaded).toBeUndefined();
  });

  it("removes the row on a 404, and shows the empty state when it was the last", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    state.details = new Map(); // the work order left this user's view
    statusChanged(detail.id);
    await vi.waitFor(() => expect(cardEls()).toHaveLength(0));
    expect(listEl().textContent).toBe("No work orders match.");
  });

  it("keeps the row on a non-404 failure", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    state.listResponder = null;
    const { server } = await import("../../helpers/handlers.js");
    const { http, HttpResponse } = await import("msw");
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: "boom" }, { status: 500 })));
    statusChanged(detail.id);
    await quiet();
    expect(cardEls()).toHaveLength(1);
  });

  it("replaces the card page with an error when its only card 404s", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    await openCard(0);
    state.details = new Map();
    statusChanged(detail.id);
    await vi.waitFor(() => expect(listEl().querySelector("p.error")).not.toBeNull());
    expect(listEl().querySelector("p.error").textContent)
      .toBe("This work order is no longer available.");
    expect(listEl().querySelector('[data-action="back-to-work-orders"]')).not.toBeNull();
  });
});

describe("frames this page ignores", () => {
  it("ignores an id that is not on screen", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    statusChanged("00000000-0000-4000-8000-999999999999");
    await quiet();
    expect(requests()).toHaveLength(0);
  });

  it("ignores everything while another page is active", async () => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
      activePage: "history",
    });
    statusChanged(detail.id);
    emit({ type: EVENT, id: null, req: null });
    await quiet();
    expect(requests()).toHaveLength(0);
  });

  it.each([
    ["not JSON", "{oops"],
    ["an extra key", JSON.stringify({ type: EVENT, id: "1", req: null, extra: 1 })],
    ["a numeric id", JSON.stringify({ type: EVENT, id: 1, req: null })],
    ["another event type", JSON.stringify({ type: "item.changed", id: "1", req: null })],
  ])("never delivers %s", async (_label, raw) => {
    const detail = workOrderDetail({ number: "4242" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    ws.last().emitMessage(raw);
    await quiet();
    expect(requests()).toHaveLength(0);
  });
});

describe("a held card", () => {
  // "Held" is any of the four editor sections being open: refreshing would
  // discard an unsaved note, quantity, or technician selection.
  it.each([
    ".wo-edit-card", ".wo-notes-section", ".wo-materials-section", ".wo-labor-section",
  ])("defers the update while %s is open", async (selector) => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await expandCard(0);
    cardEl.querySelector(selector).open = true;

    statusChanged(detail.id);
    await quiet();
    expect(cardEl.dataset.missedUpdate).toBe("1");
    expect(detailGets(detail.id)).toBe(0);
  });

  it("catches up when the editor closes -- through the capture-phase toggle listener", async () => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await expandCard(0);
    cardEl.querySelector(".wo-edit-card").open = true;
    statusChanged(detail.id);
    await quiet();
    seedDetail({ ...detail, status: "completed" });

    // `toggle` does not bubble; the module listens in the capture phase, so
    // closing the section really does reach it.
    cardEl.querySelector(".wo-edit-card").open = false;
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await vi.waitFor(() =>
      expect(cardEl.querySelector(".wo-status").textContent).toBe("Completed"));
    expect(cardEl.dataset.missedUpdate).toBeUndefined();
  });
});

describe("a membership change or a reconnect", () => {
  it("refetches the whole list for a null id", async () => {
    await mountConnected({ cards: [workOrderCard({ number: "1" })] });
    seedList([workOrderCard({ number: "1" }), workOrderCard({ number: "2" })]);
    emit({ type: EVENT, id: null, req: null });
    await vi.waitFor(() => expect(cardEls()).toHaveLength(2));
    expect(listGets()).toBe(1);
  });

  it("refetches the whole list on a socket recovery", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await mountConnected({ cards: [workOrderCard({ number: "1" })] });
    seedList([workOrderCard({ number: "1" }), workOrderCard({ number: "2" })]);
    // First open, then an unexpected close, then the retry's open: only that
    // second open is a recovery.
    ws.last().emitClose();
    vi.advanceTimersByTime(1000);
    ws.last().emitOpen();
    vi.useRealTimers();
    await vi.waitFor(() => expect(cardEls()).toHaveLength(2));
  });

  it("defers the list refetch while any card is held, and flushes it on the next toggle", async () => {
    const detail = workOrderDetail({ number: "1", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "1", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await expandCard(0);
    cardEl.querySelector(".wo-notes-section").open = true;

    seedList([
      workOrderCard({ id: detail.id, number: "1" }),
      workOrderCard({ number: "2" }),
    ]);
    emit({ type: EVENT, id: null, req: null });
    await quiet();
    expect(listGets()).toBe(0);

    cardEl.querySelector(".wo-notes-section").open = false;
    await vi.waitFor(() => expect(cardEls()).toHaveLength(2));
    expect(listGets()).toBe(1);
  });

  it("refreshes only the card on screen when a card page is showing", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242" })],
      details: [detail],
    });
    await openCard(0);
    seedDetail({ ...detail, status: "completed" });
    emit({ type: EVENT, id: null, req: null });
    await vi.waitFor(() =>
      expect(listEl().querySelector(".wo-status").textContent).toBe("Completed"));
    // A list refetch here would silently replace the card page with the list.
    expect(listGets()).toBe(0);
    expect(window.location.pathname).toBe("/workorder_card/4242");
  });

  it("defers a card page's own refresh while it is held", async () => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await openCard(0);
    cardEl.querySelector(".wo-materials-section").open = true;
    emit({ type: EVENT, id: null, req: null });
    await quiet();
    expect(cardEl.dataset.missedUpdate).toBe("1");
    expect(detailGets(detail.id)).toBe(0);
  });
});
