# Frontend Test Harness — P5d (`views/transactions.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: DONE (2026-09-11). `npm test`: 1036 tests / 32 files, ~80 s, green.**
>
> Executed with two deviations, both on the user's instruction: P5a–P5c were
> still uncommitted in the working tree rather than committed on `main`, and
> every `git commit` step was skipped — P5d's work sits in the same working
> tree for the user to review and commit.

**Goal:** Characterization coverage for `backend/static/views/transactions.js` (900 lines): the work-order gate and its cards, the scan-and-go batch lifecycle, commit / undo / retry, the `sessionStorage` snapshot and resume, the manual-entry panel, and the two seams `main.js` injects.

**Architecture:** Tests only. `transactions.js` imports `nav.js` (which imports the rest of the spine) and the work-order barrel, so mounting it boots most views — but none fetch at import, and the only page loader that runs is the one a test triggers. The module is mounted through `mountView("views/transactions.js")` with P5a's media stubs installed; every request is declared per test. Scanning is **not** driven here — `commitScannedItem` is exported and the manual-entry panel calls it through the same path, so the commit contract is exercised without a camera (P5g owns the scanner). This chunk also **consolidates the fixtures**: P5b and P5c each carry a private request recorder and confirm helper; Task 1 lifts both into `helpers/requests.js` and `helpers/dialogs.js` and re-points the two earlier fixtures with no behaviour change.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5d bullets are the requirement set)
**Depends on:** P5a (`helpers/media.js`, `pageHandlers()`), P5b (`helpers/auth.js` — re-pointed here), P5c (`helpers/items.js` — re-pointed here).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Suspected defects get a comment on the assertion and a row in Findings.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), timers (`vi.useFakeTimers`), `sessionStorage`, the shell's confirm overlay, P5a media stubs.
- `onUnhandledRequest: "error"` stays on.
- `mountView()` before import — `transactions.js` captures 26 element ids at import.
- User input through `@testing-library/user-event`. With fake timers on, construct it as `userEvent.setup({ advanceTimers: vi.advanceTimersByTime })`.
- Every test that touches `setScanResetter` / `setScanAutostarter` leaves them **unset** unless the test is about them — that is the state every file other than `main.test.js` runs in.
- Commit messages end with the attribution lines the session provides.

## Entry gate — verify before Task 1

- [ ] P5a, P5b, P5c commits on `main`; `tests/frontend/helpers/{app,media,auth,items}.js` exist.
- [ ] `npm test` green to completion; record count and wall-clock.
- [ ] No other session mid-commit in this checkout.

## Requests `transactions.js` can issue

| Trigger | Request |
| --- | --- |
| Gate shown (`enterTransactionPage`, gate return, filter input) | `GET /work-orders/` or `GET /work-orders/?q=<term>`, filtered client-side to `created` / `assigned` / `in_progress` |
| Batch start / return to an active batch | `GET /items/` once per session (manual-entry cache) |
| Assigned card → Yes | `POST /work-orders/{id}/start` body `{}` |
| Created card → Yes | `showPage("work-orders")` → `loadWorkOrders` → `GET /items/`, `GET /users/`, `GET /work-orders/filter-options`, `GET /work-orders/?...` (answer with `pageHandlers()`) |
| Commit / Retry | `POST /transactions/` body `{item_id, transaction_type, quantity, work_order_id, work_order_number}` |
| Remove | `DELETE /transactions/{id}` |
| `tryResumeBatch` | `GET /work-orders/{id}` |

---

### Task 1: Shared `requests.js` + `dialogs.js`, the transactions fixture, re-point P5b/P5c

**Files:**
- Create: `tests/frontend/helpers/requests.js`, `tests/frontend/helpers/dialogs.js`, `tests/frontend/helpers/transactions.js`
- Modify: `tests/frontend/helpers/auth.js`, `tests/frontend/helpers/items.js` (delete their private recorder / confirm copies; import the shared ones; keep every export name they already have)
- Test: `tests/frontend/views/transactions.test.js` (smoke)

**Interfaces:**
- `helpers/requests.js` produces `startRecording()`, `stopRecording()`, `requests()`, `requestFor(fragment, method = null)`, `clearRequests()` — exactly the semantics `helpers/auth.js` and `helpers/items.js` already have (JSON body parsed, method upper-cased, oldest first).
- `helpers/dialogs.js` produces `confirmOverlay()`, `answerConfirm(yes = true)`, `answerConfirmQuantity({ steps = 0, type = null, yes = true })` (quantity mode: click `+`/`−` `steps` times or type a value, then Yes/No), `confirmTitle()`.
- `helpers/transactions.js` produces:
  - `mountTransactions({ role = "technician", workOrders = [], items = [], handlers = [] })` → `{ mod, currentUser }`. Registers `GET /work-orders/` (answers `workOrders`, filtered by `q` as a substring of `number`) and `GET /items/` (answers `items`), mounts, does **not** call `enterTransactionPage()`.
  - `openGate(opts)` → `mountTransactions(opts)` then `mod.enterTransactionPage()` and waits for the cards to settle.
  - `inBatch(opts)` → `openGate` with one `in_progress` work order, clicks its card, waits for the batch view; returns `{ mod, wo, items }`. `opts.items` seeds the manual-entry cache.
  - `answerTransaction(txnOrStatus, { detail })` — `POST /transactions/` override; `answerVoid(status = 204)`; `answerStart(detailOrStatus)`.
  - `pickManual(name)` — types `name` into `#txn-item-search` and clicks the first `.manual-item-card`.
  - `el` getters: `gate`, `gateInput`, `gateMessage`, `gateCards`, `gateCardsMessage`, `gateSearchCard`, `gateCardsSection`, `active`, `woLabel`, `changeWoBtn`, `type`, `direction`, `segStock`, `segDispense`, `directionFixed`, `advancedToggle`, `quickToggle`, `quantity`, `summary`, `log`, `message`, `scanSection`, `manualSection`, `search`, `results`, `page(name)`.
  - `logLines()` → `Array.from(el.log().querySelectorAll(".scango-log-line"))`; `cardEls()`; `seedBatch` / `savedBatch` / `BATCH_KEY` re-exported from `helpers/auth.js`.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/transactions.test.js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server, pageHandlers } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, answerConfirmQuantity, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  answerStart, answerTransaction, answerVoid, cardEls, el, inBatch, logLines, mountTransactions,
  openGate, pickManual, restoreTransactions, savedBatch, seedBatch,
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
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run tests/frontend/views/transactions.test.js` → FAIL, `Cannot find module '../helpers/requests.js'`.

- [ ] **Step 3: Write `helpers/requests.js`**

```js
// tests/frontend/helpers/requests.js
//
// One request recorder for every view fixture. Wraps MSW's own `fetch`
// replacement, so the recorder sees exactly the `init` api.js built and MSW
// still answers the call. Synchronous by construction (`requestFor` right
// after an await is reliable); MSW's `request:start` event would hand back a
// body only after a further await.

import { vi } from "vitest";

let recorded = [];
let originalFetch = null;

export function startRecording() {
  if (originalFetch) return;
  originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    let body = init.body ?? null;
    if (typeof body === "string") { try { body = JSON.parse(body); } catch { /* keep the string */ } }
    recorded.push({
      url: typeof input === "string" ? input : input.url,
      method: (init.method || "GET").toUpperCase(),
      body,
    });
    return originalFetch(input, init);
  });
}

export function stopRecording() {
  if (originalFetch) { globalThis.fetch = originalFetch; originalFetch = null; }
  recorded = [];
}

export const requests = () => recorded;
export const requestFor = (fragment, method = null) =>
  [...recorded].reverse().find((r) => r.url.includes(fragment) && (!method || r.method === method)) ?? null;
export const clearRequests = () => { recorded = []; };
```

- [ ] **Step 4: Write `helpers/dialogs.js`**

```js
// tests/frontend/helpers/dialogs.js
//
// The shared confirm modal (dom.js `confirmDialog`, markup in shell-tail.html).
// A gated action resolves through the REAL overlay; a test answers it here.
// Stubbing dom.js instead would skip the wiring these tests exist to pin.

import { expect, vi } from "vitest";

export const confirmOverlay = () => document.getElementById("scan-confirm-overlay");
export const confirmTitle = () => document.getElementById("scan-confirm-title").textContent;

export async function answerConfirm(yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}

// Quantity mode: `steps` > 0 clicks "+" that many times, < 0 clicks "−";
// `type` replaces the field's value outright. Then Yes (default) or No.
export async function answerConfirmQuantity({ steps = 0, type = null, yes = true } = {}) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  expect(document.getElementById("scan-confirm-qty").hidden).toBe(false);
  if (type !== null) document.getElementById("scan-confirm-qty-input").value = String(type);
  const btn = document.getElementById(steps > 0 ? "scan-confirm-qty-inc" : "scan-confirm-qty-dec");
  for (let i = 0; i < Math.abs(steps); i += 1) btn.click();
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}
```

- [ ] **Step 5: Re-point `helpers/auth.js` and `helpers/items.js`**

In each: delete the private `recorded` / `originalFetch` / `startRecording` block and the local `requests` / `requestFor` / `clearRequests` definitions; add `import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";` and `export { requests, requestFor, clearRequests };`. In `restoreAuth` / `restoreItems`, replace the two-line fetch restore with `stopRecording()`. In `helpers/items.js` delete `answerConfirm` and add `export { answerConfirm } from "./dialogs.js";`. Run `npx vitest run tests/frontend/views/auth.test.js tests/frontend/views/items.test.js` — **identical pass count to before**; if any test changes result, the lift changed behaviour: stop and fix the helper, not the test.

- [ ] **Step 6: Write `helpers/transactions.js`**

```js
// tests/frontend/helpers/transactions.js
//
// The Transaction page fixture. transactions.js pulls nav.js (and so most of
// the spine) but nothing fetches at import; the gate fetches only when
// enterTransactionPage() runs, and the batch fetches /items/ once. Both are
// answered off the arguments the test passed.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests, requestFor } from "./requests.js";
import { workOrderCard } from "./factories.js";
export { BATCH_KEY, savedBatch, seedBatch } from "./auth.js";

const byId = (id) => () => document.getElementById(id);
export const el = {
  page: (name) => document.getElementById(`${name}-page`),
  gate: byId("wo-gate"), gateInput: byId("wo-gate-input"), gateMessage: byId("wo-gate-message"),
  gateCards: byId("wo-gate-cards"), gateCardsMessage: byId("wo-gate-cards-message"),
  gateSearchCard: byId("wo-gate-search-card"), gateCardsSection: byId("wo-gate-cards-section"),
  active: byId("scango-active"), woLabel: byId("scango-wo-label"), changeWoBtn: byId("scango-change-wo-btn"),
  type: byId("scango-type"), direction: byId("scango-direction"),
  segStock: () => document.querySelector(".scango-seg-stock"), segDispense: () => document.querySelector(".scango-seg-dispense"),
  directionFixed: byId("scango-direction-fixed"), advancedToggle: byId("scango-advanced-toggle"),
  quickToggle: byId("scango-quickmode-toggle"), quantity: byId("scango-quantity"),
  summary: byId("scango-summary"), log: byId("scango-log"), message: byId("scango-message"),
  scanSection: byId("txn-scan-section"), manualSection: byId("txn-manual-section"),
  search: byId("txn-item-search"), results: byId("txn-item-search-results"),
};
export const logLines = () => Array.from(el.log().querySelectorAll(".scango-log-line"));
export const cardEls = () => Array.from(el.gateCards().querySelectorAll("button.wo-card"));

export function answerTransaction(txnOrStatus, { detail = "Insufficient stock to dispense." } = {}) {
  server.use(http.post("/transactions/", () =>
    typeof txnOrStatus === "number"
      ? HttpResponse.json({ detail }, { status: txnOrStatus })
      : HttpResponse.json(txnOrStatus, { status: 201 })));
}
export function answerVoid(status = 204) {
  server.use(http.delete("/transactions/:id", () =>
    status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json({ detail: "no" }, { status })));
}
export function answerStart(detailOrStatus) {
  server.use(http.post("/work-orders/:id/start", () =>
    typeof detailOrStatus === "number"
      ? HttpResponse.json({ detail: "already started" }, { status: detailOrStatus })
      : HttpResponse.json(detailOrStatus)));
}

export async function mountTransactions({ role = "technician", workOrders = [], items = [], handlers = [] } = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's override must precede the fixture defaults.
  server.use(
    ...handlers,
    http.get("/work-orders/", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      return HttpResponse.json(q ? workOrders.filter((w) => w.number.includes(q)) : workOrders);
    }),
    http.get("/items/", () => HttpResponse.json(items)),
  );
  stubUserMedia();
  stubPermissions("prompt");
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/transactions.js");
  clearRequests();
  return { mod, currentUser };
}

export async function openGate(opts = {}) {
  const mounted = await mountTransactions(opts);
  mounted.mod.enterTransactionPage();
  await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
  await vi.waitFor(() => expect(el.gateCardsMessage().textContent).not.toMatch(/Loading|Searching/));
  return mounted;
}

export async function inBatch({ role = "technician", items = [], wo = null, handlers = [] } = {}) {
  const card = wo ?? workOrderCard({ number: "7001", status: "in_progress" });
  const mounted = await openGate({ role, workOrders: [card], items, handlers });
  await userEvent.setup().click(cardEls()[0]);
  await vi.waitFor(() => expect(el.active().hidden).toBe(false));
  await vi.waitFor(() => expect(requestFor("/items/", "GET")).not.toBeNull());
  clearRequests();
  return { ...mounted, wo: card, items };
}

export async function pickManual(name) {
  const user = userEvent.setup();
  await user.clear(el.search());
  await user.type(el.search(), name);
  await vi.waitFor(() => expect(el.results().querySelector(".manual-item-card")).not.toBeNull());
  await user.click(el.results().querySelector(".manual-item-card"));
}

export function restoreTransactions() {
  stopRecording();
  restoreMediaStubs();
  vi.useRealTimers();
}
```

- [ ] **Step 7: Run the smoke test and the two re-pointed files** → all PASS.
- [ ] **Step 8: Commit**

```bash
git add tests/frontend/helpers/requests.js tests/frontend/helpers/dialogs.js tests/frontend/helpers/transactions.js tests/frontend/helpers/auth.js tests/frontend/helpers/items.js tests/frontend/views/transactions.test.js
git commit -m "test(p5d): shared request recorder and dialog helpers; transactions fixture"
```

---

### Task 2: The gate — `enterTransactionPage`, role gating, cards, filter debounce

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): the work-order gate, role gating, cards, filter debounce"
```

---

### Task 3: Selecting a card — three statuses, three outcomes

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
    expect(savedBatch()).toBeNull(); // nothing persisted until the first commit
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
    await openGate({ role: "supervisor", workOrders: [card], handlers: pageHandlers() });
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): card selection across created, assigned, in_progress"
```

---

### Task 4: Arming, commit, confirm stepper, quick mode, advanced mode

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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

  it("a failed post logs ✗ with friendlyError and a Retry button; tallies untouched", async () => {
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): arming, commit contract, quick and advanced modes"
```

---

### Task 5: Remove (undo) and Retry

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): remove and retry on the batch log"
```

---

### Task 6: Persistence — snapshot shape, private-browsing, `resetBatch`, `tryResumeBatch`, change work order

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
    // supervisorAdvanced and quickMode are reset: re-enter a batch and check.
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
    // unless advanced mode is on, and supervisorAdvanced is NOT persisted.
    // Characterization: assert what the field says after resume.
    expect(el.type().value).toBe("dispense");
    expect(requestFor("/items/", "GET")).not.toBeNull();
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
```

`committedLine` is defined in Task 5; it lives at file scope and is reused here.

- [ ] **Step 2: Run** → PASS. The resume `scangoType` assertion documents whatever the field reads; keep the comment, adjust the literal, file the row.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): snapshot, resetBatch, tryResumeBatch, change work order, seams"
```

---

### Task 7: The manual-entry panel and `filterRanked`

**Files:** Modify `tests/frontend/views/transactions.test.js`.

- [ ] **Step 1: Write the tests**

```js
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
```

- [ ] **Step 2: Run the file, then `npm test`**; record count and wall-clock.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/transactions.test.js
git commit -m "test(p5d): manual entry panel"
```

---

### Task 8: Findings, docs, close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: Findings.** Append to `### N-P5-CHARACTERIZED` only rows the tests confirmed. Candidates:

| Defect | Pinned by |
| --- | --- |
| `resumeBatchFor` restores `scangoType: "stock"` but `supervisorAdvanced` is not persisted, so `showScanGoState` immediately re-pins `dispense`; a resumed stock batch silently becomes a dispense batch. | `transactions.test.js` → "owning user + active WO" |
| `startBatchFor` keeps `workOrder.status` in the snapshot but `tryResumeBatch` re-fetches and ignores it; harmless, but the persisted field is dead. | same |
| Summary copy says `1 units` — no singular for units. | → "a failing void re-enables the button" |
| `changeWorkOrder` calls `refreshWoCards()` **after** `showScanGoState()` renders; with the card list previously reset, the gate flashes empty before the fetch lands. | → "with no scans: straight back to the gate" (assert the intermediate empty state if it is observable synchronously) |

- [ ] **Step 2: `docs/current-state.md`.** Transaction / scan-and-go task-area row gains `tests/frontend/views/transactions.test.js`; update the Vitest count/time bullet.
- [ ] **Step 3: Parent plan + roadmap.** Tick P5d bullets; roadmap status `P5a–P5d landed`; add under the parent plan's deviations: *P5d lifted the request recorder and confirm helpers into `helpers/requests.js` and `helpers/dialogs.js`; `helpers/auth.js` and `helpers/items.js` re-export them. P5e+ import the shared ones directly. `helpers/workOrders.js` (P2) keeps its own copy — re-pointing it is P5h's business alongside the action audit.*
- [ ] **Step 4: Verify and commit** — `npm test` green.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: record P5d transactions coverage and its findings"
```

---

## Done when

- [x] `npm test` green: 1036 tests / 32 files, ~80 s (was 978 / 31 / ~70 s). Commits skipped on the user's instruction.
- [x] Every export exercised: `setScanResetter`, `setScanAutostarter`, `resetBatch`, `tryResumeBatch`, `scanGoArmed`, `commitScannedItem`, `enterTransactionPage`.
- [x] `auth.test.js` and `items.test.js` pass with identical counts after the helper lift (89 across the two, unchanged).
- [x] No file under `backend/` touched.

## Plan corrections found while executing

| Plan said | Actual |
| --- | --- |
| `savedBatch()` is null until the first commit | `startBatchFor` persists at batch start (finding filed) |
| The created-card test passes `handlers: pageHandlers()` | That bundle's own `GET /work-orders/` would answer the gate with `[]`; `pageHandlers()` is registered after the gate paints instead |
| After a network error `#wo-gate-message` reads `""` | Nothing clears it, so a preceding 404's copy still stands; the test blanks it by hand (finding filed) |

## Deliberately not in P5d

- Camera, upload decode, continuous-mode dwell/cooldown (P5g — they call `commitScannedItem` and `scanGoArmed`, both pinned here).
- `workOrderCardClass` / `urgentFireActive` internals (P2 `render.test.js`); only that the gate card uses them.
- What `focusWorkOrder` + `loadWorkOrders` do after the created-card hand-off (P2 `solo.test.js`).
- `filterRanked`'s ranking rules (P1 `format.test.js`).
- Re-pointing `helpers/workOrders.js` to the shared recorder (P5h).
- Fixing anything above.
