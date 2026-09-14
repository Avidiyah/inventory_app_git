// Characterization coverage for views/lowStockCard.js: the body of an open
// Low Stock card -- the five core fields, the additional-barcode rows, the
// item save at the `saveItemCore` wire, and the audited count correction.
//
// P1 / P6d own `saveItemCore`'s ladder (barcodes first, the archived-reuse
// retry); this file asserts only which requests the card sends, with which
// bodies, and the card's own copy on success, cancel and failure.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { lowStockItem } from "../helpers/factories.js";
import { importView } from "../helpers/shell.js";
import {
  actionBtn, answerConfirm, cardFor, confirmOverlay, confirmTitle, editMessage, el, listGets,
  mountLowStock, requestFor, requests, restoreLowStock,
} from "../helpers/lowStock.js";

afterEach(() => restoreLowStock());

const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
const settle = () => new Promise((r) => setTimeout(r, 0));
const field = (card, cls) => card.querySelector(`.${cls}`);
const altRows = (card) => Array.from(card.querySelectorAll(".ls-barcode-row"));
const altCodes = (card) => altRows(card).map((r) => r.querySelector(".ls-alt-barcode").value);
const writes = () => requests().map((r) => [r.method, r.url]);
const itemPatch = (row) => http.patch("/items/:id", () => HttpResponse.json(row));
const barcodesPatch = (row) => http.patch("/items/:id/barcodes", () => HttpResponse.json(row));

// One row, its card open. `handlers` are the write endpoints the test expects
// to hit; the list GET is the fixture's.
async function openCard(overrides = {}, { handlers = [] } = {}) {
  const row = lowStockItem({ id: "i1", name: "Bulb", barcode: "B1", location: "A1", ...overrides });
  const mounted = await mountLowStock({ rows: [row], handlers });
  const card = cardFor("i1");
  card.open = true;
  return { ...mounted, row, card };
}

function fillCorrection(card, { qty, reason }) {
  if (qty !== undefined) field(card, "ls-correct-qty").value = qty;
  if (reason !== undefined) field(card, "ls-correct-reason").value = reason;
}

describe("the card body", () => {
  it("prefills the five fields, a row per additional code, and the correction count", async () => {
    const { card } = await openCard({
      price: "2.50", product_link: "https://x.test/p", barcodes: ["ALT1", "ALT2"], quantity: "2.00",
    });
    expect(field(card, "ls-name").value).toBe("Bulb");
    expect(field(card, "ls-barcode").value).toBe("B1");
    expect(field(card, "ls-location").value).toBe("A1");
    const price = field(card, "ls-price");
    expect(price.value).toBe("2.50");
    expect(price.type).toBe("number");
    expect(price.getAttribute("step")).toBe("0.01");
    expect(price.getAttribute("min")).toBe("0");
    const link = field(card, "ls-product-link");
    expect(link.value).toBe("https://x.test/p");
    expect(link.type).toBe("url");

    expect(altCodes(card)).toEqual(["ALT1", "ALT2"]);
    for (const row of altRows(card)) {
      const input = row.querySelector(".ls-alt-barcode");
      expect(input.placeholder).toBe("Additional barcode");
      expect(input.getAttribute("aria-label")).toBe("Additional barcode");
      const remove = actionBtn(row, "remove-barcode");
      expect(remove.className).toBe("note-remove-btn");
      expect(remove.getAttribute("aria-label")).toBe("Remove barcode");
      expect(remove.textContent).toBe("×");
    }
    expect(actionBtn(card, "add-barcode").textContent).toBe("Add barcode");
    expect(actionBtn(card, "add-barcode").className).toBe("secondary-btn");
    expect(actionBtn(card, "save-item").textContent).toBe("Save item");

    const qty = field(card, "ls-correct-qty");
    expect(qty.value).toBe("2");
    expect(qty.getAttribute("min")).toBe("0");
    expect(qty.getAttribute("step")).toBe("1");
    expect(field(card, "ls-correct-reason").value).toBe("");
    expect(field(card, "ls-correct-reason").placeholder).toBe("Why the count changed");
    expect(actionBtn(card, "save-correction").textContent).toBe("Save correction");
    expect(card.querySelector(".low-stock-correction h4").textContent).toBe("Correct the count");
    expect(editMessage(card).textContent).toBe("");
    expect(editMessage(card).getAttribute("aria-live")).toBe("polite");
  });

  it("a null price and link prefill as empty, and a non-list barcodes value paints no rows", async () => {
    const { card } = await openCard({ price: null, product_link: null, barcodes: null });
    expect(field(card, "ls-price").value).toBe("");
    expect(field(card, "ls-product-link").value).toBe("");
    expect(altRows(card)).toEqual([]);
  });
});

describe("the additional-barcode rows", () => {
  it("add-barcode appends an empty row", async () => {
    const { card } = await openCard({ barcodes: ["ALT1"] });
    actionBtn(card, "add-barcode").click();
    expect(altCodes(card)).toEqual(["ALT1", ""]);
    expect(altRows(card)[1].querySelector(".ls-alt-barcode").placeholder).toBe("Additional barcode");
    expect(requests()).toEqual([]);
  });

  it("remove-barcode removes its own row", async () => {
    const { card } = await openCard({ barcodes: ["ALT1", "ALT2"] });
    actionBtn(altRows(card)[0], "remove-barcode").click();
    expect(altCodes(card)).toEqual(["ALT2"]);
    expect(requests()).toEqual([]);
  });
});

describe("save-item", () => {
  it.each(["ls-barcode", "ls-name", "ls-location"])(
    "refuses a blank %s before any request", async (cls) => {
      const { card } = await openCard();
      field(card, cls).value = "   ";
      actionBtn(card, "save-item").click();
      await settle();
      expect(editMessage(card).textContent).toBe("Barcode, name, and location are required.");
      expect(editMessage(card).className).toBe("error");
      expect(requests()).toEqual([]);
    });

  it("refuses a duplicated additional code by name", async () => {
    const { card } = await openCard({ barcodes: ["ALT1"] });
    actionBtn(card, "add-barcode").click();
    altRows(card)[1].querySelector(".ls-alt-barcode").value = " ALT1 ";
    actionBtn(card, "save-item").click();
    await settle();
    expect(editMessage(card).textContent).toBe('The barcode "ALT1" is listed twice. Remove the duplicate.');
    expect(editMessage(card).className).toBe("error");
    expect(requests()).toEqual([]);
  });

  it("an unchanged list PATCHes the item alone, with the price parsed and a blank link null", async () => {
    const { card, row } = await openCard(
      { barcodes: ["ALT1"], price: "2.50", product_link: "https://x.test/p" },
      { handlers: [itemPatch(lowStockItem())] },
    );
    // A blank added row is skipped, so the list is still ["ALT1"].
    actionBtn(card, "add-barcode").click();
    field(card, "ls-price").value = "3.75";
    field(card, "ls-product-link").value = "  ";
    field(card, "ls-name").value = " Bulb, 60W ";
    actionBtn(card, "save-item").click();
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Item saved."));
    expect(editMessage(card).className).toBe("success");
    expect(requestFor(`/items/${row.id}`, "PATCH").body).toEqual({
      barcode: "B1", name: "Bulb, 60W", location: "A1", price: 3.75, product_link: null,
      override_archived: false,
    });
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
    expect(writes()).toEqual([["PATCH", "/items/i1"], ["GET", "/items/low-stock"]]);
    expect(el.message().textContent).toBe("");
    expect(cardFor("i1")).not.toBe(card);
  });

  it("a changed list PATCHes the barcodes first, then the item", async () => {
    const { card } = await openCard(
      { barcodes: ["ALT1"], price: null },
      { handlers: [itemPatch(lowStockItem()), barcodesPatch(lowStockItem())] },
    );
    actionBtn(altRows(card)[0], "remove-barcode").click();
    actionBtn(card, "add-barcode").click();
    altRows(card)[0].querySelector(".ls-alt-barcode").value = "ALT9";
    actionBtn(card, "save-item").click();
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Item saved."));
    expect(requestFor("/items/i1/barcodes", "PATCH").body).toEqual({ barcodes: ["ALT9"], override_archived: false });
    expect(requestFor("/items/i1", "PATCH").body).toEqual({
      barcode: "B1", name: "Bulb", location: "A1", price: null, product_link: null, override_archived: false,
    });
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
    expect(writes()).toEqual([
      ["PATCH", "/items/i1/barcodes"], ["PATCH", "/items/i1"], ["GET", "/items/low-stock"],
    ]);
  });

  it("a changed primary barcode asks first; No clears the message and sends nothing", async () => {
    const { card } = await openCard();
    const { BARCODE_CHANGE_WARNING } = await importView("itemSave.js");
    field(card, "ls-barcode").value = "B2";
    actionBtn(card, "save-item").click();
    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    expect(confirmTitle()).toBe(BARCODE_CHANGE_WARNING);
    await answerConfirm(false);
    await settle();
    expect(editMessage(card).textContent).toBe("");
    expect(editMessage(card).className).toBe("");
    expect(requests()).toEqual([]);
  });

  it("Yes sends both writes", async () => {
    const { card } = await openCard(
      { barcodes: [] },
      { handlers: [itemPatch(lowStockItem()), barcodesPatch(lowStockItem())] },
    );
    field(card, "ls-barcode").value = "B2";
    actionBtn(card, "add-barcode").click();
    altRows(card)[0].querySelector(".ls-alt-barcode").value = "ALT1";
    actionBtn(card, "save-item").click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Item saved."));
    expect(requestFor("/items/i1/barcodes", "PATCH").body).toEqual({ barcodes: ["ALT1"], override_archived: false });
    expect(requestFor("/items/i1", "PATCH").body.barcode).toBe("B2");
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
  });

  it("a failed write reports and leaves the card as it is", async () => {
    const { card } = await openCard({}, { handlers: [http.patch("/items/:id", fail)] });
    field(card, "ls-name").value = "Bulb 2";
    actionBtn(card, "save-item").click();
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Could not save the changes. Try again."));
    expect(editMessage(card).className).toBe("error");
    await settle();
    expect(listGets()).toEqual([]);
    expect(cardFor("i1")).toBe(card);
    expect(field(card, "ls-name").value).toBe("Bulb 2");
  });
});

describe("save-correction", () => {
  // The `!Number.isFinite(newQuantity)` half of the first check is dead:
  // a `type="number"` input hands non-numeric text back as "", which the
  // blank half answers first. Same class as the N-P6 / N-P7 rows already
  // filed; this row is under N-P7-CHARACTERIZED.
  it.each([["blank", ""], ["non-numeric", "abc"]])(
    "refuses a %s count", async (_label, qty) => {
      const { card } = await openCard();
      fillCorrection(card, { qty, reason: "Recount" });
      actionBtn(card, "save-correction").click();
      await settle();
      expect(editMessage(card).textContent).toBe("Enter a valid new count.");
      expect(editMessage(card).className).toBe("error");
      expect(requests()).toEqual([]);
    });

  it("refuses a negative count", async () => {
    const { card } = await openCard();
    fillCorrection(card, { qty: "-1", reason: "Recount" });
    actionBtn(card, "save-correction").click();
    await settle();
    expect(editMessage(card).textContent).toBe("Enter a count of zero or more.");
    expect(requests()).toEqual([]);
  });

  it("refuses a blank reason, whitespace included", async () => {
    const { card } = await openCard();
    fillCorrection(card, { qty: "3", reason: "   " });
    actionBtn(card, "save-correction").click();
    await settle();
    expect(editMessage(card).textContent).toBe("Enter a reason for the correction.");
    expect(requests()).toEqual([]);
  });

  it("POSTs the absolute count with its reason, reports, and reloads in the background", async () => {
    const { card } = await openCard({}, {
      handlers: [http.post("/transactions/adjust", () => HttpResponse.json({}))],
    });
    fillCorrection(card, { qty: "0", reason: " Shelf recount " });
    actionBtn(card, "save-correction").click();
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Count corrected."));
    expect(editMessage(card).className).toBe("success");
    expect(requestFor("/transactions/adjust", "POST").body).toEqual({
      item_id: "i1", new_quantity: 0, reason: "Shelf recount",
    });
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
    expect(el.message().textContent).toBe("");
    expect(cardFor("i1")).not.toBe(card);
  });

  it("a failed POST reports and leaves the card", async () => {
    const { card } = await openCard({}, { handlers: [http.post("/transactions/adjust", fail)] });
    fillCorrection(card, { qty: "3", reason: "Recount" });
    actionBtn(card, "save-correction").click();
    await vi.waitFor(() => expect(editMessage(card).textContent).toBe("Could not save the correction. Try again."));
    expect(editMessage(card).className).toBe("error");
    await settle();
    expect(listGets()).toEqual([]);
    expect(cardFor("i1")).toBe(card);
  });
});

describe("the delegation", () => {
  // `setMessage` (dom.js) writes `className = type || ""`, so the first
  // message on a card strips `.low-stock-edit-message`, and `saveItem` /
  // `saveCorrection` re-find the paragraph by that class on every click.
  // The next Save on the same card therefore rejects inside the un-awaited
  // click handler ("Cannot set properties of null") and does nothing -- the
  // user fixes the field, clicks again, and nothing happens until a reload
  // rebuilds the card. Only the error and cancel paths leave a card in this
  // state (every success reloads). The rejection itself is unhandled and so
  // cannot be pinned here without failing the run; the class loss is.
  // Filed under N-P7-CHARACTERIZED.
  it("loses the edit-message class after the first message, which the next Save cannot find", async () => {
    const { card } = await openCard();
    expect(card.querySelector(".low-stock-edit-message")).not.toBeNull();
    field(card, "ls-name").value = "";
    actionBtn(card, "save-item").click();
    await settle();
    expect(editMessage(card).textContent).toBe("Barcode, name, and location are required.");
    expect(card.querySelector(".low-stock-edit-message")).toBeNull();
    expect(editMessage(card).getAttribute("aria-live")).toBe("polite");
  });

  it("ignores a [data-action] that sits outside any card", async () => {
    const { card } = await openCard();
    const stray = document.createElement("button");
    stray.type = "button";
    stray.dataset.action = "save-item";
    el.list().append(stray);
    stray.click();
    await settle();
    expect(requests()).toEqual([]);
    expect(editMessage(card).textContent).toBe("");
  });
});
