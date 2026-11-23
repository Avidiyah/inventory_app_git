// W6: a live update patches the Low Stock list in place. Open cards, typed
// fields, touched barcode blocks and showing messages survive; changed cards
// glow; a card that left the list with typed input is never removed silently;
// live events coalesce; an own save leaves the card clean for the next update.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { lowStockItem } from "../helpers/factories.js";
import {
  LOW_STOCK_NOW, actionBtn, cardFor, cards, clearRequests, connectLowStock, editMessage, el,
  listGets, mountLowStock, restoreLowStock, rowMessage, tabBtn, thresholdInput,
} from "../helpers/lowStock.js";

afterEach(() => restoreLowStock());

const NO_LONGER_LOW = "An item you were editing is no longer low.";
const hoursBefore = (h) => new Date(Date.parse(LOW_STOCK_NOW) - h * 3600_000).toISOString();
const q = (id, selector) => cardFor(id).querySelector(selector);
const glows = (id) => cardFor(id).classList.contains("just-changed");
const countText = (id) => q(id, ".low-stock-count").textContent;
const row = (o = {}) => lowStockItem({ id: "i1", name: "Elbow", quantity: "4", price: "2.50", ...o });

// Mount with `rows` as the server's list (mutate it to change what the next
// load returns), open the first card, and bring up a live socket.
async function open(rows) {
  const mounted = await mountLowStock({ rows });
  const rt = await connectLowStock();
  if (cards()[0]) cards()[0].open = true;
  clearRequests();
  return { ...mounted, rt };
}

// Fire one live event and wait until `painted` holds.
async function live(rt, painted) {
  rt.emit("item.low_stock.changed", { id: "i1" });
  await vi.waitFor(() => expect(painted()).toBe(true));
}

function type(input, value) {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("patch in place", () => {
  it("keeps a typed new count and reason through a live update", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    type(q("i1", ".ls-correct-qty"), "6");
    type(q("i1", ".ls-correct-reason"), "recounted shelf");
    rows[0] = row({ quantity: "2" });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(q("i1", ".ls-correct-qty").value).toBe("6");
    expect(q("i1", ".ls-correct-reason").value).toBe("recounted shelf");
  });

  it("keeps a typed name, price and threshold", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    type(q("i1", ".ls-name"), "Elbow 3/4");
    type(q("i1", ".ls-price"), "9.99");
    type(thresholdInput(cardFor("i1")), "12");
    rows[0] = row({ quantity: "2", name: "Renamed", price: "1.00", low_stock_threshold: 8 });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(q("i1", ".ls-name").value).toBe("Elbow 3/4");
    expect(q("i1", ".ls-price").value).toBe("9.99");
    expect(thresholdInput(cardFor("i1")).value).toBe("12");
  });

  it("keeps a focused field and its caret", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    const field = q("i1", ".ls-location");
    field.focus();
    field.setSelectionRange(1, 1);
    rows[0] = row({ quantity: "2", location: "Moved" });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(document.activeElement).toBe(field);
    expect(field.selectionStart).toBe(1);
    expect(field.value).toBe(row().location);
  });

  it("keeps an added barcode row", async () => {
    const rows = [row({ barcodes: ["ALT1"] })];
    const { rt } = await open(rows);
    actionBtn(cardFor("i1"), "add-barcode").click();
    expect(cardFor("i1").querySelectorAll(".ls-barcode-row")).toHaveLength(2);
    rows[0] = row({ quantity: "2", barcodes: ["ALT1"] });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(cardFor("i1").querySelectorAll(".ls-barcode-row")).toHaveLength(2);
  });

  it("keeps a removed barcode row removed", async () => {
    const rows = [row({ barcodes: ["ALT1"] })];
    const { rt } = await open(rows);
    actionBtn(cardFor("i1"), "remove-barcode").click();
    rows[0] = row({ quantity: "2", barcodes: ["ALT1"] });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(cardFor("i1").querySelectorAll(".ls-barcode-row")).toHaveLength(0);
  });

  it("keeps a row message that is showing text", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    const input = thresholdInput(cardFor("i1"));
    input.focus();
    input.value = "0";
    input.blur();
    const text = rowMessage(cardFor("i1")).textContent;
    expect(text).toBe("Threshold must be a whole number of at least 1.");
    rows[0] = row({ quantity: "2" });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(rowMessage(cardFor("i1")).textContent).toBe(text);
  });

  it("updates an untouched open card and leaves it open", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    const before = cardFor("i1");
    rows[0] = row({ quantity: "2", name: "Renamed", price: "7.00" });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(cardFor("i1")).toBe(before);
    expect(before.open).toBe(true);
    expect(q("i1", ".low-stock-title").textContent).toBe("Renamed");
    expect(q("i1", ".ls-name").value).toBe("Renamed");
    expect(q("i1", ".ls-price").value).toBe("7.00");
    expect(q("i1", ".ls-correct-qty").value).toBe("2");
  });

  it("glows a changed card, not an unchanged one", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee" })];
    const { rt } = await open(rows);
    rows[0] = row({ quantity: "2" });
    await live(rt, () => countText("i1") === "2 on hand");
    expect(glows("i1")).toBe(true);
    expect(glows("i2")).toBe(false);
  });

  it("first draw and a tab change glow nothing", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee", last_dispensed_at: hoursBefore(48) })];
    await open(rows);
    expect(el.list().querySelector(".just-changed")).toBeNull();
    tabBtn("week").click();
    expect(cards().map((c) => c.dataset.id)).toEqual(["i2"]);
    expect(el.list().querySelector(".just-changed")).toBeNull();
  });

  it("removes a card that left the list and says so when it held typed input", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee" })];
    const { rt } = await open(rows);
    type(q("i1", ".ls-correct-qty"), "6");
    rows.splice(0, 1);
    await live(rt, () => cardFor("i1") === null);
    expect(el.message().textContent).toBe(NO_LONGER_LOW);
    expect(el.message().className).toBe("error");
    expect(cardFor("i2")).not.toBeNull();
  });

  it("keeps the no-longer-low message through the next live update", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee" })];
    const { rt } = await open(rows);
    type(q("i1", ".ls-correct-qty"), "6");
    rows.splice(0, 1);
    await live(rt, () => cardFor("i1") === null);
    rows[0] = row({ id: "i2", name: "Tee", quantity: "1" });
    await live(rt, () => countText("i2") === "1 on hand");
    expect(el.message().textContent).toBe(NO_LONGER_LOW);
  });

  it("removes an untouched card silently", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee" })];
    const { rt } = await open(rows);
    rows.splice(0, 1);
    await live(rt, () => cardFor("i1") === null);
    expect(el.message().textContent).toBe("");
  });

  it("a card that moved to another tab counts as removed", async () => {
    const rows = [row(), row({ id: "i2", name: "Tee" })];
    const { rt } = await open(rows);
    type(q("i1", ".ls-name"), "typed");
    rows[0] = row({ last_dispensed_at: hoursBefore(48) });
    await live(rt, () => cardFor("i1") === null);
    expect(el.message().textContent).toBe(NO_LONGER_LOW);
  });

  it("coalesces live events into one fetch plus one rerun", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const rows = [row()];
    await mountLowStock({
      rows,
      handlers: [http.get("/items/low-stock", async () => { await gate; return HttpResponse.json(rows); })],
      load: false,
    });
    const rt = await connectLowStock();
    for (let i = 0; i < 5; i += 1) rt.emit("item.low_stock.changed", { id: "i1" });
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
    release();
    await vi.waitFor(() => expect(listGets()).toHaveLength(2));
    await vi.waitFor(() => expect(cardFor("i1")).not.toBeNull());
    await new Promise((r) => setTimeout(r, 20));
    expect(listGets()).toHaveLength(2);
  });

  it("a button in a patched-in card works", async () => {
    const rows = [row()];
    const { rt } = await open(rows);
    rows.push(row({ id: "i2", name: "Tee" }));
    await live(rt, () => cardFor("i2") !== null);
    actionBtn(cardFor("i2"), "add-barcode").click();
    expect(cardFor("i2").querySelectorAll(".ls-barcode-row")).toHaveLength(1);
    expect(editMessage(cardFor("i2")).textContent).toBe("");
  });
});
