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
