// Characterization coverage for views/history.js: the three sub-tabs, the
// overlay filters and their debounce, pagination, the role-gated Charge
// column, void, the inline billing editor hand-off, the archived-work-order
// restore offer, and the pricing list.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { fireEvent } from "@testing-library/dom";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  answerHistoryPages, cells, chargeCell, el, lastQuery, mountHistory, openHistory,
  restoreHistory, rowEls, seedUsers, voidBtn,
} from "../helpers/history.js";
import { historyRow, item as itemFactory, workOrderCard, workOrderDetail, workOrderItem } from "../helpers/factories.js";

afterEach(() => restoreHistory());

const historyState = () => import("../../../backend/static/state.js");

describe("mountHistory", () => {
  it("mounts with the results hidden and nothing fetched", async () => {
    const { mod } = await mountHistory();
    expect(typeof mod.loadHistory).toBe("function");
    expect(typeof mod.setHistoryTab).toBe("function");
    expect(typeof mod.renderHistory).toBe("function");
    expect(el.results().hidden).toBe(true);
    expect(el.page().dataset.activeFeature).toBe("all");
    expect(requests()).toHaveLength(0);
  });
});

describe("loadHistory", () => {
  it("requests page 1 of 10 with no filters and reveals the results", async () => {
    await openHistory({ rows: [historyRow()] });
    expect(lastQuery()).toEqual({ page: "1", page_size: "10" });
    expect(el.results().hidden).toBe(false);
    expect(rowEls()).toHaveLength(1);
  });

  it("paints a skeleton only while the results are hidden", async () => {
    let release;
    const { mod } = await mountHistory({ handlers: [http.get("/transactions/", () =>
      new Promise((r) => { release = () => r(HttpResponse.json({ items: [historyRow()], total: 1 })); }))] });
    const first = mod.loadHistory();
    expect(el.results().hidden).toBe(false);
    expect(el.tbody().querySelector("tr.skel-row")).not.toBeNull();
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));   // MSW reaches the handler asynchronously
    release(); release = null; await first;
    expect(el.tbody().querySelector("tr.skel-row")).toBeNull();
    const second = mod.loadHistory();          // results already visible: no flicker
    expect(el.tbody().querySelector("tr.skel-row")).toBeNull();
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    release(); await second;
  });

  it("item tab with no item, and user tab with no user, hide the results and fetch nothing", async () => {
    const { mod } = await mountHistory();
    const state = await historyState();
    state.updateHistoryState({ tab: "item", itemId: null });
    await mod.loadHistory();
    expect(el.results().hidden).toBe(true);
    state.updateHistoryState({ tab: "user", userId: null });
    await mod.loadHistory();
    expect(requests()).toHaveLength(0);
  });

  it("a failed load renders friendlyError in an 8-span error cell", async () => {
    await openHistory({ handlers: [http.get("/transactions/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    const td = el.tbody().querySelector("td.error");
    // Hardcoded 8; a supervisor's table has 7 columns -- see open-work.md N-P5-CHARACTERIZED.
    expect(td.getAttribute("colspan")).toBe("8");
    expect(td.textContent).not.toBe("");
    expect(el.results().hidden).toBe(false);
  });
});

describe("renderHistory rows", () => {
  it("formats the six columns; type badge label; WO in the detail column; void aria-label", async () => {
    await openHistory({ rows: [historyRow({ item_name: "Bulb", item_barcode: "B1", transaction_type: "dispense", quantity: "2", work_order_number: "7001", user_name: "Pat" })] });
    const c = cells(0);
    // The timestamp is `toLocaleString()` -- locale-dependent, so only non-empty is pinned.
    expect(c[0]).not.toBe("");
    expect(c[1]).toBe("Bulb (B1)");
    expect(rowEls()[0].querySelector(".type-badge").className).toBe("type-badge dispense");
    expect(c[2]).toBe("Taken Out");
    expect(c[3]).toBe("2");
    expect(c[4]).toBe("7001");
    expect(c[5]).toBe("Pat");
    expect(voidBtn(0).getAttribute("aria-label")).toBe("Void Taken Out of 2 for Bulb");
    expect(rowEls()[0].querySelector("td[data-primary]").textContent).toBe("Bulb (B1)");
  });

  it.each([
    ["stock", "Added"], ["adjust", "Correction"], ["mystery", "mystery"],
  ])("type %s labels %s", async (type, label) => {
    await openHistory({ rows: [historyRow({ transaction_type: type })] });
    expect(cells(0)[2]).toBe(label);
  });

  it("adjust rows show the reason, falling back to the WO number, then a dash", async () => {
    await openHistory({ rows: [
      historyRow({ transaction_type: "adjust", reason: "Recount", work_order_number: "1" }),
      historyRow({ transaction_type: "adjust", reason: null, work_order_number: "2" }),
      historyRow({ transaction_type: "adjust", reason: null, work_order_number: null }),
      historyRow({ transaction_type: "dispense", reason: "ignored", work_order_number: null }),
    ] });
    expect([cells(0)[4], cells(1)[4], cells(2)[4], cells(3)[4]]).toEqual(["Recount", "2", "—", "—"]);
  });

  it("a null user_name renders 'Name unavailable'; names are escaped", async () => {
    await openHistory({ rows: [historyRow({ user_name: null }), historyRow({ item_name: "<i>x</i>" })] });
    expect(cells(0)[5]).toBe("Name unavailable");
    expect(rowEls()[1].querySelector("i")).toBeNull();
  });
});

describe("empty state copy", () => {
  it.each([
    [{}, "No history found for those filters."],
    [{ workOrder: "7001" }, 'No history matches WO "7001".'],
    [{ dateFrom: "2026-01-01" }, "No history matches on/after 2026-01-01."],
    [{ dateTo: "2026-01-31" }, "No history matches on/before 2026-01-31."],
    [{ dateFrom: "2026-01-01", dateTo: "2026-01-31" }, "No history matches 2026-01-01 to 2026-01-31."],
    [{ workOrder: "7001", dateFrom: "2026-01-01" }, 'No history matches WO "7001" and on/after 2026-01-01.'],
    [{ tab: "item", itemId: "i1", itemLabel: "Bulb (B1)" }, "No history matches item Bulb (B1)."],
  ])("%j → %s", async (patch, copy) => {
    const { mod } = await mountHistory({ rows: [] });
    const state = await historyState();
    state.updateHistoryState(patch);
    await mod.loadHistory();
    expect(el.tbody().querySelector("td").textContent).toBe(copy);
    expect(el.tbody().querySelector("td").getAttribute("colspan")).toBe("7");
  });

  it("names the selected user from the option label", async () => {
    const { mod } = await mountHistory({ rows: [] });
    seedUsers([{ id: "u1", label: "Pat Example" }]);
    el.userSelect().value = "u1";
    const state = await historyState();
    state.updateHistoryState({ tab: "user", userId: "u1" });
    await mod.loadHistory();
    expect(el.tbody().querySelector("td").textContent).toBe("No history matches user Pat Example.");
  });
});

describe("pagination", () => {
  it("page info and button state follow total / page size", async () => {
    await openHistory({ rows: [historyRow()], total: 25 });
    expect(el.pageInfo().textContent).toBe("Page 1 of 3");
    expect(el.prev().disabled).toBe(true);
    expect(el.next().disabled).toBe(false);
    await userEvent.setup().click(el.next());
    await vi.waitFor(() => expect(el.pageInfo().textContent).toBe("Page 2 of 3"));
    expect(lastQuery().page).toBe("2");
    await userEvent.setup().click(el.next());
    await vi.waitFor(() => expect(el.pageInfo().textContent).toBe("Page 3 of 3"));
    expect(el.next().disabled).toBe(true);
    clearRequests();
    await userEvent.setup().click(el.next());   // disabled: nothing
    expect(requests()).toHaveLength(0);
    await userEvent.setup().click(el.prev());
    await vi.waitFor(() => expect(lastQuery().page).toBe("2"));
  });

  it("zero rows still reads Page 1 of 1", async () => {
    await openHistory({ rows: [], total: 0 });
    expect(el.pageInfo().textContent).toBe("Page 1 of 1");
  });
});

describe("sub-tabs", () => {
  it("setHistoryTab('all') on a fresh mount is a no-op (already active)", async () => {
    const { mod } = await mountHistory();
    mod.setHistoryTab("all");
    expect(requests()).toHaveLength(0);
  });

  it("switching to By Item warms the item cache, resets page to 1, and hides results until a pick", async () => {
    const { mod } = await openHistory({ rows: [historyRow()], total: 25, items: [itemFactory()] });
    await userEvent.setup().click(el.next());
    await vi.waitFor(() => expect(lastQuery().page).toBe("2"));
    clearRequests();
    await userEvent.setup().click(el.tab("item"));
    expect(el.page().dataset.activeFeature).toBe("item");
    await vi.waitFor(() => expect(requestFor("/items/", "GET")).not.toBeNull());
    expect(requestFor("/transactions/")).toBeNull();
    expect(el.results().hidden).toBe(true);
    const state = await historyState();
    expect(state.getHistoryState()).toMatchObject({ tab: "item", page: 1 });
    expect(mod).toBeTruthy();
  });

  it("the overlay filters survive a tab switch", async () => {
    await openHistory({ rows: [] });
    const state = await historyState();
    state.updateHistoryState({ workOrder: "7001", dateFrom: "2026-01-01" });
    await userEvent.setup().click(el.tab("user"));
    await userEvent.setup().click(el.tab("all"));
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ work_order_number: "7001", date_from: "2026-01-01" }));
  });
});

describe("By Item search-and-pick", () => {
  const items = () => [
    itemFactory({ name: "Bulb A19", barcode: "111", location: "A1" }),
    itemFactory({ name: "Fuse", barcode: "bulb-2", location: "" }),
  ];

  it("first keystroke loads /items/ once; results render name + meta; no match shows the hint", async () => {
    await openHistory({ rows: [], items: items() });
    await userEvent.setup().click(el.tab("item"));
    await vi.waitFor(() => expect(requestFor("/items/")).not.toBeNull());
    clearRequests();
    const user = userEvent.setup();
    await user.type(el.itemSearch(), "bulb");
    await vi.waitFor(() => expect(el.itemResults().querySelectorAll(".manual-item-card")).toHaveLength(2));
    expect(requestFor("/items/")).toBeNull(); // cached
    expect(el.itemResults().querySelector(".manual-item-meta").textContent).toBe("Barcode: 111Location: A1");
    await user.clear(el.itemSearch()); await user.type(el.itemSearch(), "zzz");
    await vi.waitFor(() => expect(el.itemResults().querySelector("p.hint").textContent).toBe("No matching items."));
    await user.clear(el.itemSearch());
    await vi.waitFor(() => expect(el.itemResults().hidden).toBe(true));
  });

  it("picking sets the filter, the box text, the message, and loads page 1 with item_id", async () => {
    const [bulb] = items();
    await openHistory({ rows: [historyRow()], items: [bulb] });
    await userEvent.setup().click(el.tab("item"));
    await userEvent.setup().type(el.itemSearch(), "bulb");
    await vi.waitFor(() => expect(el.itemResults().querySelector(".manual-item-card")).not.toBeNull());
    await userEvent.setup().click(el.itemResults().querySelector(".manual-item-card"));
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ item_id: bulb.id, page: "1" }));
    expect(el.itemSearch().value).toBe("Bulb A19");
    expect(el.itemResults().hidden).toBe(true);
    expect(el.itemMessage().textContent).toBe('Showing transactions for "Bulb A19".');
    expect(el.itemMessage().className).toBe("success");
    const state = await historyState();
    expect(state.getHistoryState().itemLabel).toBe("Bulb A19 (111)");
  });

  it("editing the text after a pick searches again but keeps the active filter", async () => {
    const [bulb, fuse] = items();
    await openHistory({ rows: [historyRow()], items: [bulb, fuse] });
    await userEvent.setup().click(el.tab("item"));
    await userEvent.setup().type(el.itemSearch(), "bulb");
    await vi.waitFor(() => expect(el.itemResults().querySelector(".manual-item-card")).not.toBeNull());
    await userEvent.setup().click(el.itemResults().querySelector(".manual-item-card"));
    await vi.waitFor(() => expect(lastQuery().item_id).toBe(bulb.id));
    clearRequests();
    await userEvent.setup().type(el.itemSearch(), "x");
    await vi.waitFor(() => expect(el.itemResults().hidden).toBe(false));
    expect(requestFor("/transactions/")).toBeNull();
    const state = await historyState();
    expect(state.getHistoryState().itemId).toBe(bulb.id);
  });
});

describe("By User", () => {
  it("changing the select loads page 1 with user_id; blank clears it and hides results", async () => {
    await openHistory({ rows: [historyRow()] });
    seedUsers([{ id: "u1", label: "Pat" }]);
    await userEvent.setup().click(el.tab("user"));
    expect(el.results().hidden).toBe(true);
    await userEvent.setup().selectOptions(el.userSelect(), "u1");
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ user_id: "u1", page: "1" }));
    await vi.waitFor(() => expect(el.results().hidden).toBe(false));
    el.userSelect().querySelector('option[value=""]').disabled = false;   // the placeholder is disabled in markup
    await userEvent.setup().selectOptions(el.userSelect(), "");
    await vi.waitFor(() => expect(el.results().hidden).toBe(true));
  });
});

describe("work-order overlay filter", () => {
  beforeEach(() => vi.useFakeTimers());

  it("debounces 250 ms, trims, sends work_order_number, resets page", async () => {
    await openHistory({ rows: [historyRow()], total: 25, role: "technician" }); // no restore lookup for technician
    clearRequests();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(el.woFilter(), " 7001 ");
    await vi.advanceTimersByTimeAsync(249);
    expect(requestFor("/transactions/")).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ work_order_number: "7001", page: "1" }));
    expect(requestFor("/work-orders/lookup")).toBeNull();
  });

  it("Clear cancels a pending timer, empties the box, and reloads with no filter immediately", async () => {
    await openHistory({ rows: [], role: "technician" });
    clearRequests();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(el.woFilter(), "70");
    await user.click(el.woClear());
    expect(el.woFilter().value).toBe("");
    await vi.waitFor(() => expect(lastQuery()).toEqual({ page: "1", page_size: "10" }));
    await vi.advanceTimersByTimeAsync(300);
    expect(requests().filter((r) => r.url.includes("work_order_number"))).toHaveLength(0);
  });
});

describe("date-range overlay filter", () => {
  it("change on either input reloads with date_from / date_to; Clear drops both", async () => {
    await openHistory({ rows: [] });
    clearRequests();
    const user = userEvent.setup();
    // A date input commits on `change`; fireEvent stands in for the picker.
    fireEvent.change(el.dateFrom(), { target: { value: "2026-01-01" } });
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ date_from: "2026-01-01" }));
    expect(lastQuery().date_to).toBeUndefined();
    fireEvent.change(el.dateTo(), { target: { value: "2026-01-31" } });
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ date_from: "2026-01-01", date_to: "2026-01-31" }));
    await user.click(el.dateClear());
    await vi.waitFor(() => expect(lastQuery()).toEqual({ page: "1", page_size: "10" }));
    expect(el.dateFrom().value).toBe("");
  });
});

describe("Charge column gating", () => {
  it.each([["supervisor", false], ["techfm_oa", true], ["admin", true], ["owner", true]])(
    "%s sees Charge: %s", async (role, sees) => {
      await openHistory({ role, rows: [historyRow({ item_price: sees ? "2.50" : null })] });
      expect(el.chargeHeader().hidden).toBe(!sees);
      expect(chargeCell(0) === null).toBe(!sees);
      expect(el.pricingBtn().hidden).toBe(!sees);
      expect(rowEls()[0].querySelectorAll("td")).toHaveLength(sees ? 8 : 7);
    });

  it("skeleton column count matches the role", async () => {
    const { mod } = await mountHistory({ role: "admin", handlers: [http.get("/transactions/", () => new Promise(() => {}))] });
    mod.loadHistory();
    expect(el.tbody().querySelector("tr.skel-row").querySelectorAll("td")).toHaveLength(8);
  });
});

describe("Charge cell", () => {
  it("base and +15%; no flag when billable equals quantity; Edit button on dispense/stock", async () => {
    await openHistory({ role: "admin", rows: [historyRow({ item_price: "2.50", quantity: "2", billable_quantity: null })] });
    const c = chargeCell(0);
    expect(c.querySelector(".charge-base").textContent).toBe("$5.00");
    expect(c.querySelector(".charge-marked").textContent).toBe("+15%: $5.75");
    expect(c.querySelector(".charge-flag")).toBeNull();
    expect(c.querySelector(".edit-charge-btn")).not.toBeNull();
    expect(c.dataset.quantity).toBe("2");
    expect(c.dataset.billable).toBe("2");
  });

  it("an override shows 'Billing N of M'; zero shows 'Not charged'", async () => {
    await openHistory({ role: "admin", rows: [
      historyRow({ item_price: "2.50", quantity: "4", billable_quantity: "1" }),
      historyRow({ item_price: "2.50", quantity: "4", billable_quantity: "0" }),
    ] });
    expect(chargeCell(0).querySelector(".charge-flag").textContent).toBe("Billing 1 of 4");
    expect(chargeCell(0).querySelector(".charge-base").textContent).toBe("$2.50");
    expect(chargeCell(1).querySelector(".charge-flag").className).toBe("charge-flag not-charged");
    expect(chargeCell(1).querySelector(".charge-base").textContent).toBe("$0.00");
  });

  it("no price renders a dash; an adjust row is not editable", async () => {
    await openHistory({ role: "admin", rows: [
      historyRow({ item_price: null }),
      historyRow({ item_price: "1.00", transaction_type: "adjust" }),
    ] });
    expect(chargeCell(0).textContent.trim()).toBe("—");
    expect(chargeCell(1).querySelector(".edit-charge-btn")).toBeNull();
    expect(chargeCell(1).querySelector(".charge-base").textContent).toBe("$2.00");
  });

  it("pricing button is disabled with no rows", async () => {
    await openHistory({ role: "admin", rows: [] });
    expect(el.pricingBtn().disabled).toBe(true);
  });
});

describe("void", () => {
  it("No: nothing sent", async () => {
    await openHistory({ rows: [historyRow()] });
    clearRequests();
    const clicking = userEvent.setup().click(voidBtn(0));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Void this transaction? This undoes its effect on the on-hand count and removes it from history."));
    await answerConfirm(false);
    await clicking;
    expect(requests()).toHaveLength(0);
    expect(voidBtn(0).disabled).toBe(false);
  });

  it("Yes: DELETE then reload on the same page", async () => {
    const row = historyRow();
    await openHistory({ rows: [row, historyRow()], handlers: [http.delete("/transactions/:id", () => new HttpResponse(null, { status: 204 }))] });
    clearRequests();
    const clicking = userEvent.setup().click(voidBtn(0));
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(requestFor(`/transactions/${row.id}`, "DELETE")).not.toBeNull());
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ page: "1" }));
  });

  it("voiding the last row on page 2 steps back to page 1", async () => {
    await openHistory({ rows: [historyRow()], total: 11, handlers: [http.delete("/transactions/:id", () => new HttpResponse(null, { status: 204 }))] });
    await userEvent.setup().click(el.next());
    await vi.waitFor(() => expect(lastQuery().page).toBe("2"));
    clearRequests();
    const clicking = userEvent.setup().click(voidBtn(0));
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(lastQuery().page).toBe("1"));
  });

  it("a failing void re-enables the button and reports friendlyError", async () => {
    await openHistory({ rows: [historyRow()], handlers: [http.delete("/transactions/:id", () => HttpResponse.json({ detail: "no" }, { status: 403 }))] });
    const clicking = userEvent.setup().click(voidBtn(0));
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(el.resultsMessage().className).toBe("error"));
    expect(voidBtn(0).disabled).toBe(false);
    expect(rowEls()).toHaveLength(1);
  });
});

describe("Edit charge", () => {
  async function editor(overrides = {}) {
    await openHistory({ role: "admin", rows: [historyRow({ id: "t1", item_price: "2.50", quantity: "4", billable_quantity: null, ...overrides })],
      handlers: [http.patch("/transactions/:id/billing", () => HttpResponse.json({}))] });
    clearRequests();
    await userEvent.setup().click(chargeCell(0).querySelector(".edit-charge-btn"));
    return chargeCell(0);
  }

  it("opens the editor prefilled with billable of quantity, focused", async () => {
    const cell = await editor();
    const input = cell.querySelector(".charge-input");
    expect(input.value).toBe("4");
    expect(input.max).toBe("4");
    expect(document.activeElement).toBe(input);
    expect(cell.textContent).toContain("of 4");
  });

  it("Save with a valid partial count PATCHes billable_quantity and reloads", async () => {
    const cell = await editor();
    const user = userEvent.setup();
    await user.clear(cell.querySelector(".charge-input")); await user.type(cell.querySelector(".charge-input"), "3");
    await user.click(cell.querySelector(".charge-save"));
    await vi.waitFor(() => expect(requestFor("/transactions/t1/billing", "PATCH").body).toEqual({ billable_quantity: 3 }));
    await vi.waitFor(() => expect(requestFor("/transactions/?", "GET")).not.toBeNull());
  });

  it.each([["", null], ["4", null]])("value %j sends null (charge everything)", async (typed, expected) => {
    const cell = await editor();
    const user = userEvent.setup();
    await user.clear(cell.querySelector(".charge-input"));
    if (typed) await user.type(cell.querySelector(".charge-input"), typed);
    await user.click(cell.querySelector(".charge-save"));
    await vi.waitFor(() => expect(requestFor("/billing", "PATCH").body).toEqual({ billable_quantity: expected }));
  });

  it("Don't charge sends 0", async () => {
    const cell = await editor();
    await userEvent.setup().click(cell.querySelector(".charge-zero"));
    await vi.waitFor(() => expect(requestFor("/billing", "PATCH").body).toEqual({ billable_quantity: 0 }));
  });

  it("out-of-range shows the range message and sends nothing", async () => {
    const cell = await editor();
    const user = userEvent.setup();
    await user.clear(cell.querySelector(".charge-input")); await user.type(cell.querySelector(".charge-input"), "9");
    await user.click(cell.querySelector(".charge-save"));
    // setMessage replaces className wholesale, so `.charge-editor-msg` no longer
    // matches once a message is shown -- see open-work.md N-P5-CHARACTERIZED.
    const msg = cell.querySelector("p[aria-live]");
    expect(msg.textContent).toBe("Enter a number between 0 and 4.");
    expect(msg.className).toBe("error");
    expect(cell.querySelector(".charge-editor-msg")).toBeNull();
    expect(requestFor("/billing")).toBeNull();
  });

  it("Cancel restores the display cell without a request", async () => {
    const cell = await editor();
    await userEvent.setup().click(cell.querySelector(".charge-cancel"));
    expect(cell.querySelector(".charge-editor")).toBeNull();
    expect(cell.querySelector(".edit-charge-btn")).not.toBeNull();
    expect(requests()).toHaveLength(0);
  });

  it("a failing save re-enables the buttons and shows friendlyError in the editor", async () => {
    await openHistory({ role: "admin", rows: [historyRow({ id: "t1", item_price: "2.50", quantity: "4" })],
      handlers: [http.patch("/transactions/:id/billing", () => HttpResponse.json({ detail: "no" }, { status: 403 }))] });
    await userEvent.setup().click(chargeCell(0).querySelector(".edit-charge-btn"));
    const cell = chargeCell(0);
    await userEvent.setup().click(cell.querySelector(".charge-zero"));
    await vi.waitFor(() => expect(cell.querySelector("p[aria-live]").className).toBe("error"));
    expect(cell.querySelector(".charge-save").disabled).toBe(false);
    expect(cell.querySelector(".charge-editor")).not.toBeNull();
  });
});

describe("offerRestoreIfArchived", () => {
  beforeEach(() => vi.useFakeTimers());
  const lookup = (info) => http.get("/work-orders/lookup", () => HttpResponse.json(info));
  async function typeFilter(text) {
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).type(el.woFilter(), text);
    await vi.advanceTimersByTimeAsync(250);
  }

  it("supervisor: archived -> confirm copy -> Yes posts restore and reports", async () => {
    await openHistory({ role: "supervisor", rows: [], handlers: [
      lookup({ found: true, archived: true, id: "w1", number: "7001" }),
      http.post("/work-orders/:id/restore", () => HttpResponse.json({})),
    ] });
    await typeFilter("7001");
    await vi.waitFor(() => expect(confirmTitle()).toBe(
      "Work order 7001 is archived, so it no longer shows on the Work Orders page. Its transactions below are unaffected. Restore the work order?"));
    // History was requested BEFORE the prompt.
    expect(lastQuery().work_order_number).toBe("7001");
    await answerConfirm(true);
    await vi.waitFor(() => expect(requestFor("/work-orders/w1/restore", "POST")).not.toBeNull());
    await vi.waitFor(() => expect(el.woMessage().textContent).toBe("Work order 7001 restored."));
    expect(el.woMessage().className).toBe("success");
  });

  it("declining is remembered: the same number does not re-prompt this session", async () => {
    await openHistory({ role: "supervisor", rows: [], handlers: [lookup({ found: true, archived: true, id: "w1", number: "7001" })] });
    await typeFilter("7001");
    await answerConfirm(false);
    clearRequests();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(el.woClear());
    await typeFilter("7001");
    await vi.waitFor(() => expect(lastQuery().work_order_number).toBe("7001"));
    expect(requestFor("/work-orders/lookup")).toBeNull();
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("a restore failure reports friendlyError and the number is NOT asked again", async () => {
    await openHistory({ role: "supervisor", rows: [], handlers: [
      lookup({ found: true, archived: true, id: "w1", number: "7001" }),
      http.post("/work-orders/:id/restore", () => HttpResponse.json({ detail: "no" }, { status: 403 })),
    ] });
    await typeFilter("7001");
    await answerConfirm(true);
    await vi.waitFor(() => expect(el.woMessage().className).toBe("error"));
    // woRestoreAsked keeps the key on failure (only deleted on success) --
    // so a retry of the same number is NOT re-offered. Characterization; the
    // comment above the Set says "declined", the code treats failure the same.
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(el.woClear());
    clearRequests();
    await typeFilter("7001");
    await vi.waitFor(() => expect(lastQuery().work_order_number).toBe("7001"));
    expect(requestFor("/work-orders/lookup")).toBeNull();
  });

  it.each([
    ["not found", { found: false }],
    ["live", { found: true, archived: false, id: "w1", number: "7001" }],
  ])("%s: no prompt", async (_label, info) => {
    await openHistory({ role: "supervisor", rows: [], handlers: [lookup(info)] });
    await typeFilter("7001");
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("a failing lookup is silent", async () => {
    await openHistory({ role: "supervisor", rows: [], handlers: [http.get("/work-orders/lookup", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await typeFilter("7001");
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    expect(el.woMessage().textContent).toBe("");
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("an empty filter never looks up", async () => {
    await openHistory({ role: "supervisor", rows: [] });
    clearRequests();
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(el.woClear());
    await vi.advanceTimersByTimeAsync(0);
    expect(requestFor("/work-orders/lookup")).toBeNull();
  });
});

describe("pricing list", () => {
  it("walks every page at page_size 100, prices rows, right-aligns, totals, selects, and snaps scroll", async () => {
    const rows1 = Array.from({ length: 100 }, (_, i) => historyRow({ item_name: `Item ${i}`, item_price: "1.00", quantity: "1" }));
    const rows2 = [historyRow({ item_name: "Last", item_price: "2.00", quantity: "3" }), historyRow({ transaction_type: "adjust", item_price: null })];
    const { mod } = await mountHistory({ role: "admin" });
    answerHistoryPages([rows1, rows2]);
    await mod.loadHistory();
    clearRequests();
    el.pricingOutput().scrollTop = 40; el.pricingOutput().scrollLeft = 40;
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingMessage().textContent).toBe("Pricing ready — select all and copy."));
    const pages = requests().filter((r) => r.url.startsWith("/transactions/?")).map((r) => new URL(r.url, "http://t").searchParams.get("page"));
    expect(pages).toEqual(["1", "2"]);
    expect(requests().find((r) => r.url.startsWith("/transactions/?")).url).toContain("page_size=100");
    const lines = el.pricingOutput().value.split("\n");
    expect(lines).toHaveLength(101 + 2); // 101 priced lines, blank, Total
    expect(lines[100]).toMatch(/^3\s+Last\s+\$6\.90$/);
    expect(lines[100]).toHaveLength(41);
    expect(lines.at(-2)).toBe("");
    expect(lines.at(-1)).toMatch(/^Total\s+\$121\.90$/); // 100 × 1.15 + 6.90
    expect(el.pricingOutput().hidden).toBe(false);
    expect(document.activeElement).toBe(el.pricingOutput());
    expect(el.pricingOutput().scrollTop).toBe(0);
    expect(el.pricingOutput().scrollLeft).toBe(0);
    expect(el.pricingBtn().disabled).toBe(false);
  });

  it("a row with no work_order_id resolves the number and fetches the work order, then drops the line anyway", async () => {
    const wo = workOrderDetail({ number: "7001", items: [workOrderItem({ item_id: "i1", unit_price: "4.00" })] });
    const { mod } = await mountHistory({ role: "admin", rows: [
      historyRow({ item_id: "i1", item_name: "Bulb", item_price: null, quantity: "2", work_order_number: "7001", work_order_id: null }),
    ], handlers: [
      http.get("/work-orders/", ({ request }) =>
        HttpResponse.json(new URL(request.url).searchParams.get("q") === "7001" ? [workOrderCard({ id: wo.id, number: "7001" })] : [])),
      http.get("/work-orders/:id", () => HttpResponse.json(wo)),
    ] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingMessage().textContent).toBe("No priced rows for these filters."));
    // fetchWorkOrderPrices resolves the NUMBER to an id and stores the prices
    // under that id, but markedCharge only consults the map when the ROW
    // carries work_order_id -- so the round trips happen and the line is
    // still unpriced. Characterization -- see open-work.md N-P5-CHARACTERIZED.
    expect(requestFor("/work-orders/?q=7001")).not.toBeNull();
    expect(requestFor(`/work-orders/${wo.id}`, "GET")).not.toBeNull();
    expect(el.pricingOutput().hidden).toBe(true);
  });

  it("a row carrying work_order_id skips the number lookup and is priced from the work order's line", async () => {
    const wo = workOrderDetail({ number: "7001", items: [workOrderItem({ item_id: "i1", unit_price: "4.00" })] });
    const { mod } = await mountHistory({ role: "admin", rows: [
      historyRow({ item_id: "i1", item_price: null, work_order_number: "7001", work_order_id: wo.id }),
    ], handlers: [http.get("/work-orders/:id", () => HttpResponse.json(wo))] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingOutput().hidden).toBe(false));
    expect(requestFor("/work-orders/?q=")).toBeNull();
    expect(el.pricingOutput().value.split("\n")[0]).toMatch(/^2\s+Bulb\s+\$9\.20$/);
  });

  it("an unloadable work order is skipped, not fatal", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { mod } = await mountHistory({ role: "admin", rows: [
      historyRow({ item_price: "1.00", quantity: "1" }),
      historyRow({ item_price: null, work_order_number: "gone", work_order_id: "w9" }),
    ], handlers: [http.get("/work-orders/:id", () => HttpResponse.json({ detail: "x" }, { status: 404 }))] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingMessage().className).toBe("success"));
    expect(el.pricingOutput().value.split("\n")).toHaveLength(3);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("nothing priceable: message, output stays hidden", async () => {
    const { mod } = await mountHistory({ role: "admin", rows: [historyRow({ item_price: null })] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingMessage().textContent).toBe("No priced rows for these filters."));
    expect(el.pricingOutput().hidden).toBe(true);
    expect(el.pricingBtn().disabled).toBe(false);
  });

  it("a failing page fetch reports the generic copy and re-enables the button", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const { mod } = await mountHistory({ role: "admin", rows: [historyRow()] });
    await mod.loadHistory();
    server.use(http.get("/transactions/", () => HttpResponse.json({ detail: "x" }, { status: 500 })));
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingMessage().textContent).toBe("Could not build the pricing list — try again."));
    expect(el.pricingBtn().disabled).toBe(false);
    err.mockRestore();
  });

  it("re-rendering hides and clears a built list", async () => {
    const { mod } = await mountHistory({ role: "admin", rows: [historyRow({ item_price: "1.00" })] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingOutput().hidden).toBe(false));
    await mod.loadHistory();
    expect(el.pricingOutput().hidden).toBe(true);
    expect(el.pricingOutput().value).toBe("");
    expect(el.pricingMessage().textContent).toBe("");
  });
});
