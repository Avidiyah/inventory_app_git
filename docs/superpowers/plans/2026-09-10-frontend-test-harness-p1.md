# Frontend Test Harness — P1 (Foundation-Layer Coverage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cover the twelve foundation modules every view imports — `api.js` first — so that later phases build on verified contracts rather than on factories that guess.

**Architecture:** Tests only, on top of the P0 harness. `api.js` gets three layers: a contract core (what `parseResponse` / `jsonRequest` / `liveGet` guarantee), one table listing every exported wrapper with its expected method / URL / body (driven through a `fetch` spy plus MSW, with a meta-test that fails when an export has no row), and hand-written cases for the shapes a table cannot express (multipart uploads, blob downloads, query-omission rules). The remaining eleven modules get direct unit or shell-mounted component tests.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P1)
**Depends on:** P0 — landed 2026-09-10 (`7da6a59`..`77224c3`), baseline `npm test` green at 4 files / 52 tests. Every helper signature this plan assumes was checked against the merged files; they match.

## Verified before execution

Four mechanisms this plan leans on were probed against the real code on
2026-09-10 (throwaway file, run, deleted). Results are baked into the tasks
below — do not re-derive them.

| Mechanism | Result |
| --- | --- |
| `installFetchSpy` wrapping MSW's `fetch` | Works. The spy sees the exact `init` `api.js` built: `credentials: "include"`, `cache: "no-store"` on `liveGet`, `method` **undefined** on a plain GET (hence `init.method ?? "GET"`), `headers["Content-Type"]` on `jsonRequest`, and `init.headers` **undefined** for the FormData uploads. |
| `server.use(http.all("*", ...))` as a sweep catch-all | Works under msw 2.x with relative paths. |
| `mountView("dom.js")` | Works. All nine confirm-overlay ids plus the password / name / role overlays resolve, and `confirmDialog` shows and resolves rather than taking its no-modal fallback. |
| Replacing `WebSocket` | **`globalThis.WebSocket = ...` throws** — jsdom defines it read-only ("Cannot assign to read only property 'WebSocket'"). Use `vi.stubGlobal` / `vi.unstubAllGlobals`; Task 12's helper already does. |
| The reconnect ladder | Measured, with `Math.random()` pinned to 0: **500, 1000, 2000, 4000, 8000, 15000, 15000, 15000** ms. Not the 1000-doubling shape it looks like — `reconnectDelay(0)` is `ceiling / 2` where `ceiling` starts at 1000. Task 12 asserts these values. |

Also pre-checked: `api.js` exports **98** `api*` wrappers, and exactly one —
**`apiGetHubAdmin`** — is not named anywhere in `docs/endpoint-map.md`. The
route (`GET /hub/admin`, `backend/app/routers/hub.py:107`) and the caller
(`views/userHub.js:374`) both exist, so this is a documentation gap, not dead
code. Task 2's doc meta-test will fail on exactly that one name; the task says
what to do with it.

## Global Constraints

- **Tests only.** No changes to any file under `backend/static/` or `backend/app/`. If a test cannot be written without changing production code, stop and raise it — do not refactor to suit the test.
- **Suspected bugs get filed, not fixed.** Anything that looks wrong (a wrong path, a doc mismatch, a missing tip key) becomes a line in `docs/open-work.md` in Task 13. P1 records behaviour; it does not change it.
- **No `vi.mock("api.js")` and no `vi.mock` of any app module.** The real module executes; seams are `fetch` (MSW), `WebSocket` (a fake class), and timers (`vi.useFakeTimers()`).
- **`onUnhandledRequest: "error"` stays on.** Every test registers the handlers it needs.
- **DOM-touching modules mount the shell first.** `dom.js`, `tooltip.js` and `itemSave.js` capture element ids at import time; use `mountView()`, never a bare `import`.
- **Coverage stays advisory.** P1 records the numbers reached; P7 turns the threshold blocking.
- **Every new test file lives under `tests/frontend/`** — `unit/` mirrors `backend/static/*.js`, `helpers/` holds shared fixtures.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Interfaces inherited from P0

Confirm these exist before Task 1; every task below assumes them.

| Helper | Signature |
| --- | --- |
| `tests/frontend/helpers/shell.js` | `shellParts(): string[]`, `assembleShell(): string`, `mountShell(): void`, `async mountView(modulePath): Promise<Module>` (path relative to `backend/static/`) |
| `tests/frontend/helpers/handlers.js` | `server` (msw/node `SetupServerApi`), `defaultHandlers` |
| `tests/frontend/helpers/session.js` | `async setTestUser(overrides = {}) -> user` |
| `tests/frontend/helpers/factories.js` | `user(overrides = {}) -> {id, username, full_name, first_name, last_name, role}` |
| `tests/frontend/setup.js` | per-test `vi.resetModules()`, storage clear, MSW lifecycle, `vi.useRealTimers()` in `afterEach` |

Already covered by P0, do not re-test: `escapeHtml`, `formatHm`, `formatMoney`, `safeHttpUrl`, `formatUserName`, `formatError` (`unit/format.test.js`); `apiGetWorkOrder`'s success / 422 / 403 / 401 / 204 / non-JSON paths (`unit/api.test.js`).

Already covered by the **Python** suite, do not duplicate: `separatedForSearch` / `squashedForSearch` rules (`backend/tests/test_search_parity.py` runs `format.js` under node against `app/services/items.py`) and `ROLE_RANK` / `ROLE_LABELS` values (`backend/tests/test_role_mirror_parity.py`). P1 covers the JS-only logic those parity tests do not reach: ranking, filtering, and the role predicates.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `tests/frontend/helpers/fetchSpy.js` | `installFetchSpy()` / `restoreFetchSpy()` — records the exact `(url, init)` each wrapper passed, then delegates to MSW |
| `tests/frontend/helpers/endpointTable.js` | `ENDPOINTS` — one row per exported `api*` wrapper |
| `tests/frontend/unit/api.contract.test.js` | `parseResponse` / `jsonRequest` / `liveGet` guarantees |
| `tests/frontend/unit/api.endpoints.test.js` | the table sweep + the two meta-tests |
| `tests/frontend/unit/api.shapes.test.js` | query-omission, encoding, multipart, blob downloads |
| `tests/frontend/unit/format.test.js` | **extended** — `friendlyError`, note helpers, ranking, `filterRanked` |
| `tests/frontend/unit/roles.test.js` | role predicates |
| `tests/frontend/unit/pricingText.test.js` | the 41-character contract |
| `tests/frontend/unit/adminReviewReceipt.test.js` | markup, labor hours, missing prices |
| `tests/frontend/unit/state.test.js` | accessors, copy semantics, cross-test isolation |
| `tests/frontend/unit/skeleton.test.js` | width ladder, sr-only placement, class-only output |
| `tests/frontend/unit/dom.dialogs.test.js` | `setMessage`, `getNoteValueRaw`, `confirmDialog`, `messageDialog`, `confirmArchivedReuse` |
| `tests/frontend/unit/dom.prompts.test.js` | `promptPasswordReset`, `promptUserName`, `promptUserRole` |
| `tests/frontend/unit/itemSave.test.js` | the item-save order of operations |
| `tests/frontend/unit/tips.test.js` | the `data-tip` audit + `tipHtml` |
| `tests/frontend/unit/tooltip.test.js` | delegated open / pin / Esc / orphan drop |
| `tests/frontend/unit/realtime.test.js` | envelope validation, subscribe, reconnect backoff |
| `tests/frontend/helpers/fakeSocket.js` | `installFakeWebSocket()` — a scriptable `WebSocket` stand-in |
| `tests/frontend/helpers/factories.js` | **extended** — `workOrder()`, `item()`, `transaction()` |

---

### Task 1: `api.js` contract core

The three private helpers every wrapper funnels through. P0 proved them on one endpoint; this pins them as a contract.

**Files:**
- Create: `tests/frontend/unit/api.contract.test.js`

**Interfaces:**
- Consumes: `server` from `helpers/handlers.js`.
- Produces: nothing later tasks import; establishes the "import `api.js` fresh in `beforeEach`" precedent for Tasks 2 and 3.

- [ ] **Step 1: Write the failing test**

```js
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

// api.js keeps `unauthorizedHandler` in module scope; setup.js resets the
// registry per test, so the import must happen inside the test's generation.
let api;
beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
});

describe("parseResponse", () => {
  it("returns null for an empty 200 body", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse("", { status: 200 })));
    await expect(api.apiMe()).resolves.toBeNull();
  });

  it("returns the raw text for a non-JSON 200 body", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse("plain", { status: 200 })));
    await expect(api.apiMe()).resolves.toBe("plain");
  });

  it("uses statusText when an error body is absent entirely", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse(null, { status: 503, statusText: "Service Unavailable" })));
    await expect(api.apiMe()).rejects.toEqual({ status: 503, detail: "Service Unavailable" });
  });

  it("prefers `detail` over the whole body object", async () => {
    server.use(http.get("/auth/me", () =>
      HttpResponse.json({ detail: "Nope", other: 1 }, { status: 400 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 400, detail: "Nope" });
  });

  it("passes a null detail through rather than substituting statusText", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: null }, { status: 400 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 400, detail: null });
  });
});

describe("the 401 handler", () => {
  it("throws normally when no handler is registered", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "no session" }, { status: 401 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 401, detail: "no session" });
  });

  it("fires for any wrapper, not just the one that registered it", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(
      http.get("/items/", () => HttpResponse.json({ detail: "x" }, { status: 401 })),
      http.post("/transactions/", () => HttpResponse.json({ detail: "x" }, { status: 401 })),
    );
    await expect(api.apiListItems()).rejects.toMatchObject({ status: 401 });
    await expect(api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1 }))
      .rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(2);
  });

  it("does not fire on a 403", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 403 })));
    await expect(api.apiMe()).rejects.toMatchObject({ status: 403 });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("does not leak across module generations", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    vi.resetModules();
    const fresh = await import("../../../backend/static/api.js");
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(fresh.apiMe()).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("jsonRequest", () => {
  it("sends the JSON content type and the serialised body", async () => {
    let seen;
    server.use(http.post("/auth/login", async ({ request }) => {
      seen = { type: request.headers.get("Content-Type"), body: await request.json() };
      return HttpResponse.json({ ok: true });
    }));
    await api.apiLogin({ username: "owner", password: "owner1" });
    expect(seen.type).toContain("application/json");
    // `remember` defaults to false and must still be sent -- the backend
    // distinguishes a shift session from a browser-session cookie.
    expect(seen.body).toEqual({ username: "owner", password: "owner1", remember: false });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run tests/frontend/unit/api.contract.test.js`
Expected: FAIL — the file does not exist yet, then (once created) all tests must pass against unmodified `api.js`.

These are characterization tests over code that already works, so "fails first" means *fails before the file exists*. If a test fails against the real `api.js`, that is a finding: record it for Task 13, and change the test to match the code rather than the code to match the test.

- [ ] **Step 3: Run and record**

Run: `npx vitest run tests/frontend/unit/api.contract.test.js`
Expected: PASS — 10 tests.

- [ ] **Step 4: Commit**

```bash
git add tests/frontend/unit/api.contract.test.js
git commit -m "pin the api.js request and error contract"
```

---

### Task 2: The endpoint table and its meta-tests

One row per exported wrapper, swept through a `fetch` spy. The sweep asserts what was *sent*; response handling is Task 1's job.

**Files:**
- Create: `tests/frontend/helpers/fetchSpy.js`, `tests/frontend/helpers/endpointTable.js`, `tests/frontend/unit/api.endpoints.test.js`

**Interfaces:**
- Consumes: `server` from `helpers/handlers.js`.
- Produces:
  - `installFetchSpy(): Array<{url: string, init: object}>` — the live call log; `restoreFetchSpy(): void`.
  - `ENDPOINTS: Array<{fn, args, method?, url, body?, cache?, headers?}>` from `helpers/endpointTable.js`. `method` defaults to `"GET"`, `credentials` is always `"include"`.

- [ ] **Step 1: Write `tests/frontend/helpers/fetchSpy.js`**

MSW replaces `globalThis.fetch`; this wraps *that* replacement, so the spy sees exactly the `init` object `api.js` built and MSW still answers the call.

```js
import { vi } from "vitest";

let original = null;

// Records every (url, init) pair, then delegates. Install inside the test --
// after MSW's own patch is in place -- and restore in afterEach.
export function installFetchSpy() {
  const calls = [];
  original = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    calls.push({ url: typeof input === "string" ? input : input.url, init });
    return original(input, init);
  });
  return calls;
}

export function restoreFetchSpy() {
  if (original) globalThis.fetch = original;
  original = null;
}
```

- [ ] **Step 2: Write `tests/frontend/helpers/endpointTable.js`**

One row per export. `url` is the full path including the query string the wrapper is expected to build. Rows are grouped by the section comments in `api.js` so the two files can be read side by side.

```js
// The wire contract of every api.js wrapper, in api.js order.
//
// A row records what the wrapper SENDS. Response handling is covered by
// api.contract.test.js, odd shapes by api.shapes.test.js. `method` defaults
// to GET; `body` is the parsed JSON payload, absent for GET/DELETE.
//
// A new endpoint without a row here fails the meta-test in
// api.endpoints.test.js. That is the point: adding a wrapper must be a
// deliberate act, not a silent one.
export const ENDPOINTS = [
  // --- Auth ---
  { fn: "apiLogin", args: [{ username: "u", password: "p" }], method: "POST", url: "/auth/login",
    body: { username: "u", password: "p", remember: false } },
  { fn: "apiLogout", args: [], method: "POST", url: "/auth/logout" },
  { fn: "apiMe", args: [], url: "/auth/me" },

  // --- Items ---
  { fn: "apiListItems", args: [{}], url: "/items/", cache: "no-store" },
  { fn: "apiCreateItem", args: [{ barcode: "b", name: "n", location: "l", quantity: 1, price: 2, product_link: null }],
    method: "POST", url: "/items/",
    body: { barcode: "b", name: "n", location: "l", quantity: 1, price: 2, product_link: null, override_archived: false } },
  { fn: "apiDeleteItem", args: [3], method: "DELETE", url: "/items/3" },
  { fn: "apiUpdateItem", args: [3, { name: "n" }], method: "PATCH", url: "/items/3", body: { name: "n" } },
  { fn: "apiUpdateNotes", args: [3, { a: 1 }], method: "PATCH", url: "/items/3/notes", body: { notes: { a: 1 } } },
  { fn: "apiUpdateBarcodes", args: [3, ["x"]], method: "PATCH", url: "/items/3/barcodes",
    body: { barcodes: ["x"], override_archived: false } },
  { fn: "apiListLowStock", args: [], url: "/items/low-stock", cache: "no-store" },
  { fn: "apiSetLowStockThreshold", args: [3, 5], method: "PATCH", url: "/items/3/low-stock-threshold",
    body: { low_stock_threshold: 5 } },
  { fn: "apiGetItemByBarcode", args: ["abc"], url: "/items/abc" },

  // ... continue for every remaining export, in api.js order.
];
```

**Filling in the rest is the bulk of this task.** Work top to bottom through `grep -n "^export async function" backend/static/api.js` (98 exports, counted) and read each body for its path, method and payload keys. Do not guess a path from the function name — several differ (`apiVoidTransaction` is `DELETE /transactions/{id}`, `apiStartWorkOrder` is not `/work-orders/{id}/start` unless the source says so). For a wrapper whose URL depends on optional arguments, put the *no-arguments* form in the table and cover the argument permutations in Task 3.

- [ ] **Step 3: Write `tests/frontend/unit/api.endpoints.test.js`**

```js
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";
import { ENDPOINTS } from "../helpers/endpointTable.js";

let api;
let calls;

beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
  // A catch-all so the sweep needs no per-row handler. Every wrapper under
  // test is expected to reach the network exactly once.
  server.use(http.all("*", () => HttpResponse.json({})));
  calls = installFetchSpy();
});

afterEach(() => {
  restoreFetchSpy();
});

describe("every wrapper sends the request its row describes", () => {
  it.each(ENDPOINTS)("$fn", async (row) => {
    await api[row.fn](...row.args);
    expect(calls).toHaveLength(1);
    const { url, init } = calls[0];
    expect(url).toBe(row.url);
    expect(init.method ?? "GET").toBe(row.method ?? "GET");
    expect(init.credentials).toBe("include");
    if (row.cache) expect(init.cache).toBe(row.cache);
    if (row.body === undefined) {
      expect(init.body).toBeUndefined();
    } else {
      expect(init.headers?.["Content-Type"]).toBe("application/json");
      expect(JSON.parse(init.body)).toEqual(row.body);
    }
  });
});

describe("the table cannot silently fall behind api.js", () => {
  it("has a row for every exported wrapper", async () => {
    const exported = Object.keys(api).filter((name) => name.startsWith("api"));
    const covered = new Set(ENDPOINTS.map((row) => row.fn));
    const missing = exported.filter((name) => !covered.has(name));
    expect(missing, `add a row to helpers/endpointTable.js for: ${missing.join(", ")}`).toEqual([]);
  });

  it("has no row for a wrapper that no longer exists", () => {
    const stale = ENDPOINTS.map((row) => row.fn).filter((name) => typeof api[name] !== "function");
    expect(stale).toEqual([]);
  });
});

describe("docs/endpoint-map.md", () => {
  // Known gap, filed in docs/open-work.md (Task 13). `apiGetHubAdmin` is live
  // -- GET /hub/admin, called by views/userHub.js -- but the map never names
  // it. Listing it here keeps the suite green while the gap stays visible; the
  // fix is a doc edit, which P1 does not make.
  const KNOWN_UNDOCUMENTED = ["apiGetHubAdmin"];

  it("names every exported wrapper", async () => {
    const { readFileSync } = await import("node:fs");
    // Name-level, not path-level: the doc is prose in a table and a reformat
    // must not turn CI red. A wrapper missing here means an endpoint shipped
    // without a documentation row.
    const doc = readFileSync("docs/endpoint-map.md", "utf8");
    const documented = new Set(doc.match(/\bapi[A-Z]\w+/g) ?? []);
    const undocumented = Object.keys(api)
      .filter((name) => name.startsWith("api"))
      .filter((name) => !documented.has(name));
    expect(undocumented, `add these to docs/endpoint-map.md: ${undocumented.join(", ")}`)
      .toEqual(KNOWN_UNDOCUMENTED);
  });
});
```

- [ ] **Step 4: Run the sweep and triage**

Run: `npx vitest run tests/frontend/unit/api.endpoints.test.js`
Expected: PASS on every row. Each failure is one of two things — a wrong row (fix the row) or a real mismatch between the wrapper and its route (leave the row asserting *actual* behaviour, mark it with a `// FINDING:` comment, and carry it to Task 13). Never edit `api.js`.

- [ ] **Step 5: Prove the meta-test guards**

```bash
node -e "const f='tests/frontend/helpers/endpointTable.js';const s=require('fs').readFileSync(f,'utf8');require('fs').writeFileSync(f+'.bak',s);require('fs').writeFileSync(f,s.replace(/\{ fn: \"apiMe\".*\n/,''))"
npx vitest run tests/frontend/unit/api.endpoints.test.js
```
Expected: FAIL — "add a row to helpers/endpointTable.js for: apiMe".

```bash
mv tests/frontend/helpers/endpointTable.js.bak tests/frontend/helpers/endpointTable.js
npx vitest run tests/frontend/unit/api.endpoints.test.js
```
Expected: PASS.

- [ ] **Step 6: Run the one-off path audit**

Compare the table's `url` against the `docs/endpoint-map.md` row for each wrapper, by hand, top to bottom. Write every mismatch into the scratchpad as `wrapper | api.js path | doc path | which looks wrong`. This list feeds Task 13. Do not fix either side now.

- [ ] **Step 7: Commit**

```bash
git add tests/frontend/helpers/fetchSpy.js tests/frontend/helpers/endpointTable.js tests/frontend/unit/api.endpoints.test.js
git commit -m "sweep every api.js wrapper against a wire-contract table"
```

---

### Task 3: `api.js` query building, encoding, uploads and downloads

The shapes a single table row cannot express.

**Files:**
- Create: `tests/frontend/unit/api.shapes.test.js`

**Interfaces:**
- Consumes: `installFetchSpy` (Task 2), `server`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";

let api;
let calls;

beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
  server.use(http.all("*", () => HttpResponse.json({})));
  calls = installFetchSpy();
});

afterEach(() => restoreFetchSpy());

const lastUrl = () => calls.at(-1).url;

describe("query parameters are omitted, not nulled", () => {
  it("apiListItems sends no query when none is given", async () => {
    await api.apiListItems();
    expect(lastUrl()).toBe("/items/");
  });

  it("apiListItems sends an empty q when the query is the empty string", async () => {
    // Deliberate: `query = ""` is `!== null`, so the parameter IS sent. A
    // cleared search box asking for everything and a blank filter are the
    // same request today.
    await api.apiListItems({ query: "" });
    expect(lastUrl()).toBe("/items/?q=");
  });

  it("apiListWorkOrders drops every falsy filter", async () => {
    await api.apiListWorkOrders({ status: null, community: "", q: null, mine: false, limit: null });
    expect(lastUrl()).toBe("/work-orders/");
  });

  it("apiListWorkOrders sends mine as the string true and keeps limit 0", async () => {
    await api.apiListWorkOrders({ mine: true, limit: 0 });
    // `limit != null` -- a 0 limit survives where `community: ""` does not.
    expect(lastUrl()).toBe("/work-orders/?mine=true&limit=0");
  });

  it("apiListWorkOrders encodes a query containing a space and an ampersand", async () => {
    await api.apiListWorkOrders({ q: "unit 4 & 5" });
    expect(lastUrl()).toBe("/work-orders/?q=unit+4+%26+5");
  });

  it("apiListTransactions always sends page and page_size, filters only when truthy", async () => {
    await api.apiListTransactions({ page: 2, pageSize: 10, itemId: null, userId: 0, workOrder: "WO-1" });
    expect(lastUrl()).toBe("/transactions/?page=2&page_size=10&work_order_number=WO-1");
  });

  it("apiGetHubTimesheets omits the query entirely when unfiltered", async () => {
    await api.apiGetHubTimesheets();
    expect(lastUrl()).toBe("/hub/timesheets");
  });
});

describe("path segments are encoded", () => {
  it("apiGetItemByBarcode escapes a barcode containing a slash", async () => {
    await api.apiGetItemByBarcode("AB/12#3");
    expect(lastUrl()).toBe("/items/AB%2F12%233");
  });

  it("apiGetNetFacilitiesEnrichment escapes the job id", async () => {
    await api.apiGetNetFacilitiesEnrichment("a b");
    expect(lastUrl()).toBe("/integrations/netfacilities/work-orders/enrich/a%20b");
  });
});

describe("apiCreateTransaction builds its body explicitly", () => {
  it("drops unknown keys the backend schema would reject", async () => {
    await api.apiCreateTransaction({
      item_id: 1, transaction_type: "out", quantity: 2,
      user_id: 99, note: "should not travel",
    });
    expect(JSON.parse(calls.at(-1).init.body)).toEqual({
      item_id: 1, transaction_type: "out", quantity: 2,
    });
  });

  it("sends work_order_id when scanning from a card", async () => {
    await api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1, work_order_id: 7 });
    expect(JSON.parse(calls.at(-1).init.body)).toMatchObject({ work_order_id: 7 });
  });

  it("sends work_order_number for a typed number", async () => {
    await api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1, work_order_number: "WO-9" });
    expect(JSON.parse(calls.at(-1).init.body)).toMatchObject({ work_order_number: "WO-9" });
  });
});

describe("multipart uploads", () => {
  it("apiDecodeBarcode posts FormData and sets no Content-Type by hand", async () => {
    const file = new File(["x"], "photo.png", { type: "image/png" });
    await api.apiDecodeBarcode(file);
    const { init } = calls.at(-1);
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get("file")).toBe(file);
    // The browser must add the multipart boundary itself; a hand-set header
    // produces a boundary-less request the server cannot parse.
    expect(init.headers).toBeUndefined();
  });

  it("apiImportWorkOrders posts FormData to the import route", async () => {
    const file = new File(["a,b"], "wo.csv", { type: "text/csv" });
    await api.apiImportWorkOrders(file);
    expect(calls.at(-1).url).toBe("/work-orders/import");
    expect(calls.at(-1).init.body.get("file")).toBe(file);
  });
});

describe("blob downloads", () => {
  it("apiExportWorkOrders returns the blob and the server filename", async () => {
    server.use(http.get("/work-orders/export", () =>
      new HttpResponse("a,b\n1,2", {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="20260910_all.csv"' },
      })));
    const result = await api.apiExportWorkOrders("all");
    expect(await result.blob.text()).toBe("a,b\n1,2");
    expect(result.filename).toBe("20260910_all.csv");
  });

  it("apiExportWorkOrders falls back when the header is stripped", async () => {
    server.use(http.get("/work-orders/export", () => new HttpResponse("a,b")));
    const result = await api.apiExportWorkOrders("mine", { variant: "client" });
    expect(result.filename).toBe("work-orders-client-mine.csv");
  });

  it("apiExportWorkOrders carries the active filters", async () => {
    server.use(http.get("/work-orders/export", () => new HttpResponse("x")));
    await api.apiExportWorkOrders("all", { filters: { serviceType: "HVAC", q: "unit 4", community: "" } });
    expect(lastUrl()).toBe("/work-orders/export?scope=all&variant=full&service_type=HVAC&q=unit+4");
  });

  it("apiExportWorkOrders still throws {status, detail} on a failure", async () => {
    server.use(http.get("/work-orders/export", () =>
      HttpResponse.json({ detail: "Admin only" }, { status: 403 })));
    await expect(api.apiExportWorkOrders("all")).rejects.toEqual({ status: 403, detail: "Admin only" });
  });

  it("apiExportHubTimesheets defaults its filename to timesheet.csv", async () => {
    server.use(http.get("/hub/timesheets/export", () => new HttpResponse("x")));
    const result = await api.apiExportHubTimesheets({ start: "2026-09-01" });
    expect(lastUrl()).toBe("/hub/timesheets/export?start=2026-09-01");
    expect(result.filename).toBe("timesheet.csv");
  });
});
```

- [ ] **Step 2: Run and triage**

Run: `npx vitest run tests/frontend/unit/api.shapes.test.js`
Expected: PASS. A failing assertion here is either a wrong expectation (fix the test — read the source again) or a finding for Task 13. `api.js` is not edited.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/api.shapes.test.js
git commit -m "cover api.js query building, encoding, uploads and downloads"
```

---

### Task 4: `format.js` — the parts P0 and the parity suite leave uncovered

**Files:**
- Modify: `tests/frontend/unit/format.test.js`

**Interfaces:**
- Consumes: nothing. `format.js` is pure — a static top-level import is correct here.
- Produces: nothing.

- [ ] **Step 1: Append the failing tests**

```js
import {
  RANK_CONTAINS, RANK_EXACT, RANK_PREFIX, RANK_TOKENS,
  detectNoteType, filterRanked, formatNoteValue, friendlyError,
  matchesSearch, searchRank, searchTokens,
} from "../../../backend/static/format.js";

describe("friendlyError", () => {
  it.each([
    [undefined, "Could not reach the app. Check your signal and try again."],
    [{}, "Could not reach the app. Check your signal and try again."],
    [{ status: 401 }, "You were signed out. Sign in again."],
    [{ status: 403 }, "Your account can't do that. Ask a supervisor if this seems wrong."],
    [{ status: 400, detail: "Insufficient stock to dispense." },
      "Not enough stock available. Check the count before taking more out."],
  ])("maps %o to crew-facing copy", (err, expected) => {
    expect(friendlyError(err, "fallback")).toBe(expected);
  });

  it("falls back to the backend detail for anything else", () => {
    expect(friendlyError({ status: 409, detail: "Barcode in use" }, "fallback")).toBe("Barcode in use");
  });

  it("collapses a validation array through formatError", () => {
    expect(friendlyError({ status: 422, detail: [{ msg: "too short" }, { msg: "required" }] }, "fallback"))
      .toBe("too short; required");
  });

  it("uses the fallback when the detail is empty", () => {
    expect(friendlyError({ status: 500, detail: "" }, "Save failed.")).toBe("Save failed.");
  });

  it("treats status 0 as a real status rather than a network failure", () => {
    // `err.status === undefined` is the network test, so 0 falls through to
    // formatError. Recorded, not endorsed.
    expect(friendlyError({ status: 0, detail: "odd" }, "fallback")).toBe("odd");
  });
});

describe("note value helpers", () => {
  it.each([[true, "true"], [false, "false"], [0, 0], ["", ""], [null, null]])(
    "formatNoteValue(%o)", (input, expected) => expect(formatNoteValue(input)).toBe(expected));

  it.each([[true, "boolean"], [3, "number"], ["x", "string"], [null, "string"], [undefined, "string"]])(
    "detectNoteType(%o)", (input, expected) => expect(detectNoteType(input)).toBe(expected));
});

describe("searchTokens", () => {
  it.each([["", []], ['"""', []], ["---", []], ["  ", []], ["PL-C 26W", ["pl", "c", "26w"]]])(
    "tokenises %o", (query, expected) => expect(searchTokens(query)).toEqual(expected));
});

describe("matchesSearch", () => {
  it("matches an empty query against everything", () => {
    expect(matchesSearch(["anything"], "")).toBe(true);
  });

  it("matches across fields, not within one", () => {
    expect(matchesSearch(["Bulb", "Aisle 3"], "bulb aisle")).toBe(true);
  });

  it("finds a squashed form through punctuation", () => {
    expect(matchesSearch(["PL-C 26W Compact Fluorescent"], "plc")).toBe(true);
  });

  it("closes up an inch mark", () => {
    expect(matchesSearch(['2"x4" stud'], "2x4")).toBe(true);
  });

  it("skips null and undefined fields instead of throwing", () => {
    expect(matchesSearch(["Bulb", null, undefined], "bulb")).toBe(true);
  });

  it("requires every token", () => {
    expect(matchesSearch(["Bulb"], "bulb missing")).toBe(false);
  });
});

describe("searchRank", () => {
  it.each([
    [["Gel-Coat"], "gel coat", RANK_EXACT],
    [["Gel-Coat"], "gelcoat", RANK_EXACT],
    [["Gel-Coat Resin"], "gel", RANK_PREFIX],
    [["Marine Gel-Coat Resin"], "gel coat", RANK_CONTAINS],
    [["Marine Resin", "Gel-Coat"], "resin gel", RANK_TOKENS],
  ])("ranks %o against %o", (fields, query, expected) => {
    expect(searchRank(fields, query)).toBe(expected);
  });

  it("ranks a blank query as exact so an unfiltered list keeps its order", () => {
    expect(searchRank(["anything"], "")).toBe(RANK_EXACT);
  });
});

describe("filterRanked", () => {
  const rows = [
    { name: "Marine Gel-Coat Resin" },
    { name: "Gel-Coat" },
    { name: "Gel-Coat Hardener" },
    { name: "Paint Thinner" },
  ];
  const fieldsOf = (row) => [row.name];

  it("floats the exact match above prefix and contains matches", () => {
    expect(filterRanked(rows, fieldsOf, "gelcoat").map((r) => r.name))
      .toEqual(["Gel-Coat", "Gel-Coat Hardener", "Marine Gel-Coat Resin"]);
  });

  it("keeps original order within a rank tier", () => {
    const tied = [{ name: "Zeta Bulb" }, { name: "Alpha Bulb" }];
    expect(filterRanked(tied, fieldsOf, "bulb").map((r) => r.name)).toEqual(["Zeta Bulb", "Alpha Bulb"]);
  });

  it("applies the tiebreak within a tier only", () => {
    const tied = [{ name: "Zeta Bulb" }, { name: "Alpha Bulb" }];
    const byName = (a, b) => a.name.localeCompare(b.name);
    expect(filterRanked(tied, fieldsOf, "bulb", byName).map((r) => r.name)).toEqual(["Alpha Bulb", "Zeta Bulb"]);
  });

  it("returns the whole list unfiltered for a blank query", () => {
    expect(filterRanked(rows, fieldsOf, "")).toHaveLength(4);
  });

  it("returns an empty array when nothing matches", () => {
    expect(filterRanked(rows, fieldsOf, "zzz")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/unit/format.test.js`
Expected: PASS.

If the `searchRank` expectations disagree with the code, re-read `rankNormalized` and fix the *test* — this is a characterization suite.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/format.test.js
git commit -m "cover format.js error copy, note helpers and search ranking"
```

---

### Task 5: `roles.js`, `pricingText.js`, `adminReviewReceipt.js`

Three pure modules, one commit. The receipt builder is the only consumer that composes the other two, so they travel together.

**Files:**
- Create: `tests/frontend/unit/roles.test.js`, `tests/frontend/unit/pricingText.test.js`, `tests/frontend/unit/adminReviewReceipt.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write `tests/frontend/unit/roles.test.js`**

```js
import { describe, expect, it } from "vitest";
import {
  ALL_ROLES, assignableRoles, canBeWorkOrderSupervisor, canBeWorkOrderTechnician,
  canManage, roleAtLeast, roleLabel,
} from "../../../backend/static/roles.js";

// The rank/label VALUES are pinned against the Python module by
// backend/tests/test_role_mirror_parity.py. These tests cover the predicates
// that only exist on the JS side.

describe("roleLabel", () => {
  it("renders the one label capitalisation cannot produce", () => {
    expect(roleLabel("techfm_oa")).toBe("TechFM OA");
  });
  it("passes an unrecognised role through unchanged", () => {
    expect(roleLabel("contractor")).toBe("contractor");
  });
  it("never returns blank, so the Tools custody separator has something to sit beside", () => {
    expect(roleLabel(null)).toBe("Unknown role");
    expect(roleLabel("")).toBe("Unknown role");
  });
});

describe("roleAtLeast", () => {
  it.each([
    ["owner", "technician", true], ["technician", "technician", true],
    ["supervisor", "admin", false], ["techfm_oa", "supervisor", true],
  ])("roleAtLeast(%s, %s)", (role, minimum, expected) => {
    expect(roleAtLeast(role, minimum)).toBe(expected);
  });

  it("treats an unknown role as below everything", () => {
    expect(roleAtLeast("contractor", "technician")).toBe(false);
  });

  it("returns true when both sides are unknown, because both rank -1", () => {
    // Recorded, not endorsed: an unknown role satisfies an unknown minimum.
    expect(roleAtLeast("contractor", "vendor")).toBe(true);
  });
});

describe("work-order assignment eligibility", () => {
  it.each(ALL_ROLES)("canBeWorkOrderSupervisor(%s)", (role) => {
    expect(canBeWorkOrderSupervisor(role)).toBe(["admin", "techfm_oa", "supervisor"].includes(role));
  });
  it.each(ALL_ROLES)("canBeWorkOrderTechnician(%s)", (role) => {
    expect(canBeWorkOrderTechnician(role)).toBe(["supervisor", "technician"].includes(role));
  });
  it("excludes owner from both, deliberately", () => {
    expect(canBeWorkOrderSupervisor("owner")).toBe(false);
    expect(canBeWorkOrderTechnician("owner")).toBe(false);
  });
});

describe("canManage", () => {
  it("requires strictly greater rank", () => {
    expect(canManage("admin", "admin")).toBe(false);
    expect(canManage("admin", "supervisor")).toBe(true);
    expect(canManage("supervisor", "admin")).toBe(false);
  });
  it("refuses an unknown target role even for an owner", () => {
    expect(canManage("owner", "contractor")).toBe(false);
  });
});

describe("assignableRoles", () => {
  it("lists everything below the actor, most senior first", () => {
    expect(assignableRoles("admin")).toEqual(["techfm_oa", "supervisor", "technician"]);
  });
  it("is empty for a technician", () => {
    expect(assignableRoles("technician")).toEqual([]);
  });
  it("is empty for an unknown role", () => {
    expect(assignableRoles("contractor")).toEqual([]);
  });
  it("gives an owner every other role", () => {
    expect(assignableRoles("owner")).toEqual(["admin", "techfm_oa", "supervisor", "technician"]);
  });
});
```

- [ ] **Step 2: Write `tests/frontend/unit/pricingText.test.js`**

The 41-character ceiling is the whole contract; assert it as an invariant, not case by case.

```js
import { describe, expect, it } from "vitest";
import {
  PRICING_LINE_WIDTH, formatPricingQuantity, pricingAmountLine, pricingLine, sanitisePricingText,
} from "../../../backend/static/pricingText.js";

describe("formatPricingQuantity", () => {
  it.each([["3.00", "3"], [3, "3"], ["2.50", "2.5"], [0, "0"]])(
    "shortens %o", (input, expected) => expect(formatPricingQuantity(input)).toBe(expected));
});

describe("sanitisePricingText", () => {
  it("collapses tabs and newlines into a single space", () => {
    expect(sanitisePricingText("a\t\tb\r\nc")).toBe("a b c");
  });
});

describe("pricingLine", () => {
  it("pads a short name so the price is flush right", () => {
    const line = pricingLine("3", "Bulb", "$4.50");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line.startsWith("3 Bulb")).toBe(true);
    expect(line.endsWith("$4.50")).toBe(true);
  });

  it("truncates a long name with an ellipsis rather than overflowing", () => {
    const line = pricingLine("1", "X".repeat(80), "$1.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line).toContain("...");
    expect(line.endsWith("$1.00")).toBe(true);
  });

  it("never exceeds the width, whatever it is given", () => {
    const cases = [
      ["1", "Bulb", "$1.00"],
      ["12.5", "A".repeat(200), "$1,234,567.89"],
      ["1", "", ""],
      ["1", "Bulb", "$".repeat(60)],
      ["1", "Tab\there", "NO PRICE"],
    ];
    for (const [qty, name, price] of cases) {
      expect(pricingLine(qty, name, price).length).toBeLessThanOrEqual(PRICING_LINE_WIDTH);
    }
  });

  it("drops the name entirely when the price alone fills the line", () => {
    expect(pricingLine("1", "Bulb", "$".repeat(60))).toHaveLength(PRICING_LINE_WIDTH);
  });
});

describe("pricingAmountLine", () => {
  it("right-aligns the amount after the label", () => {
    const line = pricingAmountLine("Total", "$12.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line.startsWith("Total")).toBe(true);
    expect(line.endsWith("$12.00")).toBe(true);
  });

  it("truncates an over-long label", () => {
    const line = pricingAmountLine("L".repeat(80), "$1.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line).toContain("...");
  });
});
```

- [ ] **Step 3: Write `tests/frontend/unit/adminReviewReceipt.test.js`**

```js
import { describe, expect, it } from "vitest";
import { PRICING_LINE_WIDTH } from "../../../backend/static/pricingText.js";
import { billedLaborHours, buildAdminReviewReceipt } from "../../../backend/static/adminReviewReceipt.js";

describe("billedLaborHours", () => {
  it.each([[60, "1"], [90, "1.5"], [1, "0.02"], [0, "0"], [null, "0"], ["120", "2"]])(
    "converts %o minutes", (minutes, expected) => expect(billedLaborHours(minutes)).toBe(expected));
});

describe("buildAdminReviewReceipt", () => {
  const detail = {
    items: [
      { item_name: "Bulb", quantity: 2, billable_quantity: null, unit_price: "10.00" },
      { item_name: "Fuse", quantity: 5, billable_quantity: 1, unit_price: "2.00" },
    ],
    labor_billed_minutes: 90,
    labor_total: 75,
    materials_total: 22,
  };

  it("bills the billable quantity when one is set, the recorded one otherwise", () => {
    const { text } = buildAdminReviewReceipt(detail);
    const [bulb, fuse] = text.split("\n");
    expect(bulb.startsWith("2 Bulb")).toBe(true);
    expect(fuse.startsWith("1 Fuse")).toBe(true);
  });

  it("applies the 15% markup to materials but not to labor", () => {
    const { text } = buildAdminReviewReceipt(detail);
    expect(text).toContain("$23.00"); // 2 x 10.00 x 1.15
    expect(text).toContain("$2.30");  // 1 x 2.00 x 1.15
    expect(text).toContain("$75.00"); // labor, unmarked
  });

  it("totals marked materials plus labor", () => {
    // 22 x 1.15 = 25.30, + 75 = 100.30
    expect(buildAdminReviewReceipt(detail).text).toContain("$100.30");
  });

  it("labels the labor line with the billed hours in brackets", () => {
    expect(buildAdminReviewReceipt(detail).text).toContain("[1.5] Labor Hours");
  });

  it("flags a missing price without dropping the line", () => {
    const result = buildAdminReviewReceipt({
      ...detail,
      items: [{ item_name: "Mystery", quantity: 1, billable_quantity: null, unit_price: null }],
    });
    expect(result.missingPrices).toEqual(["Mystery"]);
    expect(result.text).toContain("NO PRICE");
    expect(result.text).toContain("Total (incomplete)");
  });

  it("handles an empty work order", () => {
    const result = buildAdminReviewReceipt({ items: [], labor_billed_minutes: 0, labor_total: 0, materials_total: 0 });
    expect(result.missingPrices).toEqual([]);
    expect(result.text).toContain("Total");
  });

  it("keeps every emitted line inside the receipt width", () => {
    const wide = buildAdminReviewReceipt({
      ...detail,
      items: [{ item_name: "N".repeat(120), quantity: 1000, billable_quantity: null, unit_price: "9999.99" }],
    });
    for (const line of wide.text.split("\n")) {
      expect(line.length).toBeLessThanOrEqual(PRICING_LINE_WIDTH);
    }
  });
});
```

- [ ] **Step 4: Run**

Run: `npx vitest run tests/frontend/unit/roles.test.js tests/frontend/unit/pricingText.test.js tests/frontend/unit/adminReviewReceipt.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/frontend/unit/roles.test.js tests/frontend/unit/pricingText.test.js tests/frontend/unit/adminReviewReceipt.test.js
git commit -m "cover the role mirror and the receipt text builders"
```

---

### Task 6: `state.js`

**Files:**
- Create: `tests/frontend/unit/state.test.js`

**Interfaces:**
- Consumes: `setTestUser` from `helpers/session.js`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { beforeEach, describe, expect, it, vi } from "vitest";

// Imported per test: state.js is a module singleton, and the point of half
// these tests is that setup.js's resetModules actually isolates it.
let state;
beforeEach(async () => {
  state = await import("../../../backend/static/state.js");
});

describe("cache accessors", () => {
  it.each([
    ["Items", [{ id: 1 }]],
    ["Users", [{ id: 2 }]],
    ["Tools", [{ id: 3 }]],
  ])("round-trips %s", (name, value) => {
    state[`set${name}`](value);
    expect(state[`get${name}`]()).toEqual(value);
  });

  it("starts every cache empty", () => {
    expect(state.getItems()).toEqual([]);
    expect(state.getUsers()).toEqual([]);
    expect(state.getTools()).toEqual([]);
  });

  it("returns the same array reference it was given", () => {
    // Views rely on this -- the items view mutates the cached array in place.
    const rows = [{ id: 1 }];
    state.setItems(rows);
    expect(state.getItems()).toBe(rows);
  });
});

describe("editing ids", () => {
  it("default to null and round-trip", () => {
    expect(state.getEditingItemId()).toBeNull();
    expect(state.getEditingNotesItemId()).toBeNull();
    state.setEditingItemId(4);
    state.setEditingNotesItemId(5);
    expect(state.getEditingItemId()).toBe(4);
    expect(state.getEditingNotesItemId()).toBe(5);
  });
});

describe("current user", () => {
  it("starts null and exposes the role through getRole", () => {
    expect(state.getCurrentUser()).toBeNull();
    expect(state.getRole()).toBeNull();
    state.setCurrentUser({ id: 1, role: "supervisor" });
    expect(state.getRole()).toBe("supervisor");
  });

  it("is not persisted to localStorage -- a reload must re-check /auth/me", () => {
    state.setCurrentUser({ id: 1, role: "owner" });
    expect(localStorage.length).toBe(0);
  });
});

describe("history state", () => {
  it("has the documented defaults", () => {
    expect(state.getHistoryState()).toEqual({
      tab: "all", itemId: null, itemLabel: null, userId: null, workOrder: null,
      dateFrom: null, dateTo: null, page: 1, totalPages: 1,
    });
    expect(state.HISTORY_PAGE_SIZE).toBe(10);
  });

  it("returns a copy, so a caller cannot mutate it by reference", () => {
    const snapshot = state.getHistoryState();
    snapshot.page = 99;
    expect(state.getHistoryState().page).toBe(1);
  });

  it("shallow-merges a patch and leaves the rest alone", () => {
    state.updateHistoryState({ page: 3, workOrder: "WO-1" });
    state.updateHistoryState({ page: 4 });
    expect(state.getHistoryState()).toMatchObject({ page: 4, workOrder: "WO-1", tab: "all" });
  });
});

describe("isolation", () => {
  it("does not leak into the next module generation", async () => {
    state.setItems([{ id: 1 }]);
    state.setCurrentUser({ id: 1, role: "owner" });
    state.updateHistoryState({ page: 7 });
    vi.resetModules();
    const fresh = await import("../../../backend/static/state.js");
    expect(fresh.getItems()).toEqual([]);
    expect(fresh.getCurrentUser()).toBeNull();
    expect(fresh.getHistoryState().page).toBe(1);
  });
});

describe("setTestUser", () => {
  it("primes the same module generation the test reads", async () => {
    const { setTestUser } = await import("../helpers/session.js");
    await setTestUser({ role: "admin" });
    const current = await import("../../../backend/static/state.js");
    expect(current.getRole()).toBe("admin");
  });
});
```

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/unit/state.test.js`
Expected: PASS.

The last test is the important one: if `setTestUser` primes a different copy of `state.js` than the test reads, every role-gated test in P2 and P5 would be silently vacuous. Should it fail, the bug is in the P0 helper — fix `helpers/session.js`, not `state.js`.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/state.test.js
git commit -m "cover state.js accessors and per-test isolation"
```

---

### Task 7: `skeleton.js`

**Files:**
- Create: `tests/frontend/unit/skeleton.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { describe, expect, it } from "vitest";
import { skeletonCard, skeletonList, skeletonTableRows } from "../../../backend/static/skeleton.js";

// CSP drops style attributes parsed out of markup here (see the module header
// and docs/current-state.md), so "no inline style" is a correctness assertion,
// not a style preference.
const NO_INLINE_STYLE = /style=/;

describe("skeletonTableRows", () => {
  it("emits rowCount rows of colCount cells", () => {
    const html = skeletonTableRows(3, 2);
    expect(html.match(/<tr class="skel-row">/g)).toHaveLength(2);
    expect(html.match(/<td>/g)).toHaveLength(6);
  });

  it("announces loading exactly once, in the first cell", () => {
    const html = skeletonTableRows(3, 4);
    expect(html.match(/sr-only/g)).toHaveLength(1);
    expect(html.indexOf("sr-only")).toBeLessThan(html.indexOf("</td>"));
  });

  it("snaps a caller width onto the 5% class ladder", () => {
    expect(skeletonTableRows(1, 1, { widths: ["37%"] })).toContain("skel-w-35");
  });

  it("clamps a width to the ladder's ends", () => {
    expect(skeletonTableRows(1, 1, { widths: ["5%"] })).toContain("skel-w-25");
    expect(skeletonTableRows(1, 1, { widths: ["150%"] })).toContain("skel-w-95");
  });

  it("falls back to the deterministic cycle for a non-percentage width", () => {
    expect(skeletonTableRows(1, 1, { widths: ["auto"] })).toContain("skel-w-90");
  });

  it("uses classes only -- never an inline style", () => {
    expect(skeletonTableRows(2, 2, { widths: ["40%", "60%"] })).not.toMatch(NO_INLINE_STYLE);
  });

  it("is deterministic, so a repeat render is pixel-identical", () => {
    expect(skeletonTableRows(3, 3)).toBe(skeletonTableRows(3, 3));
  });
});

describe("skeletonCard", () => {
  it("renders a header bar plus the requested body lines", () => {
    const html = skeletonCard({ lines: 2 });
    expect(html).toContain("skel-line--head");
    expect(html.match(/skel-line/g)).toHaveLength(3); // head + 2 body
  });

  it("omits the header when asked", () => {
    expect(skeletonCard({ hasHeader: false })).not.toContain("skel-line--head");
  });

  it("defaults to three body lines and one announcement", () => {
    const html = skeletonCard();
    expect(html.match(/sr-only/g)).toHaveLength(1);
    expect(html.match(/skel-line/g)).toHaveLength(4);
  });

  it("renders no lines at all when asked for zero", () => {
    expect(skeletonCard({ lines: 0, hasHeader: false })).toBe(
      '<div class="skel-card"><span class="sr-only">Loading…</span></div>');
  });
});

describe("skeletonList", () => {
  it("renders two bars per item and announces once", () => {
    const html = skeletonList(3);
    expect(html.match(/skel-list-item/g)).toHaveLength(3);
    expect(html.match(/skel-line--sub/g)).toHaveLength(3);
    expect(html.match(/sr-only/g)).toHaveLength(1);
  });

  it("uses classes only", () => {
    expect(skeletonList()).not.toMatch(NO_INLINE_STYLE);
  });
});
```

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/unit/skeleton.test.js`
Expected: PASS. Check the exact `skel-w-*` numbers against `BODY_WIDTHS` in the source before assuming a failure is a bug.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/skeleton.test.js
git commit -m "cover the skeleton builders and their CSP-safe class ladder"
```

---

### Task 8: `dom.js` — messages and the shared confirm modal

`dom.js` captures nine element ids at import time, so it must be loaded through `mountView`. That import-time capture is itself worth a test: a renamed overlay id in `shell-tail.html` silently degrades every confirm to its no-modal fallback.

**Files:**
- Create: `tests/frontend/unit/dom.dialogs.test.js`

**Interfaces:**
- Consumes: `mountShell`, `mountView` (P0), `userEvent`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const overlay = () => document.getElementById("scan-confirm-overlay");
const yes = () => document.getElementById("scan-confirm-yes");
const no = () => document.getElementById("scan-confirm-no");
const qtyInput = () => document.getElementById("scan-confirm-qty-input");

describe("the shell supplies every node dom.js captures", () => {
  // Renaming one of these in shell-tail.html turns confirmDialog into its
  // silent no-modal fallback in production. This is the drift guard.
  it.each([
    "scan-confirm-overlay", "scan-confirm-title", "scan-confirm-yes", "scan-confirm-no",
    "scan-confirm-qty", "scan-confirm-qty-input", "scan-confirm-qty-dec", "scan-confirm-qty-inc",
    "pw-reset-overlay", "pw-reset-new", "pw-reset-confirm", "pw-reset-save", "pw-reset-cancel",
    "user-name-overlay", "user-name-first", "user-name-last", "user-name-save", "user-name-cancel",
    "user-role-overlay", "user-role-select", "user-role-save", "user-role-cancel",
  ])("%s exists", (id) => {
    expect(document.getElementById(id), `${id} is missing from the shell`).not.toBeNull();
  });
});

describe("setMessage", () => {
  it("sets text and class", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "Saved.", "success");
    expect(el.textContent).toBe("Saved.");
    expect(el.className).toBe("success");
  });

  it("clears both when given empty values", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "x", "error");
    dom.setMessage(el, "", "");
    expect(el.textContent).toBe("");
    expect(el.className).toBe("");
  });

  it("writes text, never markup", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "<b>x</b>", "");
    expect(el.querySelector("b")).toBeNull();
  });
});

describe("getNoteValueRaw", () => {
  it("reads the .note-value input", () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `<input class="note-value" value="42">`;
    expect(dom.getNoteValueRaw(wrap)).toBe("42");
  });

  it("returns an empty string when the row has no input", () => {
    expect(dom.getNoteValueRaw(document.createElement("div"))).toBe("");
  });
});

describe("confirmDialog", () => {
  it("shows the message as text and resolves true on Yes", async () => {
    const pending = dom.confirmDialog("Dispense <b>2</b> Bulb?");
    expect(overlay().hidden).toBe(false);
    expect(document.getElementById("scan-confirm-title").textContent).toBe("Dispense <b>2</b> Bulb?");
    expect(document.getElementById("scan-confirm-title").querySelector("b")).toBeNull();
    await user.click(yes());
    await expect(pending).resolves.toBe(true);
    expect(overlay().hidden).toBe(true);
  });

  it("resolves false on No", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.click(no());
    await expect(pending).resolves.toBe(false);
  });

  it("resolves false on Escape", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBe(false);
  });

  it("resolves false on a backdrop click but not on a click inside", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.click(document.getElementById("scan-confirm-title"));
    expect(overlay().hidden).toBe(false);
    overlay().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await expect(pending).resolves.toBe(false);
  });

  it("focuses Yes, never the number input", async () => {
    const pending = dom.confirmDialog("Take how many?", { quantity: 3 });
    expect(document.activeElement).toBe(yes());
    await user.click(no());
    await pending;
  });

  it("renames the buttons and restores the originals afterwards", async () => {
    const originalYes = yes().textContent;
    const pending = dom.confirmDialog("Archive?", { confirmText: "Archive", cancelText: "Keep" });
    expect(yes().textContent).toBe("Archive");
    expect(no().textContent).toBe("Keep");
    await user.click(yes());
    await pending;
    expect(yes().textContent).toBe(originalYes);
  });

  it("hides the No button in dismissOnly mode and restores it", async () => {
    const pending = dom.confirmDialog("Heads up.", { dismissOnly: true });
    expect(no().hidden).toBe(true);
    expect(yes().textContent).toBe("Close");
    await user.click(yes());
    await pending;
    expect(no().hidden).toBe(false);
  });

  it("cleans up its listeners, so a second dialog is not double-resolved", async () => {
    const first = dom.confirmDialog("One?");
    await user.click(yes());
    await first;
    const second = dom.confirmDialog("Two?");
    await user.keyboard("{Escape}");
    await expect(second).resolves.toBe(false);
  });
});

describe("confirmDialog in quantity mode", () => {
  it("shows the stepper seeded with the requested amount", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 3 });
    expect(document.getElementById("scan-confirm-qty").hidden).toBe(false);
    expect(qtyInput().value).toBe("3");
    await user.click(yes());
    await expect(pending).resolves.toBe(3);
  });

  it("steps up and down by one and never below one", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 1 });
    await user.click(document.getElementById("scan-confirm-qty-dec"));
    expect(qtyInput().value).toBe("1");
    await user.click(document.getElementById("scan-confirm-qty-inc"));
    await user.click(document.getElementById("scan-confirm-qty-inc"));
    await user.click(yes());
    await expect(pending).resolves.toBe(3);
  });

  it("resolves a typed amount", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.clear(qtyInput());
    await user.type(qtyInput(), "7");
    await user.click(yes());
    await expect(pending).resolves.toBe(7);
  });

  it("falls back to the requested amount when the field is left unparseable", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.clear(qtyInput());
    await user.click(yes());
    await expect(pending).resolves.toBe(2);
  });

  it("resolves false -- never a bare true -- on No", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.click(no());
    await expect(pending).resolves.toBe(false);
  });

  it("hides the stepper again for the next generic dialog", async () => {
    const first = dom.confirmDialog("How many?", { quantity: 2 });
    await user.click(yes());
    await first;
    const second = dom.confirmDialog("Sure?");
    expect(document.getElementById("scan-confirm-qty").hidden).toBe(true);
    await user.click(yes());
    await second;
  });
});

describe("messageDialog", () => {
  it("resolves once the single button is pressed", async () => {
    const pending = dom.messageDialog("Import finished.");
    expect(no().hidden).toBe(true);
    await user.click(yes());
    await expect(pending).resolves.toBeUndefined();
  });
});

describe("confirmArchivedReuse", () => {
  it("returns the first attempt's value when it succeeds", async () => {
    const action = vi.fn().mockResolvedValue({ id: 1 });
    await expect(dom.confirmArchivedReuse(action)).resolves.toEqual({ id: 1 });
    expect(action).toHaveBeenCalledExactlyOnceWith(false);
    expect(overlay().hidden).toBe(true);
  });

  it("retries with the override flag when the user confirms a 409", async () => {
    const action = vi.fn()
      .mockRejectedValueOnce({ status: 409, detail: "archived" })
      .mockResolvedValueOnce({ id: 2 });
    const pending = dom.confirmArchivedReuse(action);
    await vi.waitFor(() => expect(overlay().hidden).toBe(false));
    await user.click(yes());
    await expect(pending).resolves.toEqual({ id: 2 });
    expect(action).toHaveBeenNthCalledWith(2, true);
  });

  it("throws {cancelled: true} when the user declines", async () => {
    const action = vi.fn().mockRejectedValue({ status: 409, detail: "archived" });
    const pending = dom.confirmArchivedReuse(action);
    await vi.waitFor(() => expect(overlay().hidden).toBe(false));
    await user.click(no());
    await expect(pending).rejects.toEqual({ cancelled: true });
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("rethrows any other error unchanged, without prompting", async () => {
    const action = vi.fn().mockRejectedValue({ status: 400, detail: "Barcode in use" });
    await expect(dom.confirmArchivedReuse(action)).rejects.toEqual({ status: 400, detail: "Barcode in use" });
    expect(overlay().hidden).toBe(true);
  });

  it("uses the caller's message", async () => {
    const action = vi.fn().mockRejectedValue({ status: 409 });
    const pending = dom.confirmArchivedReuse(action, "Restore the archived tool?");
    await vi.waitFor(() =>
      expect(document.getElementById("scan-confirm-title").textContent).toBe("Restore the archived tool?"));
    await user.click(no());
    await expect(pending).rejects.toEqual({ cancelled: true });
  });
});
```

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/unit/dom.dialogs.test.js`
Expected: PASS.

If `user.click` on the overlay resolves the dialog when it should not (the backdrop check is `event.target === confirmOverlay`), re-read the handler before changing the test — the distinction between a click *on* the overlay and a click *inside* it is the behaviour under test.

- [ ] **Step 3: Prove the id guard guards**

```bash
sed -i 's/id="scan-confirm-yes"/id="scan-confirm-yes-x"/' backend/static/shell-tail.html
npx vitest run tests/frontend/unit/dom.dialogs.test.js
```
Expected: FAIL — "scan-confirm-yes is missing from the shell", plus the click tests.

```bash
git checkout backend/static/shell-tail.html
npx vitest run tests/frontend/unit/dom.dialogs.test.js
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/frontend/unit/dom.dialogs.test.js
git commit -m "cover the shared confirm modal and its archived-reuse retry"
```

---

### Task 9: `dom.js` — the three prompt dialogs

**Files:**
- Create: `tests/frontend/unit/dom.prompts.test.js`

**Interfaces:**
- Consumes: `mountView`, `userEvent`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const el = (id) => document.getElementById(id);

describe("promptPasswordReset", () => {
  it("titles the dialog with the username and starts empty", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    expect(el("pw-reset-title").textContent).toBe('New password for "jsmith"');
    expect(el("pw-reset-new").value).toBe("");
    expect(el("pw-reset-overlay").hidden).toBe(false);
    await user.click(el("pw-reset-cancel"));
    await pending;
  });

  it("resolves the password when both fields match", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2");
    await user.click(el("pw-reset-save"));
    await expect(pending).resolves.toBe("hunter2");
  });

  it("refuses a password under four characters and stays open", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "abc");
    await user.type(el("pw-reset-confirm"), "abc");
    await user.click(el("pw-reset-save"));
    expect(el("pw-reset-message").textContent).toBe("Password must be at least 4 characters.");
    expect(el("pw-reset-overlay").hidden).toBe(false);
    await user.click(el("pw-reset-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("refuses a mismatched pair -- the whole reason this replaced prompt()", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter3");
    await user.click(el("pw-reset-save"));
    expect(el("pw-reset-message").textContent).toBe("Passwords do not match.");
    await user.click(el("pw-reset-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("submits on Enter from either field", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2{Enter}");
    await expect(pending).resolves.toBe("hunter2");
  });

  it("resolves null on Escape", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
  });

  it("leaves no plaintext password in the DOM afterwards", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2");
    await user.click(el("pw-reset-save"));
    await pending;
    expect(el("pw-reset-new").value).toBe("");
    expect(el("pw-reset-confirm").value).toBe("");
    expect(el("pw-reset-new").type).toBe("password");
  });

  it("toggles visibility and re-hides on close", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.click(el("pw-reset-toggle"));
    expect(el("pw-reset-new").type).toBe("text");
    await user.click(el("pw-reset-cancel"));
    await pending;
    expect(el("pw-reset-new").type).toBe("password");
  });
});

describe("promptUserName", () => {
  it("hides the username field unless allowUsername is set", async () => {
    const pending = dom.promptUserName({ first_name: "Jo", last_name: "Smith", username: "jsmith" });
    expect(el("user-name-username").hidden).toBe(true);
    await user.click(el("user-name-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves first and last name only", async () => {
    const pending = dom.promptUserName({ first_name: "Jo", last_name: "Smith" });
    await user.clear(el("user-name-first"));
    await user.type(el("user-name-first"), "Joanne");
    await user.click(el("user-name-save"));
    await expect(pending).resolves.toEqual({ firstName: "Joanne", lastName: "Smith" });
  });

  it("includes the username when allowed", async () => {
    const pending = dom.promptUserName(
      { first_name: "Jo", last_name: "Smith", username: "jsmith" }, { allowUsername: true });
    expect(el("user-name-username").hidden).toBe(false);
    await user.click(el("user-name-save"));
    await expect(pending).resolves.toEqual({ firstName: "Jo", lastName: "Smith", username: "jsmith" });
  });

  it("requires both names -- the legacy NULL-name case this exists for", async () => {
    const pending = dom.promptUserName({ first_name: null, last_name: null });
    await user.click(el("user-name-save"));
    expect(el("user-name-message").textContent).toBe("First name and last name are required.");
    await user.click(el("user-name-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("requires a username when the field is shown", async () => {
    const pending = dom.promptUserName(
      { first_name: "Jo", last_name: "Smith", username: "jsmith" }, { allowUsername: true });
    await user.clear(el("user-name-username"));
    await user.click(el("user-name-save"));
    expect(el("user-name-message").textContent).toBe("Username is required.");
    await user.click(el("user-name-cancel"));
    await pending;
  });
});

describe("promptUserRole", () => {
  it("offers exactly the roles it is given", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ["supervisor", "technician"]);
    const options = [...el("user-role-select").options].map((o) => o.value);
    expect(options).toEqual(["supervisor", "technician"]);
    await user.click(el("user-role-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves the chosen role", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ["supervisor", "technician"]);
    await user.selectOptions(el("user-role-select"), "supervisor");
    await user.click(el("user-role-save"));
    await expect(pending).resolves.toBe("supervisor");
  });

  it("refuses an empty selection", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, []);
    await user.click(el("user-role-save"));
    expect(el("user-role-message").textContent).toBe("Select a role.");
    await user.click(el("user-role-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves null on Escape", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ["supervisor"]);
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
  });
});
```

- [ ] **Step 2: Run and reconcile the resolved shapes**

Run: `npx vitest run tests/frontend/unit/dom.prompts.test.js`
Expected: PASS.

`promptUserName`'s resolved key names and `promptUserRole`'s option markup are read off `backend/static/dom.js:329-514` — if the source uses different keys, correct the test to match the source and note it in the commit body.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/dom.prompts.test.js
git commit -m "cover the password, name and role prompt dialogs"
```

---

### Task 10: `itemSave.js`

The only foundation module that composes two others. Its three ordering guarantees are load-bearing and stated in the module header, so each gets a test by name.

**Files:**
- Create: `tests/frontend/unit/itemSave.test.js`

**Interfaces:**
- Consumes: `mountView`, `server`, `installFetchSpy` (Task 2), `userEvent`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```js
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";
import { mountView } from "../helpers/shell.js";

// itemSave.js -> dom.js -> the shell overlays, so the shell must be mounted
// before the import chain runs. mountView does both, in that order.
let itemSave;
let calls;
let user;

const FIELDS = { barcode: "B1", name: "Bulb", location: "A1", price: 2, product_link: null };

beforeEach(async () => {
  user = userEvent.setup({ document });
  itemSave = await mountView("itemSave.js");
  calls = installFetchSpy();
});

afterEach(() => restoreFetchSpy());

const yes = () => document.getElementById("scan-confirm-yes");
const no = () => document.getElementById("scan-confirm-no");
const overlayShown = () => document.getElementById("scan-confirm-overlay").hidden === false;
const paths = () => calls.map((c) => `${c.init.method ?? "GET"} ${c.url}`);

describe("saveItemCore", () => {
  it("PATCHes the item and skips the barcodes call when the list is unchanged", async () => {
    server.use(http.patch("/items/:id", () => HttpResponse.json({ id: 5 })));
    await itemSave.saveItemCore(5, FIELDS, { originalBarcode: "B1", originalBarcodes: [], barcodes: [] });
    expect(paths()).toEqual(["PATCH /items/5"]);
    expect(JSON.parse(calls[0].init.body)).toEqual({ ...FIELDS, override_archived: false });
  });

  it("PATCHes barcodes FIRST, so a duplicate-code 400 lands before the core fields move", async () => {
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({ detail: "Barcode in use" }, { status: 400 })),
      http.patch("/items/:id", () => HttpResponse.json({ id: 5 })),
    );
    await expect(itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: [], barcodes: ["EXTRA"],
    })).rejects.toEqual({ status: 400, detail: "Barcode in use" });
    expect(paths()).toEqual(["PATCH /items/5/barcodes"]);
  });

  it("sends both PATCHes in order when both changed", async () => {
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({})),
      http.patch("/items/:id", () => HttpResponse.json({ id: 5 })),
    );
    await itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: ["OLD"], barcodes: ["NEW"],
    });
    expect(paths()).toEqual(["PATCH /items/5/barcodes", "PATCH /items/5"]);
  });

  it("warns before changing the primary barcode and proceeds on Yes", async () => {
    server.use(http.patch("/items/:id", () => HttpResponse.json({ id: 5 })));
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    expect(document.getElementById("scan-confirm-title").textContent).toBe(itemSave.BARCODE_CHANGE_WARNING);
    await user.click(yes());
    await pending;
    expect(paths()).toEqual(["PATCH /items/5"]);
  });

  it("throws {cancelled: true} and sends nothing when the barcode warning is declined", async () => {
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(no());
    await expect(pending).rejects.toEqual({ cancelled: true });
    expect(calls).toHaveLength(0);
  });

  it("retries the WHOLE sequence with override_archived on a confirmed 409", async () => {
    let attempt = 0;
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({})),
      http.patch("/items/:id", () => {
        attempt += 1;
        return attempt === 1
          ? HttpResponse.json({ detail: "archived" }, { status: 409 })
          : HttpResponse.json({ id: 5 });
      }),
    );
    const pending = itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: [], barcodes: ["EXTRA"],
    });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes());
    await pending;
    // Both writes ride ONE confirmArchivedReuse: the barcodes PATCH is
    // re-sent too, with the flag set.
    expect(paths()).toEqual([
      "PATCH /items/5/barcodes", "PATCH /items/5",
      "PATCH /items/5/barcodes", "PATCH /items/5",
    ]);
    expect(JSON.parse(calls[2].init.body)).toMatchObject({ override_archived: true });
    expect(JSON.parse(calls[3].init.body)).toMatchObject({ override_archived: true });
  });

  it("prompts once, not twice, when both the barcode change and a 409 occur", async () => {
    let attempt = 0;
    server.use(http.patch("/items/:id", () => {
      attempt += 1;
      return attempt === 1
        ? HttpResponse.json({ detail: "archived" }, { status: 409 })
        : HttpResponse.json({ id: 5 });
    }));
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes()); // the barcode-change warning
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes()); // the archived-reuse confirm
    await pending;
    expect(attempt).toBe(2);
  });
});
```

Add `vi` to the vitest import list.

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/unit/itemSave.test.js`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/itemSave.test.js
git commit -m "cover the item-save order of operations"
```

---

### Task 11: `tips.js` + `tooltip.js`, and the `data-tip` audit

The audit is the roadmap's stated success check for P1: a `data-tip` key with no entry in `TIPS` is a silently dead `?` today.

**Files:**
- Create: `tests/frontend/unit/tips.test.js`, `tests/frontend/unit/tooltip.test.js`

**Interfaces:**
- Consumes: `assembleShell`, `mountShell`, `mountView`, `userEvent`.
- Produces: nothing.

- [ ] **Step 1: Write `tests/frontend/unit/tips.test.js`**

```js
import { beforeEach, describe, expect, it, vi } from "vitest";
import { assembleShell, mountShell, mountView } from "../helpers/shell.js";
import { TIPS } from "../../../backend/static/tips.js";

describe("the tip registry", () => {
  it("gives every key a label and plain-text copy", () => {
    for (const [key, tip] of Object.entries(TIPS)) {
      expect(typeof tip.label, key).toBe("string");
      expect(tip.label.length, key).toBeGreaterThan(0);
      expect(typeof tip.text, key).toBe("string");
      expect(tip.text.length, key).toBeGreaterThan(0);
      // Plain text only, by contract (spec D5) -- both fields are escaped at
      // render time, so markup here would show as literal angle brackets.
      expect(tip.text, key).not.toMatch(/<[a-z/]/i);
    }
  });

  it("uses the documented <area>.<thing> key form", () => {
    for (const key of Object.keys(TIPS)) {
      expect(key, key).toMatch(/^[a-z0-9]+(\.[a-z0-9-]+)+$/);
    }
  });
});

describe("the data-tip audit", () => {
  // Every hand-authored `?` in the shell must resolve to copy. A miss renders
  // a trigger that opens nothing, which installTooltips then hides -- invisible
  // in production, visible here.
  it("resolves every data-tip key in the assembled shell", () => {
    const keys = [...assembleShell().matchAll(/data-tip="([^"]+)"/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(0);
    const missing = [...new Set(keys)].filter((key) => !TIPS[key]);
    expect(missing, `data-tip keys with no entry in tips.js: ${missing.join(", ")}`).toEqual([]);
  });

  it("resolves every key the view modules pass to tipHtml", async () => {
    const { readdirSync, readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const dir = "backend/static/views";
    const keys = new Set();
    for (const file of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
      const source = readFileSync(join(dir, file), "utf8");
      for (const match of source.matchAll(/tipHtml\(\s*"([^"]+)"\s*\)/g)) keys.add(match[1]);
    }
    const missing = [...keys].filter((key) => !TIPS[key]);
    expect(missing, `tipHtml() keys with no entry in tips.js: ${missing.join(", ")}`).toEqual([]);
  });
});

describe("tipHtml", () => {
  let tooltip;
  beforeEach(async () => {
    tooltip = await mountView("tooltip.js");
  });

  it("emits a button carrying the key and the accessible name, never the copy", () => {
    const key = Object.keys(TIPS)[0];
    const html = tooltip.tipHtml(key);
    expect(html).toContain(`data-tip="${key}"`);
    expect(html).toContain(`aria-label="Help: ${TIPS[key].label}"`);
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain(TIPS[key].text);
  });

  it("returns nothing for an unknown key rather than a dead affordance", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(tooltip.tipHtml("nope.missing")).toBe("");
    expect(warn).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Write `tests/frontend/unit/tooltip.test.js`**

```js
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";
import { TIPS } from "../../../backend/static/tips.js";

const KEY = Object.keys(TIPS)[0];

let tooltip;
let user;
let trigger;

beforeEach(async () => {
  user = userEvent.setup({ document });
  tooltip = await mountView("tooltip.js");
  // A trigger of our own, so the test does not depend on which page fragment
  // happens to hand-author one.
  const host = document.createElement("div");
  host.innerHTML = tooltip.tipHtml(KEY);
  document.body.appendChild(host);
  trigger = host.querySelector("[data-tip]");
  tooltip.installTooltips();
});

const bubble = () => document.getElementById("tip-bubble");

describe("installTooltips", () => {
  it("opens a pinned tip on click and marks the trigger expanded", async () => {
    await user.click(trigger);
    expect(bubble().hidden).toBe(false);
    expect(bubble().textContent).toBe(TIPS[KEY].text);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-describedby")).toBe("tip-bubble");
  });

  it("closes on a second click of the same trigger", async () => {
    await user.click(trigger);
    await user.click(trigger);
    expect(bubble().hidden).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on a click elsewhere", async () => {
    await user.click(trigger);
    await user.click(document.body);
    expect(bubble().hidden).toBe(true);
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(bubble().hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps a pinned tip open when the pointer leaves", async () => {
    await user.click(trigger);
    trigger.dispatchEvent(new Event("pointerleave"));
    expect(bubble().hidden).toBe(false);
  });

  it("moves the single bubble between triggers rather than opening a second", async () => {
    const second = document.createElement("div");
    second.innerHTML = tooltip.tipHtml(Object.keys(TIPS)[1]);
    document.body.appendChild(second);
    await user.click(trigger);
    await user.click(second.querySelector("[data-tip]"));
    expect(document.querySelectorAll("#tip-bubble")).toHaveLength(1);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("drops an orphaned bubble when a refresh removes the trigger", async () => {
    await user.click(trigger);
    trigger.remove();
    await user.click(document.body);
    expect(bubble().hidden).toBe(true);
  });

  it("closes on scroll, because the bubble is fixed and would detach", async () => {
    await user.click(trigger);
    window.dispatchEvent(new Event("scroll"));
    expect(bubble().hidden).toBe(true);
  });

  it("is idempotent -- a second install does not double-bind", async () => {
    tooltip.installTooltips();
    await user.click(trigger);
    await user.click(trigger);
    expect(bubble().hidden).toBe(true);
  });

  it("labels hand-authored triggers that omit the accessible name", async () => {
    const bare = document.createElement("button");
    bare.className = "tip-btn";
    bare.dataset.tip = KEY;
    document.body.appendChild(bare);
    vi.resetModules();
    const fresh = await mountView("tooltip.js");
    document.body.appendChild(bare);
    fresh.installTooltips();
    expect(bare.getAttribute("aria-label")).toBe(`Help: ${TIPS[KEY].label}`);
  });

  it("hides a trigger naming a key that does not exist", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const bad = document.createElement("button");
    bad.dataset.tip = "nope.missing";
    document.body.appendChild(bad);
    await user.click(bad);
    expect(bad.hidden).toBe(true);
    expect(bubble().hidden).toBe(true);
    expect(warn).toHaveBeenCalled();
  });
});

describe("closeTip", () => {
  it("is safe to call with nothing open", () => {
    expect(() => tooltip.closeTip()).not.toThrow();
  });

  it("clears the bubble text so no stale copy is left in the DOM", async () => {
    await user.click(trigger);
    tooltip.closeTip();
    expect(bubble().textContent).toBe("");
  });
});
```

The `labelStaticTriggers` test needs the trigger present *before* `installTooltips` runs. If re-mounting inside the test proves awkward (the shell replaces `document.documentElement`, discarding appended nodes), restructure that one case into its own `describe` with a local `beforeEach` that appends the bare trigger and only then imports and installs.

- [ ] **Step 3: Run and file what the audit finds**

Run: `npx vitest run tests/frontend/unit/tips.test.js tests/frontend/unit/tooltip.test.js`
Expected: PASS, **or** a list of unresolved `data-tip` keys. That list is the phase's success check: copy it verbatim into the scratchpad for Task 13. If keys are missing, keep the assertion but temporarily scope it (`expect(missing).toEqual(KNOWN_MISSING)` with the list named and a comment pointing at the `open-work.md` entry) so the suite is green and the gap is recorded rather than hidden.

- [ ] **Step 4: Commit**

```bash
git add tests/frontend/unit/tips.test.js tests/frontend/unit/tooltip.test.js
git commit -m "audit every data-tip key and cover the tooltip interactions"
```

---

### Task 12: `realtime.js`

No real socket. A scriptable fake `WebSocket` plus fake timers covers envelope validation, subscription routing, and the reconnect ladder.

**Files:**
- Create: `tests/frontend/helpers/fakeSocket.js`, `tests/frontend/unit/realtime.test.js`

**Interfaces:**
- Consumes: nothing from P0 beyond `setup.js`.
- Produces: `installFakeWebSocket(): { sockets: FakeSocket[], restore(): void }`, where each `FakeSocket` has `url`, `readyState`, `close(code, reason)`, and the test-side drivers `emitOpen()`, `emitMessage(data)`, `emitError()`, `emitClose()`.

- [ ] **Step 1: Write `tests/frontend/helpers/fakeSocket.js`**

```js
// A scriptable WebSocket stand-in. realtime.js calls `new WebSocket(url)` at
// connect time, so replacing the global is enough -- no module mocking.
import { vi } from "vitest";

class FakeSocket extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.readyState = 0;
    this.closed = null;
  }

  close(code, reason) {
    this.readyState = 3;
    this.closed = { code, reason };
  }

  emitOpen() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }

  emitMessage(data) {
    // `data` is whatever the server would send: a JSON string, or a
    // deliberately malformed value for the validation tests.
    const event = new Event("message");
    event.data = data;
    this.dispatchEvent(event);
  }

  emitError() {
    this.dispatchEvent(new Event("error"));
  }

  emitClose() {
    this.readyState = 3;
    this.dispatchEvent(new Event("close"));
  }
}

// jsdom defines `WebSocket` as a read-only property -- a plain assignment
// throws "Cannot assign to read only property 'WebSocket'". vi.stubGlobal
// goes through defineProperty, which works, and unstubAllGlobals restores it.
export function installFakeWebSocket({ throwOnConstruct = false } = {}) {
  const sockets = [];
  vi.stubGlobal("WebSocket", function (url) {
    if (throwOnConstruct) throw new Error("blocked");
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket;
  });
  return {
    sockets,
    last: () => sockets.at(-1),
    restore() { vi.unstubAllGlobals(); },
  };
}
```

- [ ] **Step 2: Write `tests/frontend/unit/realtime.test.js`**

```js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket } from "../helpers/fakeSocket.js";

let realtime;
let ws;

beforeEach(async () => {
  vi.useFakeTimers();
  ws = installFakeWebSocket();
  realtime = await import("../../../backend/static/realtime.js");
});

afterEach(() => {
  realtime.disconnectRealtime();
  ws.restore();
  vi.useRealTimers();
});

const envelope = (type, id = "1") => JSON.stringify({ type, id, req: null });

describe("subscribe", () => {
  it("rejects a non-string event type and a non-function handler", () => {
    expect(() => realtime.subscribe("", () => {})).toThrow(TypeError);
    expect(() => realtime.subscribe("work_order", null)).toThrow(TypeError);
  });

  it("returns an unsubscribe that stops delivery", () => {
    const handler = vi.fn();
    const off = realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler).toHaveBeenCalledTimes(1);
    off();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("delivers to every subscriber of the type, and to no other type", () => {
    const a = vi.fn();
    const b = vi.fn();
    const other = vi.fn();
    realtime.subscribe("work_order", a);
    realtime.subscribe("work_order", b);
    realtime.subscribe("item", other);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
    expect(other).not.toHaveBeenCalled();
  });

  it("passes the envelope, the reason, and the active page", () => {
    realtime.setActivePageGetter(() => "work-orders");
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order", "42"));
    expect(handler).toHaveBeenCalledWith({
      reason: "event",
      envelope: { type: "work_order", id: "42", req: null },
      activePage: "work-orders",
    });
  });

  it("survives a throwing subscriber and still calls the next one", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const good = vi.fn();
    realtime.subscribe("work_order", () => { throw new Error("boom"); });
    realtime.subscribe("work_order", good);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(good).toHaveBeenCalled();
    expect(error).toHaveBeenCalled();
  });

  it("survives a rejecting async subscriber", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    realtime.subscribe("work_order", async () => { throw new Error("boom"); });
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    await vi.waitFor(() => expect(error).toHaveBeenCalled());
  });
});

describe("setActivePageGetter", () => {
  it("rejects a non-function", () => {
    expect(() => realtime.setActivePageGetter("work-orders")).toThrow(TypeError);
  });

  it("reports a null active page when the getter throws", () => {
    realtime.setActivePageGetter(() => { throw new Error("boom"); });
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler.mock.calls[0][0].activePage).toBeNull();
  });
});

describe("envelope validation", () => {
  const handler = vi.fn();

  beforeEach(() => {
    handler.mockClear();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
  });

  it.each([
    ["not JSON at all", "{oops"],
    ["a non-string payload", { type: "work_order" }],
    ["an array", JSON.stringify([1, 2, 3])],
    ["null", JSON.stringify(null)],
    ["a missing key", JSON.stringify({ type: "work_order", id: "1" })],
    ["an extra key", JSON.stringify({ type: "work_order", id: "1", req: null, extra: 1 })],
    ["a non-string type", JSON.stringify({ type: 3, id: "1", req: null })],
    ["an empty type", JSON.stringify({ type: "", id: "1", req: null })],
    ["a numeric id", JSON.stringify({ type: "work_order", id: 1, req: null })],
    ["a numeric req", JSON.stringify({ type: "work_order", id: "1", req: 2 })],
  ])("drops %s", (_label, data) => {
    ws.last().emitMessage(data);
    expect(handler).not.toHaveBeenCalled();
  });

  it("accepts null id and null req", () => {
    ws.last().emitMessage(JSON.stringify({ type: "work_order", id: null, req: null }));
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("connect and disconnect", () => {
  it("opens one socket at the ws(s) /ws URL", () => {
    realtime.connectRealtime();
    expect(ws.sockets).toHaveLength(1);
    expect(ws.last().url).toMatch(/^wss?:\/\/[^/]+\/ws$/);
  });

  it("is a no-op when already connected", () => {
    realtime.connectRealtime();
    realtime.connectRealtime();
    expect(ws.sockets).toHaveLength(1);
  });

  it("closes cleanly on disconnect and stops reconnecting", () => {
    realtime.connectRealtime();
    const socket = ws.last();
    socket.emitOpen();
    realtime.disconnectRealtime();
    expect(socket.closed).toEqual({ code: 1000, reason: "signed out" });
    socket.emitClose();
    vi.advanceTimersByTime(120000);
    expect(ws.sockets).toHaveLength(1);
  });
});

describe("reconnect", () => {
  it("schedules a retry after an unexpected close", () => {
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitClose();
    expect(ws.sockets).toHaveLength(1);
    // Unpinned jitter puts the first retry in [500, 1000), so 1000 always fires it.
    vi.advanceTimersByTime(1000);
    expect(ws.sockets).toHaveLength(2);
  });

  it("backs off exponentially, capped at 30s, with a non-zero floor", () => {
    // Equal jitter: delay is in [ceiling/2, ceiling), where ceiling is
    // min(30000, 1000 * 2 ** min(attempt, 10)) and the first attempt is 0.
    // Pinning Math.random to 0 gives ceiling/2 -- these exact values were
    // measured against the real module, not derived on paper.
    vi.spyOn(Math, "random").mockReturnValue(0);
    realtime.connectRealtime();
    const expected = [500, 1000, 2000, 4000, 8000, 15000, 15000];
    for (const delay of expected) {
      ws.last().emitClose();
      const before = ws.sockets.length;
      vi.advanceTimersByTime(delay - 1);
      expect(ws.sockets).toHaveLength(before);
      vi.advanceTimersByTime(1);
      expect(ws.sockets).toHaveLength(before + 1);
    }
  });

  it("resets the ladder after a successful open", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    realtime.connectRealtime();
    ws.last().emitClose();
    vi.advanceTimersByTime(500);
    ws.last().emitOpen();
    ws.last().emitClose();
    // Back to the bottom of the ladder: 500 again, not 1000.
    vi.advanceTimersByTime(500);
    expect(ws.sockets).toHaveLength(3);
  });

  it("notifies every subscriber once on recovery, whatever their event type", () => {
    const a = vi.fn();
    const b = vi.fn();
    realtime.subscribe("work_order", a);
    realtime.subscribe("item", b);
    realtime.connectRealtime();
    ws.last().emitOpen();
    a.mockClear();
    b.mockClear();
    ws.last().emitClose();
    vi.advanceTimersByTime(30000);
    ws.last().emitOpen();
    expect(a).toHaveBeenCalledWith({ reason: "reconnect", envelope: null, activePage: null });
    expect(b).toHaveBeenCalledOnce();
  });

  it("does not fire a recovery refresh on the first ever open", () => {
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    expect(handler).not.toHaveBeenCalled();
  });

  it("closes the socket on error, letting close drive the single retry path", () => {
    realtime.connectRealtime();
    const socket = ws.last();
    socket.emitOpen();
    socket.emitError();
    expect(socket.readyState).toBe(3);
  });

  it("retries when the constructor itself throws", async () => {
    realtime.disconnectRealtime();
    ws.restore();
    ws = installFakeWebSocket({ throwOnConstruct: true });
    realtime.connectRealtime();
    ws.restore();
    const live = installFakeWebSocket();
    vi.advanceTimersByTime(30000);
    expect(live.sockets.length).toBeGreaterThan(0);
    live.restore();
  });

  it("ignores messages from a socket belonging to a stale generation", () => {
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    const stale = ws.last();
    stale.emitOpen();
    realtime.disconnectRealtime();
    realtime.connectRealtime();
    stale.emitMessage(envelope("work_order"));
    expect(handler).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run and tune the backoff expectations**

Run: `npx vitest run tests/frontend/unit/realtime.test.js`
Expected: PASS.

The `expected` ladder was measured against the real module on 2026-09-10, not derived on paper: `[500, 1000, 2000, 4000, 8000, 15000, 15000, 15000]` with `Math.random()` pinned to 0. If it fails, the module changed — that is a finding, not a test bug.

- [ ] **Step 4: Commit**

```bash
git add tests/frontend/helpers/fakeSocket.js tests/frontend/unit/realtime.test.js
git commit -m "cover realtime envelope validation, routing and reconnect backoff"
```

---

### Task 13: Promote the factories, record coverage, file the findings

**Files:**
- Modify: `tests/frontend/helpers/factories.js`, `docs/open-work.md`
- Create: nothing

**Interfaces:**
- Consumes: the verified payload shapes from Tasks 1–3.
- Produces:
  - `workOrder(overrides = {}) -> object` — a complete work order matching `GET /work-orders/{id}`.
  - `item(overrides = {}) -> object`, `transaction(overrides = {}) -> object`.
  These are what P2 builds on; a factory that drifts from its endpoint produces green tests over a broken app.

- [ ] **Step 1: Extend `helpers/factories.js`**

Read the response models — `backend/app/schemas/work_orders.py`, `items.py`, `transactions.py` — and the rows in `docs/endpoint-map.md` for those routes. Every field the model declares gets a sane default; nothing is invented.

```js
// Complete, valid payloads with a sane default for every field the response
// model declares. Tests override only the field under test, so a test stays
// readable when the API shape grows a column.
//
// Shapes are taken from backend/app/schemas/*.py, verified against api.js in
// P1. A drifting factory produces green tests over a broken app.
let nextId = 1;
const id = () => nextId++;

export function item(overrides = {}) {
  return {
    id: id(), barcode: "B1", name: "Bulb", location: "A1",
    quantity: 10, price: "2.50", product_link: null,
    low_stock_threshold: null, notes: {}, barcodes: [],
    ...overrides,
  };
}

export function workOrder(overrides = {}) {
  return {
    id: id(), number: "12345", status: "assigned", priority: "normal",
    community: "Maple Ridge", building_number: "3", unit_number: "12",
    description: "Replace hallway bulb", notes: null, location: "Hallway",
    service_type: "Electrical", schedule_date: null,
    supervisor_id: null, assigned_to_ids: [], assigned_to: [],
    items: [], labor: [], materials_total: "0.00", labor_total: "0.00",
    labor_billed_minutes: 0, archived: false,
    ...overrides,
  };
}

export function transaction(overrides = {}) {
  return {
    id: id(), item_id: 1, item_name: "Bulb", transaction_type: "out",
    quantity: 1, billable_quantity: null, work_order_number: null,
    user_id: 1, user_name: "Jo Smith", created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}
```

Correct every field name against the schema files before committing. A guessed field is worse than a missing one.

- [ ] **Step 2: Add a factory-drift test to `tests/frontend/unit/api.endpoints.test.js`**

```js
describe("factories match the schemas they stand in for", () => {
  it("declares no field the work-order response model does not have", async () => {
    const { readFileSync } = await import("node:fs");
    const { workOrder } = await import("../helpers/factories.js");
    const schema = readFileSync("backend/app/schemas/work_orders.py", "utf8");
    const unknown = Object.keys(workOrder()).filter(
      (field) => !new RegExp(`^\\s*${field}\\s*:`, "m").test(schema));
    expect(unknown, `not in the response model: ${unknown.join(", ")}`).toEqual([]);
  });
});
```

If the schema file's class layout makes this check noisy (several models in one file), narrow the regex to the `WorkOrderRead`-style class body rather than dropping the test — this guard is what keeps P2's assertions meaningful.

- [ ] **Step 3: Record the coverage numbers**

```bash
npm run test:ci
```

Copy the per-file percentages for the twelve P1 modules from the coverage summary into the commit body. The number is recorded, not gated — P7 sets the threshold.

- [ ] **Step 4: File the findings in `docs/open-work.md`**

One entry is already known: **`apiGetHubAdmin` is absent from `docs/endpoint-map.md`** while the route and its caller both exist — the map's Master Endpoint Index needs a row for `GET /hub/admin`. Add that, plus one entry per finding gathered in Tasks 2, 3 and 11 — endpoint/doc path mismatches, unresolved `data-tip` keys, and any behaviour a test had to record as-is with a `// FINDING:` comment. Follow the file's existing entry form; keep each to one line plus a pointer at the test that pins the current behaviour. Delete nothing else; respect the file's word budget (12,000, per `CLAUDE.md`).

If there are no findings, say so in the commit body and change nothing in `docs/`.

- [ ] **Step 5: Full suite and commit**

```bash
npm test
```
Expected: green, every file.

```bash
git add tests/frontend/helpers/factories.js tests/frontend/unit/api.endpoints.test.js docs/open-work.md
git commit -m "promote the test factories to the verified api.js shapes"
```

---

## Done when

- `npm test` is green on a clean checkout with no database.
- Every exported `api*` wrapper has a table row, and the meta-test fails if one is added without it.
- Every `data-tip` key in the shell and in `views/*.js` either resolves to copy in `tips.js` or is filed in `docs/open-work.md`.
- `dom.js`'s import-time element ids are guarded: renaming one in `shell-tail.html` turns a test red.
- CI's `frontend` job is green.
- Coverage for the twelve P1 modules is recorded in the final commit body.

## Deliberately not in P1

- **No production fixes.** Every mismatch is filed, not fixed. A separate task decides which are real.
- **No view coverage.** `views/*.js` is P2 (`workOrders.js`) and P5–P7.
- **No coverage threshold.** P7.
- **No `service-worker.js` or `scan/*` coverage.** P7; they are not foundation.

## A note on characterization

These tests record what the foundation does today, bugs included. When an
assertion and the source disagree, the source wins and the disagreement gets
filed. That discipline is what makes the suite trustworthy as a net for the
`workOrders.js` split in P4 — a suite that was quietly edited to match a fix is
a suite that cannot tell you a refactor broke something.
