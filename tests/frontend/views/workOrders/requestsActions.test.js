// Characterization coverage for views/workOrderRequests.js, second half: the
// four `data-request-action`s (pick, send, cancel, add-requested) and the
// realtime refetch. The markup, the list, the stocked lines and the search
// are in requests.test.js; split only for this repo's 500-line cap, and
// requestsActionCoverage.test.js reads both.
//
// Mounted through P2's fixture (see requests.test.js). The `add-item` wire
// that consumes `materialRequestId` is P2's (editorActions.test.js), so
// `add-requested` is asserted at the dataset stamp and no further.

import { afterEach, describe, expect, it, vi } from "vitest";
import { importView } from "../../helpers/shell.js";
import { connectFakeRealtime } from "../../helpers/realtime.js";
import {
  answerConfirm, card, cardEls, clearRequests, confirmOverlay, expandCard, message,
  mountWorkOrders, openCard, requestFor, requests, respond, state,
} from "../../helpers/workOrders.js";
import { item as itemFactory, userRequest, workOrderCard, workOrderDetail } from "../../helpers/factories.js";

let rt = null;
afterEach(() => { rt?.disconnect(); rt = null; });

const quiet = () => new Promise((r) => setTimeout(r, 30));

const list = () => card().querySelector(".wo-request-list");
const lines = () => card().querySelector(".wo-requested-lines");
const form = () => card().querySelector(".wo-request-form");
const search = () => form().querySelector(".wo-request-search");
const results = () => form().querySelector(".wo-request-results");
const onHand = () => form().querySelector(".wo-request-onhand");
const qty = () => form().querySelector(".wo-request-qty");
const link = () => form().querySelector(".wo-request-link");
const note = () => form().querySelector(".wo-request-note");
// Positional: `setMessage` overwrites className, so `.wo-request-message`
// matches nothing once it holds a message.
const formMessage = () => form().lastElementChild;
const button = (action) => card().querySelector(`[data-request-action="${action}"]`);
const click = (action) => button(action).click();
const lineEls = (root = list()) => Array.from(root.querySelectorAll(".wo-request-line"));

const requestGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}/requests`).length;

function type(input, value) {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

const settled = (cardEl = card()) => vi.waitFor(() => {
  const el = cardEl.querySelector(".wo-request-list");
  expect(el).not.toBeNull();
  expect(el.textContent).not.toContain("Loading requests…");
});

const material = (o = {}) => userRequest({ request_type: "material_request", ...o });

// One card, opened, with its Request section settled and the recorder clear.
async function open({ role = "admin", requests: seeded = [], catalogue: items = [], ...overrides } = {}) {
  const detail = workOrderDetail(overrides);
  const { currentUser } = await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
    items,
    requests: seeded,
  });
  await openCard(0);
  await settled();
  clearRequests();
  return { detail, me: currentUser };
}

// The mount function, off the instance the mount already loaded.
const pure = () => importView("views/workOrderRequests.js");

describe("pick and send", () => {
  const bulb = itemFactory({ id: "i-bulb", name: "Bulb", barcode: "B1", quantity: "10" });
  const empty = itemFactory({ id: "i-none", name: "Nothing", barcode: "N0", quantity: "0" });

  async function picked(item = bulb) {
    const mounted = await open({ catalogue: [bulb, empty] });
    type(search(), item.name);
    click("pick");
    return mounted;
  }

  it("pick stamps the item, fills the box, closes the list, reports stock and focuses the quantity", async () => {
    await picked();
    expect(form().dataset.itemId).toBe("i-bulb");
    expect(search().value).toBe("Bulb");
    expect(results().hidden).toBe(true);
    expect(results().innerHTML).toBe("");
    expect(onHand().textContent).toBe("10 on hand — Staff will verify the count.");
    expect(document.activeElement).toBe(qty());
  });

  it("pick on an item at zero says so without the verify note", async () => {
    await picked(empty);
    expect(onHand().textContent).toBe("0 on hand.");
  });

  it("send without a picked item asks for one", async () => {
    await open({ catalogue: [bulb] });
    click("send");
    expect(formMessage().textContent).toBe("Search and pick an item first.");
    expect(formMessage().className).toBe("error");
    expect(requests()).toEqual([]);
  });

  it.each([["0"], ["-2"], ["abc"]])("send refuses a quantity of %s", async (value) => {
    await picked();
    // DEFECT (N-P7-CHARACTERIZED): an `input[type=number]` hands "abc" back as
    // "", and Number("") is 0, so the `<= 0` half answers; `!isFinite` is dead.
    qty().value = value;
    click("send");
    expect(formMessage().textContent).toBe("Enter a quantity greater than zero.");
    expect(formMessage().className).toBe("error");
    expect(requests()).toEqual([]);
  });

  it("send refuses an invalid product link and focuses it", async () => {
    await picked();
    link().value = "not a link";
    click("send");
    expect(formMessage().textContent).toBe("Enter a valid product link.");
    expect(document.activeElement).toBe(link());
    expect(requests()).toEqual([]);
    // DEFECT (N-P7-CHARACTERIZED): the message's class is gone, so a second
    // Send would find no `.wo-request-message` and reject on null.
    expect(form().querySelector(".wo-request-message")).toBeNull();
  });

  it("send posts the request, refetches the list and reports", async () => {
    const { detail } = await picked();
    respond("post", "/user-requests/material-request", { id: "new", updated: false });
    qty().value = "2.5";
    link().value = " https://example.com/bulb ";
    note().value = " keep it ";
    const btn = button("send");
    const staleForm = form();
    click("send");
    expect(btn.disabled).toBe(true);
    expect(formMessage().textContent).toBe("Sending…");
    expect(formMessage().className).toBe("");
    state.requests = [material({ id: "new", status: "open", item_name: "Bulb" })];
    await vi.waitFor(() => expect(requestGets(detail.id)).toBe(1));
    expect(requestFor("/user-requests/material-request", "POST").body).toEqual({
      item_id: "i-bulb", work_order_id: String(detail.id), quantity: 2.5,
      product_link: "https://example.com/bulb", note: "keep it",
    });
    await vi.waitFor(() => expect(formMessage().textContent).toBe("Request sent. Staff have been notified."));
    expect(formMessage().className).toBe("success");
    // The section was rebuilt: a fresh form, the new line in the list.
    expect(form()).not.toBe(staleForm);
    expect(button("send").disabled).toBe(false);
    expect(search().value).toBe("");
    expect(lineEls().map((l) => l.querySelector(".wo-request-name").textContent)).toEqual(["Bulb"]);
  });

  it("send nulls a blank link and note, and reports an update as such", async () => {
    const { detail } = await picked();
    respond("post", "/user-requests/material-request", { id: "old", updated: true });
    click("send");
    await vi.waitFor(() => expect(requestGets(detail.id)).toBe(1));
    expect(requestFor("/user-requests/material-request", "POST").body).toEqual({
      item_id: "i-bulb", work_order_id: String(detail.id), quantity: 1, product_link: null, note: null,
    });
    await vi.waitFor(() => expect(formMessage().textContent).toBe("Updated your earlier request."));
    expect(formMessage().className).toBe("success");
  });

  it("a failed send re-enables the button and shows the detail, without a refetch", async () => {
    const { detail } = await picked();
    respond("post", "/user-requests/material-request", { detail: "boom" }, { status: 500 });
    const btn = button("send");
    click("send");
    await vi.waitFor(() => expect(formMessage().textContent).toBe("boom"));
    expect(formMessage().className).toBe("error");
    expect(btn.disabled).toBe(false);
    expect(form().dataset.itemId).toBe("i-bulb");
    expect(requestGets(detail.id)).toBe(0);
  });

  it("a failed send with no detail falls back to the fixed copy", async () => {
    await picked();
    respond("post", "/user-requests/material-request", { detail: "" }, { status: 500 });
    click("send");
    await vi.waitFor(() => expect(formMessage().textContent).toBe("Could not send that request."));
  });
});

describe("cancel", () => {
  const mine = (me) => material({ id: "r1", status: "open", created_by_id: me });

  it("No leaves the request alone", async () => {
    const { me } = await open({ requests: [] });
    state.requests = [mine(me.id)];
    const { mountWorkOrderRequests } = await pure();
    await mountWorkOrderRequests(card(), { id: card().dataset.id });
    clearRequests();
    click("cancel");
    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    expect(document.getElementById("scan-confirm-title").textContent).toBe("Cancel this material request?");
    await answerConfirm(false);
    await quiet();
    expect(requests()).toEqual([]);
    expect(button("cancel").disabled).toBe(false);
  });

  it("Yes disables the button, posts the cancel and refetches", async () => {
    const detail = workOrderDetail();
    const { currentUser } = await mountWorkOrders({
      cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
    });
    state.requests = [mine(currentUser.id)];
    await openCard(0);
    await settled();
    clearRequests();
    respond("post", "/user-requests/:id/cancel", { ok: true });
    const btn = button("cancel");
    state.requests = [];
    click("cancel");
    await answerConfirm(true);
    expect(btn.disabled).toBe(true);
    await vi.waitFor(() => expect(requestGets(detail.id)).toBe(1));
    expect(requestFor("/user-requests/r1/cancel", "POST").body).toEqual({});
    await vi.waitFor(() => expect(list().textContent).toContain("No open requests on this work order."));
    expect(button("cancel")).toBeNull();
  });

  it("a failed cancel re-enables the button and reports in the card's message", async () => {
    const detail = workOrderDetail();
    const { currentUser } = await mountWorkOrders({
      cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
    });
    state.requests = [mine(currentUser.id)];
    await openCard(0);
    await settled();
    clearRequests();
    respond("post", "/user-requests/:id/cancel", { detail: "" }, { status: 500 });
    const btn = button("cancel");
    click("cancel");
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().textContent).toBe("Could not cancel that request."));
    expect(message().className).toBe("error");
    expect(btn.disabled).toBe(false);
    expect(btn.isConnected).toBe(true);
    expect(requestGets(detail.id)).toBe(0);
  });
});

describe("add-requested", () => {
  const stocked = material({
    id: "s1", status: "stocked", item_id: "i9", item_name: "Bulb", details: { quantity: "4" },
  });

  it("prefills the add row, stamps the request id, opens Materials and focuses the quantity", async () => {
    await open({ requests: [stocked] });
    const materials = card().querySelector(".wo-materials-section");
    expect(materials.open).toBe(false);
    click("add-requested");
    const container = card().querySelector(".wo-add-item");
    expect(container.dataset.itemId).toBe("i9");
    expect(container.dataset.materialRequestId).toBe("s1");
    expect(container.querySelector(".ms-item-search").value).toBe("Bulb");
    expect(container.querySelector(".wo-item-qty").value).toBe("4");
    expect(container.querySelector(".ms-item-results").hidden).toBe(true);
    expect(container.querySelector(".ms-item-results").innerHTML).toBe("");
    expect(materials.open).toBe(true);
    expect(document.activeElement).toBe(container.querySelector(".wo-item-qty"));
    expect(requests()).toEqual([]);
  });

  it("does nothing without an add row to fill", async () => {
    await open({ requests: [stocked] });
    card().querySelector(".wo-add-item").remove();
    click("add-requested");
    expect(card().querySelector(".wo-materials-section").open).toBe(false);
  });

  it("a request action outside any card is ignored", async () => {
    await open({ requests: [stocked] });
    const stray = document.createElement("button");
    stray.dataset.requestAction = "add-requested";
    document.body.append(stray);
    stray.click();
    expect(card().querySelector(".wo-materials-section").open).toBe(false);
    expect(requests()).toEqual([]);
  });
});

describe("realtime user_request.changed", () => {
  async function expanded(count, activePage = "work-orders") {
    const details = Array.from({ length: count }, (_, i) => workOrderDetail({ number: `100${i}` }));
    await mountWorkOrders({
      cards: details.map((d) => workOrderCard({ id: d.id, number: d.number })),
      details,
    });
    const cards = [];
    for (let i = 0; i < count; i += 1) {
      cards.push(await expandCard(i));
      await settled(cards[i]);
    }
    rt = await connectFakeRealtime(activePage);
    clearRequests();
    return { details, cards };
  }

  it("refetches every open card", async () => {
    const { details } = await expanded(2);
    rt.emit("user_request.changed");
    await vi.waitFor(() => {
      expect(requestGets(details[0].id)).toBe(1);
      expect(requestGets(details[1].id)).toBe(1);
    });
    expect(requests()).toHaveLength(2);
  });

  it("skips a card with focus inside an open section, and refetches the others", async () => {
    const { details, cards } = await expanded(2);
    const section = cards[0].querySelector(".wo-request-section");
    section.open = true;
    section.querySelector(".wo-request-search").focus();
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(requestGets(details[1].id)).toBe(1));
    await quiet();
    expect(requestGets(details[0].id)).toBe(0);
  });

  it("an open section without focus does not hold the card", async () => {
    const { details, cards } = await expanded(1);
    cards[0].querySelector(".wo-materials-section").open = true;
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(requestGets(details[0].id)).toBe(1));
  });

  it("skips a closed card", async () => {
    const detail = workOrderDetail();
    await mountWorkOrders({
      cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
    });
    rt = await connectFakeRealtime("work-orders");
    expect(cardEls()[0].open).toBe(false);
    rt.emit("user_request.changed");
    await quiet();
    expect(requests()).toEqual([]);
  });

  it("does not gate on the active page", async () => {
    const { details } = await expanded(1, "history");
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(requestGets(details[0].id)).toBe(1));
  });
});
