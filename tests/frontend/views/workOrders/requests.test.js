// Characterization coverage for views/workOrderRequests.js, first half: the
// card's Request section (form + list), the stocked Materials lines and the
// in-form item search. The four `data-request-action`s and the realtime
// refetch are in requestsActions.test.js; split only for this repo's
// 500-line cap, and requestsActionCoverage.test.js reads both.
//
// Mounted through P2's fixture: `workOrderList.js::paintDetail` calls
// `mountWorkOrderRequests(cardEl, detail, {items: getAllItems()})` on every
// card open, so `mountWorkOrders({requests, items})` + `openCard` is the
// production path.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import { importView } from "../../helpers/shell.js";
import {
  card, clearRequests, mountWorkOrders, openCard, requests, state,
} from "../../helpers/workOrders.js";
import {
  item as itemFactory, userRequest, workOrderCard, workOrderDetail,
} from "../../helpers/factories.js";

const REQUESTS_PATH = "/work-orders/:id/requests";
const fail = (detail = "") => HttpResponse.json({ detail }, { status: 500 });

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
const picks = () => Array.from(results().querySelectorAll('[data-request-action="pick"]'));
const lineEls = (root = list()) => Array.from(root.querySelectorAll(".wo-request-line"));

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
const catalogue = (o = {}) => userRequest({
  request_type: "catalogue_request", item_id: null, item_name: null,
  details: { searched_text: "Flux capacitor", quantity: "3" }, ...o,
});

// One card, opened, with its Request section settled and the recorder clear.
// `respondRequests` replaces the fixture's requests handler for this test; it
// has to be registered AFTER the mount, which installs the fixture's own.
async function open({
  role = "admin", requests: seeded = [], catalogue: items = [], respondRequests = null, ...overrides
} = {}) {
  const detail = workOrderDetail(overrides);
  const { currentUser } = await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
    items,
    requests: seeded,
  });
  if (respondRequests) server.use(http.get(REQUESTS_PATH, respondRequests));
  await openCard(0);
  await settled();
  clearRequests();
  return { detail, me: currentUser };
}

// The pure builders, off the instance the mount already loaded.
const pure = () => importView("views/workOrderRequests.js");
function parse(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

describe("mountWorkOrderRequests", () => {
  it("paints the form and the loading copy, then the list and the stocked lines", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const seen = [];
    const detail = workOrderDetail();
    await mountWorkOrders({
      cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
    });
    server.use(http.get(REQUESTS_PATH, async ({ params }) => {
      seen.push(params.id);
      await gate;
      return HttpResponse.json([
        material({ id: "r1", status: "open" }),
        material({ id: "r2", status: "stocked", item_name: "Tape" }),
      ]);
    }));
    await openCard(0);

    expect(seen).toEqual([String(detail.id)]);
    expect(list().innerHTML).toBe('<p class="hint">Loading requests…</p>');
    expect(lines().innerHTML).toBe("");
    const f = form();
    expect(f.querySelector(".hint").textContent)
      .toBe("Need a catalogue item the shelf does not have? Staff are notified as soon as you send it.");
    expect(search().placeholder).toBe("Search item by name or barcode");
    expect(search().getAttribute("autocomplete")).toBe("off");
    expect(qty().value).toBe("1");
    expect(qty().getAttribute("min")).toBe("0.01");
    expect(qty().getAttribute("step")).toBe("any");
    expect(qty().getAttribute("inputmode")).toBe("decimal");
    expect(qty().getAttribute("aria-label")).toBe("Quantity needed");
    expect(results().hidden).toBe(true);
    expect(results().className).toBe("wo-request-results scan-chooser");
    expect(onHand().getAttribute("aria-live")).toBe("polite");
    expect(link().type).toBe("url");
    expect(link().placeholder).toBe("Product link (optional)");
    expect(note().maxLength).toBe(500);
    expect(note().placeholder).toBe("Note (optional)");
    expect(button("send").textContent).toBe("Send request");
    expect(formMessage().className).toBe("wo-request-message");
    expect(formMessage().getAttribute("aria-live")).toBe("polite");

    release();
    await settled();
    expect(list().querySelector(".wo-request-heading").textContent).toBe("This work order's requests");
    expect(lineEls().map((l) => l.className)).toEqual(["wo-request-line wo-request-open", "wo-request-line wo-request-stocked"]);
    expect(lines().querySelectorAll(".wo-requested-line")).toHaveLength(1);
    expect(lines().querySelector(".wo-requested-text").textContent).toContain("Tape");
  });

  it("a failed load reports in the list and leaves the lines empty", async () => {
    await open({ requests: [material({ status: "stocked" })], respondRequests: () => fail() });
    expect(list().innerHTML).toBe('<p class="error">Could not load requests.</p>');
    expect(lines().innerHTML).toBe("");
    expect(form()).not.toBeNull();
  });

  it("a failure with a detail shows the detail", async () => {
    await open({ respondRequests: () => fail("boom") });
    expect(list().querySelector("p.error").textContent).toBe("boom");
  });
});

describe("requestListHtml", () => {
  it("lists live lines, then one collapsed group of resolved ones", async () => {
    await open({ requests: [
      catalogue({ id: "c1", status: "resolved" }),
      material({ id: "m1", status: "open" }),
      material({ id: "m2", status: "stocked" }),
      catalogue({ id: "c2", status: "resolved" }),
    ] });
    expect(lineEls().map((l) => l.className)).toEqual([
      "wo-request-line wo-request-open", "wo-request-line wo-request-stocked",
      "wo-request-line wo-request-resolved", "wo-request-line wo-request-resolved",
    ]);
    const group = list().querySelector("details.wo-request-resolved-group");
    expect(group.open).toBe(false);
    expect(group.querySelector("summary").textContent).toBe("Show resolved (2)");
    expect(group.querySelector("summary").className).toBe("hint");
    expect(lineEls(group)).toHaveLength(2);
    expect(list().textContent).not.toContain("No open requests");
  });

  it("with no live request says so, and with no resolved one renders no group", async () => {
    await open({ requests: [catalogue({ status: "resolved" })] });
    expect(list().querySelector("p.hint").textContent).toBe("No open requests on this work order.");
    expect(list().querySelector(".wo-request-resolved-group")).not.toBeNull();
    const { requestListHtml } = await pure();
    expect(parse(requestListHtml([], null)).querySelector(".wo-request-resolved-group")).toBeNull();
  });

  it("a line carries the type tag, the name, the quantity, the status and the creator with the time", async () => {
    const when = "2026-09-10T12:00:00Z";
    await open({ requests: [
      catalogue({ status: "open", created_by_name: "Sue <S>", created_at: when }),
      material({ status: "stocked", item_name: "Tape", details: { quantity: "4" } }),
    ] });
    const [c, m] = lineEls();
    const spans = (l) => Array.from(l.querySelectorAll("span"), (s) => s.textContent);
    expect(spans(c)).toEqual([
      "Catalogue", "Flux capacitor", "qty 3", "Open", `Sue <S> · ${new Date(when).toLocaleString()}`,
    ]);
    expect(c.querySelector(".wo-request-type").textContent).toBe("Catalogue");
    expect(c.querySelector(".wo-request-name").textContent).toBe("Flux capacitor");
    expect(c.querySelector(".wo-request-status").textContent).toBe("Open");
    expect(spans(m).slice(0, 4)).toEqual(["Material", "Tape", "qty 4", "Stocked"]);
  });

  it.each([
    ["a catalogue request with no searched text", catalogue({ details: {} }), "Unnamed item", "qty 1"],
    ["a catalogue request with null details", catalogue({ details: null }), "Unnamed item", "qty 1"],
    ["a material request with no item name", material({ item_name: null, details: null }), "Unknown item", "qty 1"],
  ])("%s falls back on the name and the quantity", async (_l, r, name, q) => {
    const { requestListHtml } = await pure();
    const line = parse(requestListHtml([r], null)).querySelector(".wo-request-line");
    expect(line.querySelector(".wo-request-name").textContent).toBe(name);
    expect(line.querySelectorAll("span")[2].textContent).toBe(q);
  });

  it.each([
    ["a missing creator and time", { created_by_name: null, created_at: null }, "Unknown · "],
    ["an unparseable time, kept raw", { created_at: "yesterday" }, "Test User · yesterday"],
    ["a parseable time, localised", { created_at: "2026-01-02T03:04:05Z" },
      `Test User · ${new Date("2026-01-02T03:04:05Z").toLocaleString()}`],
    ["an unknown status, labelled Open", { status: "weird" }, null],
  ])("%s", async (_l, o, creator) => {
    const { requestListHtml } = await pure();
    const line = parse(requestListHtml([material(o)], null)).querySelector(".wo-request-line");
    const spans = line.querySelectorAll("span");
    if (creator !== null) expect(spans[4].textContent).toBe(creator);
    else {
      expect(spans[3].textContent).toBe("Open");
      expect(line.className).toBe("wo-request-line wo-request-weird");
    }
  });

  // Cancel is the filer's, on a material request, while it is still open.
  it.each([
    ["material, open, mine", "material_request", "open", true, true],
    ["catalogue, open, mine", "catalogue_request", "open", true, false],
    ["material, stocked, mine", "material_request", "stocked", true, false],
    ["material, open, someone else's", "material_request", "open", false, false],
  ])("%s -> cancel %s", async (_l, request_type, status, mine, shown) => {
    const { requestListHtml } = await pure();
    const me = "me-1";
    const r = userRequest({ id: "r1", request_type, status, created_by_id: mine ? me : "other" });
    const btn = parse(requestListHtml([r], me)).querySelector('[data-request-action="cancel"]');
    if (!shown) { expect(btn).toBeNull(); return; }
    expect(btn.className).toBe("secondary-btn");
    expect(btn.dataset.requestId).toBe("r1");
    expect(btn.textContent).toBe("Cancel");
  });

  it("the mount compares against the signed-in user's id", async () => {
    const { me } = await open({ requests: [material({ status: "open", created_by_id: null })] });
    expect(button("cancel")).toBeNull();
    state.requests = [material({ status: "open", created_by_id: me.id })];
    // A refetch through the send path is asserted below; a direct remount
    // keeps this one about the id only.
    const { mountWorkOrderRequests } = await pure();
    await mountWorkOrderRequests(card(), { id: card().dataset.id });
    expect(button("cancel")).not.toBeNull();
  });
});

describe("stockedLinesHtml", () => {
  it("renders one line per stocked material request and nothing for the rest", async () => {
    const { stockedLinesHtml } = await pure();
    const html = stockedLinesHtml([
      material({ id: "s1", status: "stocked", item_id: "i1", item_name: "Tape <x>", item_quantity: "7",
        created_by_name: "Sue", details: { quantity: "4" } }),
      material({ status: "open" }),
      catalogue({ status: "stocked" }),
      material({ status: "resolved" }),
    ]);
    const all = parse(html).querySelectorAll(".wo-requested-line");
    expect(all).toHaveLength(1);
    const [line] = all;
    expect(line.dataset).toMatchObject({ requestId: "s1", itemId: "i1", itemName: "Tape <x>", quantity: "4" });
    expect(line.querySelector(".wo-requested-text").textContent)
      .toBe("Tape <x> · requested 4 · on hand 7 · by Sue");
    const btn = line.querySelector("button");
    expect(btn.dataset.requestAction).toBe("add-requested");
    expect(btn.textContent).toBe("Add requested material");
    expect(stockedLinesHtml([])).toBe("");
  });

  it("falls back per field: unnamed item, unknown on-hand, quantity 1, unknown creator", async () => {
    const { stockedLinesHtml } = await pure();
    const line = parse(stockedLinesHtml([material({
      status: "stocked", item_name: null, item_quantity: null, created_by_name: null, details: null,
    })])).querySelector(".wo-requested-line");
    expect(line.dataset.itemName).toBe("");
    expect(line.dataset.quantity).toBe("1");
    expect(line.querySelector(".wo-requested-text").textContent)
      .toBe("Unknown item · requested 1 · on hand ? · by Unknown");
    // `undefined` also reads as "?": the `??` fallback, not `||`.
    const zero = parse(stockedLinesHtml([material({ status: "stocked", item_quantity: "0" })]));
    expect(zero.querySelector(".wo-requested-text").textContent).toContain("on hand 0");
  });
});

describe("the search inside the Request form", () => {
  const bulb = itemFactory({ id: "i-bulb", name: "Bulb", barcode: "B1", quantity: "10" });
  const tape = itemFactory({ id: "i-tape", name: "Tape", barcode: "ZZ9", quantity: "0" });

  it("ignores input in any other field", async () => {
    await open({ catalogue: [bulb] });
    type(note(), "bulb");
    type(card().querySelector(".wo-notes-input"), "bulb");
    expect(results().hidden).toBe(true);
    expect(results().innerHTML).toBe("");
  });

  it("matches by name or barcode with pick buttons carrying the item", async () => {
    await open({ catalogue: [bulb, tape] });
    type(search(), "zz9");
    expect(results().hidden).toBe(false);
    expect(picks()).toHaveLength(1);
    const [btn] = picks();
    expect(btn.className).toBe("secondary-btn scan-choice-btn");
    expect(btn.dataset).toMatchObject({ requestAction: "pick", itemId: "i-tape", itemName: "Tape", itemQuantity: "0" });
    expect(btn.textContent).toBe("Tape ZZ9");
    expect(btn.querySelector(".ms-pick-barcode").textContent).toBe("ZZ9");
    type(search(), "BULB");
    expect(picks().map((b) => b.dataset.itemName)).toEqual(["Bulb"]);
    expect(requests()).toEqual([]);
  });

  it("caps the list at eight", async () => {
    const items = Array.from({ length: 12 }, (_, i) => itemFactory({ name: `Bulb ${i}`, barcode: `B${i}` }));
    await open({ catalogue: items });
    type(search(), "bulb");
    expect(picks()).toHaveLength(8);
  });

  it("a blank or whitespace box hides and empties the list", async () => {
    await open({ catalogue: [bulb] });
    type(search(), "bulb");
    type(search(), "   ");
    expect(results().hidden).toBe(true);
    expect(results().innerHTML).toBe("");
  });

  it("typing again drops the picked item and the on-hand line", async () => {
    await open({ catalogue: [bulb] });
    type(search(), "bulb");
    click("pick");
    expect(form().dataset.itemId).toBe("i-bulb");
    type(search(), "bul");
    expect(form().dataset.itemId).toBeUndefined();
    expect(onHand().textContent).toBe("");
    expect(results().hidden).toBe(false);
  });

  it("no match offers the catalogue prompt from the Request card", async () => {
    const { detail } = await open({ catalogue: [bulb] });
    type(search(), "  flux capacitor ");
    expect(results().hidden).toBe(false);
    expect(results().querySelector("p.hint").textContent).toBe("No matching items.");
    const prompt = results().querySelector(".catalogue-request");
    expect(prompt.dataset.source).toBe("request_card");
    expect(prompt.dataset.workOrderId).toBe(String(detail.id));
    expect(prompt.dataset.searchedText).toBe("flux capacitor");
  });
});

