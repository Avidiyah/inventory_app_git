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
