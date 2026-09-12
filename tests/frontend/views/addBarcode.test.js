// Characterization coverage for views/addBarcode.js: the panel that attaches a
// just-scanned code to an existing item found by name. The debounced search,
// the name-only narrowing through filterRanked, the stale-answer guard, and
// the append's fresh-read / prompt / retry sequence.
//
// Entered by `openAddBarcode(code)` by name -- its production entry is
// scan.js's 404 shortcut, which P5c already pins. Fake timers throughout: the
// search is debounced 200 ms and the panel auto-closes 1200 ms after a save.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  answerConfirm, answerLookup, clearRequests, el, mountItems, requestFor, requests, restoreItems,
} from "../helpers/items.js";
import { confirmTitle } from "../helpers/dialogs.js";
import { importView } from "../helpers/shell.js";
import { item as itemFactory } from "../helpers/factories.js";

afterEach(() => restoreItems());

const byId = (id) => document.getElementById(id);
const searchEl = () => byId("add-barcode-search");
const resultsEl = () => byId("add-barcode-results");
const message = () => byId("add-barcode-message");
const choices = () => Array.from(resultsEl().querySelectorAll(".scan-choice-btn"));
const listQueries = () => requests()
  .filter((r) => r.method === "GET" && r.url.startsWith("/items/?"))
  .map((r) => new URL(r.url, "http://t").searchParams.get("q"));

// Fake timers before the mount; the panel opened with a scanned code.
async function openPanel({ items = [], handlers = [], code = "NEW1" } = {}) {
  vi.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const mounted = await mountItems({ role: "admin", items, handlers });
  const mod = await importView("views/addBarcode.js");
  mod.openAddBarcode(code);
  clearRequests();
  return { ...mounted, mod, user, code };
}

// Type a term and let the 200 ms debounce fire.
async function search(ctx, term) {
  await ctx.user.type(searchEl(), term);
  await vi.advanceTimersByTimeAsync(200);
}

describe("open and close", () => {
  it("shows the scanned code, an empty search and no results", async () => {
    const ctx = await openPanel({ code: "<b>NEW1</b>" });
    expect(el.addBarcodeSection().hidden).toBe(false);
    expect(byId("add-barcode-scanned").textContent).toBe("Scanned code: <b>NEW1</b>");
    expect(byId("add-barcode-scanned").querySelector("b")).toBeNull();   // escaped
    expect(byId("add-barcode-scanned").querySelector("strong")).not.toBeNull();
    expect(searchEl().value).toBe("");
    expect(resultsEl().hidden).toBe(true);
    expect(document.activeElement).toBe(searchEl());
    expect(ctx.mod).toBeTruthy();
  });

  it("closeAddBarcode hides it, empties the results and drops the pending search", async () => {
    const ctx = await openPanel({ items: [itemFactory({ name: "Bulb" })] });
    await ctx.user.type(searchEl(), "bul");                 // a timer is now pending
    expect(vi.getTimerCount()).toBe(1);
    ctx.mod.closeAddBarcode();
    expect(el.addBarcodeSection().hidden).toBe(true);
    expect(resultsEl().hidden).toBe(true);
    expect(resultsEl().innerHTML).toBe("");
    expect(message().textContent).toBe("");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(400);
    expect(listQueries()).toEqual([]);                      // the dropped search never fired
  });

  it("Cancel does the same", async () => {
    const ctx = await openPanel();
    await ctx.user.click(byId("add-barcode-cancel-btn"));
    expect(el.addBarcodeSection().hidden).toBe(true);
  });
});

describe("the debounced search", () => {
  it("paints a three-item skeleton first and queries only after 200 ms", async () => {
    const ctx = await openPanel({ items: [itemFactory({ name: "Bulb" })] });
    await ctx.user.type(searchEl(), "bul");
    expect(resultsEl().hidden).toBe(false);
    expect(resultsEl().querySelectorAll(".skel-list-item")).toHaveLength(3);
    expect(listQueries()).toEqual([]);
    await vi.advanceTimersByTimeAsync(200);
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    expect(listQueries()).toEqual(["bul"]);
  });

  it("a second keystroke inside the window leaves one request, for the latest term", async () => {
    const ctx = await openPanel({ items: [itemFactory({ name: "Bulb" })] });
    await ctx.user.type(searchEl(), "bu");
    await vi.advanceTimersByTimeAsync(100);
    await ctx.user.type(searchEl(), "l");
    await vi.advanceTimersByTimeAsync(200);
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    expect(listQueries()).toEqual(["bul"]);
  });

  it("clearing the field hides the results without a request", async () => {
    const ctx = await openPanel({ items: [itemFactory({ name: "Bulb" })] });
    await search(ctx, "bul");
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    clearRequests();
    await ctx.user.clear(searchEl());
    expect(resultsEl().hidden).toBe(true);
    await vi.advanceTimersByTimeAsync(400);
    expect(listQueries()).toEqual([]);
  });
});

describe("narrowing the server's answer", () => {
  it("drops a barcode-only match and keeps the name match", async () => {
    const ctx = await openPanel({ items: [
      itemFactory({ name: "Bulb", barcode: "B1", location: "A1" }),
      itemFactory({ name: "Tape", barcode: "BULB-99" }),      // the API matches barcodes too
    ] });
    await search(ctx, "bulb");
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    expect(choices()[0].textContent).toBe("Bulb  ·  B1  ·  A1");
  });

  it("a punctuation-insensitive name hit survives the re-rank", async () => {
    // The module's own argument: a raw includes() post-filter would throw out
    // exactly the row the server's normalized search just found.
    const ctx = await openPanel({ items: [], handlers: [
      http.get("/items/", () => HttpResponse.json([itemFactory({ name: '2"x4"', barcode: "W24" })])),
    ] });
    await search(ctx, "2x4");
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    expect(choices()[0].textContent).toContain('2"x4"');
  });

  it("caps the list at eight", async () => {
    const many = Array.from({ length: 10 }, (_, i) => itemFactory({ name: `Bulb ${i}`, barcode: `B${i}` }));
    const ctx = await openPanel({ items: many });
    await search(ctx, "bulb");
    await vi.waitFor(() => expect(choices()).toHaveLength(8));
  });

  it("no matches says so", async () => {
    const ctx = await openPanel({ items: [itemFactory({ name: "Bulb" })] });
    await search(ctx, "zzz");
    await vi.waitFor(() => expect(resultsEl().querySelector(".hint")).not.toBeNull());
    expect(resultsEl().querySelector(".hint").textContent).toBe("No items match that name.");
  });

  it("a failing search shows the error", async () => {
    const ctx = await openPanel({ handlers: [
      http.get("/items/", () => HttpResponse.json({ detail: "Search is down" }, { status: 500 })),
    ] });
    await search(ctx, "bul");
    await vi.waitFor(() => expect(resultsEl().querySelector(".error")).not.toBeNull());
    expect(resultsEl().querySelector(".error").textContent).toBe("Search is down");
  });

  it("a stale answer is discarded: the last term's list wins", async () => {
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    const slow = itemFactory({ name: "Bulb slow" });
    const fast = itemFactory({ name: "Bulb fast" });
    const ctx = await openPanel({ handlers: [
      http.get("/items/", async ({ request }) => {
        const q = new URL(request.url).searchParams.get("q");
        if (q === "bul") { await gate; return HttpResponse.json([slow]); }
        return HttpResponse.json([fast]);
      }),
    ] });
    await search(ctx, "bul");                        // in flight, gated
    await search(ctx, "b");                          // "bulb" -- answers immediately
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    expect(choices()[0].textContent).toContain("Bulb fast");
    release();
    await vi.advanceTimersByTimeAsync(50);
    expect(choices()).toHaveLength(1);
    expect(choices()[0].textContent).toContain("Bulb fast");
  });
});

describe("attaching the code", () => {
  // The panel re-reads the item by barcode before the wholesale replace.
  function answerAppend(target, { conflictsOnce = false, status = null } = {}) {
    let conflicts = conflictsOnce ? 1 : 0;
    answerLookup(target.barcode, { ...target, barcodes: ["ALT1"] });
    server.use(http.patch(`/items/${target.id}/barcodes`, () => {
      if (conflicts > 0) {
        conflicts -= 1;
        return HttpResponse.json({ detail: "Barcode belongs to an archived item" }, { status: 409 });
      }
      if (status) return HttpResponse.json({ detail: "Append is locked" }, { status });
      return HttpResponse.json(target);
    }));
  }

  async function pick(ctx) {
    await search(ctx, "bulb");
    await vi.waitFor(() => expect(choices()).toHaveLength(1));
    clearRequests();
    ctx.user.click(choices()[0]);
    await vi.waitFor(() => expect(byId("scan-confirm-overlay").hidden).toBe(false));
  }

  it("the confirm names the code and the item; No writes nothing", async () => {
    const target = itemFactory({ name: "Bulb" });
    const ctx = await openPanel({ items: [target] });
    answerAppend(target);
    await pick(ctx);
    expect(confirmTitle()).toBe('Add barcode NEW1 to "Bulb"?');
    await answerConfirm(false);
    await vi.advanceTimersByTimeAsync(50);
    expect(requests()).toHaveLength(0);
    expect(message().textContent).toBe("");
  });

  it("Yes re-reads the item and appends the code to its current list", async () => {
    const target = itemFactory({ name: "Bulb", barcode: "B1" });
    const ctx = await openPanel({ items: [target] });
    answerAppend(target);
    const saved = vi.fn();
    ctx.mod.setOnSaved(saved);
    await pick(ctx);
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().textContent).toBe("Added NEW1 to Bulb."));
    expect(message().className).toBe("success");
    expect(requestFor("/items/B1", "GET")).not.toBeNull();
    expect(requestFor(`/items/${target.id}/barcodes`, "PATCH").body)
      .toEqual({ barcodes: ["ALT1", "NEW1"], override_archived: false });
    expect(saved).toHaveBeenCalledTimes(1);
    expect(el.addBarcodeSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1200);
    expect(el.addBarcodeSection().hidden).toBe(true);
  });

  it("an archived holder prompts once and retries with the override", async () => {
    const target = itemFactory({ name: "Bulb", barcode: "B1" });
    const ctx = await openPanel({ items: [target] });
    answerAppend(target, { conflictsOnce: true });
    await pick(ctx);
    await answerConfirm(true);                                   // the add confirm
    await vi.waitFor(() => expect(byId("scan-confirm-overlay").hidden).toBe(false));
    expect(confirmTitle()).toBe("Barcode exists but is archived. Continue?");
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().textContent).toBe("Added NEW1 to Bulb."));
    const patches = requests().filter((r) => r.method === "PATCH");
    expect(patches.map((r) => r.body.override_archived)).toEqual([false, true]);
  });

  it("declining the archived prompt clears the message", async () => {
    const target = itemFactory({ name: "Bulb", barcode: "B1" });
    const ctx = await openPanel({ items: [target] });
    answerAppend(target, { conflictsOnce: true });
    await pick(ctx);
    await answerConfirm(true);
    await vi.waitFor(() => expect(byId("scan-confirm-overlay").hidden).toBe(false));
    await answerConfirm(false);
    await vi.waitFor(() => expect(message().textContent).toBe(""));
    expect(el.addBarcodeSection().hidden).toBe(false);
  });

  it("a failing append shows the detail and keeps the panel open", async () => {
    const target = itemFactory({ name: "Bulb", barcode: "B1" });
    const ctx = await openPanel({ items: [target] });
    answerAppend(target, { status: 500 });
    await pick(ctx);
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe("Append is locked");
    expect(el.addBarcodeSection().hidden).toBe(false);
  });

  it("a failing fresh read stops before the PATCH", async () => {
    const target = itemFactory({ name: "Bulb", barcode: "B1" });
    const ctx = await openPanel({ items: [target] });
    answerLookup(target.barcode, 500);
    await pick(ctx);
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(requests().filter((r) => r.method === "PATCH")).toHaveLength(0);
  });
});
