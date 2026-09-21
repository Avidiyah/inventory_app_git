// Characterization coverage for the row actions in views/userRequests.js
// other than fulfilment (userRequestsFulfil.test.js): resolve / reopen,
// mark stocked, the per-type edit panel, the recount correction, and the
// price + link save. Every confirm resolves through the real overlay.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  answerConfirm, cardFor, clearRequests, confirmOverlay, confirmTitle, el, listRequests,
  openUserRequests, panelOf, requestFor, requests, restoreUserRequests, tab,
} from "../helpers/userRequests.js";
import { userRequest } from "../helpers/factories.js";

afterEach(() => restoreUserRequests());

const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
// Actions are named by their bare class so the audit (which matches the
// quoted name) can see which behaviour file drives each one.
const sel = (name) => `.${name}`;
const patched = () => HttpResponse.json(userRequest());

// Mount with one request on its own tab, and hand back a live getter.
async function withCard(request, { status = "open" } = {}) {
  const mounted = await openUserRequests({ requests: [request] });
  if (status !== "open") el.status().value = status;
  if (request.request_type !== "material_request") tab(request.request_type).click();
  else if (status !== "open") el.status().dispatchEvent(new Event("change"));
  await vi.waitFor(() => expect(cardFor(request.id)).not.toBeNull());
  clearRequests();
  return { ...mounted, request, card: () => cardFor(request.id) };
}

const click = (card, selector) => card.querySelector(selector).click();
const set = (card, selector, value) => { card.querySelector(selector).value = value; };

async function confirmTitled(expected, yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  expect(confirmTitle()).toBe(expected);
  await answerConfirm(yes);
}

const reloaded = () => listRequests().length > 0;

describe("resolve / reopen", () => {
  it("Resolve: confirm, PATCH the status with the other keys null, reload", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    server.use(http.patch("/user-requests/m1", patched));
    const button = ctx.card().querySelector(sel("user-request-action"));
    button.click();
    await confirmTitled("Resolve this user request?");
    expect(button.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/user-requests/m1", "PATCH").body)
      .toEqual({ status: "resolved", resolution_note: null, message: null, details: null });
  });

  it("Reopen on a resolved request uses the reopen copy and PATCHes open", async () => {
    const ctx = await withCard(userRequest({ id: "m1", status: "resolved" }), { status: "resolved" });
    server.use(http.patch("/user-requests/m1", patched));
    click(ctx.card(), sel("user-request-action"));
    await confirmTitled("Reopen this user request?");
    await vi.waitFor(() => expect(requestFor("/user-requests/m1", "PATCH")).not.toBeNull());
    expect(requestFor("/user-requests/m1", "PATCH").body.status).toBe("open");
  });

  it("No writes nothing", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    click(ctx.card(), sel("user-request-action"));
    await confirmTitled("Resolve this user request?", false);
    expect(requests()).toHaveLength(0);
    expect(ctx.card().querySelector(sel("user-request-action")).disabled).toBe(false);
  });

  it("a failure re-enables the button and names the verb", async () => {
    const ctx = await withCard(userRequest({ id: "m1", status: "resolved" }), { status: "resolved" });
    server.use(http.patch("/user-requests/m1", fail));
    const button = ctx.card().querySelector(sel("user-request-action"));
    button.click();
    await confirmTitled("Reopen this user request?");
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not reopen that request."));
    expect(el.message().className).toBe("error");
    expect(button.disabled).toBe(false);
    expect(reloaded()).toBe(false);
  });
});

describe("close a catalogue request without fulfilling", () => {
  const catalogue = () => userRequest({
    id: "c1", request_type: "catalogue_request", item_id: null, item_name: null,
    details: { searched_text: "Flux", quantity: "1", note: null },
  });

  it("opens the reason panel; Cancel empties it", async () => {
    const ctx = await withCard(catalogue());
    click(ctx.card(), sel("user-request-close-open"));
    const panel = panelOf(ctx.card());
    expect(panel.querySelector(".user-request-close-reason").value).toBe("");
    expect(panel.querySelector(".hint").textContent).toContain("without adding an item");
    click(ctx.card(), sel("user-request-close-cancel"));
    expect(panel.innerHTML).toBe("");
  });

  it("a blank reason is refused and focused, writing nothing", async () => {
    const ctx = await withCard(catalogue());
    click(ctx.card(), sel("user-request-close-open"));
    set(ctx.card(), ".user-request-close-reason", "   ");
    click(ctx.card(), sel("user-request-close-save"));
    expect(el.message().textContent).toBe("Enter a reason for closing this request.");
    expect(document.activeElement).toBe(ctx.card().querySelector(".user-request-close-reason"));
    expect(requests()).toHaveLength(0);
  });

  it("PATCHes resolved with the trimmed reason, then reloads", async () => {
    const ctx = await withCard(catalogue());
    server.use(http.patch("/user-requests/c1", patched));
    click(ctx.card(), sel("user-request-close-open"));
    set(ctx.card(), ".user-request-close-reason", " Duplicate ");
    const save = ctx.card().querySelector(sel("user-request-close-save"));
    save.click();
    expect(save.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/user-requests/c1", "PATCH").body)
      .toEqual({ status: "resolved", resolution_note: "Duplicate", message: null, details: null });
  });

  it("a failure re-enables the button with the close copy and keeps the panel", async () => {
    const ctx = await withCard(catalogue());
    server.use(http.patch("/user-requests/c1", fail));
    click(ctx.card(), sel("user-request-close-open"));
    set(ctx.card(), ".user-request-close-reason", "Duplicate");
    const save = ctx.card().querySelector(sel("user-request-close-save"));
    save.click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not close that request."));
    expect(save.disabled).toBe(false);
    expect(panelOf(ctx.card()).querySelector(".user-request-close")).not.toBeNull();
  });
});

describe("mark stocked", () => {
  it("confirms, POSTs mark-stocked with an empty body, reloads", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    server.use(http.post("/user-requests/m1/mark-stocked", patched));
    const button = ctx.card().querySelector(sel("user-request-stock"));
    button.click();
    await confirmTitled("Mark this item as stocked and notify the crew?");
    expect(button.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/user-requests/m1/mark-stocked", "POST").body).toEqual({});
  });

  it("No writes nothing; a failure re-enables with its own copy", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    click(ctx.card(), sel("user-request-stock"));
    await confirmTitled("Mark this item as stocked and notify the crew?", false);
    expect(requests()).toHaveLength(0);

    server.use(http.post("/user-requests/m1/mark-stocked", fail));
    const button = ctx.card().querySelector(sel("user-request-stock"));
    button.click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not mark that request stocked."));
    expect(button.disabled).toBe(false);
  });
});

describe("edit", () => {
  it("material: the qty / link / note fields prefilled; Cancel empties the panel", async () => {
    const ctx = await withCard(userRequest({ id: "m1", details: {
      quantity: "2", product_link: "https://x.test/p", note: "hi",
    } }));
    click(ctx.card(), sel("user-request-edit-open"));
    const panel = panelOf(ctx.card());
    expect(panel.querySelector(".user-request-edit-qty").value).toBe("2");
    expect(panel.querySelector(".user-request-edit-link").value).toBe("https://x.test/p");
    expect(panel.querySelector(".user-request-edit-note").value).toBe("hi");
    expect(panel.querySelector(".user-request-edit-message").value).toBe("Need more bulbs");
    expect(panel.querySelector(".user-request-edit-text")).toBeNull();
    click(ctx.card(), sel("user-request-edit-cancel"));
    expect(panel.innerHTML).toBe("");
  });

  it("material: a blank message, then an invalid link, are refused in that order", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    click(ctx.card(), sel("user-request-edit-open"));
    set(ctx.card(), ".user-request-edit-message", "  ");
    click(ctx.card(), sel("user-request-edit-save"));
    expect(el.message().textContent).toBe("The message cannot be blank.");
    set(ctx.card(), ".user-request-edit-message", "reworded");
    set(ctx.card(), ".user-request-edit-link", "not a url");
    click(ctx.card(), sel("user-request-edit-save"));
    expect(el.message().textContent).toBe("Enter a valid product link.");
    expect(requests()).toHaveLength(0);
  });

  it("material: PATCHes message + details with blanks as '1' / null, then reloads", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    server.use(http.patch("/user-requests/m1", patched));
    click(ctx.card(), sel("user-request-edit-open"));
    set(ctx.card(), ".user-request-edit-message", " reworded ");
    set(ctx.card(), ".user-request-edit-qty", "");
    set(ctx.card(), ".user-request-edit-link", "");
    set(ctx.card(), ".user-request-edit-note", "");
    const save = ctx.card().querySelector(sel("user-request-edit-save"));
    save.click();
    expect(save.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/user-requests/m1", "PATCH").body).toEqual({
      status: null, resolution_note: null, message: "reworded",
      details: { quantity: "1", product_link: null, note: null },
    });
  });

  it("catalogue: the searched text is required; details carry text / qty / note", async () => {
    const ctx = await withCard(userRequest({
      id: "c1", request_type: "catalogue_request",
      details: { searched_text: "Flux", quantity: "3", note: null },
    }));
    server.use(http.patch("/user-requests/c1", patched));
    click(ctx.card(), sel("user-request-edit-open"));
    expect(ctx.card().querySelector(".user-request-edit-text").value).toBe("Flux");
    set(ctx.card(), ".user-request-edit-text", " ");
    click(ctx.card(), sel("user-request-edit-save"));
    expect(el.message().textContent).toBe("Describe the item that was searched for.");
    set(ctx.card(), ".user-request-edit-text", "Flux capacitor");
    set(ctx.card(), ".user-request-edit-note", "sweat type");
    click(ctx.card(), sel("user-request-edit-save"));
    await vi.waitFor(() => expect(requestFor("/user-requests/c1", "PATCH")).not.toBeNull());
    expect(requestFor("/user-requests/c1", "PATCH").body.details)
      .toEqual({ searched_text: "Flux capacitor", quantity: "3", note: "sweat type" });
  });

  it("recount and missing price: the snapshot hint, details null", async () => {
    const ctx = await withCard(userRequest({ id: "r1", request_type: "inventory_recount", details: {} }));
    server.use(http.patch("/user-requests/r1", patched));
    click(ctx.card(), sel("user-request-edit-open"));
    expect(panelOf(ctx.card()).querySelector(".hint").textContent).toContain("cannot be edited");
    expect(panelOf(ctx.card()).querySelector(".user-request-edit-qty")).toBeNull();
    click(ctx.card(), sel("user-request-edit-save"));
    await vi.waitFor(() => expect(requestFor("/user-requests/r1", "PATCH")).not.toBeNull());
    expect(requestFor("/user-requests/r1", "PATCH").body).toEqual({
      status: null, resolution_note: null, message: "Need more bulbs", details: null,
    });
  });

  it("a failed save re-enables the button and keeps the panel", async () => {
    const ctx = await withCard(userRequest({ id: "m1" }));
    server.use(http.patch("/user-requests/m1", fail));
    click(ctx.card(), sel("user-request-edit-open"));
    const save = ctx.card().querySelector(sel("user-request-edit-save"));
    save.click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not save those changes."));
    expect(save.disabled).toBe(false);
    expect(panelOf(ctx.card()).querySelector(".user-request-edit")).not.toBeNull();
  });
});

describe("count correction", () => {
  const recount = () => userRequest({ id: "r1", item_id: "i1", request_type: "inventory_recount", details: {} });

  it("refuses a blank, non-numeric or negative count, then a blank reason, focusing each", async () => {
    const ctx = await withCard(recount());
    for (const raw of ["", "abc", "-1"]) {
      set(ctx.card(), ".user-request-count-input", raw);
      click(ctx.card(), sel("user-request-count-save"));
      expect(el.message().textContent).toBe("Enter the corrected count (zero or more).");
      expect(document.activeElement).toBe(ctx.card().querySelector(".user-request-count-input"));
    }
    set(ctx.card(), ".user-request-count-input", "0");
    click(ctx.card(), sel("user-request-count-save"));
    expect(el.message().textContent).toBe("Enter a reason for the correction.");
    expect(document.activeElement).toBe(ctx.card().querySelector(".user-request-count-reason"));
    expect(requests()).toHaveLength(0);
  });

  it("POSTs the adjust with the item id, the number and the reason, then reloads", async () => {
    const ctx = await withCard(recount());
    server.use(http.post("/transactions/adjust", () => HttpResponse.json({})));
    set(ctx.card(), ".user-request-count-input", "4");
    set(ctx.card(), ".user-request-count-reason", " recounted ");
    const save = ctx.card().querySelector(sel("user-request-count-save"));
    save.click();
    expect(save.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/transactions/adjust", "POST").body)
      .toEqual({ item_id: "i1", new_quantity: 4, reason: "recounted" });
  });

  it("a failure re-enables with the count copy", async () => {
    const ctx = await withCard(recount());
    server.use(http.post("/transactions/adjust", fail));
    set(ctx.card(), ".user-request-count-input", "4");
    set(ctx.card(), ".user-request-count-reason", "r");
    const save = ctx.card().querySelector(sel("user-request-count-save"));
    save.click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not save that count."));
    expect(save.disabled).toBe(false);
  });
});

describe("price + link", () => {
  const priced = () => userRequest({ id: "p1", item_id: "i1", request_type: "missing_item_price", details: {} });

  it("refuses a blank or non-positive price, then a blank or invalid link", async () => {
    const ctx = await withCard(priced());
    for (const raw of ["", "0", "-2"]) {
      set(ctx.card(), ".user-request-price-input", raw);
      click(ctx.card(), sel("user-request-price-save"));
      expect(el.message().textContent).toBe("Enter an item price greater than $0.00.");
      expect(document.activeElement).toBe(ctx.card().querySelector(".user-request-price-input"));
    }
    set(ctx.card(), ".user-request-price-input", "2.5");
    for (const raw of ["", "not a url"]) {
      set(ctx.card(), ".user-request-link-input", raw);
      click(ctx.card(), sel("user-request-price-save"));
      expect(el.message().textContent).toBe("Enter a valid product link.");
      expect(document.activeElement).toBe(ctx.card().querySelector(".user-request-link-input"));
    }
    expect(requests()).toHaveLength(0);
  });

  it("PATCHes the item with the number and the link, then reloads", async () => {
    const ctx = await withCard(priced());
    server.use(http.patch("/items/i1", () => HttpResponse.json({})));
    set(ctx.card(), ".user-request-price-input", "2.5");
    set(ctx.card(), ".user-request-link-input", " https://x.test/p ");
    const save = ctx.card().querySelector(sel("user-request-price-save"));
    save.click();
    expect(save.disabled).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
    expect(requestFor("/items/i1", "PATCH").body).toEqual({ price: 2.5, product_link: "https://x.test/p" });
  });

  it("a failure re-enables with the price copy", async () => {
    const ctx = await withCard(priced());
    server.use(http.patch("/items/i1", fail));
    set(ctx.card(), ".user-request-price-input", "2.5");
    set(ctx.card(), ".user-request-link-input", "https://x.test/p");
    const save = ctx.card().querySelector(sel("user-request-price-save"));
    save.click();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not save that item price."));
    expect(save.disabled).toBe(false);
  });
});
