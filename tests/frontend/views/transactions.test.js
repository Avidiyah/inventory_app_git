// Characterization coverage for views/transactions.js: the work-order gate,
// the scan-and-go batch lifecycle, commit / undo / retry, the sessionStorage
// snapshot and resume, the manual-entry panel, and the two seams main.js
// injects. Scanning itself is P5g's -- the commit contract is exercised here
// through `commitScannedItem` and the manual-entry panel, which is the same
// path a decode takes.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server, pageHandlers } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, answerConfirmQuantity, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  answerStart, answerTransaction, answerVoid, cardEls, el, inBatch, logLines, mountTransactions,
  openGate, pickManual, restoreTransactions, savedBatch,
} from "../helpers/transactions.js";
import { item as itemFactory, transaction as txnFactory, workOrderCard, workOrderDetail } from "../helpers/factories.js";

afterEach(() => restoreTransactions());

describe("mountTransactions", () => {
  it("mounts against the real Transaction markup with nothing loaded", async () => {
    const { mod } = await mountTransactions();
    expect(typeof mod.enterTransactionPage).toBe("function");
    expect(el.gate().hidden).toBe(false);   // markup default
    expect(el.active().hidden).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});

describe("enterTransactionPage at the gate", () => {
  it.each([
    ["technician", true, "No work orders assigned to you."],
    ["supervisor", false, "No ready work orders. Import the work-order CSV to add them."],
    ["owner", false, "No ready work orders. Import the work-order CSV to add them."],
  ])("%s: search card hidden=%s, empty copy", async (role, searchHidden, copy) => {
    await openGate({ role, workOrders: [] });
    expect(el.gate().hidden).toBe(false);
    expect(el.active().hidden).toBe(true);
    expect(el.scanSection().hidden).toBe(true);
    expect(el.manualSection().hidden).toBe(true);
    expect(el.gateCardsSection().hidden).toBe(false);
    expect(el.gateSearchCard().hidden).toBe(searchHidden);
    expect(el.gateCardsMessage().textContent).toBe(copy);
    expect(requestFor("/work-orders/", "GET").url).toBe("/work-orders/");
  });

  it("renders only created/assigned/in_progress cards, with status label, place, and assignee for supervisor+", async () => {
    const cards = [
      workOrderCard({ number: "1", status: "created", community: "Maple", building_number: "3", unit_number: "12", assigned_to_name: null }),
      workOrderCard({ number: "2", status: "assigned", assigned_to_name: "Pat" }),
      workOrderCard({ number: "3", status: "in_progress", priority: "Urgent" }),
      workOrderCard({ number: "4", status: "completed" }),
      workOrderCard({ number: "5", status: "on_hold" }),
    ];
    await openGate({ role: "supervisor", workOrders: cards });
    expect(cardEls().map((c) => c.dataset.wo)).toEqual(["1", "2", "3"]);
    const [c1, c2, c3] = cardEls();
    expect(c1.querySelector(".wo-card-status-label").textContent).toBe("Created");
    expect(c1.querySelector(".wo-card-meta").textContent).toBe("Maple · Bldg 3 · Unit 12");
    expect(c1.querySelector(".wo-card-assignee").textContent).toBe("Unassigned");
    expect(c2.querySelector(".wo-card-assignee").textContent).toBe("Assigned: Pat");
    expect(c3.className).toBe("wo-card wo-card-status-in_progress wo-card-urgent");
    expect(c3.dataset.woStatus).toBe("in_progress");
  });

  it("a technician's cards carry no assignee span", async () => {
    await openGate({ role: "technician", workOrders: [workOrderCard({ status: "assigned", assigned_to_name: "Me" })] });
    expect(cardEls()[0].querySelector(".wo-card-assignee")).toBeNull();
  });

  it("a failed list shows friendlyError in the cards message", async () => {
    await openGate({ role: "technician", handlers: [
      http.get("/work-orders/", () => HttpResponse.json({ detail: "x" }, { status: 500 })),
    ] });
    expect(el.gateCardsMessage().className).toBe("error");
  });
});

describe("gate filter (supervisor+)", () => {
  beforeEach(() => vi.useFakeTimers());

  it("debounces 250 ms, sends q, and reports no match with the term", async () => {
    await openGate({ role: "supervisor", workOrders: [workOrderCard({ number: "7001", status: "assigned" })] });
    clearRequests();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(el.gateInput(), "99");
    expect(requestFor("/work-orders/?q=")).toBeNull();
    await vi.advanceTimersByTimeAsync(249);
    expect(requestFor("/work-orders/?q=")).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => expect(requestFor("/work-orders/?q=99", "GET")).not.toBeNull());
    await vi.waitFor(() => expect(el.gateCardsMessage().textContent).toBe("No work orders match “99”."));
  });

  it("Enter searches immediately; clearing the box refreshes with no delay and no q", async () => {
    await openGate({ role: "supervisor", workOrders: [workOrderCard({ number: "7001", status: "assigned" })] });
    clearRequests();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(el.gateInput(), "70{Enter}");
    await vi.advanceTimersByTimeAsync(0);
    await vi.waitFor(() => expect(requestFor("/work-orders/?q=70", "GET")).not.toBeNull());
    await user.clear(el.gateInput());
    await vi.advanceTimersByTimeAsync(0);
    await vi.waitFor(() => expect(requests().at(-1).url).toBe("/work-orders/"));
  });

  it("typing again inside the window cancels the earlier timer: one request, the final term", async () => {
    await openGate({ role: "supervisor", workOrders: [] });
    clearRequests();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(el.gateInput(), "7");
    await vi.advanceTimersByTimeAsync(100);
    await user.type(el.gateInput(), "0");
    await vi.advanceTimersByTimeAsync(250);
    await vi.waitFor(() => expect(requests().filter((r) => r.url.startsWith("/work-orders/?q="))).toHaveLength(1));
    expect(requests().at(-1).url).toBe("/work-orders/?q=70");
  });

  it("a technician's input is ignored by the filter: no q is ever sent", async () => {
    // The search card is hidden for technicians; refreshWoCards also ignores
    // the field's value for that role. Both halves of the gate, pinned.
    const { mod } = await openGate({ role: "technician", workOrders: [] });
    clearRequests();
    el.gateInput().value = "42";
    mod.enterTransactionPage(); // re-runs refreshWoCards
    await vi.waitFor(() => expect(requests().at(-1).url).toBe("/work-orders/"));
  });
});

describe("selectWorkOrderForBatch", () => {
  it("in_progress starts the batch: label, quantity 1, dispense, sections, one /items/ load", async () => {
    const { wo } = await inBatch({ role: "technician", items: [itemFactory({ name: "Bulb" })] });
    expect(el.gate().hidden).toBe(true);
    expect(el.woLabel().textContent).toBe(`Work order: ${wo.number}`);
    expect(el.quantity().value).toBe("1");
    expect(el.type().value).toBe("dispense");
    expect(el.scanSection().hidden).toBe(false);
    expect(el.manualSection().hidden).toBe(false);
    expect(el.gateCardsSection().hidden).toBe(true);
    expect(el.summary().hidden).toBe(true);
    expect(el.log().hidden).toBe(true);
    // The snapshot is written at batch START, not at the first commit:
    // startBatchFor assigns batchWorkOrder before calling setScangoType, whose
    // persistBatch() is therefore no longer the no-op its comment claims.
    expect(savedBatch()).toMatchObject({ workOrder: { id: wo.id, number: wo.number, status: "in_progress" }, batchScanCount: 0, log: [] });
  });

  it("assigned → confirm copy → Yes posts /start and starts on the returned detail", async () => {
    const card = workOrderCard({ number: "7002", status: "assigned" });
    await openGate({ role: "technician", workOrders: [card] });
    answerStart(workOrderDetail({ id: card.id, number: "7002", status: "in_progress" }));
    const clicking = userEvent.setup().click(cardEls()[0]);
    await vi.waitFor(() => expect(confirmTitle()).toBe("Start WO 7002? This will set it to In-Progress."));
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(el.active().hidden).toBe(false));
    expect(requestFor(`/work-orders/${card.id}/start`, "POST").body).toEqual({});
    expect(el.woLabel().textContent).toBe("Work order: 7002");
  });

  it("assigned → No leaves the gate untouched and posts nothing", async () => {
    await openGate({ role: "technician", workOrders: [workOrderCard({ status: "assigned" })] });
    clearRequests();
    const clicking = userEvent.setup().click(cardEls()[0]);
    await answerConfirm(false);
    await clicking;
    expect(el.active().hidden).toBe(true);
    expect(requests()).toHaveLength(0);
  });

  it("assigned → start fails: error at the gate and the cards refresh", async () => {
    await openGate({ role: "technician", workOrders: [workOrderCard({ status: "assigned" })] });
    answerStart(409);
    clearRequests();
    const clicking = userEvent.setup().click(cardEls()[0]);
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(el.gateMessage().className).toBe("error"));
    expect(requestFor("/work-orders/", "GET")).not.toBeNull(); // refreshWoCards
    expect(el.active().hidden).toBe(true);
  });

  it("created → confirm → Yes hands off to Work Orders with the card focused", async () => {
    const card = workOrderCard({ number: "7003", status: "created" });
    // pageHandlers() is registered AFTER the gate has painted, not through
    // `handlers`: mountTransactions puts `handlers` first, and pageHandlers'
    // own `GET /work-orders/` would then answer the gate's list with [].
    await openGate({ role: "supervisor", workOrders: [card] });
    server.use(...pageHandlers());
    const clicking = userEvent.setup().click(cardEls()[0]);
    await vi.waitFor(() => expect(confirmTitle()).toBe("WO 7003 is not assigned. Go to Work Orders to assign it?"));
    await answerConfirm(true);
    await clicking;
    expect(el.page("work-orders").classList.contains("active")).toBe(true);
    expect(el.page("transaction").classList.contains("active")).toBe(false);
    // focusWorkOrder(id) queues a card open that loadWorkOrders consumes; the
    // list request is the observable half here. P2 owns what happens next.
    await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
  });

  it("created → No stays put", async () => {
    await openGate({ role: "supervisor", workOrders: [workOrderCard({ status: "created" })] });
    const clicking = userEvent.setup().click(cardEls()[0]);
    await answerConfirm(false);
    await clicking;
    expect(el.page("work-orders").classList.contains("active")).toBe(false);
  });

  it("with no scan autostarter injected, starting a batch does not throw", async () => {
    await expect(inBatch({ role: "technician" })).resolves.toBeTruthy();
  });
});

describe("scanGoArmed", () => {
  it("false at the gate; true with the default 1; false for 0, blank, or NaN", async () => {
    const { mod } = await openGate({ role: "technician", workOrders: [workOrderCard({ status: "in_progress" })] });
    expect(mod.scanGoArmed()).toBe(false);
    await userEvent.setup().click(cardEls()[0]);
    await vi.waitFor(() => expect(el.active().hidden).toBe(false));
    expect(mod.scanGoArmed()).toBe(true);
    for (const v of ["0", "", "abc", "-2"]) { el.quantity().value = v; expect(mod.scanGoArmed()).toBe(false); }
    el.quantity().value = "2.5";
    expect(mod.scanGoArmed()).toBe(true);
  });
});

describe("commitScannedItem", () => {
  const bulb = () => itemFactory({ name: "Bulb", quantity: "10" });

  it("returns {committed:false} with no batch, and posts nothing", async () => {
    const { mod } = await mountTransactions({ role: "technician" });
    await expect(mod.commitScannedItem(bulb())).resolves.toEqual({ committed: false });
    expect(requests()).toHaveLength(0);
  });

  it("confirm carries the item name and a stepper; + bumps the posted quantity", async () => {
    const item = bulb();
    const { wo, mod } = await inBatch({ role: "technician", items: [item] });
    answerTransaction(txnFactory({ item_quantity: "8" }));
    const committing = mod.commitScannedItem(item);
    await vi.waitFor(() => expect(confirmTitle()).toBe("Take out Bulb?"));
    await answerConfirmQuantity({ steps: 1 });
    await expect(committing).resolves.toEqual({ committed: true });
    expect(requestFor("/transactions/", "POST").body).toEqual({
      item_id: item.id, transaction_type: "dispense", quantity: 2,
      work_order_id: wo.id, work_order_number: wo.number,
    });
    expect(logLines()).toHaveLength(1);
    expect(logLines()[0].className).toBe("scango-log-line scango-log-ok");
    expect(logLines()[0].querySelector(".scango-log-text").textContent).toBe("✓ Took out 2 × Bulb (now 8 on hand)");
    expect(logLines()[0].querySelector(".scango-log-undo-btn").textContent).toBe("Remove");
    expect(el.summary().textContent).toBe("This work order: 1 scan, 2 units");
    expect(el.quantity().value).toBe("1"); // reset for the next scan
  });

  it("declining resolves {committed:false, declined:true} and posts nothing", async () => {
    const item = bulb();
    const { mod } = await inBatch({ role: "technician", items: [item] });
    const committing = mod.commitScannedItem(item);
    await answerConfirmQuantity({ yes: false });
    await expect(committing).resolves.toEqual({ committed: false, declined: true });
    expect(requestFor("/transactions/")).toBeNull();
    expect(logLines()).toHaveLength(0);
  });

  it("falls back to a computed on-hand when item_quantity is null, and pluralises scans", async () => {
    const item = bulb();
    const { mod } = await inBatch({ role: "technician", items: [item] });
    answerTransaction(txnFactory({ item_quantity: null }));
    for (let i = 0; i < 2; i += 1) {
      const committing = mod.commitScannedItem(item);
      await answerConfirmQuantity();
      await committing;
    }
    expect(logLines()[0].querySelector(".scango-log-text").textContent).toBe("✓ Took out 1 × Bulb (now 8 on hand)");
    expect(logLines()[1].querySelector(".scango-log-text").textContent).toBe("✓ Took out 1 × Bulb (now 9 on hand)");
    expect(el.summary().textContent).toBe("This work order: 2 scans, 2 units");
  });

  it("recount_required renders a warning line with the recount tail", async () => {
    const item = bulb();
    const { mod } = await inBatch({ role: "technician", items: [item] });
    answerTransaction(txnFactory({ recount_required: true, item_quantity: "0" }));
    const committing = mod.commitScannedItem(item);
    await answerConfirmQuantity();
    await committing;
    expect(logLines()[0].className).toBe("scango-log-line scango-log-warning");
    expect(logLines()[0].textContent).toContain("⚠ Took out 1 × Bulb (now 0 on hand) — Please re-count stock");
  });

  it("a failed post logs a cross with friendlyError and a Retry button; tallies untouched", async () => {
    const item = bulb();
    const { mod } = await inBatch({ role: "technician", items: [item] });
    answerTransaction(400, { detail: "Insufficient stock to dispense." });
    const committing = mod.commitScannedItem(item);
    await answerConfirmQuantity();
    await expect(committing).resolves.toEqual({ committed: false });
    expect(logLines()[0].className).toBe("scango-log-line scango-log-err");
    expect(logLines()[0].querySelector(".scango-log-text").textContent)
      .toBe("✗ Bulb: Not enough stock available. Check the count before taking more out.");
    expect(logLines()[0].querySelector(".scango-log-retry-btn")).not.toBeNull();
    expect(el.summary().hidden).toBe(true);
  });

  it("updates the manual panel's on-hand number in place after a commit", async () => {
    const item = bulb();
    const { mod } = await inBatch({ role: "technician", items: [item] });
    answerTransaction(txnFactory({ item_quantity: "7" }));
    const committing = mod.commitScannedItem(item);
    await answerConfirmQuantity();
    await committing;
    await userEvent.setup().type(el.search(), "bulb");
    expect(el.results().textContent).toContain("On hand: 7");
  });
});

describe("quick mode", () => {
  it("toggle text/aria flip; a dispense commits with no modal; the page quantity is used", async () => {
    const item = itemFactory({ name: "Bulb", quantity: "10" });
    const { mod } = await inBatch({ role: "technician", items: [item] });
    const user = userEvent.setup();
    expect(el.quickToggle().hidden).toBe(false);
    await user.click(el.quickToggle());
    expect(el.quickToggle().textContent).toBe("Quick mode: On");
    expect(el.quickToggle().getAttribute("aria-pressed")).toBe("true");
    answerTransaction(txnFactory());
    await user.clear(el.quantity()); await user.type(el.quantity(), "3");
    await expect(mod.commitScannedItem(item)).resolves.toEqual({ committed: true });
    expect(confirmOverlay().hidden).toBe(true);
    expect(requestFor("/transactions/", "POST").body.quantity).toBe(3);
  });

  it("quick mode never skips the confirm for stock", async () => {
    const item = itemFactory({ name: "Bulb" });
    const { mod } = await inBatch({ role: "supervisor", items: [item] });
    const user = userEvent.setup();
    await user.click(el.quickToggle());
    await user.click(el.advancedToggle());
    await user.click(el.segStock());
    answerTransaction(txnFactory());
    const committing = mod.commitScannedItem(item);
    await vi.waitFor(() => expect(confirmTitle()).toBe("Add Bulb?"));
    await answerConfirmQuantity();
    await committing;
    expect(requestFor("/transactions/", "POST").body.transaction_type).toBe("stock");
    expect(logLines()[0].textContent).toContain("✓ Added 1 × Bulb");
  });
});

describe("advanced mode (supervisor+ opt-in)", () => {
  it("technician: toggle hidden, direction fixed, type pinned to dispense even if set", async () => {
    await inBatch({ role: "technician" });
    expect(el.advancedToggle().hidden).toBe(true);
    expect(el.direction().hidden).toBe(true);
    expect(el.directionFixed().hidden).toBe(false);
    expect(el.type().value).toBe("dispense");
  });

  it("supervisor: default streamlined; opt-in reveals the direction toggle and browse-all", async () => {
    const items = [itemFactory({ name: "Zed" }), itemFactory({ name: "Alpha" })];
    await inBatch({ role: "supervisor", items });
    expect(el.advancedToggle().hidden).toBe(false);
    expect(el.advancedToggle().textContent).toBe("Manual entry & stock options");
    expect(el.direction().hidden).toBe(true);
    expect(el.results().hidden).toBe(true); // empty search, not advanced: nothing
    await userEvent.setup().click(el.advancedToggle());
    expect(el.advancedToggle().textContent).toBe("Hide manual entry");
    expect(el.advancedToggle().getAttribute("aria-expanded")).toBe("true");
    expect(el.direction().hidden).toBe(false);
    expect(el.directionFixed().hidden).toBe(true);
    // browse-all: every item, name-sorted
    expect(Array.from(el.results().querySelectorAll(".manual-item-name")).map((n) => n.textContent)).toEqual(["Alpha", "Zed"]);
    await userEvent.setup().click(el.segStock());
    expect(el.type().value).toBe("stock");
    expect(el.segStock().classList.contains("active")).toBe(true);
    await userEvent.setup().click(el.advancedToggle()); // opt back out
    expect(el.type().value).toBe("dispense"); // pinned again
  });
});

// One committed log line in an active batch, requests cleared. Shared with the
// persistence suite below.
async function committedLine({ role = "technician", txn = txnFactory({ item_quantity: "9" }), qty = 1 } = {}) {
  const item = itemFactory({ name: "Bulb", quantity: "10" });
  const ctx = await inBatch({ role, items: [item] });
  answerTransaction(txn);
  const committing = ctx.mod.commitScannedItem(item);
  await answerConfirmQuantity({ type: qty });
  await committing;
  clearRequests();
  return { ...ctx, item, txn };
}

describe("Remove", () => {
  it("voids, backs the tallies out, strikes the line, drops the button, persists undone", async () => {
    const { txn } = await committedLine({ qty: 2 });
    answerVoid(204);
    await userEvent.setup().click(logLines()[0].querySelector(".scango-log-undo-btn"));
    await vi.waitFor(() => expect(requestFor(`/transactions/${txn.id}`, "DELETE")).not.toBeNull());
    await vi.waitFor(() => expect(logLines()[0].classList.contains("scango-log-undone")).toBe(true));
    expect(logLines()[0].querySelector(".scango-log-text").textContent).toBe("✓ Took out 2 × Bulb (now 9 on hand) — Removed");
    expect(logLines()[0].querySelector(".scango-log-undo-btn")).toBeNull();
    expect(el.summary().textContent).toBe("This work order: 0 scans, 0 units");
    const saved = savedBatch();
    expect(saved.log[0]).toMatchObject({ undone: true, undo: null });
    expect(saved.batchScanCount).toBe(0);
  });

  it("a failing void re-enables the button and reports in #scango-message", async () => {
    await committedLine();
    answerVoid(403);
    const btn = logLines()[0].querySelector(".scango-log-undo-btn");
    await userEvent.setup().click(btn);
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(btn.disabled).toBe(false);
    expect(logLines()[0].classList.contains("scango-log-undone")).toBe(false);
    // "1 units": the units half of the summary has no singular form.
    expect(el.summary().textContent).toBe("This work order: 1 scan, 1 units");
  });

  it("the manual panel's on-hand goes back up after a dispense is removed", async () => {
    const { item } = await committedLine({ txn: txnFactory({ item_quantity: "9" }) });
    answerVoid(204);
    await userEvent.setup().click(logLines()[0].querySelector(".scango-log-undo-btn"));
    await vi.waitFor(() => expect(logLines()[0].classList.contains("scango-log-undone")).toBe(true));
    await userEvent.setup().type(el.search(), item.name);
    expect(el.results().textContent).toContain("On hand: 10");
  });
});

describe("Retry", () => {
  async function failedLine() {
    const item = itemFactory({ name: "Bulb", quantity: "10" });
    const ctx = await inBatch({ role: "technician", items: [item] });
    answerTransaction(500, { detail: "db down" });
    const committing = ctx.mod.commitScannedItem(item);
    await answerConfirmQuantity({ type: 3 });
    await committing;
    clearRequests();
    return { ...ctx, item };
  }

  it("re-posts the captured item/quantity/type and converts the line into a commit", async () => {
    const { item, wo } = await failedLine();
    el.quantity().value = "1"; // page field is NOT what retry uses
    answerTransaction(txnFactory({ item_quantity: "7" }));
    await userEvent.setup().click(logLines()[0].querySelector(".scango-log-retry-btn"));
    await vi.waitFor(() => expect(logLines()[0].classList.contains("scango-log-ok")).toBe(true));
    expect(requestFor("/transactions/", "POST").body).toEqual({
      item_id: item.id, transaction_type: "dispense", quantity: 3, work_order_id: wo.id, work_order_number: wo.number,
    });
    expect(logLines()[0].querySelector(".scango-log-text").textContent).toBe("✓ Took out 3 × Bulb (now 7 on hand)");
    expect(logLines()[0].querySelector(".scango-log-retry-btn")).toBeNull();
    expect(logLines()[0].querySelector(".scango-log-undo-btn")).not.toBeNull();
    expect(el.summary().textContent).toBe("This work order: 1 scan, 3 units");
    expect(savedBatch().log[0]).toMatchObject({ ok: true, retry: null });
  });

  it("a second failure refreshes the message and keeps Retry", async () => {
    await failedLine();
    answerTransaction(400, { detail: "Insufficient stock to dispense." });
    const btn = logLines()[0].querySelector(".scango-log-retry-btn");
    await userEvent.setup().click(btn);
    await vi.waitFor(() => expect(logLines()[0].textContent).toContain("Not enough stock available."));
    expect(btn.disabled).toBe(false);
    expect(logLines()[0].classList.contains("scango-log-err")).toBe(true);
  });

  it("retry maps the clicked line to its entry by position: newest-first after a later commit", async () => {
    const { item, mod } = await failedLine();
    answerTransaction(txnFactory());
    const committing = mod.commitScannedItem(item); // a NEW line lands above the failed one
    await answerConfirmQuantity();
    await committing;
    clearRequests();
    expect(logLines()[1].querySelector(".scango-log-retry-btn")).not.toBeNull();
    await userEvent.setup().click(logLines()[1].querySelector(".scango-log-retry-btn"));
    await vi.waitFor(() => expect(logLines()[1].classList.contains("scango-log-ok")).toBe(true));
    expect(requestFor("/transactions/", "POST").body.quantity).toBe(3);
  });
});

describe("batch snapshot", () => {
  it("is written after the first commit in the documented shape", async () => {
    const { wo, item, currentUser } = await committedLine({ qty: 2 });
    expect(savedBatch()).toEqual({
      userId: currentUser.id,
      workOrder: { id: wo.id, number: wo.number, status: "in_progress" },
      scangoType: "dispense",
      quickMode: false,
      batchScanCount: 1,
      batchUnitCount: 2,
      log: [{ text: "✓ Took out 2 × Bulb (now 9 on hand)", ok: true, warning: false, retry: null,
              undo: { txnId: expect.any(String), itemId: item.id, quantity: 2, type: "dispense" } }],
    });
  });

  it("quick-mode toggle persists immediately", async () => {
    await committedLine();
    await userEvent.setup().click(el.quickToggle());
    expect(savedBatch().quickMode).toBe(true);
  });

  it("a throwing sessionStorage.setItem does not break the commit (private browsing)", async () => {
    const item = itemFactory({ name: "Bulb" });
    const { mod } = await inBatch({ role: "technician", items: [item] });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("QuotaExceededError"); });
    answerTransaction(txnFactory());
    const committing = mod.commitScannedItem(item);
    await answerConfirmQuantity();
    await expect(committing).resolves.toEqual({ committed: true });
    expect(logLines()).toHaveLength(1);
    setItem.mockRestore();
  });
});

describe("resetBatch", () => {
  it("default clears the snapshot and returns to the gate with everything reset", async () => {
    const { mod } = await committedLine({ role: "supervisor" });
    await userEvent.setup().click(el.advancedToggle());
    await userEvent.setup().click(el.quickToggle());
    mod.resetBatch();
    expect(savedBatch()).toBeNull();
    expect(el.gate().hidden).toBe(false);
    expect(el.active().hidden).toBe(true);
    expect(el.quantity().value).toBe("1");
    expect(el.gateInput().value).toBe("");
    expect(logLines()).toHaveLength(0);
    expect(el.gateCards().children).toHaveLength(0); // resetWoCards; no refresh here
    // supervisorAdvanced and quickMode are reset too -- observable on the next
    // batch, where the toggles read their default copy again.
    expect(el.quickToggle().textContent).toBe("Quick mode: Off");
    expect(el.advancedToggle().textContent).toBe("Manual entry & stock options");
  });

  it("keepSaved:true leaves the snapshot for a resume", async () => {
    const { mod } = await committedLine();
    mod.resetBatch({ keepSaved: true });
    expect(savedBatch()).not.toBeNull();
    expect(el.gate().hidden).toBe(false);
  });
});

describe("tryResumeBatch", () => {
  const wo = { id: "00000000-0000-4000-8000-000000000042", number: "4242", status: "in_progress" };
  const snapshot = (userId, extra = {}) => ({
    userId, workOrder: wo, scangoType: "stock", quickMode: true, batchScanCount: 2, batchUnitCount: 5,
    log: [
      { text: "✓ Added 3 × Bulb (now 13 on hand)", ok: true, warning: false, retry: null, undo: { txnId: "t1", itemId: "i1", quantity: 3, type: "stock" } },
      { text: "✓ Added 2 × Bulb (now 10 on hand) — Removed", ok: true, warning: false, retry: null, undo: null, undone: true },
    ], ...extra,
  });

  it("owning user + active WO: restores label, tallies, log (with strike-through), type and quick mode", async () => {
    const { mod, currentUser } = await mountTransactions({ role: "supervisor", handlers: [
      http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo }))),
    ] });
    sessionStorage.setItem("scango-batch", JSON.stringify(snapshot(currentUser.id)));
    await expect(mod.tryResumeBatch(currentUser.id)).resolves.toBe(true);
    expect(el.active().hidden).toBe(false);
    expect(el.woLabel().textContent).toBe("Work order: 4242");
    expect(el.summary().textContent).toBe("This work order: 2 scans, 5 units");
    expect(logLines()).toHaveLength(2);
    expect(logLines()[1].classList.contains("scango-log-undone")).toBe(true);
    expect(logLines()[0].querySelector(".scango-log-undo-btn").dataset.txnId).toBe("t1");
    expect(el.quickToggle().textContent).toBe("Quick mode: On");
    // scangoType "stock" is restored -- but showScanGoState re-pins dispense
    // unless advanced mode is on, and supervisorAdvanced is NOT persisted. A
    // resumed stock batch silently becomes a dispense batch.
    expect(el.type().value).toBe("dispense");
    await vi.waitFor(() => expect(requestFor("/items/", "GET")).not.toBeNull());
  });

  it("returns false and fetches nothing for a different user", async () => {
    const { mod } = await mountTransactions({ role: "technician" });
    sessionStorage.setItem("scango-batch", JSON.stringify(snapshot(999999)));
    await expect(mod.tryResumeBatch(1)).resolves.toBe(false);
    expect(requests()).toHaveLength(0);
    expect(savedBatch()).not.toBeNull(); // untouched: the caller decides
  });

  it.each([["completed"], ["on_hold"], ["cancelled"]])("a %s work order clears the snapshot with the gate copy", async (status) => {
    const { mod, currentUser } = await mountTransactions({ role: "technician", handlers: [
      http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo, status }))),
    ] });
    sessionStorage.setItem("scango-batch", JSON.stringify(snapshot(currentUser.id)));
    await expect(mod.tryResumeBatch(currentUser.id)).resolves.toBe(false);
    expect(savedBatch()).toBeNull();
    expect(el.gateMessage().textContent).toBe("Your previous work order is no longer active — pick another to continue.");
  });

  it("404 clears; a network error keeps the snapshot and stays silent", async () => {
    const { mod, currentUser } = await mountTransactions({ role: "technician", handlers: [
      http.get("/work-orders/:id", () => HttpResponse.json({ detail: "gone" }, { status: 404 })),
    ] });
    sessionStorage.setItem("scango-batch", JSON.stringify(snapshot(currentUser.id)));
    await expect(mod.tryResumeBatch(currentUser.id)).resolves.toBe(false);
    expect(savedBatch()).toBeNull();

    sessionStorage.setItem("scango-batch", JSON.stringify(snapshot(currentUser.id)));
    server.use(http.get("/work-orders/:id", () => HttpResponse.error()));
    // The 404 above left its copy in the gate message and nothing clears it;
    // blanked by hand so "stays silent" is what the next assertion measures.
    el.gateMessage().textContent = "";
    await expect(mod.tryResumeBatch(currentUser.id)).resolves.toBe(false);
    expect(savedBatch()).not.toBeNull();
    expect(el.gateMessage().textContent).toBe("");
  });

  it("a malformed or work-order-less snapshot is ignored", async () => {
    const { mod } = await mountTransactions({ role: "technician" });
    sessionStorage.setItem("scango-batch", "{not json");
    await expect(mod.tryResumeBatch(1)).resolves.toBe(false);
    sessionStorage.setItem("scango-batch", JSON.stringify({ userId: 1, workOrder: {} }));
    await expect(mod.tryResumeBatch(1)).resolves.toBe(false);
    expect(requests()).toHaveLength(0);
  });
});

describe("Change work order", () => {
  it("with no scans: straight back to the gate, snapshot cleared, cards refreshed, focus for supervisor+", async () => {
    await inBatch({ role: "supervisor" });
    await userEvent.setup().click(el.changeWoBtn());
    expect(confirmOverlay().hidden).toBe(true);
    expect(el.gate().hidden).toBe(false);
    expect(savedBatch()).toBeNull();
    await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
    expect(document.activeElement).toBe(el.gateInput());
  });

  it("with scans: confirm copy; No keeps the batch; Yes clears it", async () => {
    await committedLine();
    const user = userEvent.setup();
    const first = user.click(el.changeWoBtn());
    await vi.waitFor(() => expect(confirmTitle()).toBe("Start a new work order? This clears the list below. Saved scans stay in history."));
    await answerConfirm(false);
    await first;
    expect(el.active().hidden).toBe(false);
    expect(savedBatch()).not.toBeNull();
    const second = user.click(el.changeWoBtn());
    await answerConfirm(true);
    await second;
    expect(el.active().hidden).toBe(true);
    expect(savedBatch()).toBeNull();
    expect(logLines()).toHaveLength(0);
  });

  it("a technician is not focused into the hidden search field", async () => {
    await inBatch({ role: "technician" });
    await userEvent.setup().click(el.changeWoBtn());
    expect(document.activeElement).not.toBe(el.gateInput());
  });
});

describe("the injected seams", () => {
  it("setScanResetter is called on change-work-order; setScanAutostarter on batch start and page re-entry", async () => {
    const { mod } = await openGate({ role: "technician", workOrders: [workOrderCard({ status: "in_progress" })] });
    const reset = vi.fn(); const auto = vi.fn();
    mod.setScanResetter(reset); mod.setScanAutostarter(auto);
    await userEvent.setup().click(cardEls()[0]);
    await vi.waitFor(() => expect(el.active().hidden).toBe(false));
    expect(auto).toHaveBeenCalledTimes(1);
    mod.enterTransactionPage();
    expect(auto).toHaveBeenCalledTimes(2);
    await userEvent.setup().click(el.changeWoBtn());
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("manual entry panel", () => {
  const catalogue = () => [
    itemFactory({ name: "Bulb A19", barcode: "111", quantity: "5", location: "A1" }),
    itemFactory({ name: "Bulb PAR38", barcode: "222", quantity: "2", location: "" }),
    itemFactory({ name: "Fuse", barcode: "bulb-333", quantity: "9" }),
    ...Array.from({ length: 9 }, (_, i) => itemFactory({ name: `Bulb spare ${i}`, barcode: `9${i}` })),
  ];

  it("filters by name or barcode, caps at 8, renders meta (location only when set)", async () => {
    await inBatch({ role: "technician", items: catalogue() });
    await userEvent.setup().type(el.search(), "bulb");
    const cards = el.results().querySelectorAll(".manual-item-card");
    expect(cards).toHaveLength(8);
    const first = cards[0];
    expect(first.querySelector(".manual-item-name").textContent).toBe("Bulb A19");
    expect(first.querySelector(".manual-item-meta").textContent).toBe("Barcode: 111On hand: 5Location: A1");
    const par = Array.from(cards).find((c) => c.textContent.includes("PAR38"));
    expect(par.querySelector(".manual-item-meta").textContent).not.toContain("Location");
  });

  it("ranking: an exact barcode match outranks a name substring", async () => {
    // filterRanked's own ordering rules are P1's; here only that the panel
    // uses it -- pinned by one concrete ordering.
    await inBatch({ role: "technician", items: catalogue() });
    await userEvent.setup().type(el.search(), "222");
    expect(el.results().querySelector(".manual-item-name").textContent).toBe("Bulb PAR38");
  });

  it("no match shows the hint; clearing the box hides the panel again (non-advanced)", async () => {
    await inBatch({ role: "technician", items: catalogue() });
    const user = userEvent.setup();
    await user.type(el.search(), "zzz");
    expect(el.results().hidden).toBe(false);
    expect(el.results().querySelector("p.hint").textContent).toBe("No matching items.");
    await user.clear(el.search());
    expect(el.results().hidden).toBe(true);
    expect(el.results().innerHTML).toBe("");
  });

  it("picking a result clears the search and commits through commitScannedItem", async () => {
    const items = catalogue();
    const { wo } = await inBatch({ role: "technician", items });
    answerTransaction(txnFactory());
    const picking = pickManual("fuse");
    await answerConfirmQuantity();
    await picking;
    expect(el.search().value).toBe("");
    expect(requestFor("/transactions/", "POST").body).toMatchObject({ item_id: items[2].id, work_order_id: wo.id });
  });

  it("the item cache is loaded once per batch and reused across page re-entry", async () => {
    const { mod } = await inBatch({ role: "technician", items: catalogue() });
    mod.enterTransactionPage();
    mod.enterTransactionPage();
    await new Promise((r) => setTimeout(r, 10));
    expect(requests().filter((r) => r.url === "/items/")).toHaveLength(0); // already loaded before clearRequests
  });

  it("a failed /items/ load leaves the panel empty but usable", async () => {
    await inBatch({ role: "technician", handlers: [http.get("/items/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await userEvent.setup().type(el.search(), "b");
    expect(el.results().querySelector("p.hint").textContent).toBe("No matching items.");
  });
});
