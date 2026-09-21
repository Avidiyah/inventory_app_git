// Characterization coverage for views/userRequests.js (the queue: tabs,
// status, counts, refresh, the realtime reload) and views/userRequestCards.js
// (one card per request type and status). The row actions are in
// userRequestsActions.test.js and userRequestsFulfil.test.js.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  actionsOf, cardFor, cards, connectUserRequests, el, hintsOf, listRequests,
  openUserRequests, requests, restoreUserRequests, statusOptions, tab, tabCount,
} from "../helpers/userRequests.js";
import { importView } from "../helpers/shell.js";
import { item, userRequest } from "../helpers/factories.js";

afterEach(() => {
  restoreUserRequests();
  vi.useRealTimers();
});

// The four types, each with the `details` its body reads.
const material = (o = {}) => userRequest(o);
const catalogue = (o = {}) => userRequest({
  request_type: "catalogue_request", item_id: null, item_name: null, item_barcode: null,
  item_quantity: null, details: { searched_text: "Flux capacitor", quantity: "1", note: null }, ...o,
});
const recount = (o = {}) => userRequest({
  request_type: "inventory_recount",
  details: { recorded_quantity_before: "5", dispensed_quantity: "3", shortage_quantity: "2" }, ...o,
});
const missingPrice = (o = {}) => userRequest({
  request_type: "missing_item_price", details: { work_order_numbers: ["12345", "12346"] }, ...o,
});

const details = (card) => card.querySelector(".user-request-details").textContent;
const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
// Actions are named by their bare class so the audit (which matches the
// quoted name) can see which behaviour file drives each one.
const sel = (name) => `.${name}`;

describe("tabs and status", () => {
  it("lands on Material requests with Open / Stocked / Resolved offered", async () => {
    await openUserRequests();
    expect(tab("material_request").classList.contains("active")).toBe(true);
    expect(tab("material_request").getAttribute("aria-selected")).toBe("true");
    expect(tab("catalogue_request").getAttribute("aria-selected")).toBe("false");
    expect(statusOptions()).toEqual(["open", "stocked", "resolved"]);
    expect(el.status().value).toBe("open");
  });

  it("a tab click swaps the active tab, drops Stocked, and reloads that type only", async () => {
    await openUserRequests({ requests: [material(), catalogue({ id: "c1" })] });
    expect(cards()).toHaveLength(1);
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("c1")).not.toBeNull());
    expect(cards()).toHaveLength(1);
    expect(tab("catalogue_request").classList.contains("active")).toBe(true);
    expect(tab("material_request").getAttribute("aria-selected")).toBe("false");
    expect(statusOptions()).toEqual(["open", "resolved"]);
    expect(listRequests().at(-1).url).toBe("/user-requests/?status=open&type=catalogue_request");
  });

  it("keeps the status when the new tab still offers it, else falls to open", async () => {
    await openUserRequests();
    el.status().value = "resolved";
    tab("inventory_recount").click();
    expect(el.status().value).toBe("resolved");
    tab("material_request").click();
    el.status().value = "stocked";
    tab("missing_item_price").click();
    expect(el.status().value).toBe("open");
    await vi.waitFor(() => expect(listRequests()).toHaveLength(3));
    expect(listRequests().at(-1).url).toBe("/user-requests/?status=open&type=missing_item_price");
  });

  it("a click on the tab strip outside a tab does nothing", async () => {
    await openUserRequests();
    el.tabs().click();
    expect(requests()).toHaveLength(0);
  });

  it("paints open counts per tab, blank for zero or missing", async () => {
    await openUserRequests({ counts: {
      material_request: { open: 2, stocked: 1 }, catalogue_request: { open: 0 },
    } });
    await vi.waitFor(() => expect(tabCount("material_request")).toBe("(2)"));
    expect(tabCount("catalogue_request")).toBe("");
    expect(tabCount("inventory_recount")).toBe("");
  });

  it("a failed counts request leaves the list and the labels alone", async () => {
    const { mod } = await openUserRequests({ requests: [material({ id: "m1" })], handlers: [
      http.get("/user-requests/counts", fail),
    ] });
    await mod.loadUserRequests();
    expect(cardFor("m1")).not.toBeNull();
    expect(tabCount("material_request")).toBe("");
  });

  it("Refresh and a status change each reload", async () => {
    await openUserRequests();
    el.refresh().click();
    await vi.waitFor(() => expect(listRequests()).toHaveLength(1));
    el.status().value = "resolved";
    el.status().dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(listRequests()).toHaveLength(2));
    expect(listRequests().at(-1).url).toBe("/user-requests/?status=resolved&type=material_request");
  });

  it("shows the loading copy, then the empty copy", async () => {
    const { mod } = await openUserRequests();
    const pending = mod.loadUserRequests();
    expect(el.message().textContent).toBe("Loading open requests...");
    await pending;
    expect(el.message().textContent).toBe("No open material requests.");
    expect(el.message().className).toBe("success");
  });

  it("counts one request in the singular, more in the plural", async () => {
    await openUserRequests({ requests: [material()] });
    expect(el.message().textContent).toBe("1 open request.");
    expect(el.message().className).toBe("");
  });

  it("counts two requests in the plural", async () => {
    await openUserRequests({ requests: [material(), material()] });
    expect(el.message().textContent).toBe("2 open requests.");
  });

  it("the empty copy names the status and the tab", async () => {
    await openUserRequests();
    el.status().value = "resolved";
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("No resolved catalogue requests."));
  });

  it("a failed list empties the cards and shows the fallback copy", async () => {
    const { mod } = await openUserRequests({ requests: [material({ id: "m1" })] });
    expect(cardFor("m1")).not.toBeNull();
    server.use(http.get("/user-requests/", fail));
    await mod.loadUserRequests();
    expect(cards()).toHaveLength(0);
    expect(el.message().textContent).toBe("Could not load User Requests.");
    expect(el.message().className).toBe("error");
  });
});

describe("realtime", () => {
  it("user_request.changed reloads when the page is showing", async () => {
    await openUserRequests();
    const rt = await connectUserRequests("user-requests");
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(listRequests()).toHaveLength(1));
  });

  it("and does nothing on another page", async () => {
    await openUserRequests();
    const rt = await connectUserRequests("history");
    rt.emit("user_request.changed");
    await new Promise((r) => setTimeout(r, 0));
    expect(requests()).toHaveLength(0);
  });

  it("a recovered connection reloads too", async () => {
    await openUserRequests();
    const rt = await connectUserRequests("user-requests");
    vi.useFakeTimers();
    rt.reconnect();
    vi.advanceTimersByTime(1000);
    rt.ws.last().emitOpen();
    expect(listRequests()).toHaveLength(1);
    await vi.runAllTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("the card", () => {
  it("carries the id, item id and type as data, and the status and type as classes", async () => {
    const r = material({ id: "m1", item_id: "i1" });
    await openUserRequests({ requests: [r] });
    const card = cardFor("m1");
    expect(card.tagName).toBe("ARTICLE");
    expect(card.className).toBe("user-request-card user-request-open user-request-type-material_request");
    expect(card.dataset.itemId).toBe("i1");
    expect(card.dataset.requestType).toBe("material_request");
    expect(card.querySelector(".user-request-type").textContent).toBe("Material request");
    expect(card.querySelector("h3").textContent).toBe("Bulb");
    expect(card.querySelector(".user-request-status").textContent).toBe("Open");
    expect(card.querySelector(".user-request-alert").textContent).toBe("Need more bulbs");
    expect(card.querySelector(".user-request-panel").innerHTML).toBe("");
  });

  it("a null item id is an empty data attribute; a missing name is 'Unknown item'", async () => {
    await openUserRequests({ requests: [material({ id: "m1", item_id: null, item_name: null })] });
    expect(cardFor("m1").dataset.itemId).toBe("");
    expect(cardFor("m1").querySelector("h3").textContent).toBe("Unknown item");
  });

  it("material body: every line, the link with rel=noopener, Unknown requester", async () => {
    await openUserRequests({ requests: [material({ id: "m1", created_by_name: null, details: {
      quantity: "2", product_link: "https://x.test/p", note: "urgent",
    } })] });
    const text = details(cardFor("m1"));
    for (const line of [
      "Barcode: B1", "Work order: 12345", "Quantity requested: 2", "Product link: https://x.test/p",
      "Note: urgent", "On hand now: 3", "Requested by: Unknown",
      `Filed: ${new Date("2026-09-10T12:00:00Z").toLocaleString()}`,
    ]) expect(text).toContain(line);
    const link = cardFor("m1").querySelector(".user-request-details a");
    expect(link.getAttribute("rel")).toBe("noopener");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(text).not.toContain("Stocked:");
    expect(text).not.toContain("Stock cycles");
  });

  it("material body: the Stocked line and the cycles line only past one cycle", async () => {
    await openUserRequests({ requests: [
      material({ id: "one", details: { quantity: "1", stocked_at: "2026-09-11T12:00:00Z", stock_cycles: 1 } }),
      material({ id: "two", details: { quantity: "1", stock_cycles: 2 } }),
    ] });
    expect(details(cardFor("one"))).toContain(`Stocked: ${new Date("2026-09-11T12:00:00Z").toLocaleString()}`);
    expect(details(cardFor("one"))).not.toContain("Stock cycles");
    expect(details(cardFor("two"))).toContain("Stock cycles: 2 — stocked 2 times, still not added");
  });

  it("catalogue body: the Find Item hint without a work order, 'Added as' once linked", async () => {
    await openUserRequests({ requests: [
      catalogue({ id: "c1", work_order_number: null, details: { searched_text: "Flux", quantity: "4", note: "n" } }),
      catalogue({ id: "c2", item_name: "Flux capacitor", details: { searched_text: "" } }),
    ] });
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("c1")).not.toBeNull());
    const text = details(cardFor("c1"));
    expect(text).toContain("Reported from Find Item — no work order attached.");
    expect(text).toContain("Quantity needed: 4");
    expect(text).toContain("Note: n");
    expect(cardFor("c1").querySelector("h3").textContent).toBe("Flux");
    expect(details(cardFor("c2"))).toContain("Work order: 12345");
    expect(details(cardFor("c2"))).toContain("Added as: Flux capacitor");
    expect(cardFor("c2").querySelector("h3").textContent).toBe("Unnamed item");
  });

  it("recount body: the three frozen figures", async () => {
    await openUserRequests({ requests: [recount({ id: "r1" })] });
    tab("inventory_recount").click();
    await vi.waitFor(() => expect(cardFor("r1")).not.toBeNull());
    const text = details(cardFor("r1"));
    expect(text).toContain("Recorded before: 5");
    expect(text).toContain("Dispensed: 3");
    expect(text).toContain("Shortage: 2");
    expect(cardFor("r1").querySelector(".user-request-type").textContent).toBe("Stock recount");
  });

  it("missing-price body: the numbers joined, or the single number", async () => {
    await openUserRequests({ requests: [
      missingPrice({ id: "p1" }), missingPrice({ id: "p2", details: {} }),
    ] });
    tab("missing_item_price").click();
    await vi.waitFor(() => expect(cardFor("p1")).not.toBeNull());
    expect(details(cardFor("p1"))).toContain("Work orders: 12345, 12346");
    expect(details(cardFor("p2"))).toContain("Work orders: 12345");
    expect(cardFor("p1").querySelector(".user-request-type").textContent).toBe("Missing price / link");
  });

  it("an open missing-price card prefills the price and link inputs from the item", async () => {
    await openUserRequests({ requests: [
      missingPrice({ id: "p1", item_price: "2.50", item_product_link: "https://x.test" }),
      missingPrice({ id: "p2" }),
    ] });
    tab("missing_item_price").click();
    await vi.waitFor(() => expect(cardFor("p1")).not.toBeNull());
    expect(cardFor("p1").querySelector(".user-request-price-input").value).toBe("2.50");
    expect(cardFor("p1").querySelector(".user-request-link-input").value).toBe("https://x.test");
    expect(cardFor("p2").querySelector(".user-request-price-input").value).toBe("");
  });

  it("the resolution block only on a resolved request, its Note only when present", async () => {
    await openUserRequests({ requests: [
      material({ id: "a", status: "resolved", resolved_at: "2026-09-12T12:00:00Z", resolution_note: "done" }),
      material({ id: "b", status: "resolved" }),
      material({ id: "c" }),
    ] });
    el.status().value = "resolved";
    el.status().dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    const a = cardFor("a").querySelector(".user-request-resolution").textContent;
    expect(a).toContain("Resolved by: Unknown");
    expect(a).toContain(`Resolved: ${new Date("2026-09-12T12:00:00Z").toLocaleString()}`);
    expect(a).toContain("Note: done");
    expect(cardFor("b").querySelector(".user-request-resolution").textContent).not.toContain("Note:");
    expect(cardFor("c")).toBeNull();
  });
});

describe("actions by type and status", () => {
  it("material: open offers stock + resolve + edit with the stocked tip", async () => {
    await openUserRequests({ requests: [material({ id: "m" })] });
    expect(actionsOf(cardFor("m"))).toEqual([
      "user-request-stock", "user-request-action secondary-btn", "secondary-btn user-request-edit-open",
    ]);
    expect(cardFor("m").querySelector('.user-request-actions [data-tip="requests.stocked"]')).not.toBeNull();
    expect(cardFor("m").querySelector(sel("user-request-action")).dataset.status).toBe("resolved");
  });

  it("material: stocked shows the waiting hint naming the work order, or 'the work order'", async () => {
    await openUserRequests({ requests: [
      material({ id: "a", status: "stocked" }), material({ id: "b", status: "stocked", work_order_number: null }),
    ] });
    el.status().value = "stocked";
    el.status().dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    expect(hintsOf(cardFor("a"))).toEqual(["Waiting for the crew to add it to 12345."]);
    expect(hintsOf(cardFor("b"))).toEqual(["Waiting for the crew to add it to the work order."]);
    expect(actionsOf(cardFor("a"))).toEqual(["user-request-action secondary-btn", "secondary-btn user-request-edit-open"]);
  });

  it("material: resolved offers Reopen + edit", async () => {
    await openUserRequests({ requests: [material({ id: "a", status: "resolved" })] });
    el.status().value = "resolved";
    el.status().dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    expect(actionsOf(cardFor("a"))).toEqual(["user-request-action secondary-btn", "secondary-btn user-request-edit-open"]);
    expect(cardFor("a").querySelector(sel("user-request-action")).dataset.status).toBe("open");
    expect(cardFor("a").querySelector(sel("user-request-action")).textContent).toBe("Reopen");
  });

  it("catalogue: open offers Fulfil + Close without fulfilling + Edit, with the closed-work-order warning when archived", async () => {
    await openUserRequests({ requests: [
      catalogue({ id: "a" }), catalogue({ id: "b", work_order_archived: true }),
      catalogue({ id: "c", work_order_archived: true, work_order_number: null }),
    ] });
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    expect(actionsOf(cardFor("a"))).toEqual([
      "user-request-fulfill-open", "secondary-btn user-request-close-open", "secondary-btn user-request-edit-open",
    ]);
    expect(cardFor("a").querySelector(sel("user-request-close-open")).textContent).toBe("Close without fulfilling");
    expect(cardFor("a").querySelector(".user-request-warning")).toBeNull();
    expect(cardFor("b").querySelector(".user-request-warning").textContent)
      .toBe("⚠ 12345 is closed. The item will still be created, but it will not be added to the work order.");
    expect(cardFor("c").querySelector(".user-request-warning").textContent).toContain("⚠ That work order is closed.");
  });

  it("catalogue: resolved with a linked item reads Fulfilled, naming the item when known, with no actions", async () => {
    await openUserRequests({ requests: [
      catalogue({ id: "a", status: "resolved", item_id: "i1", item_name: "Flux capacitor" }),
      catalogue({ id: "b", status: "resolved", item_id: "i2" }),
    ] });
    el.status().value = "resolved";
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    expect(hintsOf(cardFor("a"))).toEqual(["Fulfilled as Flux capacitor."]);
    expect(hintsOf(cardFor("b"))).toEqual(["Fulfilled."]);
    expect(actionsOf(cardFor("a"))).toEqual([]);
  });

  it("catalogue: resolved with no linked item reads Closed without fulfilling and offers Reopen", async () => {
    await openUserRequests({ requests: [catalogue({ id: "a", status: "resolved" })] });
    el.status().value = "resolved";
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("a")).not.toBeNull());
    expect(hintsOf(cardFor("a"))).toEqual(["Closed without fulfilling."]);
    expect(actionsOf(cardFor("a"))).toEqual(["user-request-action secondary-btn"]);
    expect(cardFor("a").querySelector(sel("user-request-action")).dataset.status).toBe("open");
    expect(cardFor("a").querySelector(sel("user-request-action")).textContent).toBe("Reopen");
  });

  it("recount: open offers the count fix (labelled input, recount tip) + resolve + edit", async () => {
    await openUserRequests({ requests: [recount({ id: "r1" })] });
    tab("inventory_recount").click();
    await vi.waitFor(() => expect(cardFor("r1")).not.toBeNull());
    const card = cardFor("r1");
    expect(card.querySelector("label[for='user-request-count-r1']").textContent).toBe("Correct count to");
    expect(card.querySelector("#user-request-count-r1").className).toBe("user-request-count-input");
    expect(card.querySelector('[data-tip="requests.recount"]')).not.toBeNull();
    expect(actionsOf(card)).toEqual([
      "user-request-count-save", "user-request-action", "secondary-btn user-request-edit-open",
    ]);
  });

  it("recount: resolved offers Reopen + edit", async () => {
    await openUserRequests({ requests: [recount({ id: "r1", status: "resolved" })] });
    el.status().value = "resolved";
    tab("inventory_recount").click();
    await vi.waitFor(() => expect(cardFor("r1")).not.toBeNull());
    expect(actionsOf(cardFor("r1"))).toEqual(["user-request-action secondary-btn", "secondary-btn user-request-edit-open"]);
    expect(cardFor("r1").querySelector(".user-request-count-fix")).toBeNull();
  });

  it("missing price: open offers the two inputs + save + edit; resolved the auto-resolved hint + edit", async () => {
    await openUserRequests({ requests: [missingPrice({ id: "p1" }), missingPrice({ id: "p2", status: "resolved" })] });
    tab("missing_item_price").click();
    await vi.waitFor(() => expect(cardFor("p1")).not.toBeNull());
    expect(actionsOf(cardFor("p1"))).toEqual(["user-request-price-save", "secondary-btn user-request-edit-open"]);
    expect(cardFor("p1").querySelector(".user-request-link-input").type).toBe("url");
    el.status().value = "resolved";
    el.status().dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(cardFor("p2")).not.toBeNull());
    expect(hintsOf(cardFor("p2"))).toEqual(["Resolved automatically when the item price and product link were added."]);
    expect(actionsOf(cardFor("p2"))).toEqual(["secondary-btn user-request-edit-open"]);
  });
});

describe("userRequestCards.js exports, by name", () => {
  it("formatDate, requestTypeLabel, statusLabel and the html builders", async () => {
    await openUserRequests();
    const m = await importView("views/userRequestCards.js");
    expect(m.formatDate(null)).toBe("Unknown time");
    expect(m.formatDate("not a date")).toBe("not a date");
    expect(m.formatDate("2026-09-10T12:00:00Z")).toBe(new Date("2026-09-10T12:00:00Z").toLocaleString());
    expect(m.requestTypeLabel("something_else")).toBe("something else");
    expect(m.statusLabel("anything")).toBe("Open");
    expect(m.buildRequestCard(material()).className).toContain("user-request-card");
    expect(m.editFormHtml(recount())).toContain("cannot be edited");
    expect(m.fulfillFormHtml(catalogue())).toContain('value="Flux capacitor"');
    expect(m.siblingsHtml([])).toContain("No other open requests match this material.");
    expect(m.itemChoiceHtml(item({ price: null }))).toContain("no price");
    expect(m.itemChoiceHtml(item({ price: "2.50" }))).toContain("$2.50");
  });
});
