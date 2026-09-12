// Characterization coverage for views/correction.js and the shared
// views/correctionPanel.js it is built from (P6 deviation 4: the panel is
// covered once, here, against its Saved Items host; P6e asserts only
// toolCorrection.js's own wiring).
//
// Opened from the row action on a loaded row and saved through the real
// button, so the validation ladder runs in its real order.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionSelect, clearRequests, el, mountItems, requestFor, requests, restoreItems, rows,
} from "../helpers/items.js";
import { importView } from "../helpers/shell.js";
import { item as itemFactory } from "../helpers/factories.js";

afterEach(() => restoreItems());

const byId = (id) => document.getElementById(id);
const message = () => byId("correction-message");
const quantityIn = () => byId("correction-new-quantity");
const reasonIn = () => byId("correction-reason");
const saveClick = () => byId("correction-save-btn").click();

async function loadedRow({ role = "admin", fake = false, ...overrides } = {}) {
  if (fake) vi.useFakeTimers();
  const user = userEvent.setup(fake ? { advanceTimers: vi.advanceTimersByTime } : {});
  const target = itemFactory({ name: "Target", barcode: "B1", quantity: "10", ...overrides });
  const mounted = await mountItems({ role, items: [target] });
  await user.click(el.loadAllBtn());
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
  clearRequests();
  return { ...mounted, target, user };
}

async function openCorrection(ctx) {
  await ctx.user.selectOptions(actionSelect(0), "correct");
  expect(el.correctionSection().hidden).toBe(false);
}

const answerAdjust = (status = null) => server.use(http.post("/transactions/adjust",
  () => status
    ? HttpResponse.json({ detail: "Adjustments are locked" }, { status })
    : HttpResponse.json({ id: "t1" })));

describe("opening the panel", () => {
  it("names the row, shows the current count, prefills and focuses the field", async () => {
    const ctx = await loadedRow();
    const correction = await importView("views/correction.js");
    await openCorrection(ctx);
    expect(byId("correction-selected").textContent).toBe("Correcting: Target (B1)");
    expect(byId("correction-current").textContent).toBe("Current count: 10");
    expect(quantityIn().value).toBe("10");
    expect(reasonIn().value).toBe("");
    expect(message().textContent).toBe("");
    expect(document.activeElement).toBe(quantityIn());
    expect(correction.getEditingCorrectionItemId()).toBe(ctx.target.id);
  });

  it("closeCorrection clears the panel and the editing id", async () => {
    const ctx = await loadedRow();
    const correction = await importView("views/correction.js");
    await openCorrection(ctx);
    correction.closeCorrection();
    expect(el.correctionSection().hidden).toBe(true);
    expect(quantityIn().value).toBe("");
    expect(reasonIn().value).toBe("");
    expect(correction.getEditingCorrectionItemId()).toBeNull();
  });

  it("Cancel does the same", async () => {
    const ctx = await loadedRow();
    const correction = await importView("views/correction.js");
    await openCorrection(ctx);
    reasonIn().value = "typed";
    await ctx.user.click(byId("correction-cancel-btn"));
    expect(el.correctionSection().hidden).toBe(true);
    expect(reasonIn().value).toBe("");
    expect(correction.getEditingCorrectionItemId()).toBeNull();
  });
});

describe("the validation ladder", () => {
  it("nothing open: no item selected", async () => {
    await loadedRow();
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("No item selected."));
    expect(message().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it.each([
    // A number input drops non-numeric text, so "abc" arrives as "" and the
    // blank branch answers first -- the `!Number.isFinite` half of that same
    // check is unreachable from this panel (N-P6-CHARACTERIZED).
    ["a blank count", "", "recount", "Enter a valid new count."],
    ["a non-numeric count", "abc", "recount", "Enter a valid new count."],
    ["a negative count", "-1", "recount", "Enter a count of zero or more."],
    ["no reason", "7", "   ", "Enter a reason for the correction."],
  ])("%s is refused", async (_name, quantity, reason, expected) => {
    const ctx = await loadedRow();
    await openCorrection(ctx);
    quantityIn().value = quantity;
    reasonIn().value = reason;
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe(expected);
    expect(requests()).toHaveLength(0);
    expect(el.correctionSection().hidden).toBe(false);
  });
});

describe("submitting", () => {
  it("posts the absolute count and the trimmed reason, then closes a second later", async () => {
    const ctx = await loadedRow({ fake: true });
    const correction = await importView("views/correction.js");
    const saved = vi.fn();
    correction.setOnSaved(saved);                          // replaces items.js's refresh
    answerAdjust();
    await openCorrection(ctx);
    quantityIn().value = "7.5";
    reasonIn().value = "  recount  ";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Count corrected."));
    expect(message().className).toBe("success");
    expect(requestFor("/transactions/adjust", "POST").body)
      .toEqual({ item_id: ctx.target.id, new_quantity: 7.5, reason: "recount" });
    expect(saved).toHaveBeenCalledTimes(1);
    expect(el.correctionSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(el.correctionSection().hidden).toBe(true);
    expect(quantityIn().value).toBe("");
    expect(reasonIn().value).toBe("");
  });

  it("zero is a valid count", async () => {
    const ctx = await loadedRow();
    answerAdjust();
    await openCorrection(ctx);
    quantityIn().value = "0";
    reasonIn().value = "emptied";
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Count corrected."));
    expect(requestFor("/transactions/adjust", "POST").body.new_quantity).toBe(0);
  });

  it("a failure keeps the panel open with the detail and the item still selected", async () => {
    const ctx = await loadedRow();
    const correction = await importView("views/correction.js");
    answerAdjust(500);
    await openCorrection(ctx);
    reasonIn().value = "recount";
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe("Adjustments are locked");
    expect(el.correctionSection().hidden).toBe(false);
    expect(correction.getEditingCorrectionItemId()).toBe(ctx.target.id);
  });
});

describe("createCorrectionPanel", () => {
  it("builds the same panel against another id prefix and noun", async () => {
    await mountItems({ role: "admin" });
    const { createCorrectionPanel } = await importView("views/correctionPanel.js");
    const submit = vi.fn(() => Promise.resolve());
    const panel = createCorrectionPanel({ idPrefix: "tool-correction", noun: "tool", submit });
    expect(Object.keys(panel).sort()).toEqual(["close", "getEditingId", "open", "setOnSaved"]);
    panel.open({ id: "t1", name: "Drill", barcode: "T1", quantity: "3" });
    expect(byId("tool-correction-section").hidden).toBe(false);
    expect(byId("tool-correction-selected").textContent).toBe("Correcting: Drill (T1)");
    expect(byId("tool-correction-new-quantity").value).toBe("3");
    expect(panel.getEditingId()).toBe("t1");
    panel.close();
    expect(byId("tool-correction-section").hidden).toBe(true);
    expect(panel.getEditingId()).toBeNull();
    expect(submit).not.toHaveBeenCalled();
  });

  it("its no-selection message uses the caller's noun", async () => {
    await mountItems({ role: "admin" });
    const { createCorrectionPanel } = await importView("views/correctionPanel.js");
    createCorrectionPanel({ idPrefix: "tool-correction", noun: "tool", submit: vi.fn() });
    byId("tool-correction-save-btn").click();
    await vi.waitFor(() => expect(byId("tool-correction-message").textContent).toBe("No tool selected."));
  });
});
