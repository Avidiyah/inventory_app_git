// Characterization coverage for the catalogue-request fulfilment panel in
// views/userRequests.js: the siblings proposal, the debounced item search,
// the pick, both modes' payloads, the confirm clause and the `skipped` notes.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  answerConfirm, cardFor, clearRequests, confirmOverlay, confirmTitle, el, listRequests,
  openUserRequests, panelOf, requestFor, requests, restoreUserRequests, tab,
} from "../helpers/userRequests.js";
import { item, userRequest } from "../helpers/factories.js";

afterEach(() => {
  restoreUserRequests();
  vi.useRealTimers();
});

const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
// Actions are named by their bare class so the audit (which matches the
// quoted name) can see which behaviour file drives each one.
const sel = (name) => `.${name}`;
const catalogue = (o = {}) => userRequest({
  id: "c1", request_type: "catalogue_request", item_id: null, item_name: null,
  details: { searched_text: "Flux capacitor", quantity: "2", note: null }, ...o,
});

// Mount on the Catalogue tab, open the panel, wait for the siblings answer.
async function openPanel({ siblings = [], request = catalogue(), items = [] } = {}) {
  server.use(
    http.get(`/user-requests/${request.id}/siblings`, () =>
      siblings === "fail" ? fail() : HttpResponse.json(siblings)),
    http.get("/items/", ({ request: req }) => {
      const q = new URL(req.url).searchParams.get("q") ?? "";
      return HttpResponse.json(items.filter((i) => i.name.toLowerCase().includes(q.toLowerCase())));
    }),
  );
  const mounted = await openUserRequests({ requests: [request] });
  tab("catalogue_request").click();
  await vi.waitFor(() => expect(cardFor(request.id)).not.toBeNull());
  cardFor(request.id).querySelector(sel("user-request-fulfill-open")).click();
  await vi.waitFor(() => expect(
    panelOf(cardFor(request.id)).querySelector(".user-request-siblings .hint")?.textContent,
  ).not.toContain("Checking for"));
  clearRequests();
  return { ...mounted, request, card: () => cardFor(request.id), panel: () => panelOf(cardFor(request.id)) };
}

const q = (ctx, selector) => ctx.panel().querySelector(selector);
const setValue = (ctx, selector, value) => { q(ctx, selector).value = value; };
const type = (ctx, text) => {
  const input = q(ctx, ".user-request-item-search");
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
};
const chooseMode = (ctx, value) => {
  const radio = ctx.panel().querySelector(`.user-request-mode[value="${value}"]`);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
};

async function confirmTitled(expected, yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  expect(confirmTitle()).toBe(expected);
  await answerConfirm(yes);
}

describe("opening", () => {
  it("paints the form in link mode with the searched text in both the search and the new name", async () => {
    const ctx = await openPanel();
    expect(q(ctx, '.user-request-mode[value="link"]').checked).toBe(true);
    expect(q(ctx, ".user-request-item-search").value).toBe("Flux capacitor");
    expect(q(ctx, ".user-request-new-name").value).toBe("Flux capacitor");
    expect(q(ctx, ".user-request-link-pane").hidden).toBe(false);
    expect(q(ctx, ".user-request-create-pane").hidden).toBe(true);
    expect(q(ctx, ".user-request-new-qty").value).toBe("0");
  });

  it("no siblings: the no-match hint", async () => {
    const ctx = await openPanel();
    expect(q(ctx, ".user-request-siblings").textContent).toContain("No other open requests match this material.");
  });

  it("siblings: pre-checked rows naming the work order, the closed case and the absent case", async () => {
    const ctx = await openPanel({ siblings: [
      userRequest({ id: "s1", request_type: "catalogue_request", work_order_number: "777",
        details: { searched_text: "flux cap", quantity: "3" }, created_by_name: "Ada" }),
      userRequest({ id: "s2", request_type: "catalogue_request", work_order_number: "778", work_order_archived: true,
        details: { searched_text: "flux" }, created_by_name: null }),
      userRequest({ id: "s3", request_type: "catalogue_request", work_order_number: null, details: {} }),
    ] });
    const boxes = Array.from(ctx.panel().querySelectorAll(".user-request-sibling-check"));
    expect(boxes.map((b) => b.value)).toEqual(["s1", "s2", "s3"]);
    expect(boxes.every((b) => b.checked)).toBe(true);
    const rows = Array.from(ctx.panel().querySelectorAll(".user-request-sibling span")).map((s) => s.textContent);
    expect(rows[0]).toBe('"flux cap" — 777, qty 3, Ada');
    expect(rows[1]).toBe('"flux" — 778 (closed — will be skipped), qty 1, Unknown');
    expect(rows[2]).toBe('"" — no work order, qty 1, Test User');
    expect(q(ctx, ".user-request-siblings-title").textContent).toContain("Also close these 3 requests for the same material?");
    expect(q(ctx, '[data-tip="requests.siblings"]')).not.toBeNull();
  });

  it("one sibling reads singular", async () => {
    const ctx = await openPanel({ siblings: [userRequest({ id: "s1", request_type: "catalogue_request", details: {} })] });
    expect(q(ctx, ".user-request-siblings-title").textContent).toContain("Also close these 1 request for");
  });

  it("a failed siblings check keeps the form and says fulfilling closes this one only", async () => {
    const ctx = await openPanel({ siblings: "fail" });
    expect(q(ctx, ".user-request-siblings").textContent)
      .toBe("Could not check for related requests. Fulfilling will close this one only.");
    expect(q(ctx, sel("user-request-fulfill-save"))).not.toBeNull();
  });

  it("the mode radios swap the panes; Cancel empties the panel", async () => {
    const ctx = await openPanel();
    chooseMode(ctx, "create");
    expect(q(ctx, ".user-request-link-pane").hidden).toBe(true);
    expect(q(ctx, ".user-request-create-pane").hidden).toBe(false);
    chooseMode(ctx, "link");
    expect(q(ctx, ".user-request-create-pane").hidden).toBe(true);
    q(ctx, sel("user-request-fulfill-cancel")).click();
    expect(ctx.panel().innerHTML).toBe("");
  });
});

describe("the item search", () => {
  it("debounces 250 ms, then lists up to eight picks with the barcode and the price", async () => {
    vi.useFakeTimers();
    const items = Array.from({ length: 9 }, (_, i) => item({ name: `Bulb ${i}`, barcode: `B${i}`, price: i ? "1.00" : null }));
    const ctx = await openPanel({ items });
    type(ctx, "bul");
    vi.advanceTimersByTime(249);
    expect(requests()).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(requestFor("/items/", "GET").url).toBe("/items/?q=bul");
    await vi.waitFor(() => expect(ctx.panel().querySelectorAll(sel("user-request-item-pick"))).toHaveLength(8));
    const first = q(ctx, sel("user-request-item-pick"));
    expect(first.dataset.itemId).toBe(String(items[0].id));
    expect(first.dataset.itemName).toBe("Bulb 0");
    expect(first.querySelector(".ms-pick-barcode").textContent).toBe("B0");
    expect(first.querySelector(".hint").textContent).toBe("no price");
    expect(ctx.panel().querySelectorAll(sel("user-request-item-pick"))[1].querySelector(".hint").textContent).toBe("$1.00");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a second keystroke inside the window cancels the first search", async () => {
    vi.useFakeTimers();
    const ctx = await openPanel();
    type(ctx, "a");
    vi.advanceTimersByTime(200);
    type(ctx, "ab");
    vi.advanceTimersByTime(250);
    expect(requests().filter((r) => r.url.startsWith("/items/"))).toHaveLength(1);
    expect(requestFor("/items/", "GET").url).toBe("/items/?q=ab");
    await vi.waitFor(() => expect(q(ctx, ".user-request-item-results .hint")).not.toBeNull());
    expect(q(ctx, ".user-request-item-results").textContent)
      .toContain('No catalogue item matches that. Switch to "Create a new item".');
  });

  it("a blank box empties the results without a request and clears the pick", async () => {
    vi.useFakeTimers();
    const ctx = await openPanel({ items: [item({ name: "Bulb" })] });
    type(ctx, "bulb");
    vi.advanceTimersByTime(250);
    await vi.waitFor(() => expect(q(ctx, sel("user-request-item-pick"))).not.toBeNull());
    q(ctx, sel("user-request-item-pick")).click();
    expect(ctx.panel().dataset.pickedItemId).toBeDefined();
    expect(q(ctx, ".user-request-picked").textContent).toBe("Selected: Bulb");
    expect(q(ctx, ".user-request-item-results").innerHTML).toBe("");
    clearRequests();
    type(ctx, "   ");
    expect(ctx.panel().dataset.pickedItemId).toBeUndefined();
    expect(q(ctx, ".user-request-picked").textContent).toBe("");
    vi.advanceTimersByTime(250);
    expect(requests()).toHaveLength(0);
  });

  it("a failed search renders the error inside the results", async () => {
    vi.useFakeTimers();
    const ctx = await openPanel();
    server.use(http.get("/items/", fail));
    type(ctx, "x");
    vi.advanceTimersByTime(250);
    await vi.waitFor(() => expect(q(ctx, ".user-request-item-results .error")).not.toBeNull());
    expect(q(ctx, ".user-request-item-results .error").textContent).toBe("Could not search items.");
  });
});

describe("saving", () => {
  it("link mode without a pick is refused", async () => {
    const ctx = await openPanel();
    q(ctx, sel("user-request-fulfill-save")).click();
    expect(el.message().textContent).toBe("Search and pick an item first.");
    expect(requests()).toHaveLength(0);
  });

  it("create mode requires barcode, name and location in that order", async () => {
    const ctx = await openPanel();
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-name", "");
    for (const [field, copy] of [
      [".user-request-new-barcode", "Enter a barcode for the new item."],
      [".user-request-new-name", "Enter a name for the new item."],
      [".user-request-new-location", "Enter a location for the new item."],
    ]) {
      q(ctx, sel("user-request-fulfill-save")).click();
      expect(el.message().textContent).toBe(copy);
      setValue(ctx, field, "x");
    }
    expect(requests()).toHaveLength(0);
  });

  it("link mode: confirm, POST the item id and the checked siblings, reload", async () => {
    vi.useFakeTimers();
    const bulb = item({ name: "Bulb" });
    const ctx = await openPanel({ items: [bulb], siblings: [
      userRequest({ id: "s1", request_type: "catalogue_request", details: {} }),
      userRequest({ id: "s2", request_type: "catalogue_request", details: {} }),
    ] });
    server.use(http.post("/user-requests/c1/fulfill", () => HttpResponse.json(catalogue({ status: "resolved" }))));
    type(ctx, "bulb");
    vi.advanceTimersByTime(250);
    vi.useRealTimers();
    await vi.waitFor(() => expect(q(ctx, sel("user-request-item-pick"))).not.toBeNull());
    q(ctx, sel("user-request-item-pick")).click();
    ctx.panel().querySelector('.user-request-sibling-check[value="s2"]').checked = false;
    const save = q(ctx, sel("user-request-fulfill-save"));
    save.click();
    await confirmTitled("Fulfil this catalogue request? This will also close 1 related request and add the material to their work orders.");
    expect(save.disabled).toBe(true);
    await vi.waitFor(() => expect(listRequests()).toHaveLength(1));
    expect(requestFor("/user-requests/c1/fulfill", "POST").body)
      .toEqual({ item_id: String(bulb.id), new_item: null, sibling_ids: ["s1"] });
    expect(el.message().className).not.toBe("error");
  });

  it("create mode: the plain confirm, the new-item body with blanks as null and the qty as a number", async () => {
    const ctx = await openPanel();
    server.use(http.post("/user-requests/c1/fulfill", () => HttpResponse.json(catalogue({ status: "resolved" }))));
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-barcode", " NB1 ");
    setValue(ctx, ".user-request-new-location", "A1");
    setValue(ctx, ".user-request-new-qty", "");
    q(ctx, sel("user-request-fulfill-save")).click();
    await confirmTitled("Fulfil this catalogue request?");
    await vi.waitFor(() => expect(requestFor("/user-requests/c1/fulfill", "POST")).not.toBeNull());
    expect(requestFor("/user-requests/c1/fulfill", "POST").body).toEqual({
      item_id: null, sibling_ids: [],
      new_item: { barcode: "NB1", name: "Flux capacitor", location: "A1", quantity: 0, price: null, product_link: null },
    });
  });

  it("create mode: price and link are numbers / strings when given; plural siblings in the confirm", async () => {
    const ctx = await openPanel({ siblings: [
      userRequest({ id: "s1", request_type: "catalogue_request", details: {} }),
      userRequest({ id: "s2", request_type: "catalogue_request", details: {} }),
    ] });
    server.use(http.post("/user-requests/c1/fulfill", () => HttpResponse.json(catalogue({ status: "resolved" }))));
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-barcode", "NB1");
    setValue(ctx, ".user-request-new-location", "A1");
    setValue(ctx, ".user-request-new-qty", "5");
    setValue(ctx, ".user-request-new-price", "2.50");
    setValue(ctx, ".user-request-new-link", "https://x.test/p");
    q(ctx, sel("user-request-fulfill-save")).click();
    await confirmTitled("Fulfil this catalogue request? This will also close 2 related requests and add the material to their work orders.");
    await vi.waitFor(() => expect(requestFor("/user-requests/c1/fulfill", "POST")).not.toBeNull());
    const body = requestFor("/user-requests/c1/fulfill", "POST").body;
    expect(body.new_item.quantity).toBe(5);
    expect(body.new_item.price).toBe(2.5);
    expect(body.new_item.product_link).toBe("https://x.test/p");
    expect(body.sibling_ids).toEqual(["s1", "s2"]);
  });

  it("No leaves the panel open and writes nothing", async () => {
    const ctx = await openPanel();
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-barcode", "NB1");
    setValue(ctx, ".user-request-new-location", "A1");
    q(ctx, sel("user-request-fulfill-save")).click();
    await confirmTitled("Fulfil this catalogue request?", false);
    expect(requests()).toHaveLength(0);
    expect(q(ctx, ".user-request-fulfill")).not.toBeNull();
  });

  it("skip notes from the fulfilment land as an error message after the reload", async () => {
    const ctx = await openPanel();
    server.use(http.post("/user-requests/c1/fulfill", () =>
      HttpResponse.json(catalogue({ status: "resolved", skipped: ["WO 778 is closed.", "WO 779 is closed."] }))));
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-barcode", "NB1");
    setValue(ctx, ".user-request-new-location", "A1");
    q(ctx, sel("user-request-fulfill-save")).click();
    await confirmTitled("Fulfil this catalogue request?");
    await vi.waitFor(() => expect(el.message().textContent).toBe("WO 778 is closed. WO 779 is closed."));
    expect(el.message().className).toBe("error");
    expect(listRequests()).toHaveLength(1);
  });

  it("a failure re-enables the button with the fulfil copy", async () => {
    const ctx = await openPanel();
    server.use(http.post("/user-requests/c1/fulfill", fail));
    chooseMode(ctx, "create");
    setValue(ctx, ".user-request-new-barcode", "NB1");
    setValue(ctx, ".user-request-new-location", "A1");
    const save = q(ctx, sel("user-request-fulfill-save"));
    save.click();
    await confirmTitled("Fulfil this catalogue request?");
    await vi.waitFor(() => expect(el.message().textContent).toBe("Could not fulfil that request."));
    expect(save.disabled).toBe(false);
    expect(listRequests()).toHaveLength(0);
  });
});
