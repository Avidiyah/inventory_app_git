// Characterization coverage for views/lowStock.js: the reorder queue's list
// and cards, the three recency buckets and their tabs, the in-place threshold
// control, the load-sequence guard, and the realtime background reload.
//
// The card BODY (fields, additional barcodes, the item save, the correction)
// is lowStockCard.js's and lives in lowStockCard.test.js; this file only
// asserts that the body is present.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { lowStockItem } from "../helpers/factories.js";
import {
  LOW_STOCK_NOW, cardFor, cards, connectLowStock, el, listGets, mountLowStock,
  requestFor, requests, restoreLowStock, rowMessage, tabBtn, thresholdInput,
} from "../helpers/lowStock.js";

afterEach(() => restoreLowStock());

const fail = () => HttpResponse.json({ detail: "" }, { status: 500 });
const settle = () => new Promise((r) => setTimeout(r, 0));
const hoursBefore = (h) => new Date(Date.parse(LOW_STOCK_NOW) - h * 3600_000).toISOString();
const labels = () => ["day", "week", "stale"].map((b) => tabBtn(b).textContent);
const activeTab = () => ["day", "week", "stale"].filter((b) => tabBtn(b).classList.contains("active"));
const ids = () => cards().map((c) => c.dataset.id);
const thresholdPatch = () =>
  http.patch("/items/:id/low-stock-threshold", () => HttpResponse.json(lowStockItem()));

// A promise the test resolves by hand, for the ordering races.
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

// Type into the threshold input and commit by blur. The card is opened first
// so the focus travels the way a click would have made it.
function commit(card, value) {
  const input = thresholdInput(card);
  card.open = true;
  input.focus();
  input.value = value;
  input.blur();
  return input;
}

describe("loadLowStock: the list and its cards", () => {
  it("shows the loading copy, then a details card per row", async () => {
    const row = lowStockItem({
      id: "i1", name: "Bulb <b>", barcode: "B1", barcodes: ["ALT1"], location: "A1",
      quantity: "3.00", dispensed_last_7_days: "4.50", low_stock_threshold: 5,
    });
    const { mod } = await mountLowStock({ rows: [row], load: false });
    const loading = mod.loadLowStock();
    expect(el.message().textContent).toBe("Loading low stock...");
    expect(el.message().className).toBe("");
    await loading;
    expect(requests().map((r) => r.url)).toEqual(["/items/low-stock"]);

    const [card] = cards();
    expect(cards()).toHaveLength(1);
    expect(card.tagName).toBe("DETAILS");
    expect(card.className).toBe("low-stock-card");
    expect(card.open).toBe(false);
    expect(card.dataset.id).toBe("i1");
    expect(card.dataset.barcode).toBe("B1");
    expect(card.dataset.barcodes).toBe('["ALT1"]');

    const summary = card.querySelector("summary.low-stock-summary");
    expect(summary.querySelector(".low-stock-title").textContent).toBe("Bulb <b>");
    expect(summary.querySelector(".low-stock-count").textContent).toBe("3 on hand");
    expect(summary.querySelector(".low-stock-usage").textContent).toBe("7-day used: 4.5");
    expect(summary.querySelector("input")).toBeNull();

    const details = card.querySelectorAll(".low-stock-body .low-stock-details > span");
    expect(Array.from(details, (s) => s.textContent)).toEqual(["B1", "A1"]);
    const input = thresholdInput(card);
    expect(input.type).toBe("number");
    expect(input.value).toBe("5");
    expect(input.defaultValue).toBe("5");
    expect(input.getAttribute("min")).toBe("1");
    expect(input.getAttribute("step")).toBe("1");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("aria-label")).toBe("Low stock threshold for Bulb <b>");
    expect(input.closest("label").querySelector("span").textContent).toBe("Warn at");
    expect(rowMessage(card).textContent).toBe("");
    expect(rowMessage(card).getAttribute("aria-live")).toBe("polite");
    // The body from lowStockCard.js follows the row message.
    expect(rowMessage(card).nextElementSibling.className).toBe("low-stock-edit");
    expect(el.message().textContent).toBe("");
  });

  it("stamps an empty barcodes list when the row carries none", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1", barcodes: undefined })] });
    expect(cardFor("i1").dataset.barcodes).toBe("[]");
  });

  it("an empty queue says so and paints no card", async () => {
    await mountLowStock({ rows: [] });
    expect(cards()).toEqual([]);
    expect(el.message().textContent).toBe("Nothing is below its threshold.");
    expect(el.message().className).toBe("success");
    expect(labels()).toEqual(["Last 24h (0)", "2-7 days (0)", "Older or never (0)"]);
  });

  it("a failed load empties the list and reports", async () => {
    const { mod } = await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    expect(cards()).toHaveLength(1);
    server.use(http.get("/items/low-stock", fail));
    await mod.loadLowStock();
    expect(cards()).toEqual([]);
    expect(el.message().textContent).toBe("Could not load low stock.");
    expect(el.message().className).toBe("error");
  });

  it("Refresh reloads in the foreground", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const before = cardFor("i1");
    el.refresh().click();
    expect(el.message().textContent).toBe("Loading low stock...");
    await vi.waitFor(() => expect(cardFor("i1")).not.toBe(before));
    expect(listGets()).toHaveLength(1);
    expect(el.message().textContent).toBe("");
  });

  it("a background load skips the loading copy and still repaints", async () => {
    const { mod } = await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const before = cardFor("i1");
    const loading = mod.loadLowStock({ background: true });
    expect(el.message().textContent).toBe("");
    await loading;
    expect(cardFor("i1")).not.toBe(before);
    expect(listGets()).toHaveLength(1);
  });

  it("an older, slower answer never repaints over a newer one", async () => {
    const { mod } = await mountLowStock({ load: false });
    const gate = deferred();
    let calls = 0;
    server.use(http.get("/items/low-stock", async () => {
      calls += 1;
      if (calls === 1) {
        await gate.promise;
        return HttpResponse.json([lowStockItem({ id: "old" })]);
      }
      return HttpResponse.json([lowStockItem({ id: "new" })]);
    }));
    const first = mod.loadLowStock();
    await mod.loadLowStock();
    expect(ids()).toEqual(["new"]);
    gate.resolve();
    await first;
    expect(ids()).toEqual(["new"]);
  });

  it("an older, slower failure is ignored once a newer answer has painted", async () => {
    const { mod } = await mountLowStock({ load: false });
    const gate = deferred();
    let calls = 0;
    server.use(http.get("/items/low-stock", async () => {
      calls += 1;
      if (calls === 1) {
        await gate.promise;
        return fail();
      }
      return HttpResponse.json([lowStockItem({ id: "new" })]);
    }));
    const first = mod.loadLowStock();
    await mod.loadLowStock();
    gate.resolve();
    await first;
    expect(ids()).toEqual(["new"]);
    expect(el.message().textContent).toBe("");
  });
});

describe("the recency buckets", () => {
  // Exclusive boundaries: exactly 24 h is `week`, exactly 7 d is `stale`.
  // A missing or unparseable timestamp is "never dispensed" -- the oldest
  // bucket, not a hidden row.
  it.each([
    ["one hour ago", hoursBefore(1), "day"],
    ["a minute short of 24 h", hoursBefore(24 - 1 / 60), "day"],
    ["exactly 24 h", hoursBefore(24), "week"],
    ["an hour short of 7 d", hoursBefore(7 * 24 - 1), "week"],
    ["exactly 7 d", hoursBefore(7 * 24), "stale"],
    ["null", null, "stale"],
    ["unparseable", "not a date", "stale"],
  ])("%s -> %s", async (_label, at, bucket) => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1", last_dispensed_at: at })] });
    expect(activeTab()).toEqual([bucket]);
    expect(tabBtn(bucket).textContent).toMatch(/\(1\)$/);
    expect(ids()).toEqual(["i1"]);
  });

  it("labels each tab with its count, the three summing to the queue, and keeps server order within a bucket", async () => {
    await mountLowStock({ rows: [
      lowStockItem({ id: "s2", last_dispensed_at: null }),
      lowStockItem({ id: "d1", last_dispensed_at: hoursBefore(2) }),
      lowStockItem({ id: "w1", last_dispensed_at: hoursBefore(48) }),
      lowStockItem({ id: "s1", last_dispensed_at: hoursBefore(200) }),
      lowStockItem({ id: "d2", last_dispensed_at: hoursBefore(1) }),
      lowStockItem({ id: "s3", last_dispensed_at: "garbage" }),
    ] });
    expect(labels()).toEqual(["Last 24h (2)", "2-7 days (1)", "Older or never (3)"]);
    expect(activeTab()).toEqual(["day"]);
    expect(ids()).toEqual(["d1", "d2"]);

    tabBtn("stale").click();
    expect(ids()).toEqual(["s2", "s1", "s3"]);
    expect(activeTab()).toEqual(["stale"]);
    tabBtn("week").click();
    expect(ids()).toEqual(["w1"]);
    expect(requests()).toEqual([]);
  });

  it("a click on the active tab, or off any tab, repaints nothing", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "d1" })] });
    const before = cardFor("d1");
    tabBtn("day").click();
    expect(cardFor("d1")).toBe(before);
    el.tabs().click();
    expect(cardFor("d1")).toBe(before);
    expect(requests()).toEqual([]);
  });

  it("falls to the first filled bucket when the chosen one is empty on first load", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "s1", last_dispensed_at: null })] });
    expect(activeTab()).toEqual(["stale"]);
    expect(labels()).toEqual(["Last 24h (0)", "2-7 days (0)", "Older or never (1)"]);
    expect(ids()).toEqual(["s1"]);
    expect(el.message().textContent).toBe("");
  });

  it("and when a background reload empties the tab under the user", async () => {
    const day = lowStockItem({ id: "d1" });
    const week = lowStockItem({ id: "w1", last_dispensed_at: hoursBefore(48) });
    const { mod } = await mountLowStock({ rows: [day, week] });
    expect(activeTab()).toEqual(["day"]);
    server.use(http.get("/items/low-stock", () => HttpResponse.json([week])));
    await mod.loadLowStock({ background: true });
    expect(activeTab()).toEqual(["week"]);
    expect(labels()).toEqual(["Last 24h (0)", "2-7 days (1)", "Older or never (0)"]);
    expect(ids()).toEqual(["w1"]);
  });

  // `render` falls to the first filled bucket BEFORE it looks at the active
  // bucket's rows, and an all-empty queue is answered earlier still -- so an
  // empty tab cannot be selected (a click on one bounces straight back, after
  // a repaint) and the per-bucket `EMPTY_TEXT` table can never paint. Filed
  // under N-P7-CHARACTERIZED; this pins the two messages that do paint.
  it("never paints a per-bucket empty message: an empty tab cannot be selected", async () => {
    const perBucket = [
      "Nothing low was dispensed in the last 24 hours.",
      "Nothing low was dispensed in the last week.",
      "Everything low has moved within the last week.",
    ];
    const { mod } = await mountLowStock({ rows: [lowStockItem({ id: "s1", last_dispensed_at: null })] });
    const before = cardFor("s1");
    tabBtn("day").click();
    expect(activeTab()).toEqual(["stale"]);
    expect(ids()).toEqual(["s1"]);
    expect(cardFor("s1")).not.toBe(before);
    expect(perBucket).not.toContain(el.message().textContent);
    expect(el.message().textContent).toBe("");
    expect(requests()).toEqual([]);

    server.use(http.get("/items/low-stock", () => HttpResponse.json([])));
    await mod.loadLowStock({ background: true });
    expect(el.message().textContent).toBe("Nothing is below its threshold.");
    expect(activeTab()).toEqual(["stale"]);
  });

  it("reopens by id the cards that were open before a reload", async () => {
    const { mod } = await mountLowStock({ rows: [lowStockItem({ id: "a" }), lowStockItem({ id: "b" })] });
    const before = cardFor("a");
    before.open = true;
    await mod.loadLowStock({ background: true });
    expect(cardFor("a")).not.toBe(before);
    expect(cardFor("a").open).toBe(true);
    expect(cardFor("b").open).toBe(false);
  });
});

describe("the threshold control", () => {
  it("commits on blur: disabled meanwhile, PATCHes, keeps the new default, reports, reloads in the background", async () => {
    const gate = deferred();
    await mountLowStock({
      rows: [lowStockItem({ id: "i1", low_stock_threshold: 5 })],
      handlers: [http.patch("/items/:id/low-stock-threshold", async () => {
        await gate.promise;
        return HttpResponse.json(lowStockItem());
      })],
    });
    const card = cardFor("i1");
    const input = commit(card, "7");
    expect(input.disabled).toBe(true);
    expect(requestFor("/items/i1/low-stock-threshold", "PATCH").body).toEqual({ low_stock_threshold: 7 });
    expect(listGets()).toEqual([]);

    gate.resolve();
    await vi.waitFor(() => expect(rowMessage(card).textContent).toBe("Saved."));
    expect(rowMessage(card).className).toBe("success");
    expect(input.defaultValue).toBe("7");
    expect(input.disabled).toBe(false);
    await vi.waitFor(() => expect(cardFor("i1")).not.toBe(card));
    expect(listGets()).toHaveLength(1);
    expect(el.message().textContent).toBe("");
  });

  it("Enter is swallowed and blurs the input, which commits", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })], handlers: [thresholdPatch()] });
    const card = cardFor("i1");
    const input = thresholdInput(card);
    card.open = true;
    input.focus();
    input.value = "8";
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    input.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    expect(document.activeElement).not.toBe(input);
    expect(requestFor("/items/i1/low-stock-threshold", "PATCH").body).toEqual({ low_stock_threshold: 8 });
    await vi.waitFor(() => expect(listGets()).toHaveLength(1));
  });

  it("any other key is left alone", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const card = cardFor("i1");
    const input = thresholdInput(card);
    card.open = true;
    input.focus();
    const key = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    input.dispatchEvent(key);
    expect(key.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(input);
    expect(requests()).toEqual([]);
  });

  // A `type="number"` input hands non-numeric text back as "", so "abc"
  // arrives as the blank case.
  it.each([["blank", ""], ["non-numeric", "abc"], ["a fraction", "2.5"], ["zero", "0"], ["negative", "-3"]])(
    "%s reverts to the last saved value and reports", async (_label, value) => {
      await mountLowStock({ rows: [lowStockItem({ id: "i1", low_stock_threshold: 5 })] });
      const card = cardFor("i1");
      const input = commit(card, value);
      expect(input.value).toBe("5");
      expect(input.disabled).toBe(false);
      expect(rowMessage(card).textContent).toBe("Threshold must be a whole number of at least 1.");
      expect(rowMessage(card).className).toBe("error");
      expect(requests()).toEqual([]);
      // The class the module re-finds the paragraph by is gone (see below).
      expect(card.querySelector(".low-stock-row-message")).toBeNull();
    });

  // `setMessage` (dom.js) writes `className = type || ""`, so the first
  // message on a card strips `.low-stock-row-message`, and `commitThreshold`
  // re-finds the paragraph by that class on every commit. The next commit on
  // the same card therefore rejects inside the un-awaited blur handler
  // ("Cannot set properties of null") before it validates or requests, and
  // the input keeps whatever was typed. A successful save reloads and rebuilds
  // the card, so only an invalid value or a failed PATCH leaves it stuck. The
  // rejection is unhandled and cannot be pinned without failing the run; the
  // class loss is. Filed under N-P7-CHARACTERIZED.
  it("a failed PATCH strips the row-message class the next commit needs", async () => {
    await mountLowStock({
      rows: [lowStockItem({ id: "i1", low_stock_threshold: 5 })],
      handlers: [http.patch("/items/:id/low-stock-threshold", fail)],
    });
    const card = cardFor("i1");
    expect(card.querySelector(".low-stock-row-message")).not.toBeNull();
    commit(card, "9");
    await vi.waitFor(() => expect(rowMessage(card).className).toBe("error"));
    expect(card.querySelector(".low-stock-row-message")).toBeNull();
    expect(rowMessage(card).getAttribute("aria-live")).toBe("polite");
  });

  it("an unchanged value sends nothing", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1", low_stock_threshold: 5 })] });
    const card = cardFor("i1");
    const input = commit(card, "5");
    await settle();
    expect(input.disabled).toBe(false);
    expect(rowMessage(card).textContent).toBe("");
    expect(requests()).toEqual([]);
  });

  it("a failed PATCH reverts, reports, and re-enables", async () => {
    await mountLowStock({
      rows: [lowStockItem({ id: "i1", low_stock_threshold: 5 })],
      handlers: [http.patch("/items/:id/low-stock-threshold", fail)],
    });
    const card = cardFor("i1");
    const input = commit(card, "9");
    await vi.waitFor(() => expect(rowMessage(card).textContent).toBe("Could not save that threshold."));
    expect(rowMessage(card).className).toBe("error");
    expect(input.value).toBe("5");
    expect(input.defaultValue).toBe("5");
    expect(input.disabled).toBe(false);
    await settle();
    expect(listGets()).toEqual([]);
    expect(cardFor("i1")).toBe(card);
  });
});

describe("realtime", () => {
  it("item.low_stock.changed on the page reloads in the background", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const before = cardFor("i1");
    const rt = await connectLowStock("low-stock");
    rt.emit("item.low_stock.changed");
    expect(el.message().textContent).toBe("");
    await vi.waitFor(() => expect(cardFor("i1")).not.toBe(before));
    expect(listGets()).toHaveLength(1);
    expect(el.message().textContent).toBe("");
  });

  it("and does nothing on another page", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const rt = await connectLowStock("items");
    rt.emit("item.low_stock.changed");
    await settle();
    expect(requests()).toEqual([]);
  });

  it("a recovered connection reloads too", async () => {
    await mountLowStock({ rows: [lowStockItem({ id: "i1" })] });
    const rt = await connectLowStock("low-stock");
    vi.useFakeTimers();
    rt.reconnect();
    vi.advanceTimersByTime(1000);
    rt.ws.last().emitOpen();
    expect(listGets()).toHaveLength(1);
    await vi.runAllTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  });
});
