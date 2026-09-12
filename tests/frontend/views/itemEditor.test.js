// Characterization coverage for views/itemEditor.js and the itemSave.js
// sequence it drives: the prefill, the additional-barcode rows, the
// validation, and the load-bearing write order -- barcodes first, both writes
// under one archived-reuse prompt, a changed primary barcode warned first.
//
// Opened from the row action on a loaded row (P5c's pattern) and saved through
// the real button, so dom.js's real overlays answer both prompts.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionSelect, answerConfirm, clearRequests, el, mountItems, requestFor, requests, restoreItems, rows,
} from "../helpers/items.js";
import { confirmTitle } from "../helpers/dialogs.js";
import { importView } from "../helpers/shell.js";
import { item as itemFactory } from "../helpers/factories.js";

afterEach(() => restoreItems());

const byId = (id) => document.getElementById(id);
const message = () => byId("item-editor-message");
const barcodeRows = () => Array.from(byId("item-editor-barcodes-rows").querySelectorAll(".barcode-row"));
const codeIn = (row) => row.querySelector(".barcode-code");
const saveClick = () => byId("item-editor-save-btn").click();
const patches = () => requests()
  .filter((r) => r.method === "PATCH")
  .map((r) => [r.url.replace(/^\/items\/[0-9a-f-]+/, "/items/:id"), r.body.override_archived]);

async function loadedRow({ role = "admin", fake = false, ...overrides } = {}) {
  if (fake) vi.useFakeTimers();
  const user = userEvent.setup(fake ? { advanceTimers: vi.advanceTimersByTime } : {});
  const target = itemFactory({ name: "Target", ...overrides });
  const mounted = await mountItems({ role, items: [target] });
  await user.click(el.loadAllBtn());
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
  clearRequests();
  return { ...mounted, target, user };
}

async function openEditor(ctx) {
  await ctx.user.selectOptions(actionSelect(0), "edit");
  expect(el.editorSection().hidden).toBe(false);
}

// Both writes answered; the item PATCH can be made to 409 once.
function answerWrites(target, { itemConflictsOnce = false, itemStatus = null } = {}) {
  let conflicts = itemConflictsOnce ? 1 : 0;
  server.use(
    http.patch(`/items/${target.id}/barcodes`, () => HttpResponse.json(target)),
    http.patch(`/items/${target.id}`, () => {
      if (conflicts > 0) {
        conflicts -= 1;
        return HttpResponse.json({ detail: "Barcode belongs to an archived item" }, { status: 409 });
      }
      if (itemStatus) return HttpResponse.json({ detail: "Save is locked" }, { status: itemStatus });
      return HttpResponse.json(target);
    }),
  );
}

describe("opening the editor", () => {
  it("prefills every field and one row per additional barcode", async () => {
    const ctx = await loadedRow({ barcode: "B1", location: "A1", price: "2.50",
      product_link: "https://x.test/p", barcodes: ["ALT1", "ALT2"] });
    const state = await importView("state.js");
    await openEditor(ctx);
    expect(byId("item-editor-selected").textContent).toBe("Editing: Target");
    expect(byId("item-editor-barcode").value).toBe("B1");
    expect(byId("item-editor-name").value).toBe("Target");
    expect(byId("item-editor-location").value).toBe("A1");
    expect(byId("item-editor-price").value).toBe("2.50");
    expect(byId("item-editor-product-link").value).toBe("https://x.test/p");
    expect(barcodeRows().map((r) => codeIn(r).value)).toEqual(["ALT1", "ALT2"]);
    expect(state.getEditingItemId()).toBe(ctx.target.id);
  });

  it("a null price and link open as empty fields", async () => {
    const ctx = await loadedRow({ price: null, product_link: null });
    await openEditor(ctx);
    expect(byId("item-editor-price").value).toBe("");
    expect(byId("item-editor-product-link").value).toBe("");
    expect(barcodeRows()).toHaveLength(0);
  });

  it("add and remove barcode rows; closeItemEditor clears the panel and the id", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"] });
    const state = await importView("state.js");
    const editor = await importView("views/itemEditor.js");
    await openEditor(ctx);
    await ctx.user.click(byId("item-editor-add-barcode-btn"));
    expect(barcodeRows()).toHaveLength(2);
    await ctx.user.click(barcodeRows()[0].querySelector(".note-remove-btn"));
    expect(barcodeRows()).toHaveLength(1);
    editor.closeItemEditor();
    expect(el.editorSection().hidden).toBe(true);
    expect(barcodeRows()).toHaveLength(0);
    expect(state.getEditingItemId()).toBeNull();
    expect(message().textContent).toBe("");
  });

  it("Cancel closes it too", async () => {
    const ctx = await loadedRow();
    await openEditor(ctx);
    await ctx.user.click(byId("item-editor-cancel-btn"));
    expect(el.editorSection().hidden).toBe(true);
  });
});

describe("validation", () => {
  it.each([
    ["barcode", "item-editor-barcode"],
    ["name", "item-editor-name"],
    ["location", "item-editor-location"],
  ])("a blank %s is refused", async (_field, id) => {
    const ctx = await loadedRow();
    await openEditor(ctx);
    byId(id).value = "";
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe("Barcode, name, and location are required.");
    expect(requests()).toHaveLength(0);
  });

  it("a duplicated additional code names the code", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"] });
    await openEditor(ctx);
    await ctx.user.click(byId("item-editor-add-barcode-btn"));
    codeIn(barcodeRows()[1]).value = "ALT1";
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe('The barcode "ALT1" is listed twice. Remove the duplicate.');
    expect(requests()).toHaveLength(0);
  });

  it("Save with nothing open says so", async () => {
    await loadedRow();
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("No item selected."));
    expect(requests()).toHaveLength(0);
  });
});

describe("the write sequence", () => {
  it("an unchanged barcode list costs one PATCH, with price parsed and a blank link nulled", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"], price: "2.50", product_link: null });
    answerWrites(ctx.target);
    await openEditor(ctx);
    byId("item-editor-name").value = "Renamed";
    byId("item-editor-price").value = "3.75";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    expect(patches()).toEqual([["/items/:id", false]]);
    expect(requestFor(`/items/${ctx.target.id}`, "PATCH").body).toEqual({
      barcode: "B1", name: "Renamed", location: "A1",
      price: 3.75, product_link: null, override_archived: false,
    });
  });

  it("a changed list PATCHes the barcodes first, then the item", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"] });
    answerWrites(ctx.target);
    await openEditor(ctx);
    codeIn(barcodeRows()[0]).value = "ALT9";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    expect(patches()).toEqual([["/items/:id/barcodes", false], ["/items/:id", false]]);
    expect(requestFor(`/items/${ctx.target.id}/barcodes`, "PATCH").body)
      .toEqual({ barcodes: ["ALT9"], override_archived: false });
  });

  it("a second save with no further change sends no barcodes PATCH", async () => {
    const ctx = await loadedRow({ fake: true, barcodes: ["ALT1"] });
    answerWrites(ctx.target);
    await openEditor(ctx);
    codeIn(barcodeRows()[0]).value = "ALT9";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    clearRequests();
    saveClick();                                      // still open: the close is 1 s out
    await vi.waitFor(() => expect(patches()).toEqual([["/items/:id", false]]));
  });
});

describe("the barcode-change warning", () => {
  it("No leaves the panel open, clears the message and writes nothing", async () => {
    const ctx = await loadedRow();
    const { BARCODE_CHANGE_WARNING } = await importView("itemSave.js");
    answerWrites(ctx.target);
    await openEditor(ctx);
    byId("item-editor-barcode").value = "B2";
    saveClick();
    await vi.waitFor(() => expect(byId("scan-confirm-overlay").hidden).toBe(false));
    expect(confirmTitle()).toBe(BARCODE_CHANGE_WARNING);
    await answerConfirm(false);
    await vi.waitFor(() => expect(message().textContent).toBe(""));
    expect(el.editorSection().hidden).toBe(false);
    expect(requests()).toHaveLength(0);
  });

  it("Yes lets both writes through", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"] });
    answerWrites(ctx.target);
    await openEditor(ctx);
    byId("item-editor-barcode").value = "B2";
    codeIn(barcodeRows()[0]).value = "ALT9";
    saveClick();
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    expect(patches()).toEqual([["/items/:id/barcodes", false], ["/items/:id", false]]);
    expect(requestFor(`/items/${ctx.target.id}`, "PATCH").body.barcode).toBe("B2");
  });
});

describe("archived reuse", () => {
  it("a 409 prompts once and retries the whole sequence with the override", async () => {
    const ctx = await loadedRow({ barcodes: ["ALT1"] });
    answerWrites(ctx.target, { itemConflictsOnce: true });
    await openEditor(ctx);
    codeIn(barcodeRows()[0]).value = "ALT9";
    saveClick();
    await vi.waitFor(() => expect(byId("scan-confirm-overlay").hidden).toBe(false));
    expect(confirmTitle()).toBe("Barcode exists but is archived. Continue?");
    await answerConfirm(true);
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    expect(patches()).toEqual([
      ["/items/:id/barcodes", false], ["/items/:id", false],
      ["/items/:id/barcodes", true], ["/items/:id", true],
    ]);
  });

  it("declining the prompt clears the message and stops there", async () => {
    const ctx = await loadedRow();
    answerWrites(ctx.target, { itemConflictsOnce: true });
    await openEditor(ctx);
    byId("item-editor-name").value = "Renamed";
    saveClick();
    await answerConfirm(false);
    await vi.waitFor(() => expect(message().textContent).toBe(""));
    expect(patches()).toEqual([["/items/:id", false]]);
    expect(el.editorSection().hidden).toBe(false);
  });
});

describe("success and failure", () => {
  it("success reports, awaits onSaved, and closes a second later", async () => {
    const ctx = await loadedRow({ fake: true });
    const editor = await importView("views/itemEditor.js");
    const saved = vi.fn();
    editor.setOnSaved(saved);
    answerWrites(ctx.target);
    await openEditor(ctx);
    byId("item-editor-name").value = "Renamed";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Item saved."));
    expect(message().className).toBe("success");
    expect(saved).toHaveBeenCalledTimes(1);
    expect(el.editorSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(el.editorSection().hidden).toBe(true);
  });

  it("a failure keeps the panel open with the detail", async () => {
    const ctx = await loadedRow();
    const state = await importView("state.js");
    answerWrites(ctx.target, { itemStatus: 500 });
    await openEditor(ctx);
    byId("item-editor-name").value = "Renamed";
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe("Save is locked");
    expect(el.editorSection().hidden).toBe(false);
    expect(state.getEditingItemId()).toBe(ctx.target.id);
  });
});
