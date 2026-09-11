# Frontend Test Harness — P5e (`views/history.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: NOT STARTED. Do not begin until P5a–P5d are committed on `main` and the user gives an explicit go-ahead.**

**Goal:** Characterization coverage for `backend/static/views/history.js` (754 lines): the three sub-tabs, the overlay filters and their debounce, pagination, per-role Charge column, void, the inline billing editor hand-off, the archived-work-order restore offer, and the pricing list.

**Architecture:** Tests only. `history.js` is self-contained apart from `subnav.js`, `billingEditor.js` and the foundation layer — it fetches nothing at import (`fireInitialOnShow: false`), so it mounts through `mountView("views/history.js")` with no media stubs and no page-loader bundle. State lives in `state.js`'s `historyState`, which is fresh per test because `setup.js` resets the module registry. This chunk consumes P5d's shared `helpers/requests.js` and `helpers/dialogs.js` directly and adds one factory, `historyRow()`, because `GET /transactions/` answers `TransactionHistoryItem`, a different shape from the `transaction()` factory P1 verified.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5e bullets are the requirement set)
**Depends on:** P5d (`helpers/requests.js`, `helpers/dialogs.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Suspected defects get a comment on the assertion and a row in Findings.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), timers (`vi.useFakeTimers`), the shell's confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- `mountView()` before import — `history.js` captures 24 element ids at import.
- User input through `@testing-library/user-event`; with fake timers, `userEvent.setup({ advanceTimers: vi.advanceTimersByTime })`.
- The `historyRow()` factory must pass the drift guard in `unit/api.endpoints.test.js` — add its row there in the same commit.
- Commit messages end with the attribution lines the session provides.

## Entry gate — verify before Task 1

- [ ] P5a–P5d commits on `main`; `tests/frontend/helpers/requests.js` and `helpers/dialogs.js` exist with `startRecording`, `stopRecording`, `requestFor`, `answerConfirm`, `confirmTitle`.
- [ ] `npm test` green to completion; record count and wall-clock.
- [ ] No other session mid-commit in this checkout.

## Drift from the P5 plan's P5e bullets, decided here

| Bullet | Reality | Action |
| --- | --- | --- |
| "including the pricing tab and its `scrollTop` reset" | Pricing is a **button** below the results, not a tab; the `scrollTop`/`scrollLeft` reset is on the pricing `<textarea>` after `select()`. | Task 8 asserts the output text and the two scroll properties. |
| "Role gating: cost and billing columns appear at TechFM OA and above" | One column, Charge, gated by `roleAtLeast(role, "techfm_oa")`; the pricing button shares the gate. | Task 4. |
| "`initSubNav` wiring and `openBillingEditor` hand-off, asserted at the boundary only" | `billingEditor.js` is 77 lines with no other consumer covered yet; its Save / Don't charge / Cancel are the only way to reach history's `onSave`. | Task 6 drives the real editor; its internals are pinned as a side effect and recorded so P6 does not re-cover them. |

## Requests `history.js` can issue

| Trigger | Request |
| --- | --- |
| `loadHistory()` | `GET /transactions/?page=N&page_size=10[&item_id][&user_id][&work_order_number][&date_from][&date_to]` |
| First keystroke on By Item | `GET /items/` (once per session) |
| Void → Yes | `DELETE /transactions/{id}` then reload |
| Billing editor save | `PATCH /transactions/{id}/billing` body `{billable_quantity}` then reload |
| WO filter applied (supervisor+) | `GET /work-orders/lookup?number=<n>`; on archived+Yes `POST /work-orders/{id}/restore` |
| Pricing list | `GET /transactions/?page=N&page_size=100…` per page; per referenced WO `GET /work-orders/?q=<number>` (when no `work_order_id`) then `GET /work-orders/{id}` |

---

### Task 1: `historyRow()` factory, drift row, and the history fixture

**Files:**
- Modify: `tests/frontend/helpers/factories.js` (append `historyRow`), `tests/frontend/unit/api.endpoints.test.js` (one row in the drift table)
- Create: `tests/frontend/helpers/history.js`
- Test: `tests/frontend/views/history.test.js` (smoke)

**Interfaces:**
- `historyRow(overrides)` → a `TransactionHistoryItem`: `{ id, item_id, item_barcode, item_name, user_id, user_name, transaction_type, quantity, work_order_number, work_order_id, reason, item_price, billable_quantity, created_at }`.
- `helpers/history.js` produces:
  - `mountHistory({ role = "supervisor", rows = [], total = null, items = [], handlers = [] })` → `{ mod, currentUser }`. Registers `GET /transactions/` answering `{ items: rows, total: total ?? rows.length }` and recording the parsed query on `lastQuery()`; registers `GET /items/` answering `items`. Does **not** load.
  - `openHistory(opts)` → `mountHistory` then `await mod.loadHistory()`.
  - `lastQuery()` → `URLSearchParams` of the most recent `/transactions/` request as a plain object.
  - `answerHistoryPages(pages)` — for the pricing list: `pages` is an array of row arrays; the handler answers by `page` with `total` = sum.
  - `el` getters: `page`, `results`, `tbody`, `table`, `prev`, `next`, `pageInfo`, `woFilter`, `woClear`, `woMessage`, `dateFrom`, `dateTo`, `dateClear`, `itemSearch`, `itemResults`, `itemMessage`, `userSelect`, `userMessage`, `pricingBtn`, `pricingMessage`, `pricingOutput`, `resultsMessage`, `tab(feature)`, `chargeHeader`.
  - `rowEls()`, `cells(rowIndex)` → array of `td.textContent`, `voidBtn(rowIndex)`, `chargeCell(rowIndex)`, `seedUsers([{id, label}])` — appends `<option>`s to the user select.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/history.test.js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
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

describe("mountHistory", () => {
  it("mounts with the results hidden and nothing fetched", async () => {
    const { mod } = await mountHistory();
    expect(typeof mod.loadHistory).toBe("function");
    expect(el.results().hidden).toBe(true);
    expect(el.page().dataset.activeFeature).toBe("all");
    expect(requests()).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run tests/frontend/views/history.test.js` → FAIL on the missing helper.

- [ ] **Step 3: Append `historyRow` to `helpers/factories.js`**

```js
// GET /transactions/ answers TransactionHistoryItem rows (a JOIN across
// transactions / items / users), not TransactionResponse. `item_price` and
// `billable_quantity` are present only for TechFM OA and above; the factory
// defaults them to the privileged shape and a role test nulls them.
export function historyRow(overrides = {}) {
  return {
    id: uuid(),
    item_id: uuid(),
    item_barcode: "B1",
    item_name: "Bulb",
    user_id: uuid(),
    user_name: "Test User",
    transaction_type: "dispense",
    quantity: "2",
    work_order_number: "7001",
    work_order_id: null,
    reason: null,
    item_price: "2.50",
    billable_quantity: null,
    created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}
```

Add `["historyRow", "backend/app/schemas/transactions.py"],` to the `it.each` table in `unit/api.endpoints.test.js` and run that file — it must pass (every field above is declared on `TransactionHistoryItem`).

- [ ] **Step 4: Write `helpers/history.js`**

```js
// tests/frontend/helpers/history.js
//
// The History page fixture. history.js fetches nothing at import; loadHistory()
// is the only entry point and every request is answered off the arguments
// the test passed. State is state.js's historyState, fresh per test.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { startRecording, stopRecording, clearRequests, requestFor } from "./requests.js";

const byId = (id) => () => document.getElementById(id);
export const el = {
  page: byId("history-page"), results: byId("history-results"), tbody: byId("history-tbody"), table: byId("history-table"),
  prev: byId("history-prev-btn"), next: byId("history-next-btn"), pageInfo: byId("history-page-info"),
  woFilter: byId("history-wo-filter"), woClear: byId("history-wo-clear-btn"), woMessage: byId("history-wo-message"),
  dateFrom: byId("history-date-from"), dateTo: byId("history-date-to"), dateClear: byId("history-date-clear-btn"),
  itemSearch: byId("history-item-search"), itemResults: byId("history-item-results"), itemMessage: byId("history-item-message"),
  userSelect: byId("history-user-select"), userMessage: byId("history-user-message"),
  pricingBtn: byId("history-pricing-btn"), pricingMessage: byId("history-pricing-message"), pricingOutput: byId("history-pricing-output"),
  resultsMessage: byId("history-results-message"),
  tab: (feature) => document.querySelector(`#history-tabs .sub-nav-btn[data-feature="${feature}"]`),
  chargeHeader: () => document.querySelector("#history-table thead .admin-col"),
};
export const rowEls = () => Array.from(el.tbody().querySelectorAll("tr"));
export const cells = (i = 0) => Array.from(rowEls()[i].querySelectorAll("td")).map((td) => td.textContent.trim());
export const voidBtn = (i = 0) => rowEls()[i].querySelector(".void-txn-btn");
export const chargeCell = (i = 0) => rowEls()[i].querySelector(".charge-cell");

export function seedUsers(users) {
  for (const { id, label } of users) {
    const opt = document.createElement("option");
    opt.value = id; opt.textContent = label;
    el.userSelect().appendChild(opt);
  }
}

export function lastQuery() {
  const r = requestFor("/transactions/?", "GET");
  return r ? Object.fromEntries(new URL(r.url, "http://t").searchParams) : null;
}

// Page-keyed answers for the pricing list's copy-all loop.
export function answerHistoryPages(pages) {
  const total = pages.reduce((n, p) => n + p.length, 0);
  server.use(http.get("/transactions/", ({ request }) => {
    const page = Number(new URL(request.url).searchParams.get("page"));
    return HttpResponse.json({ items: pages[page - 1] ?? [], total });
  }));
}

export async function mountHistory({ role = "supervisor", rows = [], total = null, items = [], handlers = [] } = {}) {
  server.use(
    ...handlers,
    http.get("/transactions/", () => HttpResponse.json({ items: rows, total: total ?? rows.length })),
    http.get("/items/", () => HttpResponse.json(items)),
  );
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/history.js");
  clearRequests();
  return { mod, currentUser };
}

export async function openHistory(opts = {}) {
  const mounted = await mountHistory(opts);
  await mounted.mod.loadHistory();
  return mounted;
}

export function restoreHistory() {
  stopRecording();
  vi.useRealTimers();
}
```

- [ ] **Step 5: Run the smoke test and the drift test** → both PASS.
- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/factories.js tests/frontend/unit/api.endpoints.test.js tests/frontend/helpers/history.js tests/frontend/views/history.test.js
git commit -m "test(p5e): historyRow factory and the history fixture"
```

---

### Task 2: `loadHistory` / `renderHistory` — request, rows, empty state, pagination, error

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
    release(); await first;
    expect(el.tbody().querySelector("tr.skel-row")).toBeNull();
    const second = mod.loadHistory();          // results already visible: no flicker
    expect(el.tbody().querySelector("tr.skel-row")).toBeNull();
    release(); await second;
  });

  it("item tab with no item, and user tab with no user, hide the results and fetch nothing", async () => {
    const { mod } = await mountHistory();
    const state = await import("../../backend/static/state.js");
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
    expect(td.getAttribute("colspan")).toBe("8"); // hardcoded; 7 columns for supervisor -- see Findings
    expect(el.results().hidden).toBe(false);
  });
});

describe("renderHistory rows", () => {
  it("formats the six columns; type badge label; WO in the detail column; void aria-label", async () => {
    await openHistory({ rows: [historyRow({ item_name: "Bulb", item_barcode: "B1", transaction_type: "dispense", quantity: "2", work_order_number: "7001", user_name: "Pat" })] });
    const c = cells(0);
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
    const state = await import("../../backend/static/state.js");
    state.updateHistoryState(patch);
    await mod.loadHistory();
    expect(el.tbody().querySelector("td").textContent).toBe(copy);
    expect(el.tbody().querySelector("td").getAttribute("colspan")).toBe("7");
  });

  it("names the selected user from the option label", async () => {
    const { mod } = await mountHistory({ rows: [] });
    seedUsers([{ id: "u1", label: "Pat Example" }]);
    el.userSelect().value = "u1";
    const state = await import("../../backend/static/state.js");
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): loadHistory, row render, empty-state copy, pagination"
```

---

### Task 3: Tabs, item search-and-pick, user select, WO and date filters

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
    const state = await import("../../backend/static/state.js");
    expect(state.getHistoryState()).toMatchObject({ tab: "item", page: 1 });
    expect(mod).toBeTruthy();
  });

  it("the overlay filters survive a tab switch", async () => {
    await openHistory({ rows: [] });
    const state = await import("../../backend/static/state.js");
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
    expect(el.itemResults().hidden).toBe(true);
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
    const state = await import("../../backend/static/state.js");
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
    expect(requestFor("/transactions/")).toBeNull();
    const state = await import("../../backend/static/state.js");
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
    expect(el.results().hidden).toBe(false);
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
    await user.type(el.dateFrom(), "2026-01-01");
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ date_from: "2026-01-01" }));
    expect(lastQuery().date_to).toBeUndefined();
    await user.type(el.dateTo(), "2026-01-31");
    await vi.waitFor(() => expect(lastQuery()).toMatchObject({ date_from: "2026-01-01", date_to: "2026-01-31" }));
    await user.click(el.dateClear());
    await vi.waitFor(() => expect(lastQuery()).toEqual({ page: "1", page_size: "10" }));
    expect(el.dateFrom().value).toBe("");
  });
});
```

`user.type` on a `type="date"` input fires `change` on blur in jsdom; if the first assertion times out, replace the two `type` calls with `fireEvent.change(el.dateFrom(), { target: { value: "2026-01-01" } })` from `@testing-library/dom` and note it in the test.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): sub-tabs, item pick, user select, work-order and date filters"
```

---

### Task 4: Role gating — the Charge column and its maths

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): charge column gating and maths"
```

---

### Task 5: Void

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): void both ways, page step-back, failure"
```

---

### Task 6: The inline billing editor hand-off

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
    expect(cell.querySelector(".charge-editor-msg").textContent).toBe("Enter a number between 0 and 4.");
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
    await vi.waitFor(() => expect(cell.querySelector(".charge-editor-msg").className).toBe("error"));
    expect(cell.querySelector(".charge-save").disabled).toBe(false);
    expect(cell.querySelector(".charge-editor")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): inline billing editor hand-off"
```

---

### Task 7: The archived-work-order restore offer

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("offerRestoreIfArchived", () => {
  beforeEach(() => vi.useFakeTimers());
  const lookup = (info) => http.get("/work-orders/lookup", () => HttpResponse.json(info));
  async function typeFilter(text) {
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).type(el.woFilter(), text);
    await vi.advanceTimersByTimeAsync(250);
  }

  it("supervisor: archived → confirm copy → Yes posts restore and reports", async () => {
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
    expect(el.woMessage().textContent).toBe("Work order 7001 restored.");
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

  it("a restore failure reports friendlyError and the number may be asked again", async () => {
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
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("a failing lookup is silent", async () => {
    await openHistory({ role: "supervisor", rows: [], handlers: [http.get("/work-orders/lookup", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await typeFilter("7001");
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
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
```

The technician case (no lookup at all) is already pinned in Task 3's debounce test — `PAGE_ACCESS` gates History at supervisor, so a technician never reaches this page in production; the test documents the guard, not a reachable path.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): archived work-order restore offer"
```

---

### Task 8: The pricing list

**Files:** Modify `tests/frontend/views/history.test.js`.

- [ ] **Step 1: Write the tests**

```js
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

  it("work-order rows with no item_price are priced from the work order's line", async () => {
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
    await vi.waitFor(() => expect(el.pricingOutput().hidden).toBe(false));
    expect(el.pricingOutput().value.split("\n")[0]).toMatch(/^2\s+Bulb\s+\$9\.20$/); // 4.00 × 2 × 1.15
    expect(requestFor("/work-orders/?q=7001")).not.toBeNull();
    expect(requestFor(`/work-orders/${wo.id}`, "GET")).not.toBeNull();
  });

  it("a row carrying work_order_id skips the number lookup", async () => {
    const wo = workOrderDetail({ number: "7001", items: [workOrderItem({ item_id: "i1", unit_price: "4.00" })] });
    const { mod } = await mountHistory({ role: "admin", rows: [
      historyRow({ item_id: "i1", item_price: null, work_order_number: "7001", work_order_id: wo.id }),
    ], handlers: [http.get("/work-orders/:id", () => HttpResponse.json(wo))] });
    await mod.loadHistory();
    await userEvent.setup().click(el.pricingBtn());
    await vi.waitFor(() => expect(el.pricingOutput().hidden).toBe(false));
    expect(requestFor("/work-orders/?q=")).toBeNull();
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
```

The truncation branch (`COPY_MAX_PAGES` = 100 pages) is not driven — it needs 10,000+ rows and the guard is a constant; recorded under "not in P5e".

- [ ] **Step 2: Run the file, then `npm test`**; record count and wall-clock.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/history.test.js
git commit -m "test(p5e): pricing list"
```

---

### Task 9: Findings, docs, close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: Findings.** Append to `### N-P5-CHARACTERIZED` only rows the tests confirmed. Candidates:

| Defect | Pinned by |
| --- | --- |
| The load-error row hardcodes `colspan="8"`; supervisors have 7 columns. | `history.test.js` → "a failed load renders friendlyError" |
| `woRestoreAsked` is documented as remembering a *decline*, but a failed restore also keeps the key, so the offer is never repeated after a transient error. | → "a restore failure reports friendlyError" |
| `formatRow` uses `toLocaleString()` for the timestamp — locale-dependent in the TSV/pricing paths as well as on screen. | → "formats the six columns" (assert non-empty only) |
| `renderHistory`'s comment says the Charge column is "Admin/Owner"; the gate is `techfm_oa`. Comment drift, not behaviour. | → "Charge column gating" |

- [ ] **Step 2: `docs/current-state.md`.** "History filters/export" and "Billing/charge override" rows gain `tests/frontend/views/history.test.js`; update the Vitest count/time bullet.
- [ ] **Step 3: Parent plan + roadmap.** Tick P5e bullets; roadmap status `P5a–P5e landed`; under the parent plan's deviations add: *P5e — pricing is a button, not a tab; `billingEditor.js` is driven for real here (P6 must not re-cover it); `historyRow()` factory added with a drift-guard row.*
- [ ] **Step 4: Verify and commit** — `npm test` green.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: record P5e history coverage and its findings"
```

---

## Done when

- [ ] `npm test` green at every commit; count and wall-clock in the Task 8 and Task 9 commit bodies.
- [ ] All three exports exercised (`setHistoryTab`, `loadHistory`, `renderHistory`); every listener in the file has a test that reaches it (tabs, item search + pick, user select, prev/next, WO filter + clear, date inputs + clear, void, edit charge, pricing).
- [ ] `historyRow` passes the drift guard.
- [ ] No file under `backend/` touched.

## Deliberately not in P5e

- `COPY_MAX_PAGES` truncation copy (needs 10,001 rows; the constant is the guard).
- `pricingText.js` formatting rules (P1); here only that a line is 41 wide and the price is flush right.
- `users.js` populating `#history-user-select` (P6) — options are seeded directly.
- `filterRanked` ordering (P1).
- Fixing anything above.
