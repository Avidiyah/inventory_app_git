// Characterization: the socket-driven refresh paths.
//
// Driven through the REAL dispatcher rather than a mocked emitter:
// `realtime.js` exports no test hook, and adding one would be a production
// change P2 is not allowed to make. `installFakeWebSocket` replaces the
// transport, so `parseEnvelope`, the generation guards and the reconnect
// ladder all execute exactly as they do in the browser.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { installFakeWebSocket } from "../../helpers/fakeSocket.js";
import { server } from "../../helpers/handlers.js";
import {
  card, cardBody, cardEls, listEl, mountWorkOrders, openCard, requestFor, requests, respond,
  seedDetail, seedList, state,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs, stubScroll } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../../helpers/factories.js";
import { importView } from "../../helpers/shell.js";

const EVENT = "work_order.status.changed";

let ws;
let realtime;

afterEach(() => {
  realtime?.disconnectRealtime();
  ws?.restore();
  realtime = null;
  ws = null;
  restoreBrowserStubs();
  vi.restoreAllMocks();
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
  it("repaints that card's summary in place while its status holds", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    const listCard = workOrderCard({ id: detail.id, number: "4242", status: "assigned" });
    await mountConnected({ cards: [listCard], details: [detail] });
    seedDetail({ ...detail, priority: "Urgent" });

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(cardEls()[0].querySelector(".wo-priority")?.textContent).toBe("Urgent"));
    // The summary text changed, so the card also takes the one-shot highlight.
    expect(cardEls()[0].className).toBe("wo-card wo-card-status-assigned wo-card-urgent just-changed");
    expect(detailGets(detail.id)).toBe(1);
    expect(listGets()).toBe(0);
  });

  it("reloads the list when the status moves the card to another group", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    const listCard = workOrderCard({ id: detail.id, number: "4242", status: "assigned" });
    await mountConnected({ cards: [listCard], details: [detail] });
    seedDetail({ ...detail, status: "completed" });
    seedList([{ ...listCard, status: "completed" }]);

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(listEl().querySelector(".wo-group").dataset.status).toBe("completed"));
    expect(listGets()).toBe(1);
  });

  it("leaves an open preview open and repaints it too", async () => {
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "assigned" })],
      details: [detail],
    });
    const cardEl = cardEls()[0];
    cardEl.open = true;
    seedDetail({ ...detail, description: "Patch the roof flashing" });

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(cardEl.querySelector(".wo-peek").textContent).toContain("Patch the roof flashing"));
    expect(cardEl.open).toBe(true);
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
  // "Held" is any of the four editor sections being open on the card page. A
  // live update patches around it now instead of waiting for it to close.
  it.each([
    ".wo-edit-card", ".wo-notes-section", ".wo-materials-section", ".wo-labor-section",
  ])("updates the card while %s is open, and the section stays open", async (selector) => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await openCard(0);
    // The card opens on Materials; the user is moving to `selector`.
    cardEl.querySelector(".wo-materials-section").open = false;
    cardEl.querySelector(selector).open = true;
    seedDetail({ ...detail, status: "completed" });
    // `toggle` is dispatched a task later; it is what moves the tab bar.
    await quiet();

    statusChanged(detail.id);
    await vi.waitFor(() =>
      expect(cardEl.querySelector(".wo-status").textContent).toBe("Completed"));
    expect(detailGets(detail.id)).toBe(1);
    expect(cardEl.querySelector(selector).open).toBe(true);
  });

  it("catches up when the editor closes -- through the capture-phase toggle listener", async () => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await openCard(0);
    cardEl.querySelector(".wo-edit-card").open = true;
    statusChanged(detail.id);
    // The open editor is left alone, so the update is marked missed.
    await vi.waitFor(() => expect(cardEl.dataset.missedUpdate).toBe("1"));
    seedDetail({ ...detail, status: "completed" });

    // `toggle` does not bubble; the module listens in the capture phase, so
    // closing the section really does reach it.
    cardEl.querySelector(".wo-edit-card").open = false;
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(2));
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

  it("refreshes a card page's own card while a section is open", async () => {
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    await mountConnected({
      cards: [workOrderCard({ id: detail.id, number: "4242", status: "in_progress" })],
      details: [detail],
      role: "supervisor",
    });
    const cardEl = await openCard(0);
    cardEl.querySelector(".wo-materials-section").open = true;
    seedDetail({ ...detail, status: "completed" });
    emit({ type: EVENT, id: null, req: null });
    await vi.waitFor(() =>
      expect(cardEl.querySelector(".wo-status").textContent).toBe("Completed"));
    expect(detailGets(detail.id)).toBe(1);
    expect(listGets()).toBe(0);
  });
});

// --- Stage 2: a live update patches the open card page ---------------------

const T1 = "20000000-0000-4000-8000-000000000001";
const lineId = (n) => `30000000-0000-4000-8000-00000000000${n}`;
const line = (n, over = {}) => workOrderItem({ id: lineId(n), item_name: `Item ${n}`, ...over });
const byId = (x) => document.getElementById(x);

// Holds every GET /work-orders/{id} for `id` until the test releases it. The
// detail is read when the request arrives, as the server would read it.
function holdDetailGets(id) {
  const held = [];
  server.use(http.get("/work-orders/:id", async ({ params }) => {
    if (params.id !== String(id)) return undefined;
    const detail = state.details.get(params.id);
    await new Promise((resolve) => held.push(resolve));
    return detail ? HttpResponse.json(detail) : HttpResponse.json({ detail: "Not found" }, { status: 404 });
  }));
  return held;
}

async function openLive({ role = "admin", extra = [], ...over } = {}) {
  const detail = workOrderDetail({
    number: "4242", status: "in_progress", items: [line(1), line(2)],
    assigned_to_ids: [T1], assigned_to_names: ["Pat"], ...over,
  });
  const cards = [workOrderCard({ id: detail.id, number: "4242", status: detail.status }),
    ...extra.map((d) => workOrderCard({ id: d.id, number: d.number, status: d.status }))];
  const mounted = await mountConnected({ cards, details: [detail, ...extra], role });
  const cardEl = await openCard(0);
  return { ...mounted, detail, cardEl };
}

const tap = (el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
const keyPress = (el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, detail: 0 }));

describe("a live update on the card page", () => {
  it("an event while the Materials tab is open updates the lines", async () => {
    const { detail, cardEl } = await openLive();
    cardEl.querySelector('.wo-tab[data-wo-tab="materials"]').click();
    seedDetail({ ...detail, items: [line(1), line(2), line(3)] });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(byId(`wo-line-${lineId(3)}`)).not.toBeNull());
    expect(byId("wo-sec-materials").open).toBe(true);
  });

  it("an event while a note is half-typed keeps the note and updates the status actions", async () => {
    const { detail } = await openLive();
    byId("wo-notes-input").value = "half a th";
    seedDetail({ ...detail, status: "completed" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(byId("wo-act-review-wo")).not.toBeNull());
    expect(byId("wo-notes-input").value).toBe("half a th");
  });

  it("two events whose responses arrive out of order end on the newer response", async () => {
    const { detail } = await openLive();
    const held = holdDetailGets(detail.id);
    seedDetail({ ...detail, description: "First" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    seedDetail({ ...detail, description: "Second" });
    statusChanged(detail.id);
    await quiet();
    // The second event waits for the first fetch rather than racing it.
    expect(held).toHaveLength(1);
    held[0]();
    await vi.waitFor(() => expect(held).toHaveLength(2));
    held[1]();
    await vi.waitFor(() => expect(cardBody().textContent).toContain("Second"));
    await quiet();
    expect(cardBody().textContent).not.toContain("First");
  });

  it("three events in quick succession make at most two fetches", async () => {
    const { detail } = await openLive();
    const held = holdDetailGets(detail.id);
    statusChanged(detail.id);
    statusChanged(detail.id);
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    held[0]();
    await vi.waitFor(() => expect(held).toHaveLength(2));
    held[1]();
    await quiet();
    expect(detailGets(detail.id)).toBe(2);
  });

  it("a live response that a save's repaint overtook is dropped and refetched", async () => {
    const { detail, cardEl } = await openLive();
    const list = await importView("views/workOrderList.js");
    const held = holdDetailGets(detail.id);
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    seedDetail({ ...detail, description: "Saved by me" });
    const save = list.refreshCard(cardEl);
    await vi.waitFor(() => expect(held).toHaveLength(2));
    held[1]();
    await save;
    held[0]();
    await vi.waitFor(() => expect(held).toHaveLength(3));
    expect(cardBody().textContent).toContain("Saved by me");
    held[2]();
    await quiet();
    expect(cardBody().textContent).toContain("Saved by me");
    expect(detailGets(detail.id)).toBe(3);
  });

  it("a response that arrives after the user opened another order changes nothing there", async () => {
    const other = workOrderDetail({ number: "5151", description: "Other job" });
    const { detail, mod } = await openLive({ extra: [other] });
    const held = holdDetailGets(detail.id);
    seedDetail({ ...detail, description: "Late news" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    await mod.loadWorkOrders();
    await openCard(1);
    const before = cardBody().innerHTML;
    held[0]();
    await quiet();
    expect(card().dataset.id).toBe(other.id);
    expect(cardBody().innerHTML).toBe(before);
  });

  it("a 404 that arrives after the user opened another order does not replace that order", async () => {
    const other = workOrderDetail({ number: "5151" });
    const { detail, mod } = await openLive({ extra: [other] });
    const held = holdDetailGets(detail.id);
    state.details.delete(String(detail.id));
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    await mod.loadWorkOrders();
    await openCard(1);
    held[0]();
    await quiet();
    expect(listEl().querySelector("p.error")).toBeNull();
    expect(card().dataset.id).toBe(other.id);
  });

  it("Edit details open during an event, then closed: the form shows the current values on reopen", async () => {
    const { detail, cardEl } = await openLive();
    const editor = byId("wo-edit-card");
    editor.open = true;
    seedDetail({ ...detail, location: "Lobby" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(cardEl.dataset.missedUpdate).toBe("1"));
    expect(editor.querySelector(".wo-edit-location").value).not.toBe("Lobby");
    editor.open = false;
    await vi.waitFor(() => expect(byId("wo-edit-card").querySelector(".wo-edit-location").value).toBe("Lobby"));
    byId("wo-edit-card").open = true;
    expect(byId("wo-edit-card").querySelector(".wo-edit-location").value).toBe("Lobby");
    expect(cardEl.dataset.missedUpdate).toBeUndefined();
  });

  it("a field focused during an event catches up when focus leaves it", async () => {
    const { detail, cardEl } = await openLive();
    const qty = byId(`wo-line-qty-${lineId(1)}`);
    qty.focus();
    seedDetail({ ...detail, items: [line(1, { quantity: "9" }), line(2)] });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(cardEl.dataset.missedUpdate).toBe("1"));
    expect(qty.value).toBe("1");
    qty.blur();
    await vi.waitFor(() => expect(byId(`wo-line-qty-${lineId(1)}`).value).toBe("9"));
  });

  it("a 401 on a live refresh does not call the unauthorized handler and changes nothing", async () => {
    const { detail } = await openLive();
    const api = await importView("api.js");
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/work-orders/:id", () => HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })));
    const before = cardBody().innerHTML;
    statusChanged(detail.id);
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await quiet();
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(cardBody().innerHTML).toBe(before);
  });

  it("a network failure during a live refresh changes nothing on screen", async () => {
    const { detail } = await openLive();
    server.use(http.get("/work-orders/:id", () => HttpResponse.error()));
    const before = cardBody().innerHTML;
    statusChanged(detail.id);
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await quiet();
    expect(cardBody().innerHTML).toBe(before);
  });

  it("a draft replayed on reconnect ends with the saved entry shown and no stale overwrite", async () => {
    const { detail, mod } = await openLive();
    server.use(http.post("/work-orders/:id/labor", () => HttpResponse.error()));
    cardBody().querySelector(".wo-new-labor-hours").value = "1";
    cardBody().querySelector('[data-action="add-labor"]').click();
    await vi.waitFor(() => expect(localStorage.getItem(`wo-draft:${detail.id}:labor`)).not.toBeNull());

    const entry = { id: "40000001-0000-4000-8000-000000000000", technician_id: T1, technician_name: "Pat",
      minutes: 60, hand_entered: true, recorded_by_self: false, week_open: true, session_window: null, auto_closed: false };
    server.use(http.post("/work-orders/:id/labor", () => {
      seedDetail({ ...detail, labor: [entry], labor_minutes: 60 });
      return HttpResponse.json({ ok: true });
    }));
    const held = holdDetailGets(detail.id);
    const entries = () => cardBody().querySelectorAll(".wo-labor-entry").length;
    statusChanged(detail.id);
    await vi.waitFor(() => expect(held).toHaveLength(1));
    const replay = mod.replayPendingDrafts();
    await vi.waitFor(() => expect(held).toHaveLength(2));
    held[1]();
    await replay;
    expect(entries()).toBe(1);
    held[0]();
    await vi.waitFor(() => expect(held).toHaveLength(3));
    expect(entries()).toBe(1);
    held[2]();
    await quiet();
    expect(entries()).toBe(1);
  });

  it("heldWorkOrderCards still reports a card with an open section", async () => {
    const { cardEl } = await openLive();
    const list = await importView("views/workOrderList.js");
    // Materials is open on arrival, so a fresh card page already counts as held.
    expect(list.heldWorkOrderCards()).toEqual([cardEl]);
    cardEl.querySelector(".wo-materials-section").open = false;
    expect(list.heldWorkOrderCards()).toEqual([]);
    cardEl.querySelector(".wo-notes-section").open = true;
    expect(list.heldWorkOrderCards()).toEqual([cardEl]);
  });

  it("after the user's own save the saved field is empty", async () => {
    const { detail } = await openLive();
    respond("post", "/work-orders/:id/labor", { ok: true });
    cardBody().querySelector(".wo-new-labor-hours").value = "1";
    cardBody().querySelector('[data-action="add-labor"]').click();
    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await vi.waitFor(() => expect(cardBody().querySelector(".wo-new-labor-hours").value).toBe(""));
  });

  it("a status change removes the old action button from the document instead of relabelling it", async () => {
    const { detail } = await openLive();
    const begin = byId("wo-act-start-tracking-wo");
    expect(begin).not.toBeNull();
    seedDetail({ ...detail, status: "completed" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(byId("wo-act-review-wo")).not.toBeNull());
    expect(begin.isConnected).toBe(false);
    expect(byId("wo-act-start-tracking-wo")).toBeNull();
  });

  it("a tap on the action bar within 500 ms of its buttons changing does nothing; after 500 ms it works", async () => {
    const { detail } = await openLive();
    let now = Date.parse("2026-11-15T12:00:00Z");
    vi.spyOn(Date, "now").mockImplementation(() => now);
    respond("patch", "/work-orders/:id", { ...detail, status: "completed" });
    seedDetail({ ...detail, status: "on_hold" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(byId("wo-sec-actions").textContent).toContain("On-Hold"));
    tap(byId("wo-act-complete-wo"));
    await quiet();
    expect(requestFor("/work-orders/", "PATCH")).toBeNull();
    now += 500;
    tap(byId("wo-act-complete-wo"));
    await vi.waitFor(() => expect(requestFor("/work-orders/", "PATCH")).not.toBeNull());
  });

  it("a keyboard-activated button still works", async () => {
    const { detail } = await openLive();
    vi.spyOn(Date, "now").mockImplementation(() => Date.parse("2026-11-15T12:00:00Z"));
    respond("patch", "/work-orders/:id", { ...detail, status: "completed" });
    seedDetail({ ...detail, status: "on_hold" });
    statusChanged(detail.id);
    await vi.waitFor(() => expect(byId("wo-sec-actions").textContent).toContain("On-Hold"));
    // Enter or Space on a focused button dispatches a click with detail 0.
    keyPress(byId("wo-act-complete-wo"));
    await vi.waitFor(() => expect(requestFor("/work-orders/", "PATCH")).not.toBeNull());
  });
});
