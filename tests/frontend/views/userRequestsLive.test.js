// W5: a live update patches the User Requests list in place. Open panels and
// typed fields survive, changed cards glow, a removed card is never removed
// silently, stale responses are dropped and an action's message stays.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  answerConfirm, cardFor, clearRequests, confirmOverlay, connectUserRequests, el, listRequests,
  openUserRequests, panelOf, requestFor, requests, restoreUserRequests, tab,
} from "../helpers/userRequests.js";
import { userRequest } from "../helpers/factories.js";

afterEach(() => {
  restoreUserRequests();
  vi.useRealTimers();
});

const DROPPED = "A request you were working on was closed or moved by someone else.";
const material = (o = {}) => userRequest(o);
const catalogue = (o = {}) => userRequest({
  request_type: "catalogue_request", item_id: null, item_name: null,
  details: { searched_text: "Flux capacitor", quantity: "1", note: null }, ...o,
});
const recount = (o = {}) => userRequest({
  request_type: "inventory_recount",
  details: { recorded_quantity_before: "5", dispensed_quantity: "3", shortage_quantity: "2" }, ...o,
});
const missingPrice = (o = {}) => userRequest({
  request_type: "missing_item_price", details: { work_order_numbers: ["12345"] },
  item_price: "12.5", item_product_link: "https://example.com/p", ...o,
});

const q = (id, selector) => cardFor(id).querySelector(selector);
const glows = (id) => cardFor(id).classList.contains("just-changed");
const countsLoaded = () => requests().some((r) => r.url.startsWith("/user-requests/counts"));

// Open on `type`'s tab with `seeded` as the server's list (mutate it to change
// what the next load returns) and a live socket.
async function open(seeded, type = "material_request") {
  const mounted = await openUserRequests({ requests: seeded });
  if (type !== "material_request") {
    tab(type).click();
    await vi.waitFor(() => expect(countsLoaded()).toBe(true));
  }
  const rt = await connectUserRequests();
  clearRequests();
  return { ...mounted, rt };
}

// Fire one live event and wait until its load has painted.
async function live(rt) {
  clearRequests();
  rt.emit("user_request.changed");
  await vi.waitFor(() => expect(countsLoaded()).toBe(true));
}

function type(input, value) {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("patch in place", () => {
  it("an open Fulfil panel keeps its search and pick; only the new card glows", async () => {
    const seeded = [catalogue({ id: "c1" })];
    server.use(http.get("/user-requests/c1/siblings", () => HttpResponse.json([])));
    const { rt } = await open(seeded, "catalogue_request");
    q("c1", ".user-request-fulfill-open").click();
    await vi.waitFor(() => expect(q("c1", ".user-request-item-search")).not.toBeNull());
    const panel = panelOf(cardFor("c1"));
    q("c1", ".user-request-item-search").value = "elbow";
    panel.dataset.pickedItemId = "item-9";

    seeded.unshift(catalogue({ id: "c2" }));
    await live(rt);

    expect(cardFor("c2")).not.toBeNull();
    expect(panelOf(cardFor("c1"))).toBe(panel);
    expect(q("c1", ".user-request-item-search").value).toBe("elbow");
    expect(panel.dataset.pickedItemId).toBe("item-9");
    expect(glows("c2")).toBe(true);
    expect(glows("c1")).toBe(false);
  });

  it("an open Edit panel keeps its typing while the card around it updates", async () => {
    const seeded = [material({ id: "m1" })];
    const { rt } = await open(seeded);
    q("m1", ".user-request-edit-open").click();
    q("m1", ".user-request-edit-message").value = "mine";

    seeded[0] = { ...seeded[0], message: "Changed by someone else" };
    await live(rt);

    expect(q("m1", ".user-request-edit-message").value).toBe("mine");
    expect(q("m1", ".user-request-alert").textContent).toBe("Changed by someone else");
    expect(glows("m1")).toBe(true);
  });

  it("an open Close panel is kept", async () => {
    const seeded = [catalogue({ id: "c1" })];
    const { rt } = await open(seeded, "catalogue_request");
    q("c1", ".user-request-close-open").click();
    q("c1", ".user-request-close-reason").value = "dup";
    await live(rt);
    expect(q("c1", ".user-request-close-reason").value).toBe("dup");
    expect(glows("c1")).toBe(false);
  });

  it("a typed recount survives", async () => {
    const seeded = [recount({ id: "r1" })];
    const { rt } = await open(seeded, "inventory_recount");
    q("r1", ".user-request-count-input").value = "7";
    q("r1", ".user-request-count-reason").value = "counted";
    seeded[0] = { ...seeded[0], message: "Recount again" };
    await live(rt);
    expect(q("r1", ".user-request-count-input").value).toBe("7");
    expect(q("r1", ".user-request-count-reason").value).toBe("counted");
  });

  it("a typed price stays; an untouched prefilled price takes the server's new one", async () => {
    const seeded = [missingPrice({ id: "p1" }), missingPrice({ id: "p2" })];
    const { rt } = await open(seeded, "missing_item_price");
    q("p1", ".user-request-price-input").value = "20";
    seeded[0] = { ...seeded[0], item_price: "14" };
    seeded[1] = { ...seeded[1], item_price: "14" };
    await live(rt);
    expect(q("p1", ".user-request-price-input").value).toBe("20");
    expect(q("p2", ".user-request-price-input").value).toBe("14");
  });

  it("a focused field is kept even untyped", async () => {
    const seeded = [missingPrice({ id: "p1" })];
    const { rt } = await open(seeded, "missing_item_price");
    const input = q("p1", ".user-request-price-input");
    input.focus();
    seeded[0] = { ...seeded[0], item_price: "14" };
    await live(rt);
    expect(input.value).toBe("12.5");
    expect(document.activeElement).toBe(input);
  });

  it("a card removed with its panel open goes, and the message says so", async () => {
    const seeded = [catalogue({ id: "c1" }), catalogue({ id: "c2" })];
    const { rt } = await open(seeded, "catalogue_request");
    q("c1", ".user-request-close-open").click();
    seeded.shift();
    await live(rt);
    expect(cardFor("c1")).toBeNull();
    expect(el.message().textContent).toBe(DROPPED);
  });

  it("a card removed with nothing open or typed just goes; the count updates", async () => {
    const seeded = [material({ id: "m1" }), material({ id: "m2" })];
    const { rt } = await open(seeded);
    seeded.shift();
    await live(rt);
    expect(cardFor("m1")).toBeNull();
    expect(el.message().textContent).toBe("1 open request.");
  });

  it("a button in a card the patch inserted works", async () => {
    const seeded = [material({ id: "m1" })];
    server.use(http.post("/user-requests/m2/mark-stocked", () => HttpResponse.json(material({ id: "m2", status: "stocked" }))));
    const { rt } = await open(seeded);
    seeded.push(material({ id: "m2" }));
    await live(rt);
    q("m2", ".user-request-stock").click();
    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    await answerConfirm(true);
    await vi.waitFor(() => expect(requestFor("/user-requests/m2/mark-stocked", "POST")).toBeTruthy());
  });

  it("an own Edit save closes that panel only, with no someone-else message", async () => {
    const seeded = [material({ id: "m1" }), material({ id: "m2" })];
    server.use(http.patch("/user-requests/m1", () => HttpResponse.json(seeded[0])));
    await open(seeded);
    q("m1", ".user-request-edit-open").click();
    q("m2", ".user-request-edit-open").click();
    q("m2", ".user-request-edit-message").value = "theirs";
    q("m1", ".user-request-edit-save").click();
    await vi.waitFor(() => expect(panelOf(cardFor("m1")).children).toHaveLength(0));
    expect(q("m2", ".user-request-edit-message").value).toBe("theirs");
    expect(el.message().textContent).not.toBe(DROPPED);
  });

  it("an own price save that removes its typed card is not blamed on someone else", async () => {
    const seeded = [missingPrice({ id: "p1", item_id: "i1" }), missingPrice({ id: "p2" })];
    server.use(http.patch("/items/i1", () => {
      seeded.shift();
      return HttpResponse.json({});
    }));
    await open(seeded, "missing_item_price");
    q("p1", ".user-request-price-input").value = "20";
    q("p1", ".user-request-price-save").click();
    await vi.waitFor(() => expect(cardFor("p1")).toBeNull());
    expect(el.message().textContent).toBe("1 open request.");
  });

  it("a tab change draws a new list: nothing glows, no panel carries over", async () => {
    const seeded = [material({ id: "m1" }), catalogue({ id: "c1" })];
    const { rt } = await open(seeded);
    q("m1", ".user-request-edit-open").click();
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("c1")).not.toBeNull());
    expect(glows("c1")).toBe(false);
    tab("material_request").click();
    await vi.waitFor(() => expect(cardFor("m1")).not.toBeNull());
    expect(panelOf(cardFor("m1")).children).toHaveLength(0);
    expect(glows("m1")).toBe(false);
    void rt;
  });

  it("Admin Review's focus still outlines the card and focuses its price", async () => {
    const seeded = [missingPrice({ id: "p1", item_id: "i1" })];
    const { mod } = await open(seeded);
    mod.focusMissingPriceRequest({ itemId: "i1", itemName: "Bulb" });
    await mod.loadUserRequests();
    expect(cardFor("p1").classList.contains("user-request-card-highlight")).toBe(true);
    expect(document.activeElement).toBe(q("p1", ".user-request-price-input"));
  });
});

describe("ordering and the message line", () => {
  // The list handler answers the Nth call after `delays[N]` ms with `lists[N]`.
  function scripted(lists, delays) {
    let n = 0;
    server.use(http.get("/user-requests/", async () => {
      const i = n++;
      await new Promise((r) => setTimeout(r, delays[i] ?? 0));
      return HttpResponse.json(lists[i] ?? lists.at(-1));
    }));
  }

  it("two live loads answered in reverse: the newer list wins", async () => {
    const { rt } = await open([material({ id: "m1" })]);
    scripted([[material({ id: "old" })], [material({ id: "new" })]], [60, 0]);
    rt.emit("user_request.changed");
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(cardFor("new")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 90));
    expect(cardFor("old")).toBeNull();
    expect(cardFor("new")).not.toBeNull();
  });

  it("a tab change drops the old tab's late answer", async () => {
    const { rt } = await open([material({ id: "m1" })]);
    scripted([[material({ id: "late" })], [catalogue({ id: "c1" })]], [60, 0]);
    rt.emit("user_request.changed");
    tab("catalogue_request").click();
    await vi.waitFor(() => expect(cardFor("c1")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 90));
    expect(cardFor("late")).toBeNull();
  });

  it("an action's error stays through a live update; the list still patches", async () => {
    const seeded = [recount({ id: "r1" })];
    const { rt } = await open(seeded, "inventory_recount");
    q("r1", ".user-request-count-save").click();
    expect(el.message().textContent).toBe("Enter the corrected count (zero or more).");
    seeded.push(recount({ id: "r2" }));
    await live(rt);
    expect(cardFor("r2")).not.toBeNull();
    expect(el.message().textContent).toBe("Enter the corrected count (zero or more).");
  });

  it("a showing count follows a live update", async () => {
    const seeded = [material({ id: "m1" })];
    const { rt } = await open(seeded);
    expect(el.message().textContent).toBe("1 open request.");
    seeded.push(material({ id: "m2" }));
    await live(rt);
    expect(el.message().textContent).toBe("2 open requests.");
  });

  it("a live load shows no Loading line; Refresh does", async () => {
    const { rt } = await open([material({ id: "m1" })]);
    scripted([[material({ id: "m1" })]], [40, 40]);
    rt.emit("user_request.changed");
    await vi.waitFor(() => expect(listRequests()).toHaveLength(1));
    expect(el.message().textContent).toBe("1 open request.");
    el.refresh().click();
    expect(el.message().textContent).toBe("Loading open requests...");
  });
});
