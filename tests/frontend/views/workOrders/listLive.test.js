// The Work Orders list patches in place on a live update (morph.js), and one
// tap handler per list opens cards -- including ones that arrived live.

import { afterEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket } from "../../helpers/fakeSocket.js";
import {
  cardEls, listEl, mountWorkOrders, seedDetail, seedList,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs, stubScroll } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

afterEach(restoreBrowserStubs);

const cardEl = (card) => document.getElementById(`wo-card-${card.id}`);
const flagged = () => cardEls().filter((el) => el.classList.contains("just-changed")).map((el) => el.dataset.number);
const count = (status) => document.querySelector(`#wo-group-${status} .wo-group-count`).textContent;

async function mountList(cards) {
  stubScroll();
  const { mod } = await mountWorkOrders({ cards, mine: false });
  const update = async (next) => {
    seedList(next);
    await mod.loadWorkOrders({ background: true });
  };
  return { mod, update };
}

describe("a live update to the page list", () => {
  it("keeps what the user opened and folded, and moves a card whose status changed", async () => {
    const a = workOrderCard({ number: "A1", status: "assigned" });
    const b = workOrderCard({ number: "B2", status: "assigned" });
    const done = workOrderCard({ number: "C3", status: "completed" });
    const { update } = await mountList([a, b, done]);
    const aEl = cardEl(a);
    const bEl = cardEl(b);
    aEl.open = true;
    document.getElementById("wo-group-assigned").open = false;
    document.getElementById("wo-group-completed").open = true;

    await update([a, { ...b, status: "in_progress" }, done]);

    expect(cardEl(a)).toBe(aEl);
    expect(aEl.open).toBe(true);
    expect(document.getElementById("wo-group-assigned").open).toBe(false);
    expect(document.getElementById("wo-group-completed").open).toBe(true);
    expect(cardEl(b)).toBe(bEl);
    expect(bEl.closest(".wo-group").id).toBe("wo-group-in_progress");
    expect(count("assigned")).toBe("· 1");
  });

  it("inserts, removes and flags only what changed; the first draw flags nothing", async () => {
    const a = workOrderCard({ number: "A1" });
    const b = workOrderCard({ number: "B2" });
    const gone = workOrderCard({ number: "C3" });
    const { update } = await mountList([a, b, gone]);
    expect(flagged()).toEqual([]);
    const fresh = workOrderCard({ number: "N9" });

    await update([fresh, a, { ...b, priority: "Urgent" }]);

    expect(cardEls().map((el) => el.dataset.number)).toEqual(["N9", "A1", "B2"]);
    expect(flagged()).toEqual(["N9", "B2"]);
    // Two updates back to back: the second leaves no stuck highlight.
    await update([fresh, a, { ...b, priority: "Urgent" }]);
    expect(flagged()).toEqual([]);
  });

  it("a filter change the user made flags nothing", async () => {
    const a = workOrderCard({ number: "A1" });
    const { mod } = await mountList([a]);
    seedList([a, workOrderCard({ number: "B2" })]);
    await mod.loadWorkOrders();
    expect(cardEls()).toHaveLength(2);
    expect(flagged()).toEqual([]);
  });

  it("shows the hint on an empty result, and the next update restores cards", async () => {
    const a = workOrderCard({ number: "A1" });
    const { update } = await mountList([a]);
    await update([]);
    expect(listEl().textContent).toBe("No work orders match.");
    await update([a]);
    expect(cardEls()).toHaveLength(1);
    expect(listEl().querySelector(".hint")).toBeNull();
  });

  it("survives an update that removes the focused card", async () => {
    const a = workOrderCard({ number: "A1" });
    const b = workOrderCard({ number: "B2" });
    const { update } = await mountList([a, b]);
    cardEl(a).querySelector("summary").focus();
    await update([b]);
    expect(cardEl(a)).toBeNull();
    expect(document.activeElement.isConnected).toBe(true);
  });

  it("a card that arrived live opens, with the data now on screen", async () => {
    const a = workOrderCard({ number: "A1" });
    const { update } = await mountList([a]);
    const fresh = workOrderCard({ number: "N9" });
    seedDetail(workOrderDetail({ id: fresh.id, number: "N9" }));
    seedDetail(workOrderDetail({ id: a.id, number: "A1-R" }));
    await update([{ ...a, number: "A1-R" }, fresh]);

    expect(cardEl(a).dataset.number).toBe("A1-R");
    cardEl(fresh).querySelector("[data-peek-open]").click();
    await vi.waitFor(() => expect(window.location.pathname).toContain("N9"));
  });

  it("returning from the card page draws a list whose groups still fold", async () => {
    const a = workOrderCard({ number: "A1" });
    const { mod } = await mountList([a]);
    seedDetail(workOrderDetail({ id: a.id, number: "A1" }));
    cardEl(a).querySelector("[data-peek-open]").click();
    await vi.waitFor(() => expect(listEl().querySelector(".wo-solo")).not.toBeNull());

    await mod.loadWorkOrders();

    expect(listEl().querySelector(".wo-solo")).toBeNull();
    expect([...listEl().children].map((el) => el.id)).toEqual(["wo-group-assigned"]);
    expect(cardEl(a).open).toBe(false);
  });
});

describe("the User Hub list beside the page list", () => {
  it("uses its own ids and its own Open handler for the same order", async () => {
    const a = workOrderCard({ number: "A1" });
    const { mod, update } = await mountList([a]);
    const container = document.createElement("div");
    document.body.appendChild(container);
    const onOpen = vi.fn();
    const hub = mod.mountWorkOrderList({ container, onOpen });
    await hub.refresh();
    await update([{ ...a, number: "A1-R" }]);
    await hub.refresh();

    const ids = [...document.querySelectorAll("[id]")].map((el) => el.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(container.querySelector(`#hubwo-card-${a.id}`).closest("#hubwo-group-assigned")).not.toBeNull();

    container.querySelector("[data-peek-open]").click();
    expect(onOpen).toHaveBeenCalledWith({ id: a.id, number: "A1-R" });
    expect(window.location.pathname).toBe("/");
  });
});

describe("a status event for one on-screen card", () => {
  let ws;
  let realtime;
  afterEach(() => {
    realtime?.disconnectRealtime();
    ws?.restore();
  });

  it("flags the card only when its summary text changed", async () => {
    ws = installFakeWebSocket();
    const detail = workOrderDetail({ number: "4242", status: "assigned" });
    const a = workOrderCard({ id: detail.id, number: "4242", status: "assigned" });
    await mountWorkOrders({ cards: [a], details: [detail], mine: false });
    realtime = await import("../../../../backend/static/realtime.js");
    realtime.setActivePageGetter(() => "work-orders");
    realtime.connectRealtime();
    ws.last().emitOpen();
    const emit = () => ws.last().emitMessage(
      JSON.stringify({ type: "work_order.status.changed", id: String(detail.id), req: null }));

    // Settle on the detail's own summary first, so the next two events
    // compare like with like.
    emit();
    await new Promise((resolve) => setTimeout(resolve, 30));
    cardEl(a).classList.remove("just-changed");

    emit();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(flagged()).toEqual([]);

    seedDetail({ ...detail, priority: "Urgent" });
    emit();
    await vi.waitFor(() => expect(flagged()).toEqual(["4242"]));
  });
});
