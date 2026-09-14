// Characterization coverage for views/adminReview.js: the Review queue, the
// receipt built on select, Reopen and Close through the real confirm overlay,
// the two request-ordering guards, and the realtime background reload.
//
// One consumer, so the mount is local (P7 deviation 6). P1's
// unit/adminReviewReceipt.test.js owns the receipt TEXT -- this file computes
// the expected textarea value through the real builder and asserts equality.
// P2 owns `workOrderCardClass`; only `admin-review-card` and the urgent
// outcome are asserted here.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { connectFakeRealtime } from "../helpers/realtime.js";
import { clearRequests, requestFor, requests, startRecording, stopRecording } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../helpers/factories.js";
import { buildAdminReviewReceipt } from "../../../backend/static/adminReviewReceipt.js";

let realtime = null;

afterEach(() => {
  if (realtime) { realtime.disconnect(); realtime = null; }
  stopRecording();
  vi.useRealTimers();
});

const byId = (id) => () => document.getElementById(id);
const el = {
  list: byId("admin-review-list"),
  message: byId("admin-review-list-message"),
  section: byId("admin-review-receipt-section"),
  title: byId("admin-review-receipt-title"),
  output: byId("admin-review-receipt-output"),
  receiptMessage: byId("admin-review-receipt-message"),
  reopen: byId("admin-review-reopen-btn"),
  close: byId("admin-review-close-btn"),
};
const cards = () => Array.from(el.list().querySelectorAll(".admin-review-card"));
const cardFor = (id) => el.list().querySelector(`.admin-review-card[data-id="${id}"]`);
const listGets = () => requests().filter((r) => r.url.startsWith("/work-orders/?"));
const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
const reviewCard = (o = {}) => workOrderCard({ status: "review", ...o });
const reviewDetail = (o = {}) => workOrderDetail({ status: "review", ...o });
const priced = (o = {}) => workOrderItem({ unit_price: "2.50", ...o });
const unpriced = (o = {}) => workOrderItem({ unit_price: null, ...o });

// A promise the test resolves by hand, for the ordering races.
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

// `handlers` go FIRST so a test's own override wins.
async function mountAdminReview({
  role = "admin", cards: seeded = [], details = [], handlers = [], load = true,
} = {}) {
  const byDetailId = new Map(details.map((d) => [String(d.id), d]));
  server.use(
    ...handlers,
    http.get("/work-orders/:id", ({ params }) => {
      const detail = byDetailId.get(params.id);
      return detail
        ? HttpResponse.json(detail)
        : HttpResponse.json({ detail: "Work order not found." }, { status: 404 });
    }),
    http.get("/work-orders/", () => HttpResponse.json(seeded)),
  );
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/adminReview.js");
  if (load) await mod.loadAdminReview();
  clearRequests();
  return { mod, currentUser };
}

// Click a card and wait for the receipt to land (the list message is cleared
// as the last step of a successful select).
async function select(id) {
  cardFor(id).click();
  await vi.waitFor(() => expect(el.message().textContent).toBe(""));
}

// Mounted with one card selected and its receipt showing.
async function mountSelected({ items = [priced()], number = "12345", handlers = [] } = {}) {
  const detail = reviewDetail({ number, items });
  const mounted = await mountAdminReview({
    cards: [reviewCard({ id: detail.id, number })], details: [detail], handlers,
  });
  await select(detail.id);
  clearRequests();
  return { ...mounted, detail };
}

async function connect(page = "admin-review") {
  realtime = await connectFakeRealtime(page);
  return realtime;
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe("loadAdminReview: the queue", () => {
  it("shows the loading copy, asks for Review only, and paints a button per card", async () => {
    const card = reviewCard({
      id: "w1", number: "4242", location: "Hallway", community: "Oak", building_number: "B",
      unit_number: "7", assigned_to_names: ["Ann", "Bob"],
    });
    const { mod } = await mountAdminReview({ cards: [card], load: false });
    const loading = mod.loadAdminReview();
    expect(el.message().textContent).toBe("Loading Review work orders…");
    await loading;
    expect(requests().map((r) => r.url)).toEqual(["/work-orders/?status=review"]);

    const [button] = cards();
    expect(cards()).toHaveLength(1);
    expect(button.tagName).toBe("BUTTON");
    expect(button.type).toBe("button");
    expect(button.className).toBe("wo-card wo-card-status-review admin-review-card");
    expect(button.dataset.id).toBe("w1");
    expect(button.getAttribute("aria-label")).toBe("Review work order 4242");
    expect(button.querySelector(".wo-card-wo").textContent).toBe("4242");
    expect(button.querySelector(".wo-card-status-label").textContent).toBe("Review");
    expect(button.querySelector(".wo-card-meta").textContent).toBe("Hallway · Oak · B · 7");
    expect(button.querySelector(".wo-card-assignee").textContent).toBe("Ann, Bob");
    expect(button.classList.contains("selected")).toBe(false);
  });

  // `buildCard` says the shared class builder is used "so an urgent work order
  // pulses here the way it does everywhere else" -- but `SETTLED_STATUSES` in
  // workOrderPresenters.js holds `review`, so `urgentFireActive` is false for
  // every card this queue can show. Filed under N-P7-CHARACTERIZED.
  it("never carries the urgent class: Review is a settled status", async () => {
    await mountAdminReview({ cards: [reviewCard({ priority: "Urgent" })] });
    expect(cards()[0].className).toBe("wo-card wo-card-status-review admin-review-card");
  });

  it.each([
    [{ location: "Hallway", community: null, building_number: null, unit_number: null }, "Hallway"],
    [{ location: " ", community: "Oak", building_number: "", unit_number: "7" }, "Oak · 7"],
    [{ location: null, community: null, building_number: null, unit_number: null }, "No location"],
    [{ location: "", community: "  ", building_number: undefined, unit_number: 0 }, "No location"],
  ])("locationText joins the present parts with a middle dot: %o", async (parts, expected) => {
    await mountAdminReview({ cards: [reviewCard(parts)] });
    expect(cards()[0].querySelector(".wo-card-meta").textContent).toBe(expected);
  });

  it.each([
    [["Ann", "", null, "Bob"], "Ann, Bob"],
    [[], "Unassigned"],
    [null, "Unassigned"],
    ["Ann", "Unassigned"],
  ])("assignedNames drops falsy names and falls back to Unassigned: %o", async (names, expected) => {
    await mountAdminReview({ cards: [reviewCard({ assigned_to_names: names })] });
    expect(cards()[0].querySelector(".wo-card-assignee").textContent).toBe(expected);
  });

  it.each([
    [0, "No work orders are waiting for Admin Review.", "success"],
    [1, "1 work order waiting for review.", ""],
    [2, "2 work orders waiting for review.", ""],
  ])("with %i cards the message reads %s", async (count, text, className) => {
    await mountAdminReview({ cards: Array.from({ length: count }, () => reviewCard()) });
    expect(cards()).toHaveLength(count);
    expect(el.message().textContent).toBe(text);
    expect(el.message().className).toBe(className);
  });

  it("a failed foreground load empties the list and shows the fallback copy", async () => {
    const { mod } = await mountAdminReview({ cards: [reviewCard()] });
    server.use(http.get("/work-orders/", fail));
    await mod.loadAdminReview();
    expect(cards()).toHaveLength(0);
    expect(el.message().textContent).toBe("Could not load Admin Review.");
    expect(el.message().className).toBe("error");
  });

  it("a failed background load leaves the list and the message alone", async () => {
    const { mod } = await mountAdminReview({ cards: [reviewCard()] });
    server.use(http.get("/work-orders/", fail));
    await mod.loadAdminReview({ background: true });
    expect(cards()).toHaveLength(1);
    expect(el.message().textContent).toBe("1 work order waiting for review.");
  });

  it("a background load skips the loading copy", async () => {
    const { mod } = await mountAdminReview({ cards: [reviewCard()] });
    const gate = deferred();
    server.use(http.get("/work-orders/", async () => {
      await gate.promise;
      return HttpResponse.json([reviewCard(), reviewCard()]);
    }));
    const loading = mod.loadAdminReview({ background: true });
    await settle();
    expect(el.message().textContent).toBe("1 work order waiting for review.");
    gate.resolve();
    await loading;
    expect(el.message().textContent).toBe("2 work orders waiting for review.");
  });

  // Two overlapping loads: the first is held back by the test until the second
  // has painted. The older answer must not repaint over the newer one.
  it("an older, slower answer never repaints over a newer one", async () => {
    const { mod } = await mountAdminReview({ load: false });
    const gate = deferred();
    let calls = 0;
    server.use(http.get("/work-orders/", async () => {
      calls += 1;
      if (calls === 1) {
        await gate.promise;
        return HttpResponse.json([reviewCard({ id: "old" })]);
      }
      return HttpResponse.json([reviewCard({ id: "new" })]);
    }));
    const first = mod.loadAdminReview();
    await mod.loadAdminReview();
    expect(cardFor("new")).not.toBeNull();
    gate.resolve();
    await first;
    expect(cardFor("new")).not.toBeNull();
    expect(cardFor("old")).toBeNull();
    expect(cards()).toHaveLength(1);
  });

  it("an older, slower failure is ignored once a newer answer has painted", async () => {
    const { mod } = await mountAdminReview({ load: false });
    const gate = deferred();
    let calls = 0;
    server.use(http.get("/work-orders/", async () => {
      calls += 1;
      if (calls === 1) {
        await gate.promise;
        return fail();
      }
      return HttpResponse.json([reviewCard({ id: "new" })]);
    }));
    const first = mod.loadAdminReview();
    await mod.loadAdminReview();
    gate.resolve();
    await first;
    expect(cardFor("new")).not.toBeNull();
    expect(el.message().textContent).toBe("1 work order waiting for review.");
  });
});

describe("selecting a card", () => {
  it("builds the receipt, shows the section, and readies the two buttons", async () => {
    const detail = reviewDetail({ number: "4242", items: [priced(), priced()] });
    await mountAdminReview({ cards: [reviewCard({ id: detail.id, number: "4242" })], details: [detail] });
    cardFor(detail.id).click();
    expect(el.message().textContent).toBe("Building receipt…");
    await vi.waitFor(() => expect(el.message().textContent).toBe(""));

    expect(requestFor(`/work-orders/${detail.id}`, "GET")).not.toBeNull();
    expect(el.section().hidden).toBe(false);
    expect(el.title().textContent).toBe("WO 4242 Receipt");
    expect(el.output().value).toBe(buildAdminReviewReceipt(detail).text);
    expect(cardFor(detail.id).classList.contains("selected")).toBe(true);
    expect(el.reopen().disabled).toBe(false);
    expect(el.close().disabled).toBe(false);
    expect(el.receiptMessage().textContent).toBe("Receipt ready — select all and copy.");
    expect(el.receiptMessage().className).toBe("success");
    expect(document.activeElement).toBe(el.output());
    expect(el.output().scrollTop).toBe(0);
    expect(el.output().scrollLeft).toBe(0);
  });

  it("disables Close and names every unpriced line when a price is missing", async () => {
    const detail = reviewDetail({
      items: [unpriced({ item_name: "Bulb" }), priced({ item_name: "Fuse" }), unpriced({ item_name: "Wire" })],
    });
    await mountAdminReview({ cards: [reviewCard({ id: detail.id })], details: [detail] });
    await select(detail.id);
    expect(el.reopen().disabled).toBe(false);
    expect(el.close().disabled).toBe(true);
    expect(el.receiptMessage().textContent).toBe("Cannot close until a price is added for: Bulb, Wire.");
    expect(el.receiptMessage().className).toBe("error");
    expect(el.output().value).toBe(buildAdminReviewReceipt(detail).text);
  });

  it("moves .selected to the newly chosen card", async () => {
    const a = reviewDetail({ number: "1" });
    const b = reviewDetail({ number: "2" });
    await mountAdminReview({
      cards: [reviewCard({ id: a.id, number: "1" }), reviewCard({ id: b.id, number: "2" })],
      details: [a, b],
    });
    await select(a.id);
    expect(cardFor(a.id).classList.contains("selected")).toBe(true);
    await select(b.id);
    expect(cardFor(a.id).classList.contains("selected")).toBe(false);
    expect(cardFor(b.id).classList.contains("selected")).toBe(true);
    expect(el.title().textContent).toBe("WO 2 Receipt");
  });

  it("a failed detail leaves the section hidden and says so in the list message", async () => {
    const card = reviewCard({ id: "w1" });
    await mountAdminReview({ cards: [card], handlers: [http.get("/work-orders/w1", fail)] });
    cardFor("w1").click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not load that work order."));
    expect(el.message().className).toBe("error");
    expect(el.section().hidden).toBe(true);
    expect(cardFor("w1").classList.contains("selected")).toBe(false);
  });

  it("a click outside any card is ignored", async () => {
    await mountAdminReview({ cards: [reviewCard()] });
    el.list().click();
    await settle();
    expect(requests()).toEqual([]);
    expect(el.message().textContent).toBe("1 work order waiting for review.");
  });

  // Two clicks; the first detail answers after the second. The stale one is
  // dropped: no repaint, no cleared message, no `.selected` swap.
  it("a stale selection answering last is discarded", async () => {
    const a = reviewDetail({ id: "a", number: "1" });
    const b = reviewDetail({ id: "b", number: "2" });
    const gate = deferred();
    await mountAdminReview({
      cards: [reviewCard({ id: "a", number: "1" }), reviewCard({ id: "b", number: "2" })],
      details: [b],
      handlers: [http.get("/work-orders/a", async () => { await gate.promise; return HttpResponse.json(a); })],
    });
    cardFor("a").click();
    await select("b");
    expect(el.title().textContent).toBe("WO 2 Receipt");
    gate.resolve();
    await settle();
    await settle();
    expect(el.title().textContent).toBe("WO 2 Receipt");
    expect(cardFor("a").classList.contains("selected")).toBe(false);
    expect(cardFor("b").classList.contains("selected")).toBe(true);
  });
});

describe("Return to In-Progress", () => {
  it("does nothing with no selection", async () => {
    await mountAdminReview({ cards: [reviewCard()] });
    el.reopen().click();
    await settle();
    expect(confirmOverlay().hidden).toBe(true);
    expect(requests()).toEqual([]);
  });

  it("asks first, and No leaves everything as it was", async () => {
    await mountSelected({ number: "4242" });
    el.reopen().click();
    await answerConfirm(false);
    expect(confirmTitle()).toBe("Return WO 4242 to In-Progress for corrections?");
    await settle();
    expect(requests()).toEqual([]);
    expect(el.reopen().disabled).toBe(false);
    expect(el.close().disabled).toBe(false);
  });

  it("Yes: disables both, PATCHes the status, reloads the queue, and reports", async () => {
    const gate = deferred();
    const { detail } = await mountSelected({
      number: "4242",
      handlers: [http.patch("/work-orders/:id", async () => {
        await gate.promise;
        return HttpResponse.json({});
      })],
    });
    server.use(http.get("/work-orders/", () => HttpResponse.json([])));
    el.reopen().click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(el.reopen().disabled).toBe(true));
    expect(el.close().disabled).toBe(true);
    gate.resolve();
    await vi.waitFor(() => expect(el.receiptMessage().textContent).toBe(
      "WO 4242 returned to In-Progress. The receipt remains available for reference."));

    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body).toEqual({ status: "in_progress" });
    expect(listGets()).toHaveLength(1);
    expect(cards()).toHaveLength(0);
    expect(el.receiptMessage().className).toBe("success");
    expect(el.section().hidden).toBe(false);
    expect(el.output().value).toBe(buildAdminReviewReceipt(detail).text);
    // Both buttons stay disabled after a successful reopen: nothing re-enables
    // them until another card is selected. Filed under N-P7-CHARACTERIZED.
    expect(el.reopen().disabled).toBe(true);
    expect(el.close().disabled).toBe(true);
  });

  it.each([
    ["every line priced", [priced()], false],
    ["a line unpriced", [unpriced()], true],
  ])("failure re-enables Reopen and Close per the receipt (%s)", async (_, items, closeDisabled) => {
    await mountSelected({ items, handlers: [http.patch("/work-orders/:id", fail)] });
    el.reopen().click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(el.receiptMessage().textContent).toBe("Could not return that work order."));
    expect(el.receiptMessage().className).toBe("error");
    expect(el.reopen().disabled).toBe(false);
    expect(el.close().disabled).toBe(closeDisabled);
    expect(listGets()).toHaveLength(0);
  });
});

describe("Close Work Order", () => {
  it("asks first, then archives, reloads the queue, and keeps the receipt", async () => {
    const { detail } = await mountSelected({
      number: "4242",
      handlers: [http.post("/work-orders/:id/archive", () => HttpResponse.json({}))],
    });
    server.use(http.get("/work-orders/", () => HttpResponse.json([])));
    el.close().click();
    await answerConfirm(true);
    expect(confirmTitle()).toBe("Close WO 4242? It will leave the live work-order views.");
    await vi.waitFor(() => expect(el.receiptMessage().textContent).toBe(
      "WO 4242 closed. The receipt remains available for copying."));

    expect(requestFor(`/work-orders/${detail.id}/archive`, "POST")).not.toBeNull();
    expect(listGets()).toHaveLength(1);
    expect(cards()).toHaveLength(0);
    expect(el.receiptMessage().className).toBe("success");
    expect(el.output().value).toBe(buildAdminReviewReceipt(detail).text);
    expect(el.reopen().disabled).toBe(true);
    expect(el.close().disabled).toBe(true);
  });

  it("No sends nothing", async () => {
    await mountSelected();
    el.close().click();
    await answerConfirm(false);
    await settle();
    expect(requests()).toEqual([]);
    expect(el.close().disabled).toBe(false);
  });

  it("failure re-enables both buttons", async () => {
    await mountSelected({ handlers: [http.post("/work-orders/:id/archive", fail)] });
    el.close().click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(el.receiptMessage().textContent).toBe("Could not close that work order."));
    expect(el.receiptMessage().className).toBe("error");
    expect(el.reopen().disabled).toBe(false);
    expect(el.close().disabled).toBe(false);
    expect(listGets()).toHaveLength(0);
  });

  it("a Close disabled by a missing price does nothing", async () => {
    await mountSelected({ items: [unpriced()] });
    expect(el.close().disabled).toBe(true);
    el.close().click();
    await settle();
    expect(confirmOverlay().hidden).toBe(true);
    expect(requests()).toEqual([]);
  });
});

describe("realtime", () => {
  it("work_order.review_queue.changed on the page reloads in the background, keeping the receipt", async () => {
    const { detail } = await mountSelected({ number: "4242" });
    const before = cardFor(detail.id);
    const rt = await connect("admin-review");
    rt.emit("work_order.review_queue.changed");
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
    await vi.waitFor(() => expect(cardFor(detail.id)).not.toBe(before));

    expect(cardFor(detail.id).classList.contains("selected")).toBe(true);
    expect(el.section().hidden).toBe(false);
    expect(el.title().textContent).toBe("WO 4242 Receipt");
    expect(el.output().value).toBe(buildAdminReviewReceipt(detail).text);
    expect(el.message().textContent).toBe("1 work order waiting for review.");
  });

  it("and does nothing on another page", async () => {
    await mountAdminReview({ cards: [reviewCard()] });
    const rt = await connect("history");
    rt.emit("work_order.review_queue.changed");
    await settle();
    expect(requests()).toEqual([]);
  });

  it("a recovered connection reloads too", async () => {
    await mountAdminReview({ cards: [reviewCard()] });
    const rt = await connect("admin-review");
    vi.useFakeTimers();
    rt.reconnect();
    vi.advanceTimersByTime(1000);
    rt.ws.last().emitOpen();
    expect(listGets()).toHaveLength(1);
    await vi.runAllTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  });
});
